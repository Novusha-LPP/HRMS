"""
ASGI request logging and correlation-id middleware.

For every HTTP request: takes the caller's X-Request-ID (or X-Correlation-ID) if it is a
safe token, otherwise generates one; binds it, the client address and later the tenant and
user to the logging ContextVars; times the request; writes one access-log line at a
severity matching the outcome; and returns X-Request-ID and X-App-Version on the response.

Plain ASGI rather than Starlette's BaseHTTPMiddleware, which runs the app in a separate
task and adds per-request overhead.
"""

import logging
import re
import time
from uuid import uuid4

from hrms.core.config import settings
from hrms.core.logging import (
    get_current_tenant_id,
    get_current_user_id,
    set_current_client_ip,
    set_current_request_id,
    set_current_tenant_id,
    set_current_user_id,
)
from hrms.core.version import APP_VERSION

logger = logging.getLogger("hrms.api.access")

# A caller-supplied id is echoed into logs, headers and error bodies, so it must be short and
# plain: anything else (log injection, a 10 KB header) is replaced with our own id.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}")


def _incoming_request_id(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name in (b"x-request-id", b"x-correlation-id"):
            candidate = value.decode("latin-1").strip()
            if _SAFE_REQUEST_ID.fullmatch(candidate):
                return candidate
    return None


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope.get("headers", [])) or f"req_{uuid4().hex}"
        # uvicorn --proxy-headers has already replaced scope["client"] with the caller's
        # address as reported by a *trusted* proxy (--forwarded-allow-ips). Reading
        # X-Forwarded-For ourselves would let any caller write their own.
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        set_current_request_id(request_id)
        set_current_client_ip(client_ip)
        set_current_tenant_id(None)
        set_current_user_id(None)
        scope.setdefault("state", {})["request_id"] = request_id

        started = time.perf_counter()
        status_code = 500
        failure: BaseException | None = None

        async def send_with_headers(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"x-request-id", b"x-app-version")
                ]
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-app-version", APP_VERSION.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except BaseException as exc:
            failure = exc
            status_code = 500
            raise
        finally:
            state = scope.get("state", {})
            if state.get("tenant_id"):
                set_current_tenant_id(str(state["tenant_id"]))
            principal = state.get("principal")
            if principal is not None and hasattr(principal, "user_account_id"):
                set_current_user_id(str(principal.user_account_id))
            _log_request(
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                status_code=status_code,
                duration_ms=(time.perf_counter() - started) * 1000,
                client_ip=client_ip,
                request_id=request_id,
                exc=failure,
            )


def _log_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: str,
    request_id: str,
    exc: BaseException | None,
) -> None:
    is_slow = duration_ms >= settings.log_slow_request_threshold_ms
    extra = {
        "http_method": method,
        "http_path": path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "client_ip": client_ip,
        "request_id": request_id,
        "tenant_id": get_current_tenant_id(),
        "user_id": get_current_user_id(),
        "slow_request": is_slow,
    }
    excluded = any(path == p or path.startswith(f"{p}/") for p in settings.log_exclude_paths_list)

    msg = f"{method} {path} completed {status_code} in {duration_ms:.2f}ms"
    if is_slow:
        msg += f" [SLOW REQUEST: threshold is {settings.log_slow_request_threshold_ms}ms]"

    if excluded:
        logger.debug(msg, extra=extra)
    elif status_code >= 500:
        logger.error(msg, extra=extra, exc_info=exc)
    elif status_code >= 400 or is_slow:
        logger.warning(msg, extra=extra)
    else:
        logger.info(msg, extra=extra)
