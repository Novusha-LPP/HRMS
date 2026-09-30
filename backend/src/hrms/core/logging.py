"""
Enterprise-grade structured logging subsystem for HRMS Platform.

Provides:
- Asynchronous context propagation via ContextVars (request_id, tenant_id, user_id, client_ip).
- Structured single-line JSON formatting for production collectors (Datadog, CloudWatch, ELK).
- Colorized, readable console log formatting for local developer experience.
- Automated sensitive data & PII redaction (passwords, tokens, PAN, Aadhaar) via a logging Filter.
- Root logging setup and third-party logger tuning.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# ─── Context Variables ────────────────────────────────────────────────────────

request_id_ctx: ContextVar[str | None] = ContextVar("request_id_ctx", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id_ctx", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id_ctx", default=None)
client_ip_ctx: ContextVar[str | None] = ContextVar("client_ip_ctx", default=None)


def get_current_request_id() -> str | None:
    return request_id_ctx.get()


def set_current_request_id(request_id: str | None) -> None:
    request_id_ctx.set(request_id)


def get_current_tenant_id() -> str | None:
    return tenant_id_ctx.get()


def set_current_tenant_id(tenant_id: str | None) -> None:
    tenant_id_ctx.set(tenant_id)


def get_current_user_id() -> str | None:
    return user_id_ctx.get()


def set_current_user_id(user_id: str | None) -> None:
    user_id_ctx.set(user_id)


def get_current_client_ip() -> str | None:
    return client_ip_ctx.get()


def set_current_client_ip(client_ip: str | None) -> None:
    client_ip_ctx.set(client_ip)


# ─── PII & Sensitive Data Redaction ──────────────────────────────────────────

SENSITIVE_KEY_PATTERNS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "cookie",
    "set_cookie",
    "pan",
    "pan_number",
    "aadhaar",
    "aadhaar_number",
    "ssn",
    "bank_account",
    "bank_account_number",
    "account_number",
    "salary",
}

PAN_REGEX = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_REGEX = re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b")
REDACTED_TEXT = "***REDACTED***"


def redact_text(text: str) -> str:
    """Mask known sensitive patterns such as PAN and Aadhaar in unstructured strings."""
    if not isinstance(text, str) or not text:
        return text

    # Redact PAN cards: ABCDE1234F -> ABCDE****F
    def mask_pan(match: re.Match[str]) -> str:
        val = match.group(0)
        return f"{val[:5]}****{val[-1]}"

    text = PAN_REGEX.sub(mask_pan, text)

    # Redact Aadhaar numbers: 2345 6789 0123 -> ********0123
    def mask_aadhaar(match: re.Match[str]) -> str:
        clean = match.group(0).replace(" ", "")
        return f"********{clean[-4:]}"

    return AADHAAR_REGEX.sub(mask_aadhaar, text)


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively sanitize dictionaries, lists, and strings for sensitive keys."""
    if isinstance(obj, dict):
        sanitized = {}
        for key, value in obj.items():
            key_lower = str(key).lower().replace("-", "_")
            if any(pattern in key_lower for pattern in SENSITIVE_KEY_PATTERNS):
                sanitized[key] = REDACTED_TEXT
            else:
                sanitized[key] = redact_sensitive_data(value)
        return sanitized
    if isinstance(obj, (list, tuple, set)):
        return [redact_sensitive_data(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that sanitizes record messages, arguments, and custom extra
    fields to prevent sensitive PII or credentials from leaking to log sinks.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_sensitive_data(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(redact_sensitive_data(arg) for arg in record.args)

        return True


# ─── Formatters ───────────────────────────────────────────────────────────────

STANDARD_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """
    Outputs log records as structured, single-line JSON objects suitable for
    modern cloud log ingestors (Datadog, Loki, Elasticsearch, CloudWatch).
    """

    def format(self, record: logging.LogRecord) -> str:
        # Standardize message
        message = record.getMessage()

        # Capture request correlation context
        req_id = getattr(record, "request_id", None) or get_current_request_id()
        tenant_id = getattr(record, "tenant_id", None) or get_current_tenant_id()
        user_id = getattr(record, "user_id", None) or get_current_user_id()
        client_ip = getattr(record, "client_ip", None) or get_current_client_ip()

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        if req_id:
            payload["request_id"] = req_id
        if tenant_id:
            payload["tenant_id"] = tenant_id
        if user_id:
            payload["user_id"] = user_id
        if client_ip:
            payload["client_ip"] = client_ip

        # Include any custom extra parameters attached via logger.<level>(..., extra={...})
        extra_fields: dict[str, Any] = {}
        for attr, val in record.__dict__.items():
            if attr not in STANDARD_RECORD_ATTRS and attr not in {
                "request_id",
                "tenant_id",
                "user_id",
                "client_ip",
            }:
                try:
                    extra_fields[attr] = redact_sensitive_data(val)
                except Exception:
                    extra_fields[attr] = str(val)

        if extra_fields:
            payload["extra"] = extra_fields

        # Structured exception reporting
        if record.exc_info and record.exc_info[0] is not None:
            exc_type = record.exc_info[0].__name__
            exc_msg = str(record.exc_info[1])
            formatted_tb = self.formatException(record.exc_info)
            payload["exception"] = {
                "type": exc_type,
                "message": exc_msg,
                "traceback": formatted_tb,
            }

        return json.dumps(payload, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """
    Human-readable, ANSI-colorized formatter optimized for terminal readability
    during local development.
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        created_dt = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]

        color = self.COLORS.get(record.levelname, self.RESET)
        level_tag = f"{color}[{record.levelname:<7}]{self.RESET}"

        # Context tokens
        req_id = getattr(record, "request_id", None) or get_current_request_id()
        tenant_id = getattr(record, "tenant_id", None) or get_current_tenant_id()

        context_parts = []
        if req_id:
            context_parts.append(f"req:{req_id[:8]}")
        if tenant_id:
            context_parts.append(f"tenant:{str(tenant_id)[:8]}")

        context_str = f" {self.DIM}[{' '.join(context_parts)}]{self.RESET}" if context_parts else ""

        message = record.getMessage()
        header = f"{self.DIM}{created_dt}{self.RESET} {level_tag} [{record.name}]{context_str}"
        formatted = f"{header} {message}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


# ─── Setup Function ──────────────────────────────────────────────────────────


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "console",
) -> None:
    """
    Configure the root logger, console/JSON stream handlers, and third-party
    logger severities.
    """
    root_logger = logging.getLogger()
    level_num = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level_num)

    # Remove pre-existing default handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # Attach our stream handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level_num)

    if log_format.lower() == "json":
        stream_handler.setFormatter(JsonLogFormatter())
    else:
        stream_handler.setFormatter(ConsoleLogFormatter())

    stream_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(stream_handler)

    # Silence chatty third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)
