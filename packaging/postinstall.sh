#!/bin/sh
# After installing or upgrading the package.
set -e
ROOT=/opt/smart-home-unified-control
chmod 755 "$ROOT/deploy/linux/smarthome"
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
fi
if [ -f "$ROOT/deploy/.env" ]; then
    # Already set up: finish the upgrade in the background (it rebuilds the
    # image, which takes a few minutes), so the package manager is not held.
    if command -v systemctl >/dev/null 2>&1; then
        systemctl start --no-block smarthome-upgrade.service || true
    fi
    echo "Smart Home Unified Control: updating in the background (journalctl -u smarthome-upgrade)."
else
    echo "Smart Home Unified Control is installed. Set it up with:"
    echo "  sudo smarthome install"
fi
