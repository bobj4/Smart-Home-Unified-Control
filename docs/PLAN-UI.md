# Plan: settings and graphical UI (steps U1-U11)

Written by the reviewer, 2026-10-20; integrations, TV remote, QR codes and
the settings menu added the same evening. The tests listed here are the
contract.
They are protected: never edit, skip, mark or delete them. If one looks
wrong, record its name and full output under "Blocked" in docs/PROGRESS.md
and stop.

New protected tests:
- `backend/tests/test_contract_settings.py` (API, steps U1-U4)
- `backend/tests/test_contract_features.py` (API, steps U5-U7)
- `backend/tests/test_ui.py` (browser, steps U8-U10)
- `backend/tests/test_safety_limits.py` (updated: responses now include
  `default_target`)

## Owner decisions (do not change)

- Recommended safety limits, in Fahrenheit:
  - thermostat 60-80, default target 68 (US DOE heating recommendation)
  - water heater 110-120, default target 120 (CPSC scald limit; Legionella
    grows more readily below about 110)
- New thermostats and water heaters start at the default target.
- New members join with a one-time enrollment code made by the owner. The
  code works once, for 24 hours. The person sets their own password and
  authenticator; the owner never sees either.
- Each device brand (integration) has an on/off switch per home. Only the
  demo (simulated) integration is on by default; real brands stay off until
  the owner turns them on, so nothing talks to a vendor by surprise.
- TVs get a full remote (power, volume, mute, channels, inputs, navigation
  keys, playback keys, apps), simulated until the Samsung integration exists.
- Authenticator setup shows a QR code, drawn by the backend with `segno`.
- Settings has a menu of categories on the left; one category shows at a
  time.
- Approved dependencies, already added with hashes: `segno` (requirements.in)
  and `playwright` (requirements-dev.in). Nothing else may be added.

## How to run the step's tests

From `backend/`, in the foreground:

    ../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider <files> -k "<expression>"

The browser tests (test_ui.py) start the app themselves on a random port in
a background thread and stop it afterwards. Never start uvicorn or any
server yourself, not even to "look at" the page. To see why a browser test
failed, read its assertion message: it names the data-testid it was waiting
for and what it found.

## Steps

| Step | What | Gate (files and -k) |
|---|---|---|
| U1 | Safety defaults backend | `tests/test_contract_settings.py tests/test_safety_limits.py -k "recommended or default_target or safety"` |
| U2 | Account API | `tests/test_contract_settings.py -k "account_overview or change_password or recovery_codes or authenticator or sessions"` |
| U3 | Members and enrollment API | `tests/test_contract_settings.py -k "member or enroll or joins"` |
| U4 | Device editing and activity log API | `tests/test_contract_settings.py -k "renames or activity_log"` |
| U5 | Integration on/off switches API | `tests/test_contract_features.py -k integration` |
| U6 | TV remote commands | `tests/test_contract_features.py -k "tv or remote"` |
| U7 | QR codes for authenticator setup | `tests/test_contract_features.py -k qr` |
| U8 | UI shell, graphical devices view, TV remote | `tests/test_ui.py -k "ui_static or ui_shell or ui_devices or ui_tv"` |
| U9 | Settings menu; safety limits, devices, integrations, activity | `tests/test_ui.py -k "ui_settings or ui_safety or ui_device_edit or ui_activity or ui_integrations"` |
| U10 | Settings: account (with QR) and users; enrollment page (with QR) | `tests/test_ui.py -k "ui_account or ui_members or ui_enroll"` |
| U11 | Final: every check, STATUS.md | `python scripts/check.py` all pass |

A step is done when its gate passes, every test that passed before still
passes, and ruff, ruff format --check and mypy are clean.

## Backend contract (U1-U4)

All routes need a session except `/api/v1/enroll/*`. Every POST, PUT, PATCH
and DELETE needs the X-CSRF-Token header (403 without it). Use
`require_role(db, user.id, home_id, Role.X)` from app/authorization.py
(404 if not a member, 403 if the role is too low). Use `record_event` from
app/audit.py for every change; never put passwords, codes, secrets or tokens
in event details. Bodies are Pydantic models with `extra="forbid"`.

