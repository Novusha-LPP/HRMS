#!/bin/sh
# Writes /config.js (see frontend/src/lib/runtimeConfig.ts) from this container's environment,
# so the same image serves testing and production. nginx serves it from /tmp: the html
# directory is read-only for the unprivileged nginx user.
set -eu
: "${HRMS_WEB_API_URL:?set HRMS_WEB_API_URL to this environment's API, e.g. https://hrmsapi.example.com}"
# Reject control characters/directive injection before generating JS and CSP.
origin() {
    case "$1" in
        http://*|https://*) ;;
        *) echo "Expected an HTTP(S) URL" >&2; exit 1 ;;
    esac
    case "$1" in *[!a-zA-Z0-9:/._@?=\&%+-]*) echo "Unsafe URL characters" >&2; exit 1;; esac
    printf '%s' "$1" | cut -d/ -f1-3
}
api_origin=$(origin "$HRMS_WEB_API_URL")
sentry_origin=""
if [ -n "${HRMS_WEB_SENTRY_DSN:-}" ]; then
    sentry_origin=$(origin "$HRMS_WEB_SENTRY_DSN" | sed 's#://[^/@]*@#://#')
fi
cat > /tmp/security-headers.conf <<CSP
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' $api_origin $sentry_origin; worker-src 'self' blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(self)" always;
CSP
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
