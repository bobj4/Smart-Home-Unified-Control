# Running Smart Home Control on a headless Linux server

The server runs in Docker, using the hardened container already in `deploy/`:
non-root, read-only files, no extra capabilities, restarted automatically
(including after a reboot). One script, `deploy/linux/smarthome`, does the
setup and the everyday jobs. Any 64-bit Linux that runs Docker works: Ubuntu
Server, Debian, Fedora, Raspberry Pi OS (64-bit).

## 1. Install Docker (once)

Ubuntu 24.04 or newer:

    sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
    sudo systemctl enable --now docker

Other systems: follow https://docs.docker.com/engine/install/ for yours, and
install git. Check both parts are there:

    docker --version && docker compose version

Optional, to run the script without `sudo`: `sudo usermod -aG docker $USER`,
then log out and back in.

## 2. Get the code onto the server

The repository is private, so give the server its own read-only key:

    ssh-keygen -t ed25519 -f ~/.ssh/smarthome_deploy -N "" -C "smarthome server"
    cat ~/.ssh/smarthome_deploy.pub

On GitHub: the repository > Settings > Deploy keys > Add deploy key, paste
that line, leave "Allow write access" off. Then on the server:

    printf 'Host github.com\n  IdentityFile ~/.ssh/smarthome_deploy\n' >> ~/.ssh/config
    git clone --branch main git@github.com:bobj4/Smart-Home-Control.git ~/smart-home
    cd ~/smart-home

(`main` is what has been approved; use `dev` to try changes before they are.)

Without git: on Windows, `git archive --format=zip -o smart-home.zip main`,
copy it over (`scp smart-home.zip user@server:`), and unzip it. Updates then
mean copying a new zip; git makes them one command.

## 3. Bring your settings key and database from Windows (optional)

To keep your users, devices, rooms and saved integration logins:

1. On Windows, stop the server (close its window or Ctrl+C), so the database
   is complete on disk.
2. Copy `C:\Users\oracn\Downloads\Application\backend\smart_home.db` to the
   server, for example: `scp backend\smart_home.db user@server:~/`
3. Find the SECRETS_KEY you use on Windows (your environment variable or
   start script). Saved logins only open with that same key.

Starting fresh instead? Skip this step: the installer makes a new key, and
the first login is username `admin`, password `admin` (change it at once).

## 4. Install

    deploy/linux/smarthome install --secrets-key 'YOUR-KEY'

or, starting fresh, just `deploy/linux/smarthome install`. It:

- creates `deploy/.env` from `deploy/.env.example` (readable only by you),
  with your key or a new one. Keep a copy of the key off the server.
- builds the image and starts the server (the first build takes a few
  minutes), waits until it answers, and prints its addresses.

Then bring the database in, if you copied it:

    deploy/linux/smarthome import-db ~/smart_home.db

Open `http://<server address>:8000` on a phone or computer on your network,
then press Ctrl+F5 once.

**TVs and Wake-on-LAN.** Turning a TV *on* sends a network broadcast, which
does not leave Docker's own network. If you use that, install with
`--host-network` (needs Docker Compose 2.24+): the container then shares the
server's network. Everything else works either way.

## 5. Firewall and HTTPS

Allow port 8000 from your home network only, for example with ufw:

    sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp

Do not forward port 8000 on your router: the app is built for the home
network (docs/SECURITY.md, SEC-50). For access from outside, use a VPN to
your network (WireGuard, Tailscale).

HTTPS: Settings > Admin > HTTPS, upload a certificate, turn it on, then
`deploy/linux/smarthome restart`. The address becomes `https://…:8000`.

## 6. Everyday commands

| What | Command |
| --- | --- |
| Is it running? | `deploy/linux/smarthome status` |
| Watch the log | `deploy/linux/smarthome logs` (Ctrl+C to stop watching) |
| Update to the latest approved code | `deploy/linux/smarthome update` |
| Restart (after an HTTPS change) | `deploy/linux/smarthome restart` |
| Back up now | `deploy/linux/smarthome backup` |
| List backups | `deploy/linux/smarthome backups` |
| Restore a backup | `deploy/linux/smarthome restore <name from the list>` |
| Copy backups off the volume | `deploy/linux/smarthome copy-backups ~/smarthome-backups` |
| Stop / start | `deploy/linux/smarthome stop` / `start` |

`update` pulls the code, backs the database up, rebuilds, restarts, waits
until the server answers, and removes the old image. The database update
(migrations) runs by itself when the server starts.

The server backs the database up every day (BACKUP_HOURS) and keeps 14
(BACKUP_KEEP); both are in `deploy/.env`. Those copies are inside Docker on
the same disk, so also copy them elsewhere now and then. A nightly copy with
cron (`crontab -e`):

    30 3 * * * cd ~/smart-home && deploy/linux/smarthome copy-backups /mnt/backup/smarthome >/dev/null

Keep SECRETS_KEY with your backups: logins saved in them open only with it.

## 7. Notes

- **Frigate on the same server:** enter the server's network address in
  Settings > Integrations (for example `http://192.168.1.20:5000`), not
  `localhost` (unless you installed with `--host-network`).
- **Where things are:** code in the checkout; settings in `deploy/.env`;
  database and backups in the Docker volume `deploy_data`
  (`docker volume inspect deploy_data`). Removing the checkout does not
  remove the volume.
- **Moving again later:** `deploy/linux/smarthome backup`, copy the newest
  backup out with `copy-backups`, and `import-db` it on the new server with
  the same SECRETS_KEY.
