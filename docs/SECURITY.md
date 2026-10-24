# Security Requirements

This document outlines the security requirements for the smart home control system.

## Authentication and Sessions

Owner decision 2026-10-22

- **SEC-01**: Passwords must be hashed with Argon2id (argon2-cffi). No plaintext storage.
- **SEC-02**: Two-factor login is each person's choice (My account page); turning it off needs the password and a current code; an owner can require it for everyone in a home, and members without it can then only reach My account; a server-side script resets a locked-out account.
- **SEC-03**: Server-side sessions with idle and absolute timeouts. HttpOnly, Secure, SameSite=Strict cookies.
- **SEC-04**: CSRF protection on all state-changing requests.
- **SEC-05**: Rate limiting on login, TOTP, and recovery endpoints per account and IP.
- **SEC-06**: Single-use recovery codes, hashed storage, shown only once.
- **SEC-07**: TOTP code reuse prevention within time window.

## Authorization

- **SEC-10**: Deny by default. All routes require authentication except /health.
- **SEC-11**: Home-scoped access. Users cannot access other homes' resources.
- **SEC-12**: Centralized authorization logic.
- **SEC-13**: WebSocket/ SSE connections authenticated and stop on session revocation.
- **SEC-14**: CORS origin allow-list, no origins allowed by default.

## Input and Output

- **SEC-20**: All input validated with Pydantic models, unknown fields rejected.
- **SEC-21**: SQL uses SQLAlchemy bound parameters only. No string-built SQL.
- **SEC-22**: No shell=True, eval, exec, or pickle on external data.
- **SEC-23**: Outbound requests only to declared integration hosts.
- **SEC-24**: Security headers: CSP, X-Content-Type-Options, frame-ancestors, Referrer-Policy.
- **SEC-25**: Service worker never caches authenticated responses or media.
- **SEC-26**: Client address from trusted reverse proxy only.

## Secrets and Data

- **SEC-30**: Secrets from environment variables only. Never in source, logs, or errors.
- **SEC-31**: Vendor tokens encrypted at rest with key not in database.
- **SEC-32**: Audit logs never contain passwords, tokens, sessions, or TOTP seeds.
- **SEC-33**: Camera media not stored by application.
- **SEC-34**: Development uses recorded fixtures only. No real credentials in repo.
- **SEC-35**: Encrypted backups with key stored separately.

## Device Safety

- **SEC-40**: Safety limits enforced in backend on all command paths.
- **SEC-41**: Failed validation commands change nothing and are audited.
- **SEC-42**: Control disabled until safety limits configured.

## Network and Deployment

- **SEC-50**: Only reverse proxy faces internet. Backend, DB, device ports internal only.
- **SEC-51**: TLS 1.2+ with valid certificates. HTTP redirects to HTTPS.
- **SEC-52**: Non-root containers, dropped capabilities, read-only filesystem.
- **SEC-53**: Camera streams only through authenticated backend requests.

## Updates and Plugins

- **SEC-60**: Updates verified by signature/checksum before applying.
- **SEC-61**: Owner approval before update apply (default). Failed health check triggers rollback.
- **SEC-62**: Separate updater component. Web app cannot modify updater or itself.
- **SEC-63**: Integrations declare manifest with allowed hosts and required secrets.
- **SEC-64**: Firmware updates use vendor mechanism with explicit owner confirmation.

## Supply Chain and Audit

- **SEC-70**: Pinned dependencies with hashes. pip_audit and bandit pass before merge.
- **SEC-80**: Audit log records logins, failures, commands, config changes with who/what/when/where.

## Threat model

What is protected, from whom, and where the boundaries are. Requirements above
are numbered SEC-xx; this section explains why they exist.

### Assets

- Control of physical devices: thermostat and water-heater set points (safety),
  lights, TVs.
- Camera feeds from Frigate (privacy).
- Account credentials: password hashes, TOTP secrets, recovery-code hashes,
  session tokens.
- Vendor credentials for Cync, Samsung, Rheem EcoNet (SEC-31).
- The audit log, as the record of who did what.

### Attackers considered

1. **Internet attacker** with no account, once the app is public (Phase 8):
   password guessing, session theft, CSRF from another site, XSS, exploiting
   vulnerable dependencies, scanning for exposed ports.
2. **Malicious or careless household member** with a valid account: trying to
   reach another home's devices, raise their own role, or set unsafe
   temperatures.
3. **Compromised device or integration** on the home network: returning
   hostile data to the backend, or being used to reach other hosts.
4. **Compromised update or dependency**: a tampered package, image or
   firmware.
5. **Coding agent mistakes**: the local model writes most of the code, so
   plausible-looking but wrong security code is an expected failure mode, not
   an unusual one.

