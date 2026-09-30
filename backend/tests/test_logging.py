"""Tests for enterprise logging subsystem, formatters, filters, and middleware."""

import json
import logging
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from hrms.core.logging import (
    ConsoleLogFormatter,
    JsonLogFormatter,
    SensitiveDataFilter,
    redact_sensitive_data,
    redact_text,
    request_id_ctx,
    tenant_id_ctx,
    user_id_ctx,
)
from hrms.main import app


def test_redact_text_masks_pan_and_aadhaar():
    raw_text = "Employee PAN is ABCDE1234F and Aadhaar is 2345 6789 0123 for verification."
    masked = redact_text(raw_text)
    assert "ABCDE1234F" not in masked
    assert "ABCDE****F" in masked
    assert "2345 6789 0123" not in masked
    assert "********0123" in masked


def test_redact_sensitive_data_nested_dict():
    payload = {
        "user": {
            "name": "Jane Doe",
            "password": "SuperSecretPassword123!",
            "token": "bearer-xyz-123",
            "metadata": {
                "api_key": "key-999",
                "department": "Engineering",
                "pan_number": "ABCDE1234F",
            },
        },
        "tags": ["prod", "auth"],
    }
    redacted = redact_sensitive_data(payload)
    assert redacted["user"]["name"] == "Jane Doe"
    assert redacted["user"]["password"] == "***REDACTED***"
    assert redacted["user"]["token"] == "***REDACTED***"
    assert redacted["user"]["metadata"]["api_key"] == "***REDACTED***"
    assert redacted["user"]["metadata"]["department"] == "Engineering"
    assert redacted["user"]["metadata"]["pan_number"] == "***REDACTED***"


def test_sensitive_data_filter_masks_log_record():
    log_filter = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Login failed for user %s with PAN %s",
        args=("admin@example.com", "ABCDE1234F"),
        exc_info=None,
    )
    log_filter.filter(record)
    # The PAN in args is masked
    assert record.args == ("admin@example.com", "ABCDE****F")


def test_json_log_formatter_includes_context_and_exception():
    formatter = JsonLogFormatter()
    req_id = f"req_{uuid4().hex}"
    tenant_id = str(uuid4())
    user_id = str(uuid4())

    token_req = request_id_ctx.set(req_id)
    token_tenant = tenant_id_ctx.set(tenant_id)
    token_user = user_id_ctx.set(user_id)

    try:
        try:
            raise ValueError("Test failure simulation")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="hrms.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Simulated operation failed",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "ERROR"
        assert data["logger"] == "hrms.test"
        assert data["message"] == "Simulated operation failed"
        assert data["request_id"] == req_id
        assert data["tenant_id"] == tenant_id
        assert data["user_id"] == user_id
        assert "timestamp" in data
        assert data["exception"]["type"] == "ValueError"
        assert "Test failure simulation" in data["exception"]["message"]
        assert "Traceback" in data["exception"]["traceback"]
    finally:
        request_id_ctx.reset(token_req)
        tenant_id_ctx.reset(token_tenant)
        user_id_ctx.reset(token_user)


def test_console_log_formatter_output():
    formatter = ConsoleLogFormatter()
    token_req = request_id_ctx.set("req_123456789")
    try:
        record = logging.LogRecord(
            name="hrms.service",
            level=logging.INFO,
            pathname="test.py",
            lineno=15,
            msg="Task completed successfully",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "[INFO   ]" in formatted
        assert "[hrms.service]" in formatted
        assert "req:req_1234" in formatted
        assert "Task completed successfully" in formatted
    finally:
        request_id_ctx.reset(token_req)


@pytest.mark.asyncio
async def test_middleware_injects_x_request_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"].startswith("req_")


@pytest.mark.asyncio
async def test_middleware_preserves_custom_request_id():
    custom_id = "req_custom_correlation_id_999"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-ID": custom_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id