Schema changes: add the columns and table to app/models.py, then from
backend/ run `../.venv/Scripts/python.exe -m alembic revision --autogenerate -m "<what>"`,
read the generated file, run `ruff check --fix` and `ruff format` on it,
and check it with `scripts/check.py` (alembic check
must report no new operations).

### U1 Safety defaults

- `DeviceSafetyLimits.default_target`: nullable Float.
- app/safety.py:
  - `RECOMMENDED = {"thermostat": ("F", 60.0, 80.0, 68.0), "water_heater": ("F", 110.0, 120.0, 120.0)}`
    (unit, min, max, default target).
  - `set_limits(..., default_target=None)` raises LimitsError (→ 422) if the
    default target is outside min..max.
  - `limits_out` includes `default_target`.
  - `apply_recommended(db, home_id, user_id, ip_address)` sets all of
    RECOMMENDED (enabled) and audits each.
  - `initial_state(db, home_id, device_type)` returns
    `{"target_temperature": <default>, "unit": <unit>}` for a limited type
    whose limits have a default target, otherwise `{}`. Device creation uses
    it as the new device's state.
- `PUT /api/v1/homes/{home_id}/safety-limits/{device_type}` accepts optional
  `default_target`.
- `POST /api/v1/homes/{home_id}/safety-limits/recommended` (owner, CSRF):
  applies RECOMMENDED, returns the list of limits (same shape as GET).
- `scripts/set_safety_limits.py`: positionals become optional
  (`nargs="?"`); new `--default <target>` and `--recommended`;
  `main(argv)` returns 0 on success.
- `scripts/create_owner.py` calls `apply_recommended` for the new home.

### U2 Account (`/api/v1/account`)

| Method and path | Body | Result |
|---|---|---|
| GET `` | | `{id, email, name, homes: [{id, name, role}]}` |
| POST `/password` | `{current_password, new_password}` (new: 12+ chars) | 200; ends every other session of the user; 403 wrong password; audit `password_changed` |
| POST `/recovery-codes` | `{password}` | `{recovery_codes: [10 x 8 digits]}`; old codes stop working; audit `recovery_codes_regenerated` |
| POST `/totp/setup` | `{password}` | `{secret, otpauth_uri}`; stored in `User.pending_totp_secret`; the old secret keeps working |
| POST `/totp/confirm` | `{totp_code}` | 409 if no setup started; 400 if the code does not match the new secret; 200 replaces the secret; audit `totp_reset` |
| GET `/sessions` | | list of `{id, created_at, last_activity, ip_address, current}` for the caller only |
| DELETE `/sessions/{id}` | | 200; 404 for another user's session; audit `session_revoked` |
| POST `/sessions/revoke-others` | | 200; ends all but the current session; audit `sessions_revoked` |

Password checks count as login failures for the rate limiter
(`check_login_allowed` / `record_login_failure` in app/rate_limiter.py) and
a wrong password is audited as `reauth_failure`.

### U3 Members and enrollment

Model `Enrollment` (table `enrollments`): id, home_id (FK homes, cascade),
email, name (nullable), role, code_hash (SHA-256 hex, unique),
pending_totp_secret (nullable), created_by (FK users, set null), created_at,
expires_at (24 hours after creation), used_at (nullable).

