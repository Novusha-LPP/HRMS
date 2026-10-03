#!/bin/sh
# For the host's monitoring or cron: exit 1 (and say why) if an environment's last good
# backup is older than MAX_AGE_HOURS (default 26). Run as root: backups are root-only.
#   deploy/backup/check-backups.sh /srv/hrms-backups/testing
set -eu
dir="${1:?usage: check-backups.sh <backup dir of one environment>}"
max=$(( ${MAX_AGE_HOURS:-26} * 3600 ))
[ -f "$dir/latest" ] || { echo "no backup has ever succeeded in $dir"; exit 1; }
dump=$(sed -n 1p "$dir/latest")
[ "$dump" = "$(basename "$dump")" ] && [ -s "$dir/$dump" ] && [ -s "$dir/$dump.sha256" ] \
  || { echo "latest backup artifact or checksum is missing" >&2; exit 1; }
last=$(sed -n 2p "$dir/latest")
age=$(( $(date -u +%s) - $(date -u -d "$last" +%s) ))
[ "$age" -le "$max" ] || { echo "last good backup is $((age / 3600))h old ($last)"; exit 1; }
echo "ok: $(sed -n 1p "$dir/latest") at $last"
