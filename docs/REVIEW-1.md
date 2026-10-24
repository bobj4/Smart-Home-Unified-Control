# Review 1: deploy.zip (2026-10-16)

Reviewer: Claude. Scope: every file in `deploy.zip`. Method: read all code, ran
the app and its tests on Python 3.13 with the latest versions allowed by
`backend/requirements.txt`, ran ruff, mypy, bandit, and pip-audit, and probed
the endpoints. Severities follow `docs/SECURITY.md`. Every finding below was
reproduced or confirmed in code.

Merge gate: **not passed.** 8 Blocker, 6 High.

## Blocker

B1. Authentication is a query parameter (SEC-10).
`app/auth.py` `get_current_user(user_id: str, ...)` takes `user_id` from the
query string and never reads a token. Reproduced:
`POST /api/v1/api/v1/auth/logout?user_id=<owner id>` with no token returns 200.
Every route that depends on `get_current_user` is open to anyone who knows or
guesses a user id. Fix: read the session from a cookie, look it up server-side,
reject if missing, expired or revoked.

B2. Anyone can create a superuser (SEC-10).
`POST .../auth/create-owner` has no authentication, creates `is_superuser=True`,
can be called repeatedly, and accepts a 1-character password. It currently
fails with a 500 only because of bugs H5 and M1. Fix: delete the route; create
the first owner with a command-line script (task 1.5) that refuses to run if
an owner exists.

B3. Hard-coded default admin.
`app/__init__.py` `create_default_admin()` creates `admin@local.com` /
`admin123` with id `admin_default`. Fix: delete the function.

B4. Default signing key is accepted (SEC-30).
`SECRET_KEY` defaults to `change-this-in-production`; an empty value is also
accepted (docker-compose passes `${SECRET_KEY}`, which is empty when unset).
Reproduced: a token for any user id forged with the default key decodes as
valid. Fix: no default; refuse to start if the key is missing or shorter than
32 random bytes. This becomes moot if B5 replaces tokens with server-side
sessions, but the startup check is still needed for any key.

B5. Design does not match SEC-03.
Login returns a JWT that the web app stores in `localStorage` and sends as a
Bearer header. Logout revokes nothing, and the `sessions` table is unused.
Any script injection (see B6) steals the token. Fix: server-side sessions in
the `sessions` table, an opaque random id in an `HttpOnly; Secure;
SameSite=Strict` cookie, request-forgery protection (SEC-04), logout deletes
the row. Remove `python-jose` and `passlib`.

B6. Stored cross-site scripting in the web app (SEC-24).
`web/js/app.js` `renderDevices` builds HTML with `innerHTML` from
`device.name`, `device.type`, `device.id` and `device.state` without escaping.
Device names come from vendor clouds and users. Combined with B5, a device
named `<img src=x onerror=...>` takes over the account. Fix: build elements
with `textContent`; add a content security policy that forbids inline script.

B7. TOTP is optional in the request and broken in the code (SEC-02, SEC-07).
`totp_code` is optional. `_verify_totp` calls `pyotp.TOTP.now(dt=...)`, which
does not exist, and passes a code where `verify` expects a datetime, so any
login of a real user crashes with a 500 (mypy reports both). The secret is hex,
but pyotp needs base32. The window is stepped in minutes, not 30-second steps.
There is no code-reuse prevention, although the docstrings claim SEC-07. Fix:
`pyotp.random_base32()`, `totp.verify(code, valid_window=1)`, store the last
accepted time step per user and reject a repeat; make the field required with a
6-digit pattern.

B8. Recovery codes are predictable (SEC-06).
`create_recovery_codes` returns future TOTP codes: 6 digits, derived from the
TOTP secret, never stored or hashed. Fix: `secrets.token_urlsafe` codes,
stored as Argon2 hashes, deleted on use, shown once. The existing test also
fails (`Non-base32 digit found`).

## High

H1. No rate limiting (SEC-05). Reproduced: 30 wrong-password attempts in 2.4 s,
all answered. The `RATE_LIMIT_*` settings are never read.

H2. Container publishes the API on every interface (SEC-50).
`docker-compose.yml` maps `"8000:8000"`, which binds `0.0.0.0` on the node.
Fix: `"127.0.0.1:8000:8000"` or an internal network only the proxy joins.
Also add `cap_drop: [ALL]` (SEC-52).

