# Plan: Rheem EcoNet water heaters (steps E1-E6)

Written by the reviewer, 2026-10-22. The tests are the contract. They are
protected: never edit, skip, mark or delete them. If one looks wrong, record
its name and full output under "Blocked" in docs/PROGRESS.md and stop.

- `backend/tests/test_rheem.py` (API and unit tests, E1-E4)
- `backend/tests/test_ui_rheem.py` (browser tests, E5)

Nothing in the tests talks to Rheem. They replace
`app.integrations.rheem.connect` with a fake (FakeEconet in test_rheem.py).
The owner tests the real account by hand after E6.

## Owner decisions (do not change)

- Use the `pyeconet` library (as Home Assistant does). The owner's EcoNet
  login is entered on the Settings page, checked with EcoNet, and stored
  encrypted with the `cryptography` library's Fernet, using a key from the
  `SECRETS_KEY` environment variable. There is no fallback key: without it,
  nothing is saved.
- New dependencies, already added with hashes: `pyeconet` (brings `aiohttp`
  and `paho-mqtt`) and `cryptography`. Nothing else may be added.
- Rheem's own set-point range and the home's safety limits (110-120 F by
  default) both apply. Rheem takes whole degrees F.

## Already done by the reviewer (do not rewrite)

- `backend/app/integrations/rheem.py`: the only code that talks to Rheem.
  `RheemHeater` (one water heater), `heater_from_equipment()`, the
  `RheemClient` protocol (`list_water_heaters()`, `set_set_point(serial, value)`),
  `connect(email, password)`, and the errors `RheemError` and
  `RheemLoginError` (a subclass). Use it; never import pyeconet anywhere else.
- `app/features.py`: `rheem_econet` is now `available`.
- `deploy/.env.example`: documents `SECRETS_KEY`.

## Steps

| Step | What | Gate (from backend/) |
|---|---|---|
| E1 | Credential vault | `tests/test_rheem.py -k vault` |
| E2 | EcoNet account endpoints | `tests/test_rheem.py -k "rheem_heater or rheem_connect or rheem_is_available or rheem_owner_saves or rheem_login_is_per_home"` |
| E3 | Find water heaters (sync) | `tests/test_rheem.py -k rheem_sync` |
| E4 | Set points go to EcoNet | `tests/test_rheem.py -k "rheem_set_point or rheem_command"` |
| E5 | Settings panel and water heater card | `tests/test_ui_rheem.py` |
| E6 | Final: every check, STATUS.md | `python scripts/check.py` all pass |

## E1 Credential vault

- `app/vault.py`: `encrypt(data: dict) -> str` and `decrypt(token: str) -> dict`
  using `cryptography.fernet.Fernet` with the key in the `SECRETS_KEY`
  environment variable, read at call time (`os.environ`). Raise
  `VaultError` (defined in app/vault.py) when the key is missing or invalid,
  or when a token cannot be decrypted (`InvalidToken`). The data is JSON.
- `scripts/make_secrets_key.py`: `main()` prints `Fernet.generate_key()`
  and returns 0.

## E2 EcoNet account endpoints

- Model `IntegrationCredential` (table `integration_credentials`): id,
  home_id (FK homes, cascade, indexed), integration String(50), label
  String(255) (the email: the only part ever shown), secret Text (the vault
  token of `{"email", "password"}`), updated_at; unique (home_id,
  integration). Migration as in docs/PLAN-UI.md ("Schema changes").
- `app/credentials.py`: `label()`, `load()` (decrypts; None if nothing
  saved), `save()` (encrypts before writing anything), `remove()`.
- Routes, prefix `/api/v1/homes/{home_id}/integrations/rheem_econet`, all
  owner only (`require_role(..., Role.OWNER)`):

| Method and path | Result |
|---|---|
| GET `/account` | `{"configured": bool, "email": str or null}`; never the password |
| PUT `/account` `{email, password}` (CSRF) | First `rheem.connect(email, password).list_water_heaters()`: `RheemLoginError` → 400 and nothing saved; other `RheemError` → 502. Then save encrypted (`VaultError` → 409, nothing saved). Audit `integration_account_saved` with `{integration, email}` only. Returns the GET shape. |
| DELETE `/account` (CSRF) | Removes it; audit `integration_account_removed`. Returns the GET shape. |

## E3 Find water heaters

- `Device.external_id` String(100), nullable: the integration's own id
  (Rheem: serial number). Migration.
- POST `.../rheem_econet/sync` (admin or owner, CSRF):
  - 409 if the integration is off, if no login is saved, or if the vault
    cannot read it (`VaultError`).
  - Calls `list_water_heaters()` on a client from the saved login. Any
    `RheemError` (including `RheemLoginError`) → 502 and audit
    `integration_sync_failed` with the reason (never the password).
  - For each heater: find the device with this home, integration
    `rheem_econet` and `external_id == serial`; create it if missing (type
    `water_heater`, name from the heater, capabilities "{}"). Set `state` to
    `json.dumps(heater.state())` and `online` to `heater.connected`.
    Devices of this integration no longer listed: `online = False` (keep them).
  - Returns `{"created": n, "updated": m}`; audit `integration_synced`.

## E4 Set points go to EcoNet

In the command route, for devices with integration `rheem_econet`, after the
existing checks (integration on, safety limits) pass and before the state is
saved:
- The temperature must be a whole number (117.5 → 422) and within the
  heater's own `min_set_point`-`max_set_point` from its stored state (→ 422).
- Get a client from the saved login (409 cases as in E3) and call
  `set_set_point(external_id, int(temperature))`. `RheemError` → 502.
- Any refusal: state unchanged, audit `device_command_rejected` with the
  reason. Only an accepted command updates the state.
Keep app/routes/devices.py under 300 lines: put the Rheem logic in a new
module (for example app/rheem_home.py) and call it from the route.

## E5 Settings panel and water heater card

- In Settings → Integrations, when `rheem_econet` is on and the viewer is an
  admin or owner, show a panel `rheem-account`. Turning the integration on
  or off redraws the section, so the panel appears or disappears at once.
- Owner only, in the panel: `rheem-configured` ("No EcoNet account saved."
  or "Connected as <email>"), a form with `rheem-email`, `rheem-password` and
  `rheem-save` (PUT .../account; clear the password field afterwards,
  whether it worked or not), and `rheem-forget` (DELETE .../account), shown
  only when a login is saved.
- Admin and owner: `rheem-sync` ("Find water heaters", POST .../sync); on
  success, status `success` with text containing "<created> new".
- Members see no panel.
- Rheem water heaters use the existing water heater card and dial; no
  changes are needed there.
- Web app rules from docs/PLAN-UI.md ("Web app contract") apply. Keep each
  file under 300 lines (a new web/js/rheem.js is fine; add it to
  index.html before the file that uses it).

## Manual test by the owner (after E6)

1. From backend/: `../.venv/Scripts/python.exe -m scripts.make_secrets_key`;
   put the printed key in the environment as `SECRETS_KEY` (deploy/.env
   for Docker, or `$env:SECRETS_KEY = "<key>"` before starting uvicorn).
2. Settings → Integrations: turn on Rheem EcoNet, save the EcoNet login,
   press "Find water heaters".
3. On the devices page, change the water heater's target by one degree and
   check the Rheem app shows the same value within a minute.
