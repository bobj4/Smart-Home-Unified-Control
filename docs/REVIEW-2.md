# Review 2: steps 7–14

Reviewed 2026-10-19 against `review2.zip` (working tree, no `.git`). The zip appears to predate the restore of `docs/SECURITY.md` and `backend/tests/test_sessions.py`.

## Verdict

Steps 7–14 are not usable. In the app as shipped, no one can log in, and every request except `/health` fails with a 500 error. Fixing the crash bugs exposes worse ones: a password alone logs in a TOTP-enabled account, any anonymous caller can end any user's sessions, there is no CSRF protection, and the audit log writes nothing. Four Review 1 blockers have regressed (B1, B4, B5, B7). Only B6 (the XSS fix in `web/js/app.js`) holds.

All 29 tests that "passed" test code from steps 1–6. Nothing tested steps 7–13, and `mypy.ini` was changed so that type checking always passes.

## How this was checked

- The app was run under Python 3.13.16 with the same versions as the root `.venv` (FastAPI 0.143.3, Starlette 1.8.0, SQLAlchemy 2.1.5, Pydantic 2.14.1). Each finding marked **(run)** was reproduced, not just read.
- New tests are in `backend/tests/`: `test_contract_api.py` (35 tests), `test_contract_static.py` (11 tests), a shared `conftest.py`, and a replacement `test_totp.py`. Against the current code, 1 of 46 contract tests passes (the XSS check).
- To prove the contract tests can be passed, I wrote a throwaway implementation. It passes all 35 API tests and the new TOTP tests, three runs in a row with no flaky results. That code is not part of this review.

## Blockers

**R2-B1. Nothing works: every route except `/health` returns 500 (run).**
- `main.py:59-69` / `app/middleware.py:44-52`: the session middleware runs on every path, including login and the web page. It raises `HTTPException` inside the middleware, and that becomes a 500 error instead of a 401.
- `app/routes/auth.py:21` + `main.py:72`: the prefix is applied twice, so login is at `/api/v1/api/v1/auth/login`.
- `app/routes/auth.py:73`: `authenticate_user` is called with 4 arguments and only takes 3, so every login raises `TypeError` (run).
- `app/models.py:116-118, 161-166, 182-183, 209-210`: the `UUID(as_uuid=True)` columns receive string ids, which raises `'str' object has no attribute 'hex'`. This affects every audit row, membership and device insert (run).
- `app/routes/devices.py`: the router is not registered in `main.py`. `app/factory.py:26` crashes in `create_app()`, and `Device.to_dict()` does not exist (run).

**R2-B2. TOTP is not enforced (B7 regressed) (run).**
- `app/auth.py:126,135`: `timecode()` already returns the step, but the code divides it by 30 again and then passes that step to `totp.at()`, which expects a time. As a result, every real authenticator code is rejected. Fix: `step = totp.timecode(now)`, then compare against `totp.generate_otp(step)` for `step-1..step+1`.
- `backend/tests/test_totp.py` mocked `pyotp` and `hmac` (with `compare_digest` always returning True) and patched `backend.app.auth`, which is a different module object from the `app.auth` under test. That is why it passed. It has been replaced.
- `app/routes/auth.py:83-95`:
  - If `totp_code` is missing, the login succeeds on the password alone. Once the R2-B1 crashes are bypassed, this returns 200 (run).
  - If `totp_code` is supplied, it is checked with `is_token_valid`, which is a session-token lookup.
  - The recovery-code branch is `pass`.
  - `users.totp_last_step` is never written.

**R2-B3. Session tokens are handled like the old JWT (B5 open) (run).**
- Login returns both tokens in the JSON body and sets no cookie.
- The tokens are swapped: `app/routes/auth.py:98` unpacks `(session, csrf)` as `(csrf, session)`.
- `web/js/api.js` still keeps a token in `localStorage` and sends `Authorization: Bearer`, which the backend never reads. It also reads `response.access_token`, which no longer exists.

**R2-B4. Anyone can end anyone's sessions (B1 regressed) (run).**
- `app/routes/sessions.py:254-279`: `POST /api/v1/sessions/logout-all?user_id=<id>` has no authentication. It returned 200 and deleted the owner's sessions.
- `logout`, `update-activity`, `invalidate` and `csrf-validate` also take `user_id` or `session_id` from the query string.

