#!/bin/sh
# Nightly backup of one HRMS environment: the database (pg_dump custom format) and the KYC
# document store, kept BACKUP_KEEP_DAYS days in /backups. Each dump is checked with
# pg_restore --list before it counts, and a `latest` marker records the last good one,
# which deploy/backup/check-backups.sh (and the off-site copy) rely on.
#
#   backup.sh            one backup now
#   backup.sh --daemon   one now, then every day at BACKUP_AT (container TZ)
set -eu
# Dumps hold every employee's personal data: readable by their owner (root) only. The host's
# off-site copy job therefore runs as root (docs/ENVIRONMENTS.md, "Backups").
umask 077

backup_once() {
  stamp=$(date +%Y%m%d-%H%M%S)
  dir="/backups/${HRMS_ENVIRONMENT:-unknown}"
  mkdir -p "$dir"
  db="$dir/hrms-$stamp.dump"
  files="$dir/kyc-$stamp.tar.gz"
  pg_dump --format=custom --compress=9 --file="$db.partial"
  pg_restore --list "$db.partial" >/dev/null   # a dump that can't be listed isn't a backup
  mv "$db.partial" "$db"
  if [ -d /kyc ]; then tar -czf "$files.partial" -C /kyc . && mv "$files.partial" "$files"; fi
  printf '%s\n%s\n' "$(basename "$db")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$dir/latest"
  find "$dir" -name 'hrms-*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
  find "$dir" -name 'kyc-*.tar.gz' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
  echo "backup ok: $db ($(du -h "$db" | cut -f1))"
}

seconds_until() {  # HH:MM today or tomorrow, in the container's TZ
  now=$(date +%s)
  target=$(date -d "$(date +%Y-%m-%d) $1" +%s 2>/dev/null || date -D "%Y-%m-%d %H:%M" -d "$(date +%Y-%m-%d) $1" +%s)
  [ "$target" -le "$now" ] && target=$((target + 86400))
  echo $((target - now))
}

if [ "${1:-}" = "--daemon" ]; then
  while true; do
    backup_once || echo "backup FAILED (will retry at the next slot)" >&2
    sleep "$(seconds_until "${BACKUP_AT:-01:30}")"
  done
else
  backup_once
fi
