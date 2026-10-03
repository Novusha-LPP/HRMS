#!/bin/sh
# Host cron, once a minute; node_exporter reads the resulting textfile.
set -eu
: "${METRICS_DIR:?set node_exporter textfile directory}"
mkdir -p "$METRICS_DIR"
tmp="$METRICS_DIR/hrms-backups.prom.tmp"
: > "$tmp"
for dir in "$@"; do
  env_name=$(basename "$dir")
  case "$env_name" in testing|production) ;; *) echo "invalid environment" >&2; exit 1;; esac
  ts=0
  if "$(dirname "$0")/check-backups.sh" "$dir" >/dev/null 2>&1; then
    ts=$(date -u -d "$(sed -n 2p "$dir/latest")" +%s)
  fi
  printf 'hrms_backup_last_success_timestamp_seconds{environment="%s"} %s\n' "$env_name" "$ts" >> "$tmp"
done
mv "$tmp" "$METRICS_DIR/hrms-backups.prom"
