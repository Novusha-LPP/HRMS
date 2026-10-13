"""Connected-app credentials: API keys, OAuth tokens, scopes, IP limits, rate limits."""

import base64

import pytest

from tests.helpers import client_from, ok, tenant
from tests.integration_support import make_app, world

pytestmark = pytest.mark.database


async def test_a_key_is_shown_once_and_works_only_on_the_integrations_api(api):
    client, _ = api
    w = await world(client)
    assert w.key.startswith("hrms_test_")
    keys = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/keys",
                    headers=w.admin)
    assert len(keys) == 1 and "key" not in keys[0] and keys[0]["status"] == "ACTIVE"

    data = await ok(client, "GET", "/v1/integrations/reference-data", headers=w.erp)
    assert data["departments"][0]["name"] == "Ops"

    # A key never reaches the rest of the API, which only accepts a user's token.
    async with client_from("127.0.0.1") as bare:
        response = await bare.get("/v1/employees", headers=w.erp)
    assert response.status_code == 401


async def test_a_bad_revoked_or_paused_key_is_refused(api):
    client, _ = api
    w = await world(client)
    bad = await client.get("/v1/integrations/reference-data",
                           headers={"X-API-Key": w.key[:-3] + "xyz"})
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_API_KEY"
    junk = await client.get("/v1/integrations/reference-data", headers={"X-API-Key": "junk"})
    assert junk.json()["code"] == "INVALID_API_KEY"
    # A user's own sign-in token is not an integration credential.
    user_token = await client.get("/v1/integrations/reference-data")
    assert user_token.status_code == 401 and user_token.json()["code"] == "INVALID_TOKEN"
    async with client_from("127.0.0.1") as bare:
        missing = await bare.get("/v1/integrations/reference-data")
    assert missing.status_code == 401 and missing.json()["code"] == "API_KEY_REQUIRED"

    await ok(client, "PATCH", f"/v1/admin/integrations/apps/{w.app['id']}",
             json={"status": "PAUSED"}, headers=w.admin)
    paused = await client.get("/v1/integrations/reference-data", headers=w.erp)
    assert paused.status_code == 403 and paused.json()["code"] == "APP_PAUSED"
    await ok(client, "PATCH", f"/v1/admin/integrations/apps/{w.app['id']}",
             json={"status": "ACTIVE"}, headers=w.admin)

    keys = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/keys",
                    headers=w.admin)
    await ok(client, "POST",
             f"/v1/admin/integrations/apps/{w.app['id']}/keys/{keys[0]['id']}/revoke",
             json={"reason": "rotated"}, headers=w.admin)
    revoked = await client.get("/v1/integrations/reference-data", headers=w.erp)
    assert revoked.status_code == 401 and revoked.json()["code"] == "API_KEY_REVOKED"


async def test_scopes_ip_limits_and_rate_limits(api):
    client, _ = api
    registered = await tenant(client)
    admin = {"Authorization": client.headers["Authorization"]}
    _, narrow = await make_app(client, admin, code="BI", kind="READ_ONLY", scopes=["org.read"],
                               allowed_ips=["10.1.2.0/24"], rate_limit_per_minute=10)
    headers = {"X-API-Key": narrow["key"]}
    del registered

    async with client_from("10.1.2.7") as inside:
        assert (await inside.get("/v1/integrations/org/companies", headers=headers)).is_success
        missing = await inside.get("/v1/integrations/events", headers=headers)
        assert missing.status_code == 403 and missing.json()["code"] == "SCOPE_MISSING"
        statuses = [
            (await inside.get("/v1/integrations/org/companies", headers=headers)).status_code
            for _ in range(10)
        ]
        assert statuses[-1] == 429
        limited = await inside.get("/v1/integrations/org/companies", headers=headers)
        assert limited.json()["code"] == "RATE_LIMITED" and "retry-after" in limited.headers

    async with client_from("10.9.9.9") as outside:
        refused = await outside.get("/v1/integrations/org/companies", headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "IP_NOT_ALLOWED"


async def test_a_read_only_app_cannot_hold_write_scopes(api):
    client, _ = api
    await tenant(client)
    admin = {"Authorization": client.headers["Authorization"]}
    app = await ok(client, "POST", "/v1/admin/integrations/apps",
                   json={"code": "BI", "name": "BI", "kind": "READ_ONLY"}, headers=admin)
    response = await client.post(f"/v1/admin/integrations/apps/{app['id']}/keys",
                                 json={"name": "x", "scopes": ["employees.sync"]}, headers=admin)
    assert response.status_code == 422 and response.json()["code"] == "SCOPE_NOT_ALLOWED"


async def test_oauth_client_credentials(api):
    client, _ = api
    w = await world(client)
    client_id = "_".join(w.key.split("_")[:3])
    basic = base64.b64encode(f"{client_id}:{w.key}".encode()).decode()
    token = await ok(client, "POST", "/v1/integrations/oauth/token",
                     data={"grant_type": "client_credentials"},
                     headers={"Authorization": "Basic " + basic})
    assert token["token_type"] == "bearer" and token["expires_in"] == 900
    bearer = {"Authorization": "Bearer " + token["access_token"]}
    assert (await client.get("/v1/integrations/reference-data", headers=bearer)).is_success
    # The integration token is not a user's token.
    async with client_from("127.0.0.1") as bare:
        assert (await bare.get("/v1/employees", headers=bearer)).status_code == 401

    wrong = await client.post("/v1/integrations/oauth/token",
                              data={"grant_type": "client_credentials", "client_id": client_id,
                                    "client_secret": w.key + "x"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_client"


async def test_another_companys_key_sees_nothing_of_this_one(api):
    client, _ = api
    first = await world(client)
    await first.put("EMP-1", expect=201, **first.new_hire())
    client.headers.pop("Authorization")
    second = await world(client)
    response = await client.get("/v1/integrations/employees/EMP-1", headers=second.erp)
    assert response.status_code == 404
    listing = await ok(client, "GET", "/v1/integrations/employees", headers=second.erp)
    assert listing["employees"] == []


async def test_use_from_a_new_address_is_logged(api):
    client, _ = api
    w = await world(client)
    for ip in ("10.7.0.1", "10.7.0.1", "10.7.0.2"):
        async with client_from(ip) as erp_server:
            response = await erp_server.get("/v1/integrations/reference-data", headers=w.erp)
            assert response.is_success
    log = await ok(client, "GET",
                   f"/v1/admin/integrations/apps/{w.app['id']}/requests?operation=NEW_IP",
                   headers=w.admin)
    assert [r["error_detail"]["ip"] for r in log] == ["10.7.0.2"]
