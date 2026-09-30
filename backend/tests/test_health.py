"""In-process smoke checks: no server, demo data, or thread portal required."""

import pytest
from httpx import ASGITransport, AsyncClient

from hrms.main import app


async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_openapi_schema_loads():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in [
        "/v1/org/legal-entities",
        "/v1/org/locations",
        "/v1/org/org-units",
        "/v1/persons",
        "/v1/employees",
        "/v1/personnel-actions",
        "/v1/kyc/me",
    ]:
        assert path in paths


async def test_health_reports_the_packaged_version():
    import tomllib
    from pathlib import Path

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        live = (await client.get("/health/live")).json()
    assert live["version"] == project["project"]["version"]
    assert set(live) >= {"status", "version", "commit", "built_at"}


@pytest.mark.database
async def test_ready_checks_database_and_schema(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine

    from hrms.core import health

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.get("/health/ready")
        assert ok.status_code == 200, ok.text
        assert ok.json()["checks"] == {"database": "ok", "schema": "ok"}

        # Code that ships a newer migration than the database has: not ready.
        heads, revisions = health._known_revisions()
        monkeypatch.setattr(
            health, "_known_revisions", lambda: (frozenset({"9999"}), revisions | {"9999"})
        )
        pending = await client.get("/health/ready")
        assert pending.status_code == 503
        assert pending.json()["checks"]["schema"].startswith("migrations pending")

        # A database the code doesn't know is ahead (mid-rollout): still ready.
        monkeypatch.setattr(health, "_known_revisions", lambda: (frozenset({"0001"}), frozenset()))
        assert (await client.get("/health/ready")).status_code == 200

        # No database: not ready, and liveness is unaffected.
        dead = create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none")
        monkeypatch.setattr(health, "engine", dead)
        down = await client.get("/health/ready")
        assert down.status_code == 503 and down.json()["checks"] == {"database": "unavailable"}
        assert (await client.get("/health")).status_code == 200
        await dead.dispose()
