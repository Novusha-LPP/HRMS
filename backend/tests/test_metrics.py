"""GET /metrics and what the middleware records."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from hrms.core.config import Settings, settings
from hrms.main import app


async def _get(path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def test_requests_are_labelled_by_route_template_not_url():
    await _get("/v1/employees/emp_literal_id_123")  # 401 without a token; the route matched
    await _get("/no/such/path/abc123")
    body = (await _get("/metrics")).text

    assert (
        'hrms_http_requests_total{method="GET",route="/v1/employees/{employment_id}",status="401"}'
        in body
    )
    assert "emp_literal_id_123" not in body
    assert 'route="unmatched"' in body and "abc123" not in body
    assert "hrms_http_request_duration_seconds_bucket" in body
    assert "hrms_db_statements_per_request_bucket" in body
    for gauge in (
        "hrms_db_pool_size",
        "hrms_db_pool_checked_out",
        "hrms_db_pool_overflow",
        "hrms_db_pool_limit",
    ):
        assert f"\n{gauge} " in body, gauge


async def test_scrape_token_is_enforced_when_set(monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", "scrape-secret")
    assert (await _get("/metrics")).status_code == 401
    assert (await _get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    ok = await _get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert ok.status_code == 200 and "hrms_http_requests_total" in ok.text


def test_production_requires_a_scrape_token():
    production = dict(
        _env_file=None,
        environment="production",
        secret_key="x" * 40,
        database_url="postgresql+asyncpg://owner:strong@db/hrms",
        app_database_url="postgresql+asyncpg://hrms_app:strong@db/hrms",
        cors_origins="https://hrms.example.com",
    )
    with pytest.raises(ValidationError, match="HRMS_METRICS_TOKEN"):
        Settings(**production)
    Settings(**production, metrics_token="t")
    Settings(**production, metrics_enabled=False)
