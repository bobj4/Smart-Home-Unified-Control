#!/bin/bash
# Installs Smart Home Unified Control from its package repository and turns
# on automatic updates. Published at the repository's GitHub Pages site:
#   curl -fsSL https://bobj4.github.io/Smart-Home-Unified-Control/install.sh | sudo bash
#   ... | sudo bash -s -- dev     (the dev channel: every change merged into dev)
set -euo pipefail

CHANNEL="${1:-stable}"
BASE="${SMARTHOME_REPO_BASE:-https://bobj4.github.io/Smart-Home-Unified-Control}"
NAME="smart-home-unified-control"
[[ "$CHANNEL" == "stable" || "$CHANNEL" == "dev" ]] || { echo "Channel is stable or dev" >&2; exit 1; }
[[ "$(id -u)" -eq 0 ]] || { echo "Run it as root (sudo)." >&2; exit 1; }

if command -v dnf >/dev/null 2>&1; then
    cat > /etc/yum.repos.d/$NAME.repo <<REPO
[$NAME]
name=Smart Home Unified Control ($CHANNEL)
baseurl=$BASE/$CHANNEL/rpm
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=$BASE/KEY.asc
REPO
    dnf -y makecache --repo "$NAME"
    dnf -y install "$NAME"
    # Automatic updates for this package only, every night.
    dnf -y install dnf-automatic
    sed -i 's/^apply_updates *=.*/apply_updates = yes/' /etc/dnf/automatic.conf
    systemctl enable --now dnf-automatic.timer
    echo "Automatic updates: dnf-automatic.timer (it updates every package with updates; see /etc/dnf/automatic.conf)."
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y curl gnupg unattended-upgrades
    curl -fsSL "$BASE/KEY.asc" | gpg --dearmor -o /usr/share/keyrings/$NAME.gpg
    echo "deb [signed-by=/usr/share/keyrings/$NAME.gpg] $BASE/$CHANNEL/deb ./" > /etc/apt/sources.list.d/$NAME.list
    apt-get update
    apt-get install -y "$NAME"
    cat > /etc/apt/apt.conf.d/52$NAME <<CONF
Unattended-Upgrade::Origins-Pattern { "origin=$NAME"; };
CONF
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<CONF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
    echo "Automatic updates: unattended-upgrades (daily)."
else
    echo "Needs dnf (Rocky, RHEL, Fedora) or apt (Debian, Ubuntu)." >&2
    exit 1
fi
echo
echo "Installed. Next, once: sudo smarthome install"
