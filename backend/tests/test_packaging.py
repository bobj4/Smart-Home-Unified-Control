"""The package build (packaging/, .github/workflows/packages.yml): every file
it names exists, its scripts are executable and pass shellcheck, and the
smarthome command works through the /usr/bin link the package installs."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_nfpm_config_names_real_files():
    text = (REPO / "packaging/nfpm.yaml").read_text()
    for src in re.findall(r"^\s+- src: (\./\S+)", text, flags=re.M):
        assert (REPO / src).exists(), src
    for script in re.findall(r"^\s+\w+: (\./packaging/\S+\.sh)", text, flags=re.M):
        path = REPO / script
        assert path.exists() and os.access(path, os.X_OK), script
    assert "${VERSION}" in text and "type: symlink" in text


def test_workflow_publishes_both_channels():
    text = (REPO / ".github/workflows/packages.yml").read_text()
    assert "branches: [dev]" in text and 'tags: ["v*"]' in text
    assert "createrepo_c" in text and "InRelease" in text and "KEY.asc" in text
    assert "keep_files: true" in text  # one channel never wipes the other
    # Every action is pinned to a version.
    for uses in re.findall(r"uses: (\S+)", text):
        assert re.search(r"@v\d", uses), uses


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck")
def test_scripts_pass_shellcheck():
    tool = str(shutil.which("shellcheck"))
    scripts = sorted(str(p) for p in (REPO / "packaging").glob("*.sh"))
    r = subprocess.run(
        [tool, "-S", "warning", *scripts], capture_output=True, text=True
    )  # noqa: S603
    assert r.returncode == 0, r.stdout


@pytest.mark.skipif(os.name == "nt", reason="needs bash and symbolic links")
def test_smarthome_works_through_a_link(tmp_path):
    link = tmp_path / "smarthome"
    link.symlink_to(REPO / "deploy/linux/smarthome")
    r = subprocess.run(
        ["bash", str(link), "help"], capture_output=True, text=True, timeout=30
    )  # noqa: S603, S607
    assert r.returncode == 0, r.stderr
    assert "offsite-setup" in r.stdout