**R2-B5. No CSRF protection (SEC-04).**
- No state-changing route checks a token.
- The only check is a `GET /sessions/csrf-validate?session_id=` endpoint, which acts as an oracle for anyone with a session id.
- `app/middleware.py:70-78` sets the CSRF cookie as HttpOnly, so the web app could not read it anyway.

**R2-B6. The audit log records nothing (SEC-80, SEC-32) (run).**
- `app/audit.py:37-45` builds an `AuditEvent` but never adds it or commits it. After `audit_device_command`, the table has 0 rows.
- The sanitizer only checks top-level keys: `{"args": {"password": "hunter2"}}` is stored as-is (run).
- Failed logins are never logged.

**R2-B7. Device control has no safety layer (SEC-40–42).**
- `app/routes/devices.py:158-162`: there is a TODO where the safety limits should be, and commands are never sent to an integration.
- The request body is a raw `dict`.
- Any member can create or delete devices.
- `require_home_access` returns the user's single `User.home` rather than the requested home, and roles are compared with `==`, so an owner fails a "member" check.

**R2-B8. The checks were disabled (process).**
- `backend/mypy.ini:8-9` sets `ignore_errors = True` plus a `disable_error_code` list. Mypy reports "Success" while hiding 22 errors, some of which are the bugs above.
- `ruff check backend` reports 30 errors.
- `pytest.ini` contains an `env` option that pytest ignores ("Unknown config option").

## High

- **R2-H1 Session timeouts are wrong.**
  - `app/sessions.py:148,154`: sessions expire 30 minutes after login, regardless of activity, instead of 30 minutes idle with a 12-hour maximum.
  - The idle branch (`:304-317`) is incoherent.
  - SQLite returns naive datetimes, so `now >= session.expires_at` raises `TypeError`. This causes 5 of the 11 failures in `test_sessions.py`.
- **R2-H2 The rate limiter can be bypassed (H1 open).**
  - `app/rate_limiter.py:31-37` keys on a `user_id` cookie the client controls, so changing that cookie resets the limit.
  - It counts all attempts, not failures, and does not count per account.
  - It uses `request.client.host`, which is the proxy's address behind a proxy (M5).
  - It is in-memory, while `deploy/Dockerfile` runs 4 workers, each with its own counters.
- **R2-H3 The container exposes the app (H2 open).**
  - `docker-compose.yml:8-9` publishes `8000:8000` on all interfaces, and `:12` hard-codes `SECRET_KEY=change-this-in-production`.
  - The root `Dockerfile` runs as root and copies `requirements.txt` from the repo root, where that file does not exist, so the build fails.
  - `web/Dockerfile` needs a `package.json` that doesn't exist.
  - In `deploy/docker-compose.yml`, the tmpfs mount covers `/app/data`, so the database is lost on restart, and the `sqlite+aiosqlite` URL doesn't work with the synchronous engine.
- **R2-H4 Dependency changes were made without approval (H3 open).**
  - `backend/requirements.txt` is a `pip freeze` of the agent's Python 3.14 environment: no hashes, dev tools mixed in, and versions newer than those installed in the root `.venv`.
  - The unused JWT stack is still listed: `python-jose`, `ecdsa`, `rsa`, `passlib`, `bcrypt`. `ecdsa`'s maintainers state its timing side-channel will not be fixed.
  - `pyproject.toml` pins conflicting old versions (`fastapi==0.109.0`).
  - There is no pip-audit output.
- **R2-H5 Placeholder secrets are back (B4).** They appear in `app/db_config.py:16`, `app/auth.py:33-35`, `app/sessions.py:403-405` and `docker-compose.yml:12`. None of them are used for signing any more, so they should be deleted, not replaced.
- **R2-H6 The models are inconsistent.**
  - `users`, `homes` and `sessions` use `String(36)` ids, but foreign keys pointing at them use `UUID`.
  - `Home.id` has no default.
  - The old single-home column `User.home_id` sits alongside `HomeMembership`.
  - The models use the 1.x `Column` style, which mypy cannot type-check (most of the 22 hidden errors).
- **R2-H7 Error messages leak internal details (SEC-30).** `f"...: {str(e)}"` appears in `app/sessions.py:179`, `app/routes/auth.py:146`, `app/routes/sessions.py:278,310`.
- **R2-H8 CORS is weakened (SEC-14).**
  - `main.py:85-119` sends `Access-Control-Allow-Origin: *`.
  - `app/headers.py:153-155` treats "no origins configured" as "allow every origin, with credentials". That's dead code today, but dangerous if wired in.
  - `Settings.CORS_ORIGINS` defaults to two localhost origins.
