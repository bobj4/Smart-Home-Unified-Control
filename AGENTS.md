# Repository instructions

## Scope

This repository builds a self-hosted smart-home control system: a Python FastAPI
backend, an installable web app (PWA), and device integrations for Cync lights,
the Cync thermostat, Samsung TVs, a Rheem water heater (EcoNet), and Frigate.
This file is the only project file loaded automatically. Read the documents
listed below only when the task needs them.

## Operating principles

- Working code only. Plausibility is not correctness; verify before reporting
  done.
- Never fabricate file paths, APIs, library functions, commit hashes, command
  output, or test results. Read the file, run the command, or say what is
  unknown.
- Say when a premise appears wrong before implementing around it.
- Ask before proceeding only when a request has multiple plausible
  interpretations and the choice materially affects the result.
- Touch only what the task requires. Avoid drive-by refactors, formatting, or
  cleanup.
- Keep communication direct and concise. Skip flattery, filler, and emoji.
- Use only C:/Users/oracn/Downloads/Application/.venv/Scripts/python.exe for every Python command. Never create another virtual environment.

## Working in small steps

- Work on one step at a time: the next unticked step in `docs/PROGRESS.md`
  (the steps and their plan are named at the top of that file), otherwise
  the next `TASKS.md` item. Finish and verify it
  before starting the next.
- State the plan and the verification you expect to run before editing.
- Before editing, find the code and the callers and tests that define its
  behavior with search (grep), then read only those parts.
- Match the existing layout, naming, and style.
- Keep source files under 300 lines. Split by responsibility when they grow.
- Check that a library function exists in the installed version before using
  it, as SOUL.md describes (`inspect.signature`, never `help()` on a module).
- Read complete errors before fixing. If one fix fails twice, stop and report
  what you tried.
- Never add, remove, or upgrade a dependency, and never `pip install` a
  package. Ask the owner; approved changes go in `backend/requirements.in` or
  `backend/requirements-dev.in` and are recompiled with the command at the
  top of that file. Prefer the standard library. Never invent cryptography,
  password hashing, or token formats; use argon2-cffi, pyotp, and the
  `secrets` module.
- Do not add speculative features, abstractions, or configuration.
- Ask before deleting files outside the working tree, force-pushing, resetting
  history, or running anything with elevated privileges.

## Commands

Run every command from the `backend/` folder with `../.venv/Scripts/python.exe`:

- Lint: `../.venv/Scripts/python.exe -m ruff check .`
- Format: `../.venv/Scripts/python.exe -m ruff format .`
- Types: `../.venv/Scripts/python.exe -m mypy app main.py`
- Tests: `../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider > ../pytest-last.txt 2>&1; tail -n 40 ../pytest-last.txt`
- If a command was moved to the background, read its result with `tail -n 40 ../pytest-last.txt`. Never run tasklist, ps or sleep.
- Security lint: `../.venv/Scripts/python.exe -m bandit -r app main.py`
- Dependency audit: `../.venv/Scripts/python.exe -m pip_audit -r requirements.txt --require-hashes --disable-pip`
- All checks at once: `../.venv/Scripts/python.exe ../scripts/check.py`
- Write every file path with forward slashes (backend/app/models.py or C:/Users/...). Never use backslashes in paths: the shell is bash and drops them.
- Import project code as `app.<module>`. Never use `backend.app` or change `sys.path`.
- Never start uvicorn or any other server. Test HTTP behaviour with pytest only.
  The browser tests in tests/test_ui.py start and stop their own server; that
  is the only allowed way.
- Run every check in the foreground, from backend/, with the exact commands
  above. Never run a command in the background, and never wait for one by
  polling with tasklist, sleep or repeated status checks.
- If a command does not finish within the terminal timeout, stop it and run
  `../.venv/Scripts/python.exe -m pytest -x -v` from backend/ to find the test
  that hangs. Record the test name under "Blocked" and stop.

Run the smallest relevant test after each change and every check before
reporting a task done. If a check fails, fix the cause; do not weaken the check.

## Documentation routing

- `SPEC.md`: requirements, boundaries, acceptance criteria.
- `ROADMAP.md`: phases, risks, exit criteria.
- `TASKS.md`: current tasks and status.
- `docs/PLAN-UI.md`: the settings API and the web app contract (done).
- `docs/PLAN-RHEEM.md`: steps E1-E6, the Rheem EcoNet integration.
- `docs/SECURITY.md`: security requirements (`SEC-*` IDs) and the review
  checklist. Read it before any change to login, sessions, permissions,
  secrets, network calls, updates, plugins, or device limits.
- `docs/CYNC_THERMOSTAT_PROTOCOL.md`: unverified notes on the Cync thermostat
  protocol. Read it before working on that integration.
- `docs/LOCAL_MODEL.md`: model and runtime settings. Not needed for coding
  tasks.

Do not edit `SPEC.md`, `ROADMAP.md`, or anything in `docs/` except
`docs/PROGRESS.md` and `docs/NOTES.md`. Propose changes in the task report. In
`TASKS.md`, tick the box only for a task that is verified.

## Security rules

- Every route requires an authenticated user except `/health` and the login
  flow.
