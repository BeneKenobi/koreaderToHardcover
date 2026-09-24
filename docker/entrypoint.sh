#!/bin/sh
# Starts as root only to hand /data to the app user (volumes from older
# versions are root-owned), then drops privileges for the actual process.
set -e

APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown -R "$APP_UID:$APP_GID" /data
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
fi

exec "$@"
