"""Tests for unified error handling, exception handlers, and dual-compatible error envelopes."""

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError

from hrms.core.error_handlers import register_exception_handlers
from hrms.core.errors import CodedHTTPException
from hrms.core.middleware import RequestLoggingMiddleware
from hrms.core.security import PasswordTooLong


def create_test_app():
    test_app = FastAPI()
    test_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(test_app)

    class SampleInput(BaseModel):
        email: EmailStr
        age: int

    @test_app.post("/test-validation")
    async def endpoint_validation(data: SampleInput):
        return {"status": "ok"}

    @test_app.get("/test-not-found")
    async def endpoint_not_found():
        raise HTTPException(status_code=404, detail="Entity does not exist")

    @test_app.get("/test-coded")
    async def endpoint_coded():
        raise CodedHTTPException(
            status_code=403,
            detail="Password reset mandatory",
            code="PASSWORD_CHANGE_REQUIRED",
        )

    @test_app.get("/test-password-too-long")
    async def endpoint_password_too_long():
        raise PasswordTooLong("Password exceeds maximum allowed 72 bytes")

    @test_app.get("/test-integrity")
    async def endpoint_integrity():
        orig_exc = Exception("unique_email_idx violation")
        raise IntegrityError("INSERT INTO ...", params={}, orig=orig_exc)

    @test_app.get("/test-500")
    async def endpoint_unhandled():
        raise RuntimeError("Unexpected internal crash simulation")

    return test_app


@pytest.mark.asyncio
async def test_404_http_exception_envelope():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-not-found")

    assert res.status_code == 404
    data = res.json()
    assert data["detail"] == "Entity does not exist"
    assert data["code"] == "HTTP_404_NOT_FOUND"
    assert "request_id" in data
    assert data["request_id"].startswith("req_")
    assert "error" in data
    assert data["error"]["code"] == "HTTP_404_NOT_FOUND"
    assert data["error"]["message"] == "Entity does not exist"
    assert data["error"]["request_id"] == data["request_id"]
    assert res.headers.get("X-Request-ID") == data["request_id"]


@pytest.mark.asyncio
async def test_422_validation_error_envelope():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/test-validation", json={"email": "not-an-email", "age": "abc"})

    assert res.status_code == 422
    data = res.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert "Validation error on" in data["detail"]
    assert len(data["error"]["details"]) >= 2

    fields = [d["field"] for d in data["error"]["details"]]
    assert "email" in fields
    assert "age" in fields


@pytest.mark.asyncio
async def test_coded_http_exception_envelope():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-coded")

    assert res.status_code == 403
    data = res.json()
    assert data["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert data["detail"] == "Password reset mandatory"
    assert data["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.asyncio
async def test_password_too_long_envelope():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-password-too-long")

    assert res.status_code == 422
    data = res.json()
    assert data["code"] == "PASSWORD_TOO_LONG"
    assert "72 bytes" in data["detail"]


@pytest.mark.asyncio
async def test_integrity_error_envelope():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-integrity")

    assert res.status_code == 409
    data = res.json()
    assert data["code"] == "RESOURCE_CONFLICT"
    assert "conflicts with an existing record" in data["detail"]


@pytest.mark.asyncio
async def test_unhandled_500_exception_envelope():
    app = create_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        res = await client.get("/test-500")

    assert res.status_code == 500
    data = res.json()
    assert data["code"] == "INTERNAL_SERVER_ERROR"
    assert "An internal server error occurred" in data["detail"]
    assert data["request_id"].startswith("req_")
    assert data["request_id"] in data["detail"]
