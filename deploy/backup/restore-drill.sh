#!/bin/sh
# Run through the backup container against the environment DB, restoring only a new scratch DB.
set -eu
umask 077
dump="${1:?usage: restore-drill.sh <dump>}"
[ -f "$dump.sha256" ] || { echo "checksum missing" >&2; exit 1; }
(cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256")
target="hrms_restore_$(date -u +%Y%m%d%H%M%S)_test"
cleanup() { dropdb --if-exists "$target" >/dev/null; }
trap cleanup EXIT INT TERM
createdb "$target"
pg_restore --no-owner --exit-on-error --dbname="$target" "$dump"
psql --no-psqlrc --set=ON_ERROR_STOP=1 --dbname="$target" -c \
  "SELECT version_num FROM alembic_version; SELECT count(*) FROM tenants; SELECT count(*) FROM employments;"
# Record actual timing, recovered object checks and key verification separately.
echo "Database restore succeeded into $target; complete KYC/key validation before signing off recovery."