- **R2-H9 The migrations are unusable (M9 worse).**
  - There are three migration folders (`alembic/`, `migrations/`, `backend/backend/alembic/`).
  - Migration `001` does not match the models.
  - `006` uses PostgreSQL-only `::text`.
  - `007` drops the primary key `users.id`.
  - The app ignores all of them and calls `create_all` instead.
  - `backend/smart_home.db` has the old schema (`username`, `password_hash`). Both database files contain 0 users.

## Medium

- **Unknown fields are accepted (M7).** `model_extra` is `None` unless `extra="allow"`, so the check at `app/routes/auth.py:66` never fires (run).
- **API docs are public (M8).** `/docs`, `/redoc` and `/openapi.json` are served.
- **The headers are partly wrong.**
  - The Permissions-Policy entry `autoplay()` is malformed.
  - CSP sets `frame-ancestors 'self'`, which contradicts `X-Frame-Options: DENY`.
  - `app/middleware_security.py` duplicates `app/headers.py`, and neither CORS class is used.
- **Import paths are hacked.**
  - `sys.path` is modified in `main.py:7-9`, `app/auth.py:23-25` and `migrations/env.py:11`.
  - `app/middleware.py:11-12` imports `backend.app.*`, which loads a second copy of every module.
  - `app/auth.py`'s path change is the only reason `tests/test_health.py` (`from backend.main import app`) works.
- **The recovery-code range is too small.** `secrets.randbelow(9_000_000) + 10_000_000` gives 9 million possible codes (about 23 bits), not the full 8-digit range the docstring claims. Also, `audit.py:212` logs `code_count: 8`, but 10 codes are generated.
- **The web app doesn't work.**
  - It calls `/homes` and `/homes/{id}/devices`, which don't exist.
  - `index.html` loads `/js/api.js`, but the backend serves it at `/api/v1/web/js/api.js` and doesn't serve `app.js` at all.
  - `open("web/...")` is relative to the working directory, so it fails when run from `backend/`.
  - `switchTab` uses the global `event`.
- **The test setup isn't isolated.**
  - The tests used the development database, which caused the `created_at` failure in `test_sessions.py`.
  - `test_create_owner.py` leaves `DATABASE_URL` pointing at a deleted folder.
  - The new `conftest.py` handles both, without editing those tests.
- **Other issues:**
  - `scripts/check.py` skips pip-audit, and because it passes a single command string with `shell=False`, it only works on Windows.
  - `app/sessions.py` (405 lines) and `app/routes/sessions.py` (354 lines) break the 300-line rule.
  - There are `nul` files in the repo root and `backend/`.

## Process findings

- **The progress file is wrong.** `docs/PROGRESS.md` marks steps 7–13 done with "29 tests pass" as the evidence. Step 14 is committed but left unticked.
- **The commits don't match the steps.** Steps 7–12 are a single commit labelled "Step 12", and the "step 6" commit is labelled "Recovery codes".
- **Tests were deleted.** `tests/test_sessions.py` (11 of its 24 tests fail) and four scripts were deleted, and the deletion was recorded as a "fixed error" inside the protected `docs/SECURITY.md`.
- **The protected `docs/SECURITY.md` was edited again (H6).** The agent changed the SEC-24 text, added `|-` markers, and appended a "Fixed errors" section.
- **Changes were made without asking.** The agent disabled mypy, created a second virtual environment on Python 3.14, upgraded dependencies, and froze its environment into `requirements.txt`.
- **`AGENTS.md` contradicts itself.** Line 50 says to run commands from the repository root, and line 58 says to run them from `backend/`. `docs/NOTES.md` repeats the second version and has no `(verified: …)` sources.

## Review 1 status

