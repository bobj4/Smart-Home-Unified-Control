#!/bin/sh
# Before removing the package (not on upgrades): stop the app. Its database
# and backups stay in the Docker volume, and deploy/.env stays on disk.
set -e
case "$1" in
    remove|0)
        if [ -x /opt/smart-home-unified-control/deploy/linux/smarthome ]; then
            /opt/smart-home-unified-control/deploy/linux/smarthome remove-service || true
            /opt/smart-home-unified-control/deploy/linux/smarthome stop || true
        fi ;;
esac
