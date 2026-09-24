"""Basic smoke tests — no database required."""

import pytest
from fastapi.testclient import TestClient

from hrms.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_loads() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "HRMS Platform"
    # Verify core endpoints are documented
    paths = schema["paths"]
    assert "/v1/org/legal-entities" in paths
    assert "/v1/org/locations" in paths
    assert "/v1/org/org-units" in paths
    assert "/v1/persons" in paths
    assert "/v1/employees" in paths
    assert "/v1/personnel-actions" in paths
