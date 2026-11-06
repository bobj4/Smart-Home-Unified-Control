"""deploy/linux/smarthome on an internet-facing server: copying backups off
the server (now and daily) and fail2ban. Docker, systemd and fail2ban are
replaced by small fakes; nothing outside a temporary folder is touched."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The deploy script is for Linux servers; these run it with bash.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux deploy script")


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "checkout"
    (root / "deploy" / "linux").mkdir(parents=True)
    for path in [
        REPO / "deploy/linux/smarthome",
        *(REPO / "deploy/linux").glob("*.sh"),
    ]:
        shutil.copy(path, root / "deploy" / "linux" / path.name)
    shutil.copy(REPO / "deploy" / "docker-compose.yml", root / "deploy")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    # docker compose ... cp SERVICE:/app/data/backups/. DIR -> two backups in DIR
    _fake(
        bin_dir,
        "docker",
        f'echo "docker $*" >> {calls}\n'
        'if [[ "$*" == *" cp "* ]]; then dest="${@: -1}";'
        ' touch "$dest/smart_home-1.db" "$dest/smart_home-2.db"; fi\nexit 0\n',
    )
    for name in ("systemctl", "fail2ban-client", "sudo"):
        _fake(
            bin_dir,
            name,
            f'echo "{name} $*" >> {calls}\n'
            + ('"$@"\n' if name == "sudo" else "exit 0\n"),
        )
    _fake(bin_dir, "rsync", f'echo "rsync $*" >> {calls}\nexit 0\n')
    logs = tmp_path / "logs"
    (logs / "var/log/httpd").mkdir(parents=True)
    (logs / "var/log/httpd/ssl_access_log").write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SMARTHOME_SYSTEMD_DIR": str(tmp_path / "systemd"),
        "SMARTHOME_FAIL2BAN_DIR": str(tmp_path / "fail2ban"),
        "SMARTHOME_LOG_ROOT": str(logs),
    }
    (tmp_path / "systemd").mkdir()

    def run(*args):
        return subprocess.run(  # noqa: S603
            ["bash", str(root / "deploy/linux/smarthome"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    return {"run": run, "root": root, "tmp": tmp_path, "calls": calls}


def test_offsite_backup_to_a_folder(server):
    dest = server["tmp"] / "nas" / "smarthome"
    r = server["run"]("offsite-backup", str(dest))
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == [
        "smart_home-1.db",
        "smart_home-2.db",
    ]
    assert "SECRETS_KEY" in r.stdout


def test_offsite_backup_over_ssh_uses_rsync_without_prompts(server):
    r = server["run"]("offsite-backup", "me@backup-box:/srv/smarthome")
    assert r.returncode == 0, r.stderr
    calls = server["calls"].read_text()
    assert "rsync -a -e ssh -o BatchMode=yes" in calls
    assert "me@backup-box:/srv/smarthome/" in calls


def test_offsite_setup_installs_a_daily_timer(server):
    dest = server["tmp"] / "usb"
    r = server["run"]("offsite-setup", str(dest), "3")
    assert r.returncode == 0, r.stderr
    unit = server["tmp"] / "systemd"
    service = (unit / "smarthome-offsite.service").read_text()
    timer = (unit / "smarthome-offsite.timer").read_text()
    assert f"offsite-backup {dest}" in service
    assert "OnCalendar=*-*-* 03:15:00" in timer and "Persistent=true" in timer
    assert (
        "systemctl enable --now smarthome-offsite.timer" in server["calls"].read_text()
    )
    conf = (server["root"] / "deploy/linux/local.conf").read_text()
    assert f"OFFSITE={dest}" in conf
    r = server["run"]("offsite-remove")
    assert r.returncode == 0 and not (unit / "smarthome-offsite.timer").exists()


@pytest.mark.parametrize(
    "args",
    [
        ("offsite-setup", "/tmp/x", "24"),
        ("offsite-setup", "/tmp/a b"),
        ("offsite-backup",),
    ],
)
def test_offsite_refuses_bad_input(server, args):
    r = server["run"](*args)
    assert r.returncode != 0


def test_fail2ban_setup_watches_the_proxy_log(server):
    r = server["run"]("fail2ban-setup")
    assert r.returncode == 0, r.stderr
    f2b = server["tmp"] / "fail2ban"
    jail = (f2b / "jail.d/smarthome.local").read_text()
    assert "logpath  = /var/log/httpd/ssl_access_log" in jail
    assert "maxretry = 10" in jail
    rules = (f2b / "filter.d/smarthome.conf").read_text()
    assert '"POST /api/v1/auth/login HTTP/[0-9.]+" 401' in rules


def test_fail2ban_filter_matches_failed_logins_only(server):
    server["run"]("fail2ban-setup")
    import re

    text = (server["tmp"] / "fail2ban/filter.d/smarthome.conf").read_text()
    patterns = [
        re.compile(p.strip().replace("<HOST>", r"(?P<host>\S+)"))
        for p in text.split("failregex =")[1].split("ignoreregex")[0].splitlines()
        if p.strip()
    ]
    line = '203.0.113.9 - - [05/Nov/2026:22:00:00 -0500] "POST /api/v1/auth/login HTTP/1.1" {} 52 "-" "x"'
    assert any(p.search(line.format(401)) for p in patterns)
    assert any(p.search(line.format(429)) for p in patterns)
    assert not any(p.search(line.format(200)) for p in patterns)
    other = '203.0.113.9 - - [05/Nov/2026:22:00:00 -0500] "GET /api/v1/account HTTP/1.1" 401 52'
    assert not any(p.search(other) for p in patterns)
