#!/bin/sh
# Restore a backup into an environment's database. DESTRUCTIVE: replaces what is there.
# Practise it regularly on a scratch database (docs/ENVIRONMENTS.md, "Restore drill").
#
#   docker compose --env-file deploy/env/testing.env -f deploy/compose.yml run --rm \
#     --entrypoint /bin/sh backup /backup/restore.sh /backups/testing/hrms-YYYYMMDD-HHMMSS.dump
set -eu
dump="${1:?usage: restore.sh /backups/<env>/hrms-<stamp>.dump [target-database]}"
target="${2:-$PGDATABASE}"
pg_restore --list "$dump" >/dev/null
echo "Restoring $dump into database '$target' on $PGHOST — this replaces its contents."
printf "Type the database name to continue: "
read -r answer
[ "$answer" = "$target" ] || { echo "aborted"; exit 1; }
pg_restore --clean --if-exists --no-owner --exit-on-error --dbname="$target" "$dump"
echo "restored. Run 'python -m hrms.deploy migrate' (the migrate service) before starting the API."
