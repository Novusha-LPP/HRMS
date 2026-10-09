from types import SimpleNamespace
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from hrms.core.active_users import ActiveUsers


def test_distinct_users_expire_and_logout():
    now = [0]
    users = ActiveUsers(clock=lambda: now[0])
    users.record("tenant", "alice")
    users.record("tenant", "alice")
    users.record("tenant", "bob")
    assert users.count() == 2
    now[0] = 200
    users.record("tenant", "alice")
    now[0] = 300
    assert users.count() == 1
    users.remove("tenant", "alice")
    assert users.count() == 0


def test_metric_contains_no_user_identifiers():
    users = ActiveUsers()
    users.record("private-tenant", "private-user")
    registry = CollectorRegistry()
    registry.register(users)
    body = generate_latest(registry).decode()
    assert "hrms_active_users 1.0" in body
    assert "private-user" not in body and "private-tenant" not in body


@pytest.mark.parametrize(
    "status,route,expected",
    [
        (200, "/v1/auth/me", 1),
        (401, "/v1/auth/me", 0),
        (403, "/v1/auth/me", 0),
        (500, "/v1/auth/me", 0),
        (204, "/v1/auth/logout", 0),
    ],
)
async def test_only_successful_authenticated_requests_count(monkeypatch, status, route, expected):
    from hrms.core import metrics

    users = ActiveUsers()
    principal = SimpleNamespace(tenant_id=uuid4(), user_account_id=uuid4())
    if route.endswith("logout"):
        users.record(principal.tenant_id, principal.user_account_id)
    monkeypatch.setattr(metrics, "active_users", users)

    async def app(scope, receive, send):
        scope["state"]["principal"] = principal
        scope["route"] = SimpleNamespace(path=route)
        await send({"type": "http.response.start", "status": status})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        pass

    await metrics.MetricsMiddleware(app)(
        {"type": "http", "method": "GET", "path": route}, None, send
    )
    assert users.count() == expected


async def test_authenticated_http_activity_reaches_metrics(monkeypatch):
    """Real JWT authentication, ASGI middleware and scrape output; no shared database."""
    from fastapi import FastAPI, Response
    from httpx import ASGITransport, AsyncClient

    from hrms.core import metrics
    from hrms.core.authn import CurrentUser
    from hrms.core.security import create_access_token

    now = [0]
    users = ActiveUsers(clock=lambda: now[0])
    monkeypatch.setattr(metrics, "active_users", users)
    monkeypatch.setattr(metrics.settings, "metrics_token", None)
    monkeypatch.setattr(metrics.settings, "secret_key", "isolated-active-user-test-key-32-bytes")

    async def no_job_history():
        return []

    monkeypatch.setattr(metrics, "_last_job_successes", no_job_history)
    app = FastAPI()
    app.add_middleware(metrics.MetricsMiddleware)
    app.include_router(metrics.router)

    @app.get("/v1/auth/me")
    async def me(principal: CurrentUser):
        return {"id": str(principal.user_account_id)}

    @app.post("/v1/auth/logout", status_code=204)
    async def logout(principal: CurrentUser):
        return Response(status_code=204)

    tenant_id = uuid4()
    headers = [
        {
            "Authorization": "Bearer "
            + create_access_token(
                user_account_id=uuid4(),
                tenant_id=tenant_id,
                employment_id=None,
                role_names=["EMPLOYEE"],
            )
        }
        for _ in range(2)
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def expect_count(count):
            response = await client.get("/metrics")
            assert response.status_code == 200
            assert f"\nhrms_active_users {count}.0\n" in response.text

        await expect_count(0)
        assert (await client.get("/v1/auth/me")).status_code == 401
        assert (
            await client.get("/v1/auth/me", headers={"Authorization": "Bearer invalid"})
        ).status_code == 401
        await expect_count(0)
        assert (await client.get("/v1/auth/me", headers=headers[0])).status_code == 200
        await expect_count(1)
        assert (await client.get("/v1/auth/me", headers=headers[0])).status_code == 200
        await expect_count(1)
        assert (await client.get("/v1/auth/me", headers=headers[1])).status_code == 200
        await expect_count(2)
        assert (await client.post("/v1/auth/logout", headers=headers[0])).status_code == 204
        await expect_count(1)
        now[0] = 300
        await expect_count(0)


def test_activity_history_survives_logout_and_deduplicates():
    now = [0]
    wall = [1000]
    users = ActiveUsers(clock=lambda: now[0], wall_clock=lambda: wall[0])
    users.record("tenant", "alice")
    wall[0] = 1100
    users.record("tenant", "alice")
    users.record("tenant", "bob")
    users.remove("tenant", "alice")
    assert users.count() == 1
    families = list(users.collect())
    history = families[1].samples
    assert len(history) == 2
    assert {s.value for s in history} == {1100}
    assert all("alice" not in str(s.labels) and "tenant" not in str(s.labels) for s in history)
    now[0] = 30 * 86400
    assert list(users.collect())[1].samples == []
