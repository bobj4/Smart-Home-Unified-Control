# Smart Home Unified Control

An open-source smart home control application. A single backend connects to
your devices' services and serves one web app to every phone, tablet and
computer in the house, so you stop switching between vendor apps to run
your home. Built with scalability and control in mind: every command passes
through the backend's permission checks and device safety limits.

## Current support

- **GE Cync**
  - Smart lights (power, brightness, color temperature, color)
  - Smart plugs and switches (a dimmer switch works like a light)
  - Thermostats (mode, set points, fan, hold, weekly schedules, sensor
    schedules, and the thermostat's own settings such as Early On)
  - Temperature sensors
- **Philips Hue** lights, through the Hue Bridge on your network
- **TP-Link Kasa** plugs, power strips, switches, dimmers and bulbs (older
  and newer firmware)
- **Rheem EcoNet** water heaters (set point, modes, away, schedule, usage)
- **Samsung**, **LG** and **Roku** TVs (remote control, apps, inputs; TVs
  can be found on the network automatically). Samsung TV inputs by name
  through SmartThings (optional).
- **ratgdo** garage door openers (open, close, stop)
- **Frigate** cameras and events
- **Demo devices** to try the app without hardware

## Features

- One installable web app (PWA, with its own icon on phones) for all
  devices, grouped by room, with device groups and live state. Every page
  updates by itself.
- Rooms side by side, packed together, in an order and size of your choice
  (separately for phones and wide screens); rooms fold shut; search and
  filters by type or "on only".
- Thermostats and water heaters on a page of their own, and garage doors
  on a Doors page, shown while their integration is on.
- Themes: light, dark, device theme, preset colors or your own accent and
  background color, and a background picture.
- More than one home (Admin › Home: Add a Home, an address and an icon
  each, your own order, and the last one viewed opens first), and a home
  at another site run by its own server, linked to this one
  ([docs/MULTI-HOME.md](docs/MULTI-HOME.md)).
- Multiple homes and users, with admin, operator and member roles, and
  guests who get only what an admin ticks for them (lights, light settings,
  cameras, the water heater, and chosen thermostats).
- Two-factor login (authenticator app) asked for after the password,
  single-use recovery codes, named "remembered" devices, and "keep me
  logged in" (times set by an admin).
- Login rules: account and password requirements, lockouts and lockdowns
  after failed logins.
- A setup checklist for new homes, a message of the day, and admins who
  can edit people's details.
- Safety limits on thermostats and water heaters, enforced in the backend
  on every command path.
- Audit log of logins, settings changes and device commands, with secrets
  redacted.
- Integration logins encrypted at rest; automatic daily database backups,
  and optional off-site copies.
- Optional HTTPS with your own certificate, or the same certificate as the
  server's web server (Apache, nginx, Caddy or certbot), picked up again
  after each renewal. The app restarts itself to apply an HTTPS change.

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
are in `deploy/proxy/`. A server reachable from the internet can add
fail2ban (`deploy/linux/smarthome fail2ban-setup`) and daily off-site
backups (`offsite-setup`). The full guide, including moving your database
over from another computer, is [docs/DEPLOY-LINUX.md](docs/DEPLOY-LINUX.md).

To use the web server's HTTPS certificate, switch on **Settings > Admin >
HTTPS > Use the web server's certificate**; `smarthome install` and
`smarthome update` set up the server side.

### Packages and automatic updates

The app is also published as `.rpm` and `.deb` packages that a server
updates every night (stable from release tags, dev from every change to
`dev`):

    curl -fsSL https://bobj4.github.io/Smart-Home-Unified-Control/install.sh | sudo bash -s -- dev
    sudo smarthome install

Details, and moving a git-checkout install over, are in
[packaging/README.md](packaging/README.md).

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
- A change in Settings > Admin > HTTPS takes effect after a restart; the
  app offers to restart itself when it runs in Docker.
- Writing the Cync thermostat's schedules and own settings has not been
  tried on every model: the app reads each change back and reports it if
  the thermostat did not keep it.
- Rheem limits how often it can be asked, so water heater readings are
  up to 5 minutes old.
- The Samsung 2014-2015 (H and J series) encrypted remote protocol has only
  been tested against a fake TV.

## Project layout

| Path | What |
| --- | --- |
| `backend/app` | FastAPI server: routes, models, security, device integrations |
| `backend/app/integrations` | One adapter per vendor (Cync, Hue, Kasa, Rheem, Samsung, LG, Roku, SmartThings, ratgdo, Frigate) |
| `backend/alembic` | Database migrations |
| `backend/tests` | Unit, contract and browser (Playwright) tests |
| `backend/scripts` | Server start, backups, secrets key, account recovery |
| `web` | The web app (plain JavaScript, no build step) |
| `deploy` | Dockerfile, Compose files, the Linux installer (`deploy/linux`) and reverse-proxy examples (`deploy/proxy`) |
| `packaging` | The `.rpm`/`.deb` packages and nightly updates |
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

Not affiliated with or endorsed by GE Lighting (Cync), Signify (Philips
Hue), TP-Link (Kasa), Rheem, Samsung, LG, Roku, Chamberlain, the ratgdo or
Frigate projects. Product names are
trademarks of their owners.

## License

No license has been chosen yet. Until one is added, all rights are reserved
by the author.