- Check the caller's access to the home on every query for homes, devices,
  automations, and cameras.
- Validate all input with Pydantic models. Use SQLAlchemy bound parameters
  only.
- Never pass external input to a shell, `eval`, `exec`, or `pickle`.
- Enforce device safety limits in the backend on every command path.
- Keep credentials and tokens out of source, logs, and error messages. Read
  configuration from environment variables.
- Make outbound requests only to hosts the integration declares.
- Use recorded fixtures and the simulated integration. Do not call real vendor
  services, devices, or Frigate; the owner runs those manual tests.
- Never edit, skip, mark, or delete these files; propose changes in the report:
  `backend/tests/conftest.py`, `backend/tests/test_contract_api.py`,
  `backend/tests/test_contract_static.py`, `backend/tests/test_totp.py`,
  `backend/tests/test_safety_limits.py`,
  `backend/tests/test_contract_settings.py`,
  `backend/tests/test_contract_features.py`, `backend/tests/test_ui.py`,
  `backend/tests/test_rheem.py`, `backend/tests/test_ui_rheem.py`,
  `backend/tests/test_samsung.py`, `backend/tests/test_two_factor.py`,
  `backend/tests/test_ui_tv_security.py`,
  `backend/tests/test_lights.py`, `backend/tests/test_frigate.py`,
  `backend/tests/test_preferences.py`, `backend/tests/test_admin.py`,
  `backend/tests/test_refresh.py`, `backend/tests/test_https.py`, `backend/tests/test_samsung_encrypted.py`, `backend/tests/test_backup.py`, `backend/tests/test_deploy.py`, `backend/tests/test_cync.py`, `backend/tests/test_roles.py`, `backend/tests/test_device_settings.py`, `backend/tests/test_accounts.py`, `backend/tests/test_package1.py`, `backend/tests/test_groups.py`, `backend/tests/test_water_heater.py`, `backend/tests/test_thermostat.py`, `backend/app/integrations/cync_thermostat.py`, `backend/app/mailer.py`, `backend/app/integrations/cync.py`, `deploy/Dockerfile`, `deploy/docker-compose.yml`, `backend/app/backup.py`, `backend/app/tls.py`,
  `backend/app/integrations/rheem.py`, `backend/app/integrations/samsung.py`,
  `backend/app/integrations/frigate.py`,
  `backend/mypy.ini`, `.ruff.toml`, `backend/requirements*.in`,
  `backend/requirements*.txt`, and the shared security code:
  `backend/app/dependencies.py`, `backend/app/sessions.py`,
  `backend/app/rate_limiter.py`, `backend/app/headers.py`,
  `backend/app/authorization.py`. No step needs to change them. If a test
  seems to need a change there, the new code is using them wrongly: read how
  an existing route (app/routes/safety_limits.py) uses them and do the same.
  A git hook refuses commits that touch any of these files.
- Never delete any test file.
- Stop and flag for security review before merging any change to
  authentication, sessions, permissions, encryption, updates, plugin loading,
  network exposure, or safety limits.

## Unattended run

Work through the steps in `docs/PROGRESS.md` in order without waiting for the
owner. The steps, their gate tests and the full contract are in the plan
named at the top of `docs/PROGRESS.md`. For each step:

1. Run the step's gate tests from `backend/` (the files and `-k`
   expression are in the plan's Steps table):
   `../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider <files> -k "<expression>" > ../gate.txt 2>&1; tail -n 40 ../gate.txt`
2. If any fail, delegate the first failing test only, with `delegate_task`:
   "Make <test name> pass. Follow 'Building new behaviour' in SOUL.md."
   Pass the test's source code, its failure output from `../gate.txt`, the
   step's section of the plan (for web app steps also the "Web app
   contract" rules in `docs/PLAN-UI.md`), and `docs/NOTES.md`. One test per delegation.
   When it returns, go back to 1. Tests that an earlier fix already made
   pass need no delegation.
3. When every gate test passes, run from `backend/`: ruff check, ruff
   format --check, mypy and the full test suite (commands above). The step
   is done only when no test that passed before the step now fails and ruff
   and mypy are clean. Then commit as `<step id>: <title>`, tick it in
   `docs/PROGRESS.md` with the files changed and the last 5 lines of each
   check's output, and start the next step.
4. If the same test still fails after two delegations, or a check fails
   after one fix attempt, record the test or check and its complete output
   under "Blocked" and stop.
5. Record every TODO, placeholder, or deferred item under "Open items" with
   the reason. Do not decide whether it is a blocker.
6. If a step needs an owner decision (a dependency change, deleting a file
   the step does not name, a protected file, safety limit values,
   credentials), record the exact question under "Blocked", skip the step,
   and continue with the next step if it does not depend on it.
7. If a gate test looks wrong, do not change it. Record its name and full
   output under "Blocked" and stop.
8. After the last step, stop and report.

## Task report

End every task with a short report: files changed, commands run with their
results, security-relevant changes, and open questions. Commit on a feature
branch, one coherent change per commit. Do not merge; the owner merges after
review.

## Maintenance

- Keep this file short enough to follow. Add a rule only when it prevents a
  repeat mistake.
- When the owner corrects an approach, tighten the relevant rule instead of
  appending a vague warning.
