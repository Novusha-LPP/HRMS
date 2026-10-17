#!/usr/bin/env bash
# Called as root by SSM, from the verified deployment bundle. No source builds on EC2.
set -Eeuo pipefail
umask 077
release_dir=$(realpath "${1:?usage: deploy.sh /opt/hrms/testing/releases/<release> [--code-only]}")
mode=${2:-}
[[ "$mode" == "" || "$mode" == "--code-only" ]] || { echo 'Unknown deployment mode' >&2; exit 1; }
[[ "$EUID" == 0 ]] || { echo 'Run as root (SSM Run Command does this)' >&2; exit 1; }
[[ "$release_dir" == /opt/hrms/testing/releases/* ]] || { echo 'Invalid release directory' >&2; exit 1; }
[[ -f "$release_dir/images.json" ]] || { echo 'Deployment manifest missing' >&2; exit 1; }
mkdir -p /opt/hrms/testing
exec 9>/opt/hrms/testing/deploy.lock
flock -n 9 || { echo 'Another deployment is already running' >&2; exit 1; }

mkdir -p /etc/hrms
for file in testing.runtime.env testing.migrate.env testing.deploy.env; do
  if [[ -f "$release_dir/$file" ]]; then
    install -m 600 -o root -g root "$release_dir/$file" "/etc/hrms/$file"
  fi
  path="/etc/hrms/$file"
  [[ -f "$path" && "$(stat -c '%a:%u' "$path")" == '600:0' ]] || {
    echo "Install $path as root with permissions 600" >&2; exit 1;
  }
done
if [[ ! -s /etc/hrms/rds-global-bundle.pem ]]; then
  curl --fail --silent --show-error \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    -o /tmp/hrms-rds-global-bundle.pem 2>/dev/null && \
    install -m 644 -o root -g root /tmp/hrms-rds-global-bundle.pem /etc/hrms/rds-global-bundle.pem 2>/dev/null && \
    rm -f /tmp/hrms-rds-global-bundle.pem || true
fi
[[ -s /etc/hrms/rds-global-bundle.pem ]] || { echo 'RDS CA bundle is missing' >&2; exit 1; }
python3 "$release_dir/validate.py" "$release_dir"
compose() {
  docker compose --env-file /etc/hrms/testing.deploy.env --env-file "$release_dir/images.env" \
    -f "$release_dir/compose.yml" "$@"
}
compose config --quiet
registry=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["api"].split("/")[0])' "$release_dir/images.json")
region=${registry#*.dkr.ecr.}
region=${region%.amazonaws.com}
# Keep the instance role's short-lived registry token out of the persistent Docker config.
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG
previous=$(readlink -f /opt/hrms/testing/current || true)
services_started=false
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" != 0 && "$services_started" == true && -f "$previous/images.env" ]]; then
    echo 'Deployment failed; attempting to restore the previous service images' >&2
    # Schema stays at its migrated revision; rollback requires backward-compatible migrations.
    docker compose --env-file /etc/hrms/testing.deploy.env --env-file "$previous/images.env" \
      -f "$previous/compose.yml" up -d --no-deps --wait --wait-timeout 180 api jobs web || \
      echo 'Automatic service rollback failed; inspect the instance' >&2
  fi
  rm -rf "$DOCKER_CONFIG"
  exit "$result"
}
trap cleanup EXIT
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
compose --profile tools pull --quiet
if [[ "$mode" != '--code-only' ]]; then
  # Old services stay running if preflight or migration fails.
  compose run --rm --no-deps migrate python /app/database-preflight.py
  compose run --rm --no-deps migrate
fi
services_started=true
compose up -d --no-deps --wait --wait-timeout 180 api jobs web
# Confirm the process is from this exact commit, beyond a successful DB readiness check.
expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$release_dir/images.json")
compose exec -T api python -c \
  'import json,sys,urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:8015/health", timeout=5)); sys.exit(0 if data["commit"] == sys.argv[1] else 1)' "$expected"
ln -sfn "$release_dir" /opt/hrms/testing/current
echo "Testing deployment healthy at commit $expected"
