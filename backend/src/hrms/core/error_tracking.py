"""
Error tracking (Sentry). Off unless HRMS_SENTRY_DSN is set.

This is an HR system, so what leaves the process is kept to what's needed to fix a bug:
- no request bodies, no local variables from stack frames, no default PII (IP, cookies,
  user details beyond the account id);
- everything else that could carry data — headers, query strings, exception messages,
  breadcrumbs, extra fields — goes through the same redaction as the logs (core/logging);
- each event is tagged with the release, commit, request id and tenant id, so it links to
  the exact build and to the matching log lines.
"""

import logging
from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger
from sentry_sdk.types import Event, Hint

from hrms.core.config import settings
from hrms.core.logging import (
    get_current_request_id,
    get_current_tenant_id,
    get_current_user_id,
    redact_sensitive_data,
    redact_text,
)
from hrms.core.version import APP_VERSION, GIT_SHA


def init_error_tracking(**overrides: Any) -> bool:
    """Start Sentry if a DSN is configured. Returns whether it was started."""
    dsn = overrides.pop("dsn", settings.sentry_dsn)
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment or settings.environment,
        release=f"hrms@{APP_VERSION}",
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=scrub_event,
        before_breadcrumb=_scrub_breadcrumb,
        # ERROR log records become events; lower levels ride along as breadcrumbs.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        **overrides,
    )
    sentry_sdk.set_tag("commit", GIT_SHA)
    # "GET /x completed 500" duplicates the exception event it follows.
    ignore_logger("hrms.api.access")
    return True


def scrub_event(sentry_event: Event, hint: Hint) -> Event | None:
    event = cast(dict[str, Any], sentry_event)
    tags = event.setdefault("tags", {})
    if request_id := get_current_request_id():
        tags["request_id"] = request_id
    if tenant_id := get_current_tenant_id():
        tags["tenant_id"] = tenant_id
    if user_id := get_current_user_id():
        event["user"] = {"id": user_id}
    else:
        event.pop("user", None)

    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        request.pop("data", None)
        if isinstance(request.get("headers"), dict):
            request["headers"] = redact_sensitive_data(request["headers"])
        if isinstance(request.get("query_string"), str):
            request["query_string"] = redact_text(request["query_string"])

    for exception in event.get("exception", {}).get("values", []) or []:
        if isinstance(exception.get("value"), str):
            exception["value"] = redact_text(exception["value"])
        for frame in (exception.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)

    if isinstance(event.get("logentry"), dict):
        entry = event["logentry"]
        for field in ("message", "formatted"):
            if isinstance(entry.get(field), str):
                entry[field] = redact_text(entry[field])
        if entry.get("params"):
            entry["params"] = redact_sensitive_data(entry["params"])
    if isinstance(event.get("message"), str):
        event["message"] = redact_text(event["message"])
    if event.get("extra"):
        event["extra"] = redact_sensitive_data(event["extra"])
    return sentry_event


def _scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    if isinstance(crumb.get("message"), str):
        crumb["message"] = redact_text(crumb["message"])
    if crumb.get("data"):
        crumb["data"] = redact_sensitive_data(crumb["data"])
    return crumb
