"""
Unified error handling subsystem for HRMS Platform.

Standardizes all error responses into an enterprise dual-compatible envelope:
{
    "detail": "...",
    "code": "...",
    "request_id": "...",
    "error": {
        "code": "...",
        "message": "...",
        "details": [...],
        "request_id": "...",
        "timestamp": "..."
    }
}

Preserves 100% backwards compatibility with existing frontend code checking
body.detail or body.code, while supplying structured observability for clients,
logging collectors, and support workflows.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from hrms.core.config import settings
from hrms.core.errors import CodedHTTPException
from hrms.core.logging import get_current_request_id
from hrms.core.security import PasswordTooLong

logger = logging.getLogger("hrms.errors")


def _get_status_code_name(status_code: int) -> str:
    """Generate a clean machine code for standard HTTP status codes."""
    try:
        phrase = HTTPStatus(status_code).name
        return f"HTTP_{status_code}_{phrase}"
    except ValueError:
        return f"HTTP_{status_code}"


def create_error_response(
    status_code: int,
    code: str,
    detail: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """
    Build a standardized dual-compatible error response.
    Maintains top-level 'detail', 'code', and 'request_id' alongside a rich
    inner 'error' dictionary.
    """
    req_id = get_current_request_id() or ""
    now_iso = datetime.now(UTC).isoformat()

    body = {
        "detail": detail,
        "code": code,
        "request_id": req_id,
        "error": {
            "code": code,
            "message": detail,
            "details": details or [],
            "request_id": req_id,
            "timestamp": now_iso,
        },
    }

    resp_headers = dict(headers or {})
    if req_id and "X-Request-ID" not in resp_headers:
        resp_headers["X-Request-ID"] = req_id

    return JSONResponse(status_code=status_code, content=body, headers=resp_headers)


async def coded_http_exception_handler(
    request: Request, exc: CodedHTTPException
) -> JSONResponse:
    """Handles domain exceptions that define a specific business error code."""
    return create_error_response(
        status_code=exc.status_code,
        code=exc.code,
        detail=exc.detail,
        headers=exc.headers,
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Normalizes standard FastAPI/Starlette HTTP exceptions."""
    code = _get_status_code_name(exc.status_code)
    detail_str = exc.detail or "An error occurred"
    return create_error_response(
        status_code=exc.status_code,
        code=code,
        detail=detail_str,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Transforms Pydantic validation errors into clean, structured field descriptions
    rather than leaking raw internal tuples.
    """
    field_errors: list[dict[str, Any]] = []
    summary_messages: list[str] = []

    for err in exc.errors():
        loc_parts = [str(x) for x in err.get("loc", []) if x != "body"]
        field_path = ".".join(loc_parts) or "payload"
        msg = err.get("msg", "Invalid value")
        err_type = err.get("type", "validation_error")

        field_errors.append(
            {
                "field": field_path,
                "message": msg,
                "type": err_type,
            }
        )
        summary_messages.append(f"{field_path}: {msg}")

    detail_summary = (
        f"Validation error on {', '.join(summary_messages)}"
        if summary_messages
        else "Invalid request parameters"
    )

    return create_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        detail=detail_summary,
        details=field_errors,
    )


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    """
    Safely captures database integrity/foreign-key/unique constraint errors.
    Logs the exact constraint internally for diagnostics, but shields the client.
    """
    cause = getattr(exc.orig, "__cause__", None)
    constraint = getattr(cause, "constraint_name", None) or str(exc.orig)
    logger.warning(
        "Database integrity conflict on %s %s: constraint=%s",
        request.method,
        request.url.path,
        constraint,
        extra={"constraint": str(constraint), "db_cause": str(exc.orig)},
    )
    return create_error_response(
        status_code=409,
        code="RESOURCE_CONFLICT",
        detail="This change conflicts with an existing record or references a missing record",
    )


async def password_too_long_handler(
    request: Request, exc: PasswordTooLong
) -> JSONResponse:
    """Handles oversized passwords rejected by bcrypt."""
    return create_error_response(
        status_code=422,
        code="PASSWORD_TOO_LONG",
        detail=str(exc),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Catches all unexpected 500 exceptions:
    - Logs the full traceback server-side tagged with correlation and request metadata.
    - Returns an opaque, non-leaking error response in production with request_id for support.
    - In development mode (debug=True), includes debug traceback details in the response.
    """
    req_id = get_current_request_id() or ""
    logger.exception(
        "Unhandled server exception on %s %s: %s",
        request.method,
        request.url.path,
        str(exc),
        extra={"request_id": req_id, "url": str(request.url)},
    )

    detail = (
        f"An internal server error occurred. Please quote request ID '{req_id}' to support."
        if req_id
        else "An internal server error occurred. Please contact support."
    )

    debug_details: list[dict[str, Any]] = []
    if settings.debug:
        debug_details = [
            {
                "exception_type": exc.__class__.__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
            }
        ]

    return create_error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        detail=detail,
        details=debug_details,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all unified exception handlers with the FastAPI application."""
    app.add_exception_handler(CodedHTTPException, cast(Any, coded_http_exception_handler))
    app.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, validation_exception_handler))
    app.add_exception_handler(IntegrityError, cast(Any, integrity_error_handler))
    app.add_exception_handler(PasswordTooLong, cast(Any, password_too_long_handler))
    app.add_exception_handler(Exception, cast(Any, unhandled_exception_handler))