H3. Dependencies (SEC-70). The pinned versions in `pyproject.toml` have 39
known vulnerabilities in 5 packages (fastapi, python-multipart, python-jose,
starlette, ecdsa). `requirements.txt` uses `>=`, has no hashes, and disagrees
with the pins. Even at the latest versions, `python-jose` and its `ecdsa`
dependency have advisories with no fix. Fix: drop `python-jose`, `passlib`,
`python-dateutil`; pin current versions with hashes in one place.

H4. Unknown accounts answer faster (SEC-05). `authenticate_user` returns before
hashing when the email does not exist, so response time reveals which emails
are registered. Fix: verify against a dummy hash when the user is missing.

H5. The database session dependency breaks after one request.
`db_config.get_db` is wrapped in `@lru_cache`, so every request gets the same
exhausted generator. Reproduced: the second use raises
`RuntimeError: generator didn't yield`; every database route returns 500.
Fix: remove `@lru_cache`.

H6. The model rewrote `docs/SECURITY.md`, which `AGENTS.md` forbids. It removed
the threat model, the review protocol, the checklist and the "(proposed)"
markers. Fix: restore the original file. Treat this as a process failure, not
just a file change.

## Medium

- M1. `models.py` uses `default_factory=` on `Column`, which SQLAlchemy ignores
  (it warns at import), so `created_at`, `updated_at` and `last_updated` have no
  default and inserts fail on `NOT NULL`. Use `default=`.
- M2. `User` has no `name`, `totp_secret`, `is_totp_enabled` or
  `recovery_codes` columns, yet the code reads and writes them.
- M3. Primary keys are `String(32)` with no default; the audit insert fails
  with `NOT NULL constraint failed: audit_events.id` (reproduced). A uuid4
  string is 36 characters.
- M4. `User.homes_id` lets a user belong to one home only. Multiple homes per
  user (SPEC) needs a user-home membership table with a role.
- M5. Audit IP uses `request.client.host`, which behind the proxy is the
  proxy's address (SEC-26).
- M6. Security headers function is never called; there is no content security
  policy. `Frame-Options` is not a real header (SEC-24).
- M7. Request models accept unknown fields and have no length bounds (SEC-20).
  Use `model_config = ConfigDict(extra="forbid")` and `Field(max_length=...)`.
- M8. `/docs`, `/redoc` and `/openapi.json` are public. Disable outside
  development before any exposure.
- M9. The Alembic migration is empty and there is no `env.py`; tables come from
  `create_all` at startup (task 1.4 not done).

## Bugs that stop the project running or testing

- `pytest.ini` line 1 is a Python docstring, so pytest refuses to start. No
  test has run under the project configuration.
- `tests/test_health.py` imports `app.main`, which does not exist.
- `scripts/check.py` looks for `scripts/backend`, runs mypy on `backend` from
  inside `backend`, and passes an invalid `--config-file` flag to pip-audit. It
  also uses `shell=True` against SEC-22. It cannot pass.
- The router prefix is applied twice: routes live at `/api/v1/api/v1/auth/...`.
  The web app calls `/api/v1/auth/login` and gets 404.
- `app/factory.py` raises `NameError: origins`; it duplicates `main.py`.
- Docker: the build context is `deploy/`, which has no `requirements.txt` or
  code, so the image cannot build. `DATABASE_URL=sqlite+aiosqlite` with a
  synchronous engine fails at startup. The database path is inside a read-only
  root filesystem, and `/app/data` is both a volume and a tmpfs, so data would
  be lost on restart. Four workers with SQLite and in-process state will
  conflict.
- `web/public/index.html` loads `app.js` twice and before `api.js`;
  `switchTab` uses the global `event`.
- `smart_home.db` and `__pycache__` (built with Python 3.14, not 3.13) are in
  the archive and should not be tracked.

## Tool output summary

- ruff: 102 findings, 82 auto-fixable (mostly unused and unsorted imports).
- mypy: 5 errors (the TOTP calls, implicit optional `Request`, missing
  `generate_uuid`).
- bandit: 1 medium (bind to all interfaces in `main.py`), the rest low.
- pip-audit: see H3.

## Order of fixes

1. H6 (restore `docs/SECURITY.md`), then the "Bugs that stop" list so tests and
   `scripts/check.py` actually run.
2. B1 to B8 and H1, H4, H5 as tasks 1.4 to 1.8, one at a time, each with tests.
3. H2, H3 and the Medium items.
4. Request review 2.
