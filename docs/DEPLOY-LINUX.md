# Running Smart Home Unified Control on a headless Linux server

The server runs in Docker, using the hardened container already in `deploy/`:
non-root, read-only files, no extra capabilities. One script,
`deploy/linux/smarthome`, sets it up, installs a systemd service so it starts
at every boot, and does the everyday jobs. Any 64-bit Linux that runs Docker
works: Rocky Linux, RHEL, AlmaLinux, Fedora, Ubuntu Server, Debian,
Raspberry Pi OS (64-bit).

Pick how it will be reached before you start:

| Choice | Who can open it | What you need |
| --- | --- | --- |
| **This network only** (default) | Phones and computers at home, or anywhere over a VPN such as Tailscale or WireGuard | Nothing else. Recommended. |
| **Internet, through a reverse proxy** | Anyone who has the address and a login | A domain name pointing at this server, a reverse proxy on it (Apache, nginx or Caddy), and two-factor login for everyone |

## 1. Install Docker and git (once)

Rocky Linux, RHEL, AlmaLinux 8 or newer (Docker's own RHEL packages):

    sudo dnf -y install dnf-plugins-core git
    sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
    sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker

If dnf asks to accept a key, its fingerprint is
`060A 61C5 1B55 8A7F 742B 77AA C52F EB6B 621E 9F35`. If it reports a conflict
with `podman` or `runc`, something on the server uses Podman: check before
removing it.

Ubuntu 24.04 or newer, Debian:

    sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
    sudo systemctl enable --now docker

Other systems: https://docs.docker.com/engine/install/. Then, to run the
script without `sudo`:

    sudo usermod -aG docker $USER

and log out and back in. Check: `docker run --rm hello-world`.

The script tells these cases apart if one is missed: Docker not installed,
the Compose plugin missing, Docker not running or not starting at boot, or
your account not allowed to use it, each with the command that fixes it.

## 2. Get the code

    git clone https://github.com/bobj4/Smart-Home-Unified-Control.git ~/smart-home
    cd ~/smart-home

That is the approved code (`master`). To try changes before they are approved,
add `--branch dev`.

## 3. Bring your settings key and database from another computer (optional)

To keep your users, devices, rooms and saved integration logins:

1. On the old computer, stop the server, so the database is complete on disk.
2. Copy its database to this server, for example from Windows, in the
   project folder: `scp backend\smart_home.db you@server:~/`
3. Find the SECRETS_KEY the old computer uses (its environment variable or
   start script). Saved logins only open with that same key.

Starting fresh instead? Skip this step: the installer makes a new key.

## 4. Install

    deploy/linux/smarthome install

It asks how the app will be reached (section 5) and, for the home-network
choice, whether you turn TVs on with Wake-on-LAN. Then it:

- creates `deploy/.env` (readable only by you) with a SECRETS_KEY: the one you
  give with `--secrets-key 'KEY'`, the one already there, or a new one. A new
  key is shown once, and the installer waits until you type `saved`.
- builds the image and starts the server (the first build takes a few
  minutes), and waits until it answers.
- installs and enables the systemd service `smarthome.service`, so the app
  starts at every boot (uses `sudo`; skip it with `--no-service`).
- prints the address to open and, on a new database, the first login.

Everything can be given up front, for scripts: `--access lan|proxy`,
`--host-network`, `--secrets-key KEY`, `--no-service`, and `--yes` to ask
nothing.

Then bring the database in, if you copied one:

    deploy/linux/smarthome import-db ~/smart_home.db

Open the address it printed, then press Ctrl+F5 once.

**First login.** On a new database the installer creates the account
`admin` with a random password and shows it once at the end (it stays in
`deploy/.env` as `FIRST_ADMIN_PASSWORD`, used only while the database has no
accounts). Log in and change it (Settings > My account). Without the
installer, the first password is `admin`. Locked out?
`deploy/linux/smarthome reset-login`.

**TVs and Wake-on-LAN.** Turning a TV *on* sends a network broadcast, which
does not leave Docker's own network. The Wake-on-LAN choice (or
`--host-network`, needs Docker Compose 2.24+) lets the container share the
server's network. Everything else works either way.

**Check it.** `deploy/linux/smarthome doctor` reports, in plain words: Docker
and the service starting at boot, the app's health, which addresses port
8000 is open on, whether the reverse proxy's visitor addresses are trusted,
the key, and the newest backup. It ends with what to fix, if anything.

## 5. Who can reach it

Docker opens port 8000 itself, ahead of the server's firewall (ufw or
firewalld). A firewall rule such as `ufw allow from 192.168.1.0/24 to any port
8000` therefore does **not** stop other networks reaching it. What decides it
is the address the port is published on, `BIND_ADDRESS` in `deploy/.env`,
which the installer sets:

| Choice | `BIND_ADDRESS` | Port 8000 is open on |
| --- | --- | --- |
| This network only | empty | every address of this server: the home network (and the internet, if the server has a public address; then use the proxy choice) |
| Reverse proxy | `127.0.0.1` | this server only, for the proxy |
| By hand | e.g. `192.168.1.20` | that one address |

After changing it by hand run `deploy/linux/smarthome start` (it recreates the
container) and check with `deploy/linux/smarthome doctor`. With Wake-on-LAN
(`--host-network`) the container shares the server's network, `BIND_ADDRESS`
does not apply, and the server's firewall does: allow port 8000 from your
home network only, for example

    sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.168.1.0/24 port port=8000 protocol=tcp accept'
    sudo firewall-cmd --reload