Codes: 16 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` drawn with the
`secrets` module, shown as `XXXX-XXXX-XXXX-XXXX`. Store only the hash.
Before hashing, upper-case the code and drop everything that is not a letter
or digit, so "abcd efgh ..." matches.

`/api/v1/homes/{home_id}/members`:

| Method and path | Who | Result |
|---|---|---|
| GET `` | any member | `[{user_id, email, name, role}]` for this home only |
| PATCH `/{user_id}` `{role}` | owner | role is owner, admin or member (422 otherwise); 409 on yourself; 404 if not a member; audit `member_role_changed` |
| DELETE `/{user_id}` | owner | 409 on yourself; 404 if not a member; if the person has no homes left, end all their sessions; audit `member_removed` |
| POST `/enrollments` `{email, name?, role}` | owner | 201 `{id, enrollment_code, expires_at}`; role admin or member only (422 for owner); 409 if that email is already a member; audit `enrollment_created` |
| GET `/enrollments` | owner | unused, unexpired: `[{id, email, role, expires_at}]` (never the code) |
| DELETE `/enrollments/{id}` | owner | 200; audit `enrollment_cancelled` |

`/api/v1/enroll` (no session, rate-limited like login: 429 after repeated bad codes from one address):

- POST `/start` `{code}`: 404 for unknown, used or expired codes. If no
  account has that email: `{email, existing_account: false, totp_secret,
  otpauth_uri}` (the secret is kept on the enrollment until finish). If an
  account exists: `{email, existing_account: true}` and no secret.
- POST `/finish` `{code, password, totp_code}`:
  - new account: password 12+ chars (422), code must match the pending
    secret (400); creates the user with TOTP enabled and returns
    `{email, recovery_codes: [10]}`.
  - existing account: their own password and current authenticator code
    (403 if either is wrong); returns `{email, recovery_codes: []}`.
  - Adds the membership with the enrollment's role, marks the code used,
    audits `member_added`.

### U4 Devices and activity log

- PATCH `/api/v1/homes/{home_id}/devices/{device_id}` (admin+, CSRF):
  `{name?, room?}`; name 1-100 chars, room up to 50; 422 for an empty body
  or other fields; 404 for a device in another home; audit `device_updated`.
- GET `/api/v1/homes/{home_id}/audit?limit=N` (owner only; N 1-200,
  default 50; 422 outside): newest first; events with this home_id plus
  account events (home_id empty) of this home's members; each
  `{created_at, event_type, user_email, ip_address, details}`.
- Allow PUT and PATCH in the CORS middleware's allow_methods.

### U5 Integration on/off switches

- Table `home_integrations` (model `HomeIntegration`): id, home_id (FK
  homes, cascade, indexed), integration String(50), enabled Boolean,
  updated_at; unique (home_id, integration). A missing row means the
  default.
- app/features.py holds the catalogue, in this order (id, name, default,
  available = its code exists):
  - `simulated`, "Demo devices", on, available
  - `cync`, "GE Cync", off, not available
  - `samsung_tv`, "Samsung TV", off, not available
  - `rheem_econet`, "Rheem EcoNet", off, not available
  - `frigate`, "Frigate cameras", off, not available
  Each has a one-line description.
- GET `/api/v1/homes/{home_id}/integrations` (any member):
  `[{id, name, description, enabled, available}]` in catalogue order.
- PUT `/api/v1/homes/{home_id}/integrations/{id}` (owner, CSRF)
  `{enabled: <true|false>}` (strict boolean: "yes" or 1 is 422): returns the
  row; 404 for an unknown id; audit `integration_toggled` with
  `{integration, enabled}`.
- When a device's integration is off: every command is refused with 409 and
  a detail containing "turned off" (audited as `device_command_rejected`),
  checked before anything else; creating a device for it is refused with 409.

### U6 TV remote commands

Put the TV logic in a new module app/tv.py (pure functions, no database)
and call it from the command route for devices of type `tv`. A TV's state
starts from these defaults for any key it lacks:
`{"on": false, "volume": 10, "muted": false, "channel": 1, "input": "tv", "app": null, "last_key": null}`
and every successful TV command returns and stores the full state.

| Command | Payload | Effect |
|---|---|---|
| turn_on, turn_off | `{}` | on true / false (the only commands allowed while off) |
| volume_up, volume_down | `{}` | volume ±1, kept within 0-100; unmutes |
| set_volume | `{"level": 0-100}` | volume = level; unmutes |
| toggle_mute | `{}` | muted flips |
| channel_up, channel_down | `{}` | channel ±1, kept within 1-9999; input "tv", app null |
| set_channel | `{"channel": 1-9999}` | channel set; input "tv", app null |
| set_input | `{"source": tv, hdmi1, hdmi2, hdmi3, hdmi4 or usb}` | input set; app null |
| launch_app | `{"app": netflix, youtube, prime_video, disney_plus, hulu or spotify}` | app set |
| press_key | `{"key": up, down, left, right, select, back, home, menu, info, guide, play, pause, stop, rewind or fast_forward}` | last_key = key; "home" also sets app null |

- Numbers must be JSON integers (not strings, booleans or 5.5); anything
  else, a missing or extra payload key, or an unknown command is 422.
- Any command except turn_on/turn_off while the TV is off is 409 ("the TV
  is off").
- Remote commands sent to a light (or any non-TV) are 422.
- Keep app/routes/devices.py under 300 lines.

### U7 QR codes

- Add `totp_qr_svg(otpauth_uri)` to app/auth.py:
  `segno.make(otpauth_uri, error="m").svg_data_uri(scale=4, border=2, dark="#000000", light="#ffffff")`
  (the tests compare against exactly this).
- POST /api/v1/account/totp/setup and POST /api/v1/enroll/start (new
  accounts only) also return `qr_svg`: that data URI, made from the
  `otpauth_uri` in the same response.

## Web app contract (U8-U10)

The tests find elements only by `data-testid`. Markup, layout and styling
are yours. Rules:

- Plain JavaScript files in web/js, each under 300 lines, all loaded by
  `<script src="/js/...">` tags in web/public/index.html. Load api.js first.
  main.py serves every .js file in web/js and .css file in web/css that
  exists at start-up, and nothing else.
- No innerHTML, outerHTML, insertAdjacentHTML, document.write, eval,
  localStorage, sessionStorage, alert, confirm or prompt. Build elements
  with document.createElement / createElementNS and set text with
  textContent. No inline scripts, styles or onclick attributes (the
  Content-Security-Policy blocks them).
- Keep `id="login-form"` on the login form.
- Routes are URL hashes: `#/devices` (default), `#/settings`, `#/enroll`.
  Reloading keeps the view.
