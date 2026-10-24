# Running the smart home server in Docker

Docker Desktop (Windows) or Docker Engine (Linux). All commands run from the
project folder (`C:\Users\oracn\Downloads\Application`).

## First start

1. Copy `deploy\.env.example` to `deploy\.env`. Set `SECRETS_KEY` to the key
   you already use (otherwise saved Rheem, TV and Frigate logins can't be read).
2. Build and start:

       docker compose -f deploy/docker-compose.yml up -d --build

3. Open `http://<this computer's IP>:8000` on a phone, or
   `http://localhost:8000` on this computer.

## Moving your existing database in (once)

Stop the app if it is running outside Docker, then:

    docker compose -f deploy/docker-compose.yml stop
    docker compose -f deploy/docker-compose.yml run --rm --user root -v "${PWD}\backend:/import:ro" smart-home sh -c "cp /import/smart_home.db /app/data/smart_home.db && chown 10001:10001 /app/data/smart_home.db"
    docker compose -f deploy/docker-compose.yml start

## Everyday commands

| What | Command |
| --- | --- |
| Logs | `docker compose -f deploy/docker-compose.yml logs -f` |
| Restart (after an HTTPS change) | `docker compose -f deploy/docker-compose.yml restart` |
| Update after applying a package | `docker compose -f deploy/docker-compose.yml up -d --build` |
| Backup now | `docker compose -f deploy/docker-compose.yml exec smart-home python scripts/backup.py` |
| List backups | `docker compose -f deploy/docker-compose.yml exec smart-home python scripts/backup.py --list` |

Restoring a backup (the server must be stopped):

    docker compose -f deploy/docker-compose.yml stop
    docker compose -f deploy/docker-compose.yml run --rm smart-home python scripts/backup.py --restore /app/data/backups/<file>.db
    docker compose -f deploy/docker-compose.yml start

Copy backups off the computer now and then:

    docker compose -f deploy/docker-compose.yml cp smart-home:/app/data/backups .\backups-copy

## HTTPS

Upload the certificate in Settings > Admin > HTTPS, turn the switch on, then
restart the container. The address becomes `https://<IP>:8000`.

## Things that differ inside Docker

- **Frigate on this same computer:** enter the computer's network address
  (for example `http://192.168.1.20:5000`), not `localhost`; inside the
  container, localhost is the container itself.
- **Turning TVs on with Wake-on-LAN:** the broadcast does not leave Docker's
  network. On Linux, use `network_mode: host` (see docker-compose.yml). On
  Windows, run the server outside Docker if you need this.
- **One server at a time:** stop the one started with `scripts\serve.py`
  before starting the container; both use port 8000.
