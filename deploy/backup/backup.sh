#!/bin/sh
# Successful artifacts and the marker are published only after every required check passes.
set -eu
umask 077

backup_locked() {
  stamp=$(date +%Y%m%d-%H%M%S)
  dir="${BACKUP_ROOT:-/backups}/${HRMS_ENVIRONMENT:-unknown}"
  mkdir -p "$dir" || return 1
  db="$dir/hrms-$stamp.dump"
  files="$dir/kyc-$stamp.tar.gz"
  pg_dump --format=custom --compress=6 --file="$db.partial" || return 1
  pg_restore --list "$db.partial" >/dev/null || return 1
  [ -d "${KYC_ROOT:-/kyc}" ] || { echo "document volume missing" >&2; return 1; }
  if [ -d "${KYC_ROOT:-/kyc}" ]; then
    tar -czf "$files.partial" -C "${KYC_ROOT:-/kyc}" . || return 1
    tar -tzf "$files.partial" >/dev/null || return 1
    mv "$files.partial" "$files" || return 1
    (cd "$dir" && sha256sum "$(basename "$files")" > "$(basename "$files").sha256") || return 1
  fi
  mv "$db.partial" "$db" || return 1
  (cd "$dir" && sha256sum "$(basename "$db")" > "$(basename "$db").sha256") || return 1
  printf '%s\n%s\n' "$(basename "$db")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$dir/latest.partial" || return 1
  mv "$dir/latest.partial" "$dir/latest" || return 1
  # Cleanup is deliberately after publication. Failed backups cannot discard good backups.
  find "$dir" -name 'hrms-*.dump*' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete || echo "backup retention cleanup failed" >&2
  find "$dir" -name 'kyc-*.tar.gz*' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete || echo "backup retention cleanup failed" >&2
  echo "backup ok: $db"
}

seconds_until() {
  now=$(date +%s)
  target=$(date -d "$(date +%Y-%m-%d) $1" +%s 2>/dev/null || date -D "%Y-%m-%d %H:%M" -d "$(date +%Y-%m-%d) $1" +%s) || return 1
  [ "$target" -le "$now" ] && target=$((target + 86400))
  echo $((target - now))
}

backup_once() {
  dir="${BACKUP_ROOT:-/backups}/${HRMS_ENVIRONMENT:-unknown}"
  mkdir -p "$dir" || return 1
  export BACKUP_SCRIPT="$0" BACKUP_RESULT_FILE="$dir/.result-$$"
  rm -f "$BACKUP_RESULT_FILE" || return 1
  # SHARE ROW EXCLUSIVE permits pg_dump reads but serializes backups and blocks
  # document row changes until both snapshots are complete. lock_timeout bounds waiting.
  psql --no-psqlrc --set=ON_ERROR_STOP=1 <<'SQL' || return 1
BEGIN;
SET LOCAL lock_timeout = '30s';
SET LOCAL idle_in_transaction_session_timeout = '15min';
LOCK TABLE employee_kyc_documents IN SHARE ROW EXCLUSIVE MODE;
\! timeout -k 10 600 sh "$BACKUP_SCRIPT" --locked
ROLLBACK;
SQL
  [ -f "$BACKUP_RESULT_FILE" ] || return 1
  rm -f "$BACKUP_RESULT_FILE" || return 1
}

if [ "${1:-}" = "--locked" ]; then
  backup_locked
  printf 'success\n' > "$BACKUP_RESULT_FILE"
elif [ "${1:-}" = "--daemon" ]; then
  while true; do
    if backup_once; then
      delay=$(seconds_until "${BACKUP_AT:-01:30}") || exit 1
    else
      echo "backup FAILED; verified artifacts retained; retrying soon" >&2
      delay=${BACKUP_RETRY_SECONDS:-300}
    fi
    sleep "$delay"
  done
else
  backup_once
fi
