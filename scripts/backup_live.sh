#!/bin/sh
# Copy data/live to the rclone destination in $BACKUP_REMOTE.
# Uses `rclone copy`, not `sync`: files deleted locally are never deleted remotely.
set -eu

cd "$(dirname "$0")/.."

# Load the nearest .env (this folder or a parent).
dir=$(pwd)
while [ "$dir" != "/" ]; do
    if [ -f "$dir/.env" ]; then
        set -a; . "$dir/.env"; set +a
        break
    fi
    dir=$(dirname "$dir")
done

: "${BACKUP_REMOTE:?BACKUP_REMOTE is not set (see .env.example)}"
exec rclone copy data/live "$BACKUP_REMOTE" --checksum --transfers 4 --log-level NOTICE
