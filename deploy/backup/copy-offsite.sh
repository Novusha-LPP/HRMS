#!/bin/sh
# Scheduled by the host. A crypt remote (or explicitly verified encrypted provider) is required.
# Copies append-only artifacts; never mirrors deletions into the disaster-recovery destination.
set -eu
umask 077
source_dir="${1:?usage: copy-offsite.sh <environment backup directory>}"
: "${HRMS_BACKUP_REMOTE:?set an encrypted off-site rclone destination}"
: "${HRMS_BACKUP_REMOTE_ENCRYPTED:?set true after verifying destination encryption}"
[ "$HRMS_BACKUP_REMOTE_ENCRYPTED" = true ] || { echo "encrypted destination required" >&2; exit 1; }
"$(dirname "$0")/check-backups.sh" "$source_dir"
rclone copy "$source_dir" "$HRMS_BACKUP_REMOTE" --immutable --checksum --contimeout 10s --timeout 1m --retries 3 \
  --exclude '*.partial' --exclude 'latest*' --exclude '.result-*'
# The remote retains unique artifacts even when local retention removes older copies.
if [ -n "${METRICS_DIR:-}" ]; then
  mkdir -p "$METRICS_DIR"
  env_name=$(basename "$source_dir")
  case "$env_name" in testing|production) ;; *) echo "invalid environment" >&2; exit 1;; esac
  printf 'hrms_offsite_backup_last_success_timestamp_seconds{environment="%s"} %s\n' \
    "$env_name" "$(date -u +%s)" > "$METRICS_DIR/offsite-$env_name.prom.tmp"
  mv "$METRICS_DIR/offsite-$env_name.prom.tmp" "$METRICS_DIR/offsite-$env_name.prom"
fi
