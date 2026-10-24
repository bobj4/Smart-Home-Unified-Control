"""Docker deployment files: what they must keep doing.

Written by the reviewer (deployment phase). Do not edit, skip, mark or delete
these tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it. The image itself is built by the owner.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text()
COMPOSE = (ROOT / "deploy" / "docker-compose.yml").read_text()
IGNORE = (ROOT / ".dockerignore").read_text().split()


def test_image_installs_only_hashed_runtime_requirements():
    assert "pip install --require-hashes -r /tmp/requirements.txt" in DOCKERFILE
    assert "requirements-dev" not in DOCKERFILE


def test_image_runs_as_non_root_and_serves_with_serve_py():
    users = re.findall(r"^USER (\S+)$", DOCKERFILE, re.M)
    assert users == ["smarthome"]
    assert 'CMD ["python", "scripts/serve.py"' in DOCKERFILE
    assert (ROOT / "backend" / "scripts" / "serve.py").is_file()


def test_data_and_backups_live_in_the_volume():
    assert "DATABASE_URL=sqlite:////app/data/smart_home.db" in DOCKERFILE
    assert "BACKUP_DIR=/app/data/backups" in DOCKERFILE
    assert "- data:/app/data" in COMPOSE


def test_container_is_locked_down():
    for line in ("read_only: true", "- ALL", "no-new-privileges:true", "- /tmp"):
        assert line in COMPOSE, line


def test_secrets_and_tests_stay_out_of_the_image():
    for pattern in ("**/.env", "**/*.db", "backend/tests", ".git", ".venv"):
        assert pattern in IGNORE, pattern
    assert "SECRETS_KEY=" in (ROOT / "deploy" / ".env.example").read_text()
    assert ".env" in (ROOT / ".gitignore").read_text().split()  # deploy/.env too
