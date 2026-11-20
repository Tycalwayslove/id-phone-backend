#!/usr/bin/env bash
set -euo pipefail

trap 'exit 0' TERM INT

while true; do
    if bash /scripts/backup.sh; then
        now=$(date -u +%s)
        next=$(date -u -d "$(date -u -d "@$now" +%F) 02:00:00" +%s)
        if (( next <= now )); then
            next=$((next + 86400))
        fi
        delay=$((next - now))
    else
        delay=900
    fi

    sleep "$delay" &
    wait "$!"
done
