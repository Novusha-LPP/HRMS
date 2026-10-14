#!/usr/bin/env bash
# Read-only checks. Does not print secrets, mutate the DB or restart services.
set -euo pipefail
cd "$(dirname "$0")/.."
env_file=${1:?usage: deploy/preflight.sh <environment env file>}
[ -f "$env_file" ] || { echo 'Environment file missing' >&2; exit 1; }
[ "$(stat -c '%a' "$env_file")" = 600 ] || { echo 'Environment file must be mode 600' >&2; exit 1; }
docker compose --env-file "$env_file" -f deploy/compose.yml config --quiet
python3 - "$env_file" <<'PY'
import re, sys
from pathlib import Path
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    key, sep, value = line.partition('=')
    if sep:
        values[key.strip()] = value.strip().strip('\"').strip("'")
required = ['HRMS_ENVIRONMENT','HRMS_VERSION','HRMS_SECRET_KEY','HRMS_METRICS_TOKEN',
            'HRMS_FIELD_ENCRYPTION_KEYS','HRMS_APP_ROLE_PASSWORD','HRMS_DB_OWNER_PASSWORD',
            'HRMS_PLATFORM_ROLE_PASSWORD',
            'HRMS_WEB_API_URL','HRMS_CORS_ORIGINS','HRMS_BACKUP_DIR']
missing = [name for name in required if not values.get(name)]
if missing:
    raise SystemExit('Missing deployment settings: ' + ', '.join(missing))
if values['HRMS_ENVIRONMENT'] not in ['testing','production']:
    raise SystemExit('Must use a deployed environment')
if len(values['HRMS_SECRET_KEY']) < 32 or 'change-me' in values['HRMS_SECRET_KEY']:
    raise SystemExit('Signing secret is too short or still a placeholder')
if values.get('HRMS_DEBUG','false').lower() != 'false':
    raise SystemExit('Debug must be disabled')
for name in ['HRMS_APP_ROLE_PASSWORD','HRMS_DB_OWNER_PASSWORD','HRMS_PLATFORM_ROLE_PASSWORD']:
    if not re.fullmatch(r'[A-Za-z0-9_-]{24,}', values[name]):
        raise SystemExit(name + ' must be a long URL-safe secret for this compose template')
roles = ['HRMS_APP_ROLE_PASSWORD','HRMS_DB_OWNER_PASSWORD','HRMS_PLATFORM_ROLE_PASSWORD']
if len({values[name] for name in roles}) != len(roles):
    raise SystemExit('Owner, runtime and platform credentials must all differ')
if not values['HRMS_WEB_API_URL'].startswith('https://'):
    raise SystemExit('Deployed web API must use HTTPS')
if '*' in values.get('HRMS_FORWARDED_ALLOW_IPS',''):
    raise SystemExit('Forwarded proxy trust must be limited to the actual gateway')
print('Static deployment configuration passed. Key custody, restore/decryption, receiver delivery,')
print('proxy behavior and image provenance still require operational acceptance checks.')
PY
