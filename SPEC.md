# Smart home control specification

Items marked (proposed) were not specified by the owner and need confirmation
before they are built. Open decisions are listed under "Unresolved questions".

## Problem

Each device brand ships its own app and cloud. The owner wants one place to
read and control lights, a thermostat, TVs, a water heater, and cameras. It
must run on the owner's own nodes, work from a browser and an installable phone
web app, and grow to new brands, more users and homes, and more automations.
It must update itself, safely.

## Users

- Owner and administrator: configures integrations, users, safety limits, login
  methods, and updates.
- Household members (proposed): control devices within the access the owner
  grants.
- More users and more homes must fit without redesign. Every record belongs to
  a home, and every request is checked against the caller's access to that
  home.

## Required behavior

### Devices

- One device model for all brands: id, home, room (optional), integration,
  type, capabilities, state, online status, last-updated time.
- First-version integrations: Cync lights, Cync thermostat, Samsung TVs, Rheem
  water heater (EcoNet), Frigate.
- Each integration is a plugin behind one interface: discover devices, read
  state, execute a command, report health. Core code never imports a brand
  library directly.
- A new brand is added by adding a plugin, with no change to core code.
- Each integration ships read-only first. Control is added after the safety
  limits for that device type exist.
- State changes reach connected clients in real time, without the browser
  polling.

### Device-specific constraints

- Cync thermostat: the protocol is unofficial and unverified (see
  `docs/CYNC_THERMOSTAT_PROTOCOL.md`). The cloud allows one connection per
  account, so a second login ends the first. The integration reconnects with
  backoff and shows a "disconnected by another session" state instead of
  competing for the session.
- Cync lights: reached through the same Cync cloud account, so they share its
  one-connection limit.
- Frigate is already running on the owner's nodes. The backend talks to it
  through Frigate's own API. Clients never receive Frigate addresses or
  credentials.
- Samsung TVs and the Rheem water heater: the control path depends on model and
  account type (see "Unresolved questions").

### Control and safety

- Every command is validated in the backend against per-device-type safety
  limits, whether it comes from a user, an automation, or an integration.
- Control for a device type stays disabled until its limits are configured.
- A command that fails validation changes nothing and is recorded in the audit
  log.

### Automations

- Schedules, scenes (named groups of commands), and rules (trigger, condition,
  action) are stored and run by the backend, not the browser.
- Automation actions pass the same safety limits as manual commands.
- Each run is logged with its outcome. Failures are visible to the owner.

### Login

- The owner selects which login methods are enabled: password with an
  authenticator code (TOTP), passkeys (WebAuthn), or an external identity
  provider (OIDC).
- Password login always requires an authenticator code. There is no
  password-only login (proposed).
- Account recovery uses single-use recovery codes. There is no email or SMS
  reset (proposed).

### Updates

- App and backend: updates are fetched only from a source the owner
  configures, verified before applying, and rolled back automatically if the
  health check fails afterwards. The default is owner approval before applying
  (proposed).
- Integrations: new or updated integrations are installed from a source the
  owner configures, pinned to a version, and run with only the access their
  manifest declares.
- Device firmware: the app triggers the vendor's own update mechanism where one
  exists, after explicit owner confirmation for each device. It never flashes
  arbitrary firmware.

### Operations

- A health endpoint reports liveness without device or account details.
- Logs are structured and contain no secrets.
- Nightly encrypted database backup with a documented restore (proposed).

## Architecture

- `backend/`: FastAPI application on Python 3.13. The `pycync` library, if
  used, requires 3.13 or newer.
- `backend/app/integrations/<name>/`: one folder per integration plugin.
- Data layer: SQLAlchemy with Alembic migrations, SQLite first, so a move to
  PostgreSQL is a configuration change (proposed).
- `web/`: installable web app (PWA). Framework is unresolved.
- `deploy/`: container files and node deployment notes. The runtime is
  unresolved.
- `scripts/`: repository tooling, including `check.py`.
- `docs/`: security requirements, local-model settings, protocol notes.

## Security and privacy

- Full requirements and the review checklist are in `docs/SECURITY.md`. Its
  `SEC-*` requirements are part of this specification.
- The backend is the only component that reaches vendors, Frigate, and devices.
  Only the reverse proxy faces the internet.
- Camera media and event data stay in Frigate. The app streams them through
  authenticated requests and does not store them.
- Never track secrets, sessions, logs, databases, or backups in the repository.
- Public internet access is the owner's requirement. It stays off until the
  Phase 8 exit criteria are met.

## Compatibility

- Backend: Python 3.13, Linux containers on the owner's Rocky 8 nodes.
- Development: the owner's laptop, assumed to run Windows (unresolved).
- Browsers: current Chrome, Safari, and Firefox on desktop and phone
  (proposed).
- Optional tools may add validation but must not be required to run the app.

## Non-goals

- Flashing or modifying device firmware.
- Exposing any device, Frigate, or database port to the internet.
- Running as a multi-tenant hosted service (proposed). Multiple homes belong to
  the owner's household group.
- Replacing vendor apps for setup tasks such as pairing devices (proposed).

## Acceptance criteria

- `python scripts/check.py` passes from a clean checkout.
- For every resource type, a test shows a user cannot read or command another
  home's resources.
- Password login without a valid authenticator code never creates a session,
  shown by a test.
- Login, TOTP, and recovery endpoints are rate limited, with tests.
- A command outside a device's safety limits is rejected and audited, whether it
  arrives through the API or an automation.
- Every integration passes the same contract test suite using recorded
  fixtures. Continuous checks make no live vendor calls.
- A second simulated integration can be added in a test without changing core
  code.
- A failed update triggers automatic rollback in a test.
- Real devices are checked by manual tests recorded in the task report, one per
  integration and control path.
- The web app installs to the home screen on Android and iOS (manual test).
- The latest security review has no open Blocker or High findings before
  public exposure is enabled.

## Unresolved questions

Each item names the phase that needs the answer.

- Phase 0: How does code reach the reviewer: a GitHub repository, or uploaded
  files?
- Phase 0: Which operating system does the laptop run? Windows is assumed.
- Phase 1: Which container runtime do the nodes use, and which node hosts the
  backend?
- Phase 1: Is SQLite enough, or is PostgreSQL needed because the backend spans
  nodes?
- Phase 2: Which Samsung TV models, and which control path: the local network
  or Samsung's cloud?
- Phase 2: Which Rheem water heater model, is it on an EcoNet cloud account,
  and which control path is available?
- Phase 2: Which Frigate version, how is it secured, and which features does
  the app need: events, snapshots, live view, or camera movement?
- Phase 2: Can a second, home-shared Cync account avoid the one-connection
  limit?
- Phase 2: `pycync` is licensed GPL-3.0. Depend on it, or write a client from
  the protocol notes?
- Phase 3: What are the thermostat limits and the maximum water temperature to
  enforce, and in which unit (Fahrenheit or Celsius)?
- Phase 4: Which web framework? Are push notifications needed? Platform support
  for them differs between Android and iOS.
- Phase 6: Which roles beyond owner and member?
- Phase 8: Do the nodes already have a reverse proxy, a domain name, and TLS
  certificates?