- One status line, `status`, with attribute `data-kind`: set it to
  `pending` (empty text) when an action starts, then `success` or `error`
  with a message. Every API error shows its `detail` text there.
- Controls a role may not use are not rendered (count 0), except where a
  test says disabled.
- Roles: owner > admin > member. Read the caller's role per home from
  GET /api/v1/account.
- Must fit a 390 px wide phone without sideways scrolling.

### Login and shell (U8)

- `login-page`, `login-form`, `login-email`, `login-password`, `login-code`
  (6-digit authenticator code or 8-digit recovery code), `login-submit`,
  `login-error`, `enroll-link` (goes to `#/enroll`).
- `app-shell` (hidden when logged out), `home-name`, `home-select` (a
  `<select>` with one option per home, shown only with 2 or more homes),
  `nav-devices`, `nav-settings`, `logout`, `status`, `view-devices`,
  `view-settings`.
- Clear the password and code fields after a successful login.

### Devices view (U8)

- One `room` element per room, attribute `data-room="<room>"`, containing
  the room name and that room's cards. `devices-empty` when the home has no
  devices.
- `device-card` with `data-device-id`, `data-device-type`,
  `data-online="true|false"`.
- Lights and TVs: `power-toggle` button, `aria-pressed="true|false"`,
  disabled when offline; sends turn_on / turn_off.
- Thermostats and water heaters: `temp-gauge` (an `<svg>` dial showing the
  target between the limits), `target-temp` (e.g. "68 °F"), `temp-limits`
  (e.g. "Allowed 60–80 °F"), `temp-down` and `temp-up` (send
  set_temperature with target −1 / +1; disabled when the next value would
  leave the limits or the device is offline). If the home has no enabled
  limits for the type: show `limits-missing` and disable both buttons.
- After every command, reload the devices. A refused command (409/422)
  shows the error in `status`.
- A device whose integration is off (GET .../integrations) shows
  `integration-off` and all its controls are disabled.

### TV remote (U8)

- Each TV card has `tv-remote-open` ("Remote"; disabled when the TV is
  offline or its integration is off). It opens a panel `tv-remote` over the
  page (an element, not a browser dialog) titled with the TV's name.