Never forward port 8000 on your router.

### This network only (and a VPN for outside)

Nothing more to do. For access from outside, a VPN such as Tailscale or
WireGuard keeps the app off the internet altogether. Browsers keep the login
cookie only over HTTPS (or on `localhost`), so turn on HTTPS: Settings > Admin >
HTTPS, upload a certificate, turn it on, then `deploy/linux/smarthome restart`.
The address becomes `https://…:8000`.

### Internet, through a reverse proxy

`deploy/linux/smarthome install --access proxy` (or choice 2):

- publishes port 8000 on `127.0.0.1` only (`BIND_ADDRESS=127.0.0.1`);
- sets `FORWARDED_ALLOW_IPS` to the Docker network's gateway, the address the
  proxy's requests arrive from, so the app believes the proxy's
  `X-Forwarded-For`. Login limits (5 failures per account, 20 per address, in
  5 minutes) and the audit log then use each visitor's own address (SEC-26).
  Without it every visitor looks like the proxy. `start` and `update` keep it
  current if the network changes.

Then set up the proxy, with HTTPS at the proxy (leave the app's own HTTPS off):

1. Point a DNS name at the server, and let ports 80 and 443 reach it.
2. Print a ready-made configuration for that name:

       deploy/linux/smarthome proxy-example apache home.example.com
       deploy/linux/smarthome proxy-example nginx home.example.com
       deploy/linux/smarthome proxy-example caddy home.example.com

   The files are in `deploy/proxy/`. Each redirects HTTP to HTTPS, passes the
   visitor's address, and says where its certificate comes from (Caddy gets
   one by itself; Apache and nginx with `certbot`).
3. SELinux (Rocky, RHEL): let the proxy connect to the app, once:
   `sudo setsebool -P httpd_can_network_connect 1`.
4. A web application firewall (ModSecurity with the OWASP rules) allows only
   GET, HEAD, POST and OPTIONS and answers 403 to the app's PUT, PATCH and
   DELETE. The Apache example removes that rule (911100) for this site.
5. Before the site is public: change the first `admin` password, and turn on
   Settings > Admin > Two-factor login > "Require two-factor login" for each
   home. Everyone then sets up an authenticator app at their next login,
   before they can see anything.
6. Check from a phone on mobile data: the page loads over HTTPS, login works,
   switching a light works (a PUT through the proxy), and
   `deploy/linux/smarthome logs` shows the phone's own address, not 172.x.

Until the proxy is up, you can still open the app from your own computer with
`ssh -L 8000:127.0.0.1:8000 you@server` and http://localhost:8000.

## 6. Everyday commands

| What | Command |
| --- | --- |
| Is it running? | `deploy/linux/smarthome status` |
| Is it set up safely? | `deploy/linux/smarthome doctor` |
| Watch the log | `deploy/linux/smarthome logs` (Ctrl+C to stop watching) |
| Update to the latest approved code | `deploy/linux/smarthome update` |
| Restart (after an HTTPS change) | `deploy/linux/smarthome restart` |
| Back up now | `deploy/linux/smarthome backup` |
| List backups | `deploy/linux/smarthome backups` |
| Restore a backup | `deploy/linux/smarthome restore <name from the list>` |
| Copy backups off the volume | `deploy/linux/smarthome copy-backups ~/smarthome-backups` |
| Stop / start | `deploy/linux/smarthome stop` / `start` (or `sudo systemctl stop/start smarthome`) |
| New password for a locked-out account | `deploy/linux/smarthome reset-login` |
| A new SECRETS_KEY | `deploy/linux/smarthome make-key` |
| Service on / off | `deploy/linux/smarthome install-service` / `remove-service` |

`update` pulls the code, backs the database up, rebuilds, restarts, waits
until the server answers, and removes the old image. The database update
(migrations) runs by itself when the server starts.

The server backs the database up every day (BACKUP_HOURS) and keeps 14
(BACKUP_KEEP); both are in `deploy/.env`. Those copies are inside Docker on
the same disk, so also copy them elsewhere. A nightly copy with cron
(`crontab -e`):

    30 3 * * * cd ~/smart-home && deploy/linux/smarthome copy-backups /mnt/backup/smarthome >/dev/null

Keep SECRETS_KEY with your backups: logins saved in them open only with it.

To be told when the app fails to start at boot, add an `OnFailure=` unit to
`smarthome.service` (`sudo systemctl edit smarthome`), for example one that
sends you an email.

## 7. Notes

- **Frigate on the same server:** enter the server's network address in
  Settings > Integrations (for example `http://192.168.1.20:5000`), not
  `localhost` (unless you use Wake-on-LAN / `--host-network`).
- **Where things are:** code in the checkout; settings in `deploy/.env`; the
  script's choices in `deploy/linux/local.conf`; the service in
  `/etc/systemd/system/smarthome.service`; database and backups in the Docker
  volume `deploy_data` (`docker volume inspect deploy_data`). Removing the
  checkout does not remove the volume.
- **Moving again later:** `deploy/linux/smarthome backup`, copy the newest
  backup out with `copy-backups`, and `import-db` it on the new server with
  the same SECRETS_KEY.
