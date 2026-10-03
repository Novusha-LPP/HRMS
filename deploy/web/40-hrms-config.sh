#!/bin/sh
# Writes /config.js (see frontend/src/lib/runtimeConfig.ts) from this container's environment,
# so the same image serves testing and production. nginx serves it from /tmp: the html
# directory is read-only for the unprivileged nginx user.
set -eu
: "${HRMS_WEB_API_URL:?set HRMS_WEB_API_URL to this environment's API, e.g. https://hrmsapi.example.com}"
json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cat > /tmp/config.js <<JS
window.__HRMS_CONFIG__ = {
  apiUrl: "$(json "$HRMS_WEB_API_URL")",
  environment: "$(json "${HRMS_ENVIRONMENT:-production}")",
  sentryDsn: "$(json "${HRMS_WEB_SENTRY_DSN:-}")",
  sentryEnvironment: "$(json "${HRMS_ENVIRONMENT:-production}")"
};
JS
echo "hrms web: config.js written for ${HRMS_ENVIRONMENT:-production} -> $HRMS_WEB_API_URL"
