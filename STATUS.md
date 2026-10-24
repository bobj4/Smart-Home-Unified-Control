# Status

As of 2026-10-20, Phase 1 (secure backend foundation) is complete on branch
`review2-fixes`, pending the owner's merge.

## What works

- Login with password plus TOTP or a single-use recovery code; lockout after
  5 failures; server-side sessions (30 min idle, 12 h maximum); CSRF checks.
- Homes and devices with owner/admin/member roles, scoped to the caller's
  homes.
- Simulated lights, TVs, thermostat and water heater, controlled from the web
  app. Thermostat limited to 60-80 F; water heater locked until its limits
  are set.
- Audit log of logins, failures, logouts, device commands (accepted and
  refused) and safety-limit changes, with secrets redacted.
- Security headers, no CORS by default, API docs off, container files for
  deployment behind the reverse proxy.
- All checks pass: `.venv/Scripts/python.exe scripts/check.py`.

## Try it locally

From `backend/` in PowerShell (the owner runs these, never the agent):

```powershell
..\.venv\Scripts\python.exe -m scripts.create_owner
..\.venv\Scripts\python.exe -m scripts.add_demo_devices
..\.venv\Scripts\python.exe -m scripts.set_safety_limits thermostat 60 80 F
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

`create_owner` prints an `otpauth://` link and key for your authenticator app
and ten recovery codes; save them, they are shown once. Then open
http://localhost:8000 (use `localhost`, so the browser accepts the secure
cookies over plain HTTP) and log in.

## Open

- Water-heater limits: choose a minimum and maximum (hard bounds 50-140 F;
  120 F is the usual scald-safety maximum), then run
  `scripts.set_safety_limits water_heater <min> <max> F`.
- Approve the new sections of docs/SECURITY.md.
- Real integrations (Cync, Samsung, Rheem, Frigate) are Phase 2; only the
  simulated integration exists.
- Deployment: set FORWARDED_ALLOW_IPS to the reverse proxy's address as the
  container sees it; build and run the image on the node.
- The PWA has no icons yet (manifest points to /icons/*.png).
