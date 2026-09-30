"""
ASGI Request Logging and Correlation ID Middleware.

Extracts or generates an X-Request-ID correlation token, binds request-scoped
ContextVars, times latency with a monotonic clock, records completion at the
appropriate severity, and injects X-Request-ID into the outgoing response.
"""

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from hrms.core.config import settings
from hrms.core.logging import (
    get_current_tenant_id,
    get_current_user_id,
    set_current_client_ip,
    set_current_request_id,
    set_current_tenant_id,
    set_current_user_id,
)

logger = logging.getLogger("hrms.api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Captures every incoming request lifecycle for end-to-end observability:
    - Binds unique request_id and client_ip to ContextVars and request.state.
    - Tracks millisecond response latency.
    - Flags slow requests (> settings.log_slow_request_threshold_ms) as warnings.
    - Filters health probes to DEBUG severity to prevent log pollution.
    - Emits structured access log events with standard HTTP metadata.
    - Ensures the X-Request-ID header is present on all HTTP responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 1. Determine or generate correlation ID
        incoming_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        request_id = incoming_id.strip() if incoming_id else f"req_{uuid4().hex}"

        # 2. Determine client IP (supporting reverse proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host
        else:
            client_ip = "unknown"

        # 3. Bind to ContextVars & request state
        set_current_request_id(request_id)
        set_current_client_ip(client_ip)
        request.state.request_id = request_id

        start_time = time.perf_counter()
        status_code = 500
        exc_to_log: Exception | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            exc_to_log = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            # Sync contextvars from request.state in case authn set them mid-flight
            tenant_id = getattr(request.state, "tenant_id", None)
            if tenant_id:
                set_current_tenant_id(str(tenant_id))

            principal = getattr(request.state, "principal", None)
            if principal and hasattr(principal, "user_account_id"):
                set_current_user_id(str(principal.user_account_id))

            self._log_request(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
                request_id=request_id,
                exc=exc_to_log,
            )

    def _log_request(
        self,
        request: Request,
        status_code: int,
        duration_ms: float,
        client_ip: str,
        request_id: str,
        exc: Exception | None = None,
    ) -> None:
        path = request.url.path
        method = request.method
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

        # Check if route is excluded from normal INFO logging (e.g. /health)
        is_excluded = any(
            path == p or path.startswith(f"{p}/") for p in settings.log_exclude_paths_list
        )

        msg = f"{method} {path} completed {status_code} in {duration_ms:.2f}ms"
        if is_slow:
            msg += f" [SLOW REQUEST: threshold is {settings.log_slow_request_threshold_ms}ms]"

        if is_excluded:
            logger.debug(msg, extra=extra)
        elif status_code >= 500:
            if exc:
                logger.error(msg, extra=extra, exc_info=exc)
            else:
                logger.error(msg, extra=extra)
        elif status_code >= 400 or is_slow:
            logger.warning(msg, extra=extra)
        else:
            logger.info(msg, extra=extra)
