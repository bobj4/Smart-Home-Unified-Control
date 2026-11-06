# Packages and automatic updates

`.github/workflows/packages.yml` builds a `.rpm` and a `.deb` and publishes
them as package repositories on this repository's GitHub Pages site:

| Channel | Built from | Version |
| --- | --- | --- |
| `stable` | a tag such as `v1.0.0` | the tag |
| `dev` | every push to `dev` | `0.0.<run number>` |

A server installs once and then updates itself every night
(`dnf-automatic` on Rocky/RHEL, `unattended-upgrades` on Debian/Ubuntu).
After each upgrade the package starts `smarthome-upgrade.service`, which
backs up the database, rebuilds the app and restarts it.

## One-time setup (the repository owner)

1. A signing key. On Windows, Git for Windows includes gpg:

       "C:\Program Files\Git\usr\bin\gpg.exe" --quick-generate-key "Smart Home Unified Control packages" rsa4096 sign 0
       "C:\Program Files\Git\usr\bin\gpg.exe" --armor --export-secret-keys "Smart Home Unified Control packages" > package-key.asc

   It asks for a passphrase: keep it, with `package-key.asc`, in your
   password manager, and delete the file from Downloads afterwards.
2. GitHub > the repository > Settings > Secrets and variables > Actions >
   New repository secret: `PACKAGE_GPG_KEY` (the whole of package-key.asc)
   and `PACKAGE_GPG_PASSPHRASE`.
3. Push to `dev` (or merge a pull request into it). The **packages**
   workflow runs and creates the `gh-pages` branch.
4. Settings > Pages > Build and deployment: Deploy from a branch,
   `gh-pages`, `/ (root)`.

## Installing on a server

    curl -fsSL https://bobj4.github.io/Smart-Home-Unified-Control/install.sh | sudo bash -s -- dev
    sudo smarthome install

(`-s -- dev` for the dev channel; leave it out for stable.)

## Moving a git-checkout install to the package

The database and backups stay in the Docker volume `deploy_data`, which both
use. From the old checkout (`~/smart-home`):

    deploy/linux/smarthome remove-service
    sudo mkdir -p /opt/smart-home-unified-control/deploy/linux
    sudo cp deploy/.env /opt/smart-home-unified-control/deploy/.env
    sudo cp deploy/linux/local.conf /opt/smart-home-unified-control/deploy/linux/ 2>/dev/null || true
    curl -fsSL https://bobj4.github.io/Smart-Home-Unified-Control/install.sh | sudo bash -s -- dev
    sudo smarthome install-service
    sudo smarthome doctor

The package finds the copied settings, rebuilds the app from its own files
and starts it with the same data. The old checkout can then be deleted.
