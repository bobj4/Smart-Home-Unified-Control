# Smart Home Unified Control

An open-source smart home control application. A single backend connects to
your devices' services and serves one web app to every phone, tablet and
computer in the house, so you stop switching between vendor apps to run
your home. Built with scalability and control in mind: every command passes
through the backend's permission checks and device safety limits.

## Current support

- **GE Cync**
  - Smart lights (power, brightness, color temperature, color)
  - Smart plugs
  - Thermostats (mode, set points, hold, weekly schedules, sensor schedules)
  - Temperature sensors
- **Frigate** cameras and events
- **Rheem EcoNet** water heaters (set point, modes, usage)
- **Samsung** TVs (remote control)

## Planned support

- Google Nest devices
- myQ garage doors (limited)

## Features

- One installable web app (PWA) for all devices, grouped by room, with
  device groups and live state.
- Multiple homes and users, with admin, operator and member roles, and
  guests who get only what an admin ticks for them (lights, light settings,
  cameras, the water heater, and chosen thermostats).
- Two-factor login (authenticator app), single-use recovery codes,
  "keep me logged in" and "remember this device" (times set by an admin).
- Safety limits on thermostats and water heaters, enforced in the backend
  on every command path.
- Audit log of logins, settings changes and device commands, with secrets
  redacted.
- Integration logins encrypted at rest; automatic daily database backups.
- Optional HTTPS with your own certificate.

## Headless Linux server

The recommended way to run it: Docker on any 64-bit Linux (Rocky, RHEL,
Ubuntu, Debian and others), set up and kept up to date by one script:

    git clone https://github.com/bobj4/Smart-Home-Unified-Control.git ~/smart-home
    cd ~/smart-home
    deploy/linux/smarthome install     # asks a few questions, starts at every boot
    deploy/linux/smarthome doctor      # checks the setup in plain words
    deploy/linux/smarthome update      # later: the latest approved code

It runs on your home network (use a VPN such as Tailscale from outside), or,
with `install --access proxy`, behind a reverse proxy on the same server for
access from the internet; ready-made Apache, nginx and Caddy configurations
are in `deploy/proxy/`. The full guide, including moving your database over
from another computer, is [docs/DEPLOY-LINUX.md](docs/DEPLOY-LINUX.md).

## Quick start (Docker, any system)

1. Create a secrets key. It encrypts saved integration logins; keep it
   private and keep a copy, since a lost key means re-entering every login.

       python backend/scripts/make_secrets_key.py

   (Needs Python with the `cryptography` package. Any Fernet key works.)

2. Copy `deploy/.env.example` to `deploy/.env` and set `SECRETS_KEY` to
   that key.

3. Build and start:

       docker compose -f deploy/docker-compose.yml up -d --build

4. Open `http://<this computer's IP>:8000`. On first start, log in with
   username `admin` and password `admin`, then change the password in
   **Settings > My account** straight away.

5. Add your integrations in **Settings > Integrations** and set safety
   limits in **Settings > Admin** before controlling devices.

More in [docs/DEPLOY.md](docs/DEPLOY.md): backups, restoring, HTTPS, and
what differs inside Docker.

## Running without Docker (Windows)

From the project folder, with Python 3.13:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r backend\requirements.txt
$env:SECRETS_KEY = "<the key>"
cd backend
..\.venv\Scripts\python.exe scripts\serve.py --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 on the same computer. Browsers only accept the
secure login cookies over plain HTTP on `localhost`, so turn on HTTPS
before using other devices.

## Known issues

- Wake-on-LAN cannot reach TVs when the app runs in Docker on Windows (a
  Docker networking limit there). On Linux, install with Wake-on-LAN
  (`--host-network`); on Windows, run the app without Docker.
- With the app's own HTTPS and a self-signed certificate, each device shows a
  browser warning once: choose Advanced, then Proceed.
- A change in Settings > Admin > HTTPS takes effect after a restart.
- The Samsung 2014-2015 (H and J series) encrypted remote protocol has only
  been tested against a fake TV.

## Project layout

| Path | What |
| --- | --- |
| `backend/app` | FastAPI server: routes, models, security, device integrations |
| `backend/app/integrations` | One adapter per vendor (Cync, Rheem, Samsung, Frigate) |
| `backend/alembic` | Database migrations |
| `backend/tests` | Unit, contract and browser (Playwright) tests |
| `backend/scripts` | Server start, backups, secrets key, account recovery |
| `web` | The web app (plain JavaScript, no build step) |
| `deploy` | Dockerfile, Compose files, the Linux installer (`deploy/linux`) and reverse-proxy examples (`deploy/proxy`) |
| `docs` | Deployment, security requirements, integration notes |

## Development

Install the development requirements, then run every check (lint, format,
types, tests, security scan, migrations, dependency audit):

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes -r backend\requirements-dev.txt
.venv\Scripts\python.exe scripts\check.py
```

Tests use recorded fixtures and a simulated integration; they never contact
real devices or vendor services.

## Contributing

- Branch from `dev`, one change per branch, with a message describing what
  changed.
- Every check must pass before a branch is pushed.
- Changes reach `main` from `dev` through a pull request with two approving
  reviews.
- Changes to login, sessions, permissions, encryption or safety limits get
  a security review first; see [docs/SECURITY.md](docs/SECURITY.md).
- Never commit credentials, vendor app files, or decompiled vendor code.

## Disclaimer

Not affiliated with or endorsed by GE Lighting (Cync), Rheem, Samsung,
Chamberlain (myQ), Google (Nest) or the Frigate project. Product names are
trademarks of their owners.

## License

No license has been chosen yet. Until one is added, all rights are reserved
by the author.