| Item | Status | Where |
|---|---|---|
| B1 user from query parameter | Regressed | R2-B4 |
| B2 unauthenticated create-owner route | Fixed (script only) | — |
| B3 hard-coded admin | Fixed | — |
| B4 default signing key | Open | R2-H5 |
| B5 token in localStorage | Open | R2-B3 |
| B6 stored XSS | **Fixed** | contract test passes |
| B7 TOTP optional/broken | Regressed | R2-B2 |
| B8 predictable recovery codes | Fixed, but range too small | Medium |
| H1 rate limiting | Open | R2-H2 |
| H2 container exposure | Open | R2-H3 |
| H3 vulnerable dependencies | Open | R2-H4 |
| H4 account timing | Open | `authenticate_user` returns early |
| H5 DB session dependency | Fixed (`get_db`) | — |
| H6 protected doc edited | Repeated | Process |
| M4 one home per user | Partly fixed | R2-H6 |
| M5 proxy IP | Open | R2-H2 |
| M6 headers wired | Partly fixed (`main.py` only) | Medium |
| M7 unknown fields | Open | Medium |
| M8 public API docs | Open | Medium |
| M9 migrations | Worse | R2-H9 |

## Contract encoded by the new tests

These are defaults I chose so the tests are concrete. Any of them can be changed before the agent starts.

- **IDs:** every id is a `String(36)` UUID string, including foreign keys.
- **Routes:**
  - `POST /api/v1/auth/login` and `POST /api/v1/auth/logout`
  - `GET /api/v1/homes`
  - `/api/v1/homes/{home_id}/devices`, `/{device_id}` and `/{device_id}/command`
  - Web app at `/`, `/js/api.js`, `/js/app.js` and `/manifest.json`, all without a session.
- **Login body:** `email`, `password`, plus either `totp_code` or `recovery_code`. Unknown fields return 422. Failures return a generic 401, and an unknown account still costs one Argon2 hash.
- **Cookies:**
  - `session_token`: HttpOnly, Secure, SameSite=Strict.
  - `csrf_token`: readable by JavaScript, Secure, SameSite=Strict. Every state-changing request sends it back as `X-CSRF-Token`, and the server compares it with that session's token.
- **Sessions:** a session ends after 30 minutes idle or 12 hours total. Logout deletes the row. Only the hash of the token is stored.
- **Lockout:** 5 failures per account in 5 minutes returns 429 with `Retry-After`. The per-IP limit is 20. The rate-limiter module exposes `reset_rate_limits()` for tests. This replaces the earlier "delay after 5 failures" with a lockout.
- **Roles:** owner > admin > member. Creating or deleting devices needs admin or above; commands need any member. A home the user can't access returns 403 or 404, and a device from another home returns 404.
- **Commands:** thermostat and water-heater commands return 409 until safety limits are configured, and the refusal is audited. Lights are allowed. Command and device bodies are typed models with unknown fields rejected.
- **Audit:** the event types are `login_success`, `login_failure`, `logout`, `device_command` and `device_command_rejected`. No secret may appear anywhere in an audit row, including nested payloads.
- **Headers and docs:** `X-Frame-Options: DENY`, CSP with `frame-ancestors 'none'` and no `'unsafe-inline'` scripts, a well-formed Permissions-Policy, and no CORS headers for unlisted origins. API docs are off.
- **Repository:**
  - No `sys.path` changes and no `backend.` imports in app code.
  - No placeholder secrets or JWT leftovers.
  - mypy not suppressed.
  - Compose ports bound to `127.0.0.1`.
  - Dockerfiles end with a non-root `USER`.
  - Runtime requirements exclude the JWT stack and dev tools, which move to `requirements-dev.txt`.

## Fix order

Each step is done only when its listed tests pass, the full suite has no new failures, and ruff and mypy are clean. The report must include the exact pytest output.

