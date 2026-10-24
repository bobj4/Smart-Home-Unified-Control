# Review 3: steps R8-R10 and safety limits

Reviewed 2026-10-20 against `review4.zip`.

## Findings on the agent's R8-R10

The agent ticked R8-R10 in docs/PROGRESS.md and wrote a STATUS.md saying all
steps were complete. The checks did pass, but the static tests only look for
banned patterns, and the code behind R8 and R9 did not work:

- **Web client (R8).** `checkAuth()` always showed the dashboard, so a
  logged-out user never saw the login page. The toggle button called
  `getDeviceState(deviceId)` with one argument, producing
  `/homes/<device id>/devices/undefined`, and sent a `toggle` command the
  backend does not support. Errors read `error.message`; FastAPI returns
  `detail`. There was no stylesheet, so the `hidden` class did nothing and
  both pages showed at once.
- **Containers (R9).** `deploy/Dockerfile` still copied `requirements.txt`
  from a build context that does not contain it, installed curl, and wrote
  the database outside the volume (`./smart_home.db` relative to `/app`
  while the volume is `/app/data`), so data would be lost on every rebuild.
  No migrations ran on start; no proxy-header settings. `deploy/.env.example`
  still listed settings that do not exist (`ALGORITHM`, rate-limit values,
  `sqlite+aiosqlite`).
- **Process.** The work was left uncommitted although the run loop requires a
  commit per step, and STATUS.md reported the checks without saying they do
  not exercise the web client or the container.

All three were redone by the reviewer (below). Lesson for the run loop: a
step whose gate is only static checks needs a behavioural test before the
agent can be trusted with it.

## Changes in this review

- **Safety limits (owner decision: thermostat 60-80 F).**
  - `device_safety_limits` gains `unit` (F or C), `updated_at` and one row
    per home and device type (migration `39880655b171`).
  - Hard bounds no limit may exceed: thermostat 40-90 F, water heater
    50-140 F (Celsius converted).
  - `GET /api/v1/homes/{home_id}/safety-limits` (members) and
    `PUT /api/v1/homes/{home_id}/safety-limits/{thermostat|water_heater}`
    (owner, CSRF). Every change writes `safety_limits_changed` with the old
    and new values.
  - CLI: `python -m scripts.set_safety_limits thermostat 60 80 F`.
  - Commands are checked against the limits; the state records the unit.
  - Tests: `tests/test_safety_limits.py` (8 tests).
- **Water heater:** no limits set yet (owner to choose), so control stays off.
- **Startup migrations.** `init_db()` now runs `alembic upgrade head` for new
  or Alembic-managed databases, so a model change can no longer leave an old
  database without its new columns.
- **Web client rewritten.** Login page when not logged in; 6-digit TOTP or
  8-digit recovery code; lights and TVs on/off; thermostat and water heater
  set points with the backend's refusal shown; safety limits listed under
  Settings; logout. Stylesheet added (`web/css/app.css`). Tested in Chromium:
  login failure message, login, lamp on, thermostat 70 accepted and 85
  refused, water heater refused without limits, reload keeps the session,
  logout, recovery-code login, phone-width layout.
- **Containers rewritten.** Build context is the repo root; hashed install;
  non-root user; app files read-only; database on the volume; migrations then
  one uvicorn worker with `--proxy-headers`; read-only root filesystem,
  dropped capabilities, port on 127.0.0.1. The image build itself could not
  be run here (no registry access); the start command was run against the
  same file layout.
- **docs/SECURITY.md:** threat model, review protocol and review checklist
  added, for the owner to approve.
- **Demo data:** `python -m scripts.add_demo_devices` adds four simulated
  devices for trying the web app.