- In the panel: `remote-screen` (shows the input name, e.g. "HDMI 2", or
  the app name, e.g. "Netflix"), `remote-channel` (e.g. "Channel 7"),
  `remote-volume` (e.g. "Volume 11", or "Muted"), `remote-power`,
  `remote-mute`, `remote-volume-up`, `remote-volume-down`,
  `remote-volume-level` (range 0-100), `remote-channel-up`,
  `remote-channel-down`, `remote-channel-input` + `remote-channel-go`,
  `remote-input` (a `<select>` with values tv, hdmi1-hdmi4, usb),
  `remote-key-<key>` for every key in the U6 table, `remote-app-<app>` for
  every app, and `remote-close`. Escape also closes it.
- While the TV is off, everything except `remote-power` and `remote-close`
  is disabled.
- Each button sends its command (status `pending`, then `success` or
  `error`) and the panel shows the state the command returned. Closing the
  panel reloads the devices.
- Must fit a 390 px wide phone (scroll inside the panel if needed).

### Settings view (U9, U10)

- A menu `settings-menu` with links `settings-nav-<category>` in this
  order: account ("My account"), members ("Users"), devices, integrations,
  safety ("Safety limits"), activity ("Activity log", owner only: not
  rendered for others). On wide screens it is a pane on the left; on a phone
  it may sit above the content.
- Routes: `#/settings` shows the first category (account);
  `#/settings/<category>` shows that one. The current link has
  `aria-current="page"`. Only one category's section, `settings-<category>`,
  is shown at a time. An unknown or forbidden category shows the first one.
- Integrations: one `integration-row` per integration with
  `data-integration="<id>"` and `data-available="true|false"`, showing its
  name, description and a "not built yet" note when unavailable, and an
  `integration-toggle` checkbox (styled as a switch) that saves when
  changed. Disabled for anyone but the owner.

- Safety: one `limits-row` per type with `data-device-type`, containing
  `limits-min`, `limits-max`, `limits-default`, `limits-unit`,
  `limits-enabled` (checkbox) and, for the owner only, `limits-save`.
  Owner only: `limits-recommended` (POST .../recommended, then show the new
  values). Others see the inputs disabled.
- Devices: one `device-row` per device with `data-device-id`, containing
  `device-name`, `device-room` and (admin+) `device-save`.
- Activity: `activity-refresh`, and one `activity-row` per event showing
  event type, user email and time.
- Account: `password-current`, `password-new`, `password-confirm`,
  `password-save` (a mismatch shows an error without calling the API; clear
  the fields after success); `recovery-password`, `recovery-generate`,
  `recovery-codes` (the 10 new codes); `totp-password`, `totp-start`,
  `totp-qr` (an `<img>` whose src is `qr_svg`, at least 120 px square),
  `totp-secret` (the new secret, spaces allowed), `totp-code`,
  `totp-confirm`; one `session-row` per session with
  `data-current="true|false"`, `session-end` on other sessions only, and
  `sessions-end-others`.
- Members: one `member-row` per member with `data-user-id` and
  `data-role`. Owner only, and not on the owner's own row: `member-role`
  (a `<select>`; changing it saves) and `member-remove`, which shows
  `member-remove-confirm` (removing needs both clicks). Owner only:
  `invite-email`, `invite-name`, `invite-role` (member or admin),
  `invite-submit`, `invite-code` (the new code), one `enrollment-row` per
  pending code with `enrollment-cancel`.

### Enrollment page (U10)

`enroll-page` (at `#/enroll`, shown when logged out), `enroll-code`,
`enroll-start`, `enroll-error`, `enroll-email`, `enroll-qr` and
`enroll-secret` (new accounts only; the QR `<img>` as for `totp-qr`), `enroll-existing` (message for existing accounts),
`enroll-password`, `enroll-password-confirm` (new accounts only; a mismatch
shows `enroll-error` without calling the API), `enroll-totp`,
`enroll-finish`, `enroll-recovery-codes` (new accounts), `enroll-done`
(returns to the login page).

### Look

A calm, clean dashboard that works in light and dark mode
(`prefers-color-scheme`): cards on a soft background, clear type, large
touch targets (at least 44 px for the dial buttons and toggles), lit
styling for lights that are on, a coloured arc for the temperature dial.
No external fonts, images or libraries.