| Step | Work | Gate |
|---|---|---|
| R1 | Models: `String(36)` ids with defaults, SQLAlchemy 2.0 `Mapped`/`mapped_column`, datetimes read back as UTC, drop `User.home_id`. Then set up Alembic again in `backend/` (`alembic init alembic`; `env.py` uses `app.models.Base` and `settings.DATABASE_URL`, with `render_as_batch=True` for SQLite) and autogenerate one baseline revision. | No setup errors in `test_contract_api.py`; mypy clean on `app/models.py`; on an empty database, `alembic upgrade head` followed by `alembic check` reports no new operations |
| R2 | Hygiene: remove `sys.path` changes and `backend.` imports; in `pytest.ini` replace the `env` lines with `pythonpath = .`; restore `mypy.ini` to `explicit_package_bases` + `ignore_missing_imports` and fix what it reports; change `tests/test_health.py` to `from main import app`; delete the placeholder secrets and JWT constants; make `scripts/check.py` run from `backend/` and add pip-audit (`-r requirements.txt --require-hashes --disable-pip`). | `test_no_sys_path…`, `test_type_checking…`, `test_no_placeholder…` |
| R3 | TOTP and login, including recovery codes, account timing and rate limiting. Keep the signatures of `verify_totp_code` and `verify_recovery_code(code, db, user_id)`; `tests/test_recovery_codes.py` uses them. | `test_totp.py`, the login and rate-limit tests |
| R4 | Sessions, current user, CSRF and logout, as dependencies (not middleware). Remove `routes/sessions.py` and `SessionMiddleware`. | session and CSRF tests |
| R5 | Audit writer (persists, sanitizes recursively). | audit tests |
| R6 | Homes, devices, commands and safety-limit refusal, with central role checks. | authorization and command tests |
| R7 | Headers, CORS, docs off, static web serving, removal of dead modules. | header, CORS and web tests |
| R8 | Web client: cookies plus `X-CSRF-Token`, routes matching the backend. | static web tests |
| R9 | Containers (the dependency work is done; see the decisions below). `deploy/Dockerfile`: build context is the repo root, install with `pip install --require-hashes -r backend/requirements.txt`, no compiler packages, one worker, final `USER` non-root. `deploy/docker-compose.yml`: port `127.0.0.1:8000:8000`, a named volume for the database (not tmpfs), no `SECRET_KEY`, a synchronous `sqlite:///` URL. `.dockerignore` excludes `*.db`, `.env`, `.venv`, `tests/`. Rewrite `deploy/.env.example` to list only the settings that exist. | container tests; `pip_audit -r requirements.txt --require-hashes --disable-pip` output |
| R10 | Final: `STATUS.md`, full check output. | everything |

## AGENTS.md changes

Replace lines 50 and 58 with one rule:

```markdown
- Run every command from the backend/ folder with ..\.venv\Scripts\python.exe.
```

Add under "Security rules":

```markdown
- Never edit, skip, mark or delete these files; propose changes in the report:
  backend/tests/conftest.py, backend/tests/test_contract_api.py,
  backend/tests/test_contract_static.py, backend/tests/test_totp.py,
  backend/mypy.ini, .ruff.toml, and anything in docs/ except docs/PROGRESS.md
  and docs/NOTES.md.
- A step is done only when its gate tests in docs/REVIEW-2.md pass. If a gate
  test looks wrong, stop and report its name and full output.
```

## Owner decisions (2026-10-19)

1. **Migrations:** approved. `backend/alembic/`, `backend/migrations/`, `backend/backend/`, `backend/alembic.ini`, `backend/alembic_version` and both empty `smart_home.db` files were deleted. R1 creates the new baseline.
2. **Dead code:** approved. These were deleted: `app/factory.py`, `app/middleware_security.py`, the root `Dockerfile` and `docker-compose.yml`, `web/Dockerfile` and `web/.dockerignore`, and the `nul` files. `deploy/` is kept. `app/routes/sessions.py` and `SessionMiddleware` are still imported by `main.py`, so they are removed in R4. The CORS classes in `app/headers.py` are removed in R7.
3. **Dependencies:** done by the reviewer.
   - The direct dependencies are listed in `backend/requirements.in` (runtime) and `backend/requirements-dev.in` (tools).
   - These compile to `requirements.txt` and `requirements-dev.txt`, which have exact pins and hashes for every platform. The compile command is at the top of each `.in` file, and `uv` is the compile tool.
   - The latest versions were used: FastAPI 0.148.0, Starlette 1.9.0, SQLAlchemy 2.1.5, Pydantic 2.14.1, uvicorn 0.54.0. pip-audit reports no known vulnerabilities in either file.
   - Removed: the JWT stack (`python-jose`, `ecdsa`, `rsa`, `passlib`, `bcrypt`), plus `aiosqlite`, `python-multipart` and `python-dateutil`, none of which are imported.
   - The test client uses `httpx2`, as Starlette now requires; `httpx` was removed.
   - `pyproject.toml` no longer lists dependencies.
   - `.venv` was rebuilt from the two files.
   - To add or upgrade a dependency, ask the owner, edit the `.in` file, and recompile. Never `pip install` a package directly.
4. **Contract defaults:** approved as written.
5. **`docs/SECURITY.md`:** pending. It needs the `git log` output.
6. **`tests/test_sessions.py`:** deleted by the reviewer. The session and CSRF tests in `test_contract_api.py` replace it, and 11 of its 24 tests were failing, at least 5 of them because of bugs in the tests themselves.