Out of scope: an attacker with administrator access to the host nodes, and
attacks on the vendors' own cloud services.

### Trust boundaries

- Internet to reverse proxy: TLS ends here (SEC-50, SEC-51). Nothing else is
  reachable from outside.
- Reverse proxy to backend: the backend trusts client-address headers only from
  the proxy's address (SEC-26).
- Browser to backend: every request is untrusted until the session, CSRF and
  home-membership checks pass (SEC-03, SEC-04, SEC-10, SEC-11).
- Backend to devices and vendor services: device data is untrusted input;
  outbound connections go only to hosts an integration declares (SEC-23,
  SEC-63).
- Agent-written code to main branch: nothing merges without passing the
  checks and the review below.

### Main risks and the controls that address them

| Risk | Controls |
|---|---|
| Unsafe heating or hot-water temperature | SEC-40 to SEC-42: backend-enforced limits inside fixed hard bounds, control off until set, owner-only changes, every change audited |
|| Account takeover | SEC-01, SEC-02, SEC-05 to SEC-07: Argon2id, TOTP optional per user with owner override, lockout after repeated failures, single-use recovery codes |
| Session theft or cross-site requests | SEC-03, SEC-04, SEC-14, SEC-24: HttpOnly Secure SameSite cookies, CSRF header check, no CORS by default, strict CSP |
| Access to another home | SEC-10 to SEC-12: deny by default, one central membership check |
| Exposed services | SEC-50, SEC-52: only the proxy faces the internet; non-root, read-only containers |
| Supply-chain compromise | SEC-60, SEC-70: hashed pins, pip-audit and bandit before merge, verified updates |
| Secrets leaking | SEC-30 to SEC-32: environment-only secrets, encrypted vendor tokens, redacted audit log |

## Review protocol

1. The coding agent works on a feature branch, one step per commit, and never
   merges.
2. Before a step is reported done, `python scripts/check.py` passes from a
   clean checkout: ruff, ruff format, mypy, the full test suite, bandit,
   Alembic schema check, pip-audit.
3. A change to anything in "Stop and flag" in AGENTS.md (authentication,
   sessions, permissions, encryption, updates, plugin loading, network
   exposure, safety limits) goes to a security review before merge. The
   reviewer reads the diff against this document and the checklist below,
   not the agent's report.
4. Every new behaviour has a test that would fail without it. Tests written by
   the reviewer are protected; the agent may not edit, skip or delete them.
5. Findings are recorded in docs/REVIEW-<n>.md with an ID, a severity
   (blocker, high, medium), file and line, and the fix. A blocker stops the
   merge.
6. The owner merges after the review passes, and runs the manual hardware
   tests; the agent never touches real devices or vendor services (SEC-34).

## Review checklist

Authentication and sessions
- [ ] Two-factor login is optional per user; turning it off needs the password and a current code; an owner can require it for a home; failed logins give one generic error and take the same time for unknown accounts; session token only in an HttpOnly, Secure, SameSite=Strict cookie.
- [ ] Failed logins give one generic error and take the same time for unknown accounts.
- [ ] Session token only in an HttpOnly, Secure, SameSite=Strict cookie; never in a response body, URL or browser storage.
- [ ] Sessions expire on idle and absolute timeouts; logout deletes the row.

Authorization
- [ ] Every new route depends on current_user, except /health and login.
- [ ] Every query for home data goes through require_role with the home in the path.
- [ ] The acting user always comes from the session, never from a parameter or body.
- [ ] State-changing routes depend on require_csrf.

Input, output and headers
- [ ] Every request body is a Pydantic model with extra="forbid".
- [ ] No string-built SQL; no shell, eval, exec or pickle on external data.
- [ ] Web code sets text with textContent only; no innerHTML or inline scripts.
- [ ] Error responses contain no exception text, stack traces or secrets.
- [ ] Security headers present on success and error responses; no CORS origin added without owner approval.

Device safety
- [ ] Every command path validates against limits in the backend before anything changes.
- [ ] Refused commands change nothing and write a device_command_rejected audit row.
- [ ] Limits can be changed only by an owner, only inside the hard bounds, and every change is audited.

Secrets, logging and data
- [ ] No credential, token or key in code, config, tests or logs; settings come from the environment.
- [ ] Audit details are redacted (nested keys included) and record who, what, when and where.
- [ ] Schema changes come with an Alembic migration; `alembic check` reports nothing.

Dependencies and deployment
- [ ] Any dependency change was approved by the owner and recompiled with hashes; pip-audit is clean.
- [ ] Containers run as non-root, with dropped capabilities and a read-only filesystem.
- [ ] Only the reverse proxy is reachable from outside the host; published ports bind to 127.0.0.1.
