# Smart home control roadmap

Phases run in order. Public internet access is enabled only in Phase 8.

## Phase 0: Local model and workflow setup

Status: Not started

### Outcome

Hermes Agent runs the chosen local model with at least 64K tokens of context,
and one small task has gone through the full build, review, and fix loop.

### Included work

- Install Hermes Agent on the laptop and serve candidate models with
  `llama-server`.
- Run the bake-off in `docs/LOCAL_MODEL.md` and record the results.
- Create the repository with these documents.
- Complete one trivial task end to end, including a security review.

### Risks

- 8 GB of VRAM and 16 GB of RAM may be too little for reliable agent work at
  64K context.
- Small models can produce malformed tool calls or lose track of long tasks.

### Exit criteria

- Bake-off results and the chosen model are recorded.
- The chosen model completes a trivial task with passing checks.
- The review loop has run once and its findings were fixed.

## Phase 1: Secure backend foundation

Status: Not started

### Outcome

A FastAPI backend with login, sessions, access control, audit logging, a device
model, and a plugin interface exercised by a simulated integration.

### Included work

- Application skeleton, configuration, database, migrations, check script.
- Password login with TOTP and recovery codes, built on maintained libraries
  for hashing, TOTP, and sessions. No hand-written cryptography.
- Deny-by-default authorization with home scoping.
- Audit log.
- Device model, plugin interface, and a simulated integration.
- Non-root backend container, not exposed outside the node.

### Risks

- Authentication and authorization mistakes are the most damaging defects in
  this project.

### Exit criteria

- All checks pass.
- Security review 1 reports no open Blocker or High findings.

## Phase 2: Read-only integrations

Status: Not started

### Outcome

The backend reads state from every first-version device and Frigate. No
commands are sent.

### Included work

- Cync thermostat and lights: read-only probe first, to confirm
  `docs/CYNC_THERMOSTAT_PROTOCOL.md` against the live device.
- Samsung TVs, Rheem water heater, and Frigate state and events.
- Contract tests with recorded fixtures for each integration.

### Risks

- The Cync protocol is unofficial, unverified, and can change without notice.
- The Cync cloud allows one connection per account.
- Vendor terms of service may restrict unofficial access.
- Control paths for the TVs and the water heater are not yet known.

### Exit criteria

- Each integration reports real device state in a manual test.
- Every integration passes the contract suite.
- Security review 2 covers outbound requests, vendor credential storage, and
  Frigate access.

## Phase 3: Device control and safety limits

Status: Not started

### Outcome

Commands reach devices only through the backend, after validation against
configured safety limits.

### Included work

- Safety limit configuration and enforcement for each device type.
- Control for each integration, enabled one device type at a time.
- Command audit trail.

### Risks

- The water heater and thermostat can cause physical harm or damage if limits
  are wrong or bypassed.
- Firmware may apply its own rules, such as the Cync Eco mode rule, that the
  app does not know about.

### Exit criteria

- Out-of-limit commands are rejected and audited in tests.
- Each control path passes a manual test on real hardware.
- Security review 3 covers the safety limit paths.

## Phase 4: Web app (PWA)

Status: Not started

### Outcome

An installable web app for desktop and phone with live device state and
control.

### Included work

- Framework decision, recorded in `SPEC.md`.
- Dashboard, device pages, login screens.
- Real-time updates, installability, and offline shell.
- Camera views through authenticated backend requests.

### Risks

- Service workers can cache sensitive responses if configured carelessly.
- Browser and platform differences affect installability and push.

### Exit criteria

- The app installs on Android and iOS in a manual test.
- No authenticated response or media is cached by the service worker.
- Security review 4 covers cross-site scripting, request forgery, and caching.

## Phase 5: Automations

Status: Not started

### Outcome

Schedules, scenes, and rules run on the backend.

### Included work

- Scene, schedule, and rule model and engine.
- Run history and failure reporting.
- Safety limits applied to every automated action.

### Risks

- Rule loops and runaway command rates.

### Exit criteria

- Automation tests cover loops, failures, and safety limit enforcement.

## Phase 6: Multiple users and homes

Status: Not started

### Outcome

Several users and homes with roles, and the full set of login methods.

### Included work

- Roles and per-home access management.
- Passkeys (WebAuthn) and external identity provider (OIDC) login.
- Owner-selectable login methods.

### Risks

- New login paths widen the attack surface and the recovery edge cases.

### Exit criteria

- The cross-home access test matrix passes for every resource type.
- Security review 5 covers each enabled login method.

## Phase 7: Updates

Status: Not started

### Outcome

App, backend, integration, and device firmware updates with verification and
rollback.

### Included work

- Separate minimal updater component.
- Signed or checksum-pinned release verification and automatic rollback.
- Integration manifests, version pinning, and owner approval for installs.
- Firmware update triggers with per-device confirmation.

### Risks

- Self-updating software is a high-value target. Mounting the container runtime
  socket into the app would give it full control of the node.
- A bad update could leave the home unreachable.

### Exit criteria

- A failed update rolls back automatically in a test.
- The web-facing app cannot modify its own code or the updater.
- Security review 6 covers the update and plugin paths.

## Phase 8: Hardening and public exposure

Status: Not started

### Outcome

The app is reachable from the internet behind a hardened reverse proxy.

### Included work

- Reverse proxy, domain, TLS, and security headers.
- Rate limiting at the proxy and the app.
- Backup and restore test.
- Full review against every `SEC-*` requirement.

### Risks

- Camera feeds and home occupancy patterns become reachable if access control
  fails.
- A residential connection offers little protection against floods.

### Exit criteria

- The final security review has no open Blocker or High findings.
- Only the reverse proxy is reachable from outside, confirmed by a port scan
  from an outside network.
- The owner approves enabling public exposure.
