"""In-process smoke checks: no server, demo data, or thread portal required."""

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
