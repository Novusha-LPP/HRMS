"""
The fixed cost of an authenticated request (core/database.get_session + core/authz scope),
and that folding its checks into one query didn't make any of them less live.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core import database, perf
from hrms.core.ids import to_uuid
from tests.helpers import employee, ok, tenant

pytestmark = pytest.mark.database

PASSWORD = "Test-password-123"


async def _statements(client, url, headers):
    seen = []
    perf.REQUEST_OBSERVER = lambda scope, tally: seen.append(tally)
    try:
        await ok(client, "GET", url, headers=headers)
    finally:
        perf.REQUEST_OBSERVER = None
    return seen[-1]


async def test_authenticated_request_overhead_is_two_statements(api):
    client, _ = api
    admin = await tenant(client)
    _, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = {"Authorization": "Bearer " + login["access_token"]}
    perf.instrument_engine(database.AsyncSessionLocal.kw["bind"])

    # /v1/leave/types runs one query of its own; everything else is per-request overhead:
    # set_config, then one statement for tenant + account + grants + due actions.
    tally = await _statements(client, "/v1/leave/types", headers)
    assert tally.count == 3, tally.statements


async def test_revoked_role_takes_effect_on_the_next_request(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    await employee(client, company)
    email = uuid4().hex + "@example.com"
    account = await ok(
        client,
        "POST",
        "/v1/users",
        json={"email": email, "password": PASSWORD, "role": "HR_MANAGER", "scope_type": "ALL"},
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": "Bearer " + login["access_token"]}
    before = await ok(client, "GET", "/v1/employees", headers=headers)
    assert len(before) >= 1

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM role_assignments WHERE user_account_id = :u"),
            {"u": to_uuid(account["id"])},
        )
    # Same token, no role left: the account fails closed to its own record (it has none)
    # on the very next request — nothing of the company is visible any more.
    after = await client.get("/v1/employees", headers=headers)
    assert after.status_code == 403 or after.json() == [], after.text


async def test_suspended_tenant_and_disabled_account_still_cut_off(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    _, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = {"Authorization": "Bearer " + login["access_token"]}
    assert (await client.get("/v1/leave/types", headers=headers)).status_code == 200

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE tenants SET status='SUSPENDED' WHERE id=:t"), {"t": tid})
    assert (await client.get("/v1/leave/types", headers=headers)).status_code == 403

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE tenants SET status='ACTIVE' WHERE id=:t"), {"t": tid})
        await conn.execute(
            text("UPDATE user_accounts SET status='DISABLED' WHERE email=:e"),
            {"e": login["user"]["email"]},
        )
    assert (await client.get("/v1/leave/types", headers=headers)).status_code == 401


async def test_directory_and_daily_analysis_query_budgets(api):
    client, _ = api
    admin = await tenant(client)
    await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = {"Authorization": "Bearer " + admin["access_token"]}
    perf.instrument_engine(database.AsyncSessionLocal.kw["bind"])
    directory = await _statements(client, "/v1/users?limit=1", headers)
    daily = await _statements(client, "/v1/time/daily-analysis?limit=1", headers)
    assert directory.count <= 3, directory.statements
    # Building a persisted snapshot adds bounded writes/cleanup to the source queries.
    assert daily.count <= 20, daily.statements
    report = (await client.get("/v1/time/daily-analysis?limit=1", headers=headers)).json()
    cached = await _statements(
        client,
        f"/v1/time/daily-analysis?limit=1&snapshot_id={report['snapshot_id']}",
        headers,
    )
    # Subsequent pages must not repeat policy, attendance or snapshot construction.
    assert cached.count <= 5, cached.statements
