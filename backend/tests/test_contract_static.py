"""Repository rules checked by reading files. Written by the reviewer (Review 2).

Do not edit, skip, mark or delete these tests. If one looks wrong, stop and
report the test name and its full failure output instead of changing it.
"""

import configparser
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
WEB_JS = [REPO_DIR / "web" / "js" / "api.js", REPO_DIR / "web" / "js" / "app.js"]


def app_sources():
    files = [BACKEND_DIR / "main.py", *sorted((BACKEND_DIR / "app").rglob("*.py"))]
    return [(f, f.read_text(encoding="utf-8")) for f in files]


def test_reviewer_tests_and_existing_tests_are_present():
    """Tests must never be deleted to make a run pass."""
    tests = BACKEND_DIR / "tests"
    for name in (
        "conftest.py",
        "test_contract_api.py",
        "test_contract_static.py",
        "test_auth.py",
        "test_create_owner.py",
        "test_health.py",
        "test_recovery_codes.py",
        "test_totp.py",
    ):
        assert (tests / name).is_file(), name


def test_web_js_keeps_no_tokens_in_browser_storage():
    """B5."""
    for path in WEB_JS:
        text = path.read_text(encoding="utf-8")
        for banned in ("localStorage", "sessionStorage"):
            assert banned not in text, f"{path.name}: {banned}"


def test_web_js_does_not_inject_html():
    """B6."""
    for path in WEB_JS:
        text = path.read_text(encoding="utf-8")
        for banned in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
        ):
            assert banned not in text, f"{path.name}: {banned}"


def test_web_api_client_uses_cookies_and_csrf_header():
    text = (REPO_DIR / "web" / "js" / "api.js").read_text(encoding="utf-8")
    assert "X-CSRF-Token" in text
    assert "Bearer" not in text
    assert "Authorization" not in text


def test_no_sys_path_changes_or_backend_prefixed_imports():
    """AGENTS.md: import project code as app.<module>; never change sys.path."""
    for path, text in app_sources():
        assert "sys.path" not in text, path
        assert not re.search(r"^\s*(from|import)\s+backend\.", text, re.M), path


def test_no_placeholder_secrets_or_jwt_leftovers():
    """B4: no fallback secret keys anywhere the app or deployment reads."""
    banned = re.compile(
        r"change-this-in-production|change-in-production|your-secret-key|"
        r"SECRET_KEY|ALGORITHM|python-jose|from jose",
        re.I,
    )
    files = [path for path, _ in app_sources()]
    files += [
        p
        for p in (
            REPO_DIR / "docker-compose.yml",
            REPO_DIR / "deploy" / "docker-compose.yml",
        )
        if p.is_file()
    ]
    for path in files:
        match = banned.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path}: {match.group(0) if match else ''}"


def test_type_checking_is_not_disabled():
    config = configparser.ConfigParser()
    config.read(BACKEND_DIR / "mypy.ini", encoding="utf-8")
    for section in config.sections():
        assert "ignore_errors" not in config[section], section
        assert "disable_error_code" not in config[section], section


def compose_port_mappings(text):
    mappings, ports_indent = [], None
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "ports:":
            ports_indent = indent
            continue
        if ports_indent is not None:
            if stripped.startswith("-") and indent > ports_indent:
                mappings.append(stripped[1:].strip().strip("'\""))
            elif stripped:
                ports_indent = None
    return mappings


def test_compose_publishes_only_the_app_port():
    """H2 / SEC-50, revised for the Docker phase: there is no reverse proxy;
    the app (with its own HTTPS) is the one thing facing the home network,
    so only its port 8000 may be published."""
    for path in (
        REPO_DIR / "docker-compose.yml",
        REPO_DIR / "deploy" / "docker-compose.yml",
    ):
        if not path.is_file():
            continue
        for mapping in compose_port_mappings(path.read_text(encoding="utf-8")):
            assert mapping in ("8000:8000", "127.0.0.1:8000:8000"), f"{path}: {mapping}"


def test_dockerfiles_run_as_non_root():
    """SEC-52."""
    found = [
        p
        for p in (
            REPO_DIR / "Dockerfile",
            REPO_DIR / "deploy" / "Dockerfile",
            REPO_DIR / "web" / "Dockerfile",
        )
        if p.is_file()
    ]
    assert found, "no Dockerfile found"
    for path in found:
        users = re.findall(r"^\s*USER\s+(\S+)", path.read_text(encoding="utf-8"), re.M)
        assert users, f"{path}: no USER line"
        assert users[-1] not in ("root", "0", "0:0"), path


def requirement_names(path):
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[\s\[=<>!~;]", line, maxsplit=1)[0]
        names.add(name.lower().replace("_", "-"))
    return names


def test_runtime_requirements_exclude_jwt_libraries_and_dev_tools():
    """H3: unused JWT stack removed; dev tools go in requirements-dev.txt."""
    names = requirement_names(BACKEND_DIR / "requirements.txt")
    for banned in ("python-jose", "ecdsa", "rsa", "passlib", "bcrypt"):
        assert banned not in names, banned
    for dev_tool in ("pytest", "mypy", "ruff", "bandit", "pip-audit"):
        assert dev_tool not in names, dev_tool
    assert (BACKEND_DIR / "requirements-dev.txt").is_file()


def test_rate_limiter_has_reset_hook_for_tests():
    from app import rate_limiter

    assert callable(getattr(rate_limiter, "reset_rate_limits", None))
