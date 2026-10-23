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
from hrms.core.field_crypto import FieldCryptoError
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


# What to tell the user when a known constraint refuses a write. Anything not listed gets the
# generic conflict message. Add an entry with every constraint a user can run into.
CONSTRAINT_MESSAGES: dict[str, str] = {
    "uq_user_accounts_employment": "This employee already has a login",
    "uq_account_email_lower": "A user with this email already exists",
    "uq_role_assignments_grant": "This login already has that role with that scope",
    "uq_leave_types_code": "A leave type with this code already exists",
    "uq_legal_entities_name": "A company with this name already exists",
    "uq_jobs_code": "A job title with this code already exists",
    "uq_grades_code": "A grade with this code already exists",
    "uq_cost_centres_code": "A cost centre with this code already exists",
    "uq_holidays_calendar_day": "This holiday is already on the calendar for that date",
    "uq_employments_number_ci": "This employee number is already used in the company",
    "uq_company_employee_number": "This employee number is already used in the company",
    "uq_punches_live": "This punch was already recorded",
    "ex_assignment_managers_period": (
        "The employee already has a manager of this kind for that period"
    ),
    "ex_hca_employment": "This employee already follows another holiday calendar then",
    "ex_hca_org_unit": "This department already follows another holiday calendar then",
    "ex_hca_legal_entity": "This company already follows another holiday calendar then",
    "ex_hca_tenant_default": "Another holiday calendar is already the default then",
    **{
        f"uq_{kind}_same_start_{scope}": "Another policy for the same target starts on that date"
        for kind in ("epa", "lpa")
        for scope in ("employment", "org_unit", "legal_entity")
    },
    "ck_leave_applications_dates": "The leave can't end before it starts",
    "ck_leave_applications_days": "The number of leave days can't be negative",
    "ck_approval_delegations_period": "A delegation must end after it starts",
    "ck_punches_coordinates": "The punch location is not a valid position",
    "ck_assignments_fte": "Working time (FTE) must be above 0 and at most 1",
    "ck_employments_separation": "An employee can't leave before they join",
    "ck_leave_balances_not_negative": "A leave balance can't go below zero",
    "ck_lpa_exactly_one_target": "A policy assignment must specify exactly one target",
    "ck_leave_balance_transactions_reference_type": "Invalid transaction reference type",
    **{
        f"ck_{table}_{column}_half_day": "Leave is counted in whole or half days"
        for table, column in (
            ("leave_applications", "days_requested"),
            ("leave_encashments", "days"),
            ("comp_off_grants", "days_granted"),
            ("attendance_days", "comp_off_days"),
            ("leave_types", "days_per_year"),
            ("leave_types", "min_days_per_application"),
            ("leave_types", "max_days_per_application"),
            ("leave_types", "max_carry_forward_days"),
            ("leave_bucket_policies", "days_per_year"),
            ("leave_bucket_policies", "max_carry_forward_days"),
            ("leave_bucket_policies", "max_encashment_days"),
        )
    },
    **{
        f"ck_{table}_effective_range": "The end date can't be before the start date"
        for table in (
            "assignment_managers",
            "assignments",
            "employee_policy_assignments",
            "leave_policy_assignments",
            "org_units",
            "positions",
        )
    },
}


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    """
    Safely captures database integrity/foreign-key/unique constraint errors.
    Logs the exact constraint internally for diagnostics, but shields the client: only the
    message registered for the constraint in CONSTRAINT_MESSAGES is shown.
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
    detail_msg = CONSTRAINT_MESSAGES.get(str(constraint))
    if not detail_msg:
        detail_msg = (
            f"Database conflict on constraint '{constraint}': {getattr(cause, 'detail', str(exc.orig))}"
            if not settings.is_deployed
            else "This change conflicts with an existing record or references a missing record"
        )
    return create_error_response(
        status_code=409,
        code="RESOURCE_CONFLICT",
        detail=detail_msg,
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


async def field_crypto_error_handler(request: Request, exc: FieldCryptoError) -> JSONResponse:
    """Encrypted data whose key is not configured: say so, never a bare 500."""
    return create_error_response(
        status_code=409,
        code="ENCRYPTION_KEY_UNAVAILABLE",
        detail=(
            "This record is encrypted with a key that is not configured on the server. "
            f"{exc}"
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all unified exception handlers with the FastAPI application."""
    app.add_exception_handler(CodedHTTPException, cast(Any, coded_http_exception_handler))
    app.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, validation_exception_handler))
    app.add_exception_handler(IntegrityError, cast(Any, integrity_error_handler))
    app.add_exception_handler(PasswordTooLong, cast(Any, password_too_long_handler))
    app.add_exception_handler(FieldCryptoError, cast(Any, field_crypto_error_handler))
    app.add_exception_handler(Exception, cast(Any, unhandled_exception_handler))
