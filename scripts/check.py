"""Run every check and exit non-zero if any fails.

Run with the project's interpreter, from any folder:
    .venv/Scripts/python.exe scripts/check.py      (Windows)
    .venv/bin/python scripts/check.py              (Linux)
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

CHECKS = [
    ("ruff lint", ["ruff", "check", "."]),
    ("ruff format", ["ruff", "format", "--check", "."]),
    ("mypy", ["mypy", "app", "main.py", "scripts"]),
    (
        "pytest",
        ["pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "-o", "addopts="],
    ),
    ("bandit", ["bandit", "-q", "-r", "app", "main.py", "scripts"]),
    # The migrations must build exactly the schema the models describe.
    ("alembic upgrade (empty database)", ["alembic", "upgrade", "head"]),
    ("alembic check", ["alembic", "check"]),
    (
        "pip-audit (needs internet)",
        ["pip_audit", "-r", "requirements.txt", "--require-hashes", "--disable-pip"],
    ),
]


def main() -> int:
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ}
        for name, args in CHECKS:
            if args[0] == "alembic":
                env["DATABASE_URL"] = "sqlite:///" + (Path(tmp) / "check.db").as_posix()
            print(f"\n== {name}", flush=True)
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-m", *args], cwd=BACKEND, env=env
            )
            if result.returncode != 0:
                failed.append(name)
    print(
        "\n" + ("All checks passed." if not failed else f"FAILED: {', '.join(failed)}")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
