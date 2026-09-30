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


def test_redaction_matches_whole_words_not_substrings():
    cleaned = redact_sensitive_data(
        {
            "company_name": "Suraj Exim",
            "author": "hr",
            "expand": "all",
            "span_id": "s1",
            "pan_number": "ABCDE1234F",
            "panNumber": "ABCDE1234F",
            "accessToken": "t",
            "x-api-key": "k",
            "bank_account_number": "123",
            "nested": {"password": "p", "department": "Ops"},
        }
    )
    assert cleaned["company_name"] == "Suraj Exim"
    assert (cleaned["author"], cleaned["expand"], cleaned["span_id"]) == ("hr", "all", "s1")
    for key in ("pan_number", "panNumber", "accessToken", "x-api-key", "bank_account_number"):
        assert cleaned[key] == "***REDACTED***", key
    assert cleaned["nested"] == {"password": "***REDACTED***", "department": "Ops"}


def test_exception_text_and_traceback_are_redacted():
    try:
        raise ValueError("duplicate key value: Key (pan)=(ABCDE1234F) already exists")
    except ValueError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, None)
        import sys

        record.exc_info = sys.exc_info()
    payload = json.loads(JsonLogFormatter().format(record))
    assert "ABCDE1234F" not in json.dumps(payload)
    assert "ABCDE****F" in payload["exception"]["message"]
    assert "ABCDE1234F" not in ConsoleLogFormatter().format(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", ["x" * 300, "abc\ninjected-line", "id with spaces", "<script>"])
async def test_unsafe_request_ids_are_replaced(unsafe):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-ID": unsafe})
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Request-ID"] != unsafe


@pytest.mark.asyncio
async def test_forwarded_for_header_is_not_trusted_for_client_ip(caplog):
    transport = ASGITransport(app=app, client=("10.0.0.7", 1234))
    with caplog.at_level(logging.DEBUG, logger="hrms.api.access"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/health", headers={"X-Forwarded-For": "1.2.3.4"})
    [record] = [r for r in caplog.records if r.name == "hrms.api.access"]
    assert record.client_ip == "10.0.0.7"


@pytest.mark.asyncio
async def test_responses_carry_the_app_version():
    from hrms.core.version import APP_VERSION

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.headers["X-App-Version"] == APP_VERSION


def test_uvicorn_loggers_go_through_the_app_handler():
    from hrms.core.config import settings
    from hrms.core.logging import setup_logging

    logging.getLogger("uvicorn.error").addHandler(logging.StreamHandler())
    try:
        setup_logging("INFO", "json")
        for name in ("uvicorn", "uvicorn.error"):
            assert logging.getLogger(name).handlers == [] and logging.getLogger(name).propagate
        [handler] = logging.getLogger().handlers
        assert isinstance(handler.formatter, JsonLogFormatter)
    finally:
        setup_logging(settings.log_level, settings.log_format)  # as the app configured it
