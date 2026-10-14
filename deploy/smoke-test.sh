#!/usr/bin/env bash
# Brings the whole deployed stack (deploy/compose.yml) up from freshly built images with
# throwaway secrets, checks every guarantee an environment relies on, and tears it down.
# CI runs it on every change (.github/workflows/checks.yml); run it locally the same way:
#   deploy/smoke-test.sh            (builds images tagged :smoke)
#   SKIP_BUILD=1 deploy/smoke-test.sh
set -euo pipefail
# Any unexpected failure still says where it happened.
trap 'echo "SMOKE FAIL: line $LINENO: $BASH_COMMAND" >&2' ERR
cd "$(dirname "$0")/.."
work=$(mktemp -d)
project=hrms-smoke-$$
api_port=${SMOKE_API_PORT:-18915}
web_port=${SMOKE_WEB_PORT:-18980}
compose() { docker compose -p "$project" --env-file "$work/smoke.env" -f deploy/compose.yml "$@"; }
cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  # The backups are root-owned and private (umask 077), so remove them through a container.
  docker run --rm -v "$work:/w" alpine:3 rm -rf /w/backups >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
fail() { echo "SMOKE FAIL: $*" >&2; compose logs --tail 40 >&2 || true; exit 1; }
secret() { openssl rand -hex 24; }

if [ -z "${SKIP_BUILD:-}" ]; then
  docker build -q -t ghcr.io/novusha-lpp/hrms/api:smoke backend >/dev/null
  docker build -q -t ghcr.io/novusha-lpp/hrms/web:smoke -f deploy/web/Dockerfile . >/dev/null
fi

token=$(secret)
mkdir -p "$work/backups"
cat > "$work/smoke.env" <<ENV
HRMS_ENVIRONMENT=testing
HRMS_ENV_FILE=$work/smoke.env
HRMS_VERSION=smoke
HRMS_DB_OWNER_PASSWORD=$(secret)
HRMS_APP_ROLE_PASSWORD=$(secret)
HRMS_PLATFORM_ROLE_PASSWORD=$(secret)
HRMS_SECRET_KEY=$(secret)$(secret)
HRMS_METRICS_TOKEN=$token
HRMS_FIELD_ENCRYPTION_KEYS=smoke:$(python3 -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
HRMS_API_PORT=$api_port
HRMS_WEB_PORT=$web_port
HRMS_WEB_API_URL=http://127.0.0.1:$api_port
HRMS_CORS_ORIGINS=https://smoke.example.com
HRMS_ALLOW_PUBLIC_REGISTRATION=false
HRMS_BACKUP_DIR=$work/backups
ENV

compose up -d --wait --wait-timeout 180 db migrate api web || fail "stack did not become healthy"
compose up -d jobs backup
api=http://127.0.0.1:$api_port
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

[ "$(code "$api/health/ready")" = 200 ] || fail "API not ready"
for path in /docs /redoc /openapi.json; do
  [ "$(code "$api$path")" = 404 ] || fail "$path is public on a deployed environment"
done
[ "$(code "$api/metrics")" = 401 ] || fail "/metrics served without the token"
curl -s -X OPTIONS "$api/v1/auth/login" -H "Origin: https://evil.example.com" \
  -H "Access-Control-Request-Method: POST" -D - -o /dev/null \
  | grep -qi "access-control-allow-origin" && fail "CORS allows an unknown origin"
docker exec "$project-db-1" sh -c \
  "PGPASSWORD=hrms_app_dev_password psql -h db -U hrms_app -d hrms -c 'select 1'" >/dev/null 2>&1 \
  && fail "the published hrms_app password still works"

compose run --rm --no-deps -T migrate python -m hrms.deploy encrypt-pii --check >/dev/null \
  || fail "identifiers left unencrypted after migrate"
compose logs migrate | grep -q "encrypt-pii:" || fail "migrate did not run encrypt-pii"
[ "$(docker exec "$project-db-1" psql -U hrms -d hrms -tAc \
  "select array_to_string(setconfig, ',') from pg_db_role_setting s join pg_roles r on r.oid = s.setrole where r.rolname = 'hrms_app'" \
  | grep -c statement_timeout)" = 1 ] || fail "the app role has no statement timeout"

for _ in $(seq 1 20); do
  curl -s -H "Authorization: Bearer $token" "$api/metrics" \
    | grep -Eq 'hrms_job_last_success_timestamp_seconds\{job_name="accrual"\} [1-9]' && break
  sleep 3
done || true
curl -s -H "Authorization: Bearer $token" "$api/metrics" \
  | grep -Eq 'hrms_job_last_success_timestamp_seconds\{job_name="accrual"\} [1-9]' || fail "the jobs container did not record a successful accrual"

web=http://127.0.0.1:$web_port
curl -s "$web/config.js" | grep -q "\"http://127.0.0.1:$api_port\"" || fail "config.js not written"
curl -s "$web/config.js" | grep -q '"testing"' || fail "config.js has the wrong environment"
curl -s -D - -o /dev/null "$web/some/deep/link" | grep -qi "x-frame-options: DENY" \
  || fail "web security headers missing"
curl -s -D - -o /dev/null "$web/some/deep/link" | grep -qi "content-security-policy:.*script-src 'self'" \
  || fail "CSP missing from SPA"
curl -s -D - -o /dev/null "$web/config.js" | grep -qi "content-security-policy:" \
  || fail "CSP missing from config.js"
[ "$(code "$web/some/deep/link")" = 200 ] || fail "SPA fallback broken"

# Backups are root-only (umask 077), so look at them through a container.
backups() { docker run --rm -v "$work/backups:/b:ro" alpine:3 "$@"; }
latest=""
for _ in $(seq 1 20); do
  latest=$(backups sh -c 'cat /b/testing/latest 2>/dev/null | head -1') && [ -n "$latest" ] && break
  sleep 3
done
[ -n "$latest" ] || fail "no backup was written"
perms=$(backups stat -c '%a' "/b/testing/$latest")
[ "$perms" = 600 ] || fail "backup is mode $perms; it must be private (600)"
docker exec "$project-db-1" createdb -U hrms restore_drill
backups cat "/b/testing/$latest" \
  | docker exec -i "$project-db-1" pg_restore --no-owner --exit-on-error -U hrms -d restore_drill \
  || fail "the backup does not restore"
tables=$(docker exec "$project-db-1" psql -U hrms -d restore_drill -tAc \
  "select count(*) from information_schema.tables where table_schema = 'public'")
[ "$tables" -gt 40 ] || fail "restored backup has only $tables tables"

echo "SMOKE OK: health, hidden docs, metrics token, CORS, db password, PII encrypted, db timeouts, jobs, web config, private backup + restore ($tables tables)"
