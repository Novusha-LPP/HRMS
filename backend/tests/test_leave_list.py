"""
GET /v1/leave/applications paging, filtering and scoping, GET /applications/summary, and
the query budget that keeps the list from going back to one query per row.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core import database, perf
from hrms.core.ids import to_uuid
from tests.helpers import employee, ok, tenant

pytestmark = pytest.mark.database

PASSWORD = "Test-password-123"


def _weekdays(start: date, count: int) -> list[date]:
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


async def _world(client, engine):
    """Two companies; 5 applications in A (2 drafts, 3 submitted) and 3 in B (1 draft)."""
    admin = await tenant(client)
    company_a = admin["user"]["legal_entities"][0]["id"]
    entity_b = {"name": "Company B", "country_code": "IN"}
    company_b = (await ok(client, "POST", "/v1/org/legal-entities", json=entity_b))["id"]
    _, a_login = await employee(client, company_a)
    _, b_login = await employee(client, company_b)
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Casual", "code": "CL", "days_per_year": 120, "accrual_enabled": True},
    )
    await ok(client, "POST", "/v1/leave/accrual/run")
    days = _weekdays(date(date.today().year + 1, 2, 2), 8)
    apps = {"a": [], "b": []}
    for key, login, dates, submit in [
        ("a", a_login, days[:5], 3),
        ("b", b_login, days[5:], 2),
    ]:
        headers = {"Authorization": "Bearer " + login["access_token"]}
        for i, day in enumerate(dates):
            row = await ok(
                client,
                "POST",
                "/v1/leave/applications",
                headers=headers,
                json={"leave_type_id": lt["id"], "from_date": str(day), "to_date": str(day)},
            )
            if i < submit:
                await ok(
                    client,
                    "POST",
                    f"/v1/leave/applications/{row['id']}/submit",
                    headers=headers,
                    json={},
                )
            apps[key].append(row["id"])

    # An HR manager for company A only.
    email = uuid4().hex + "@example.com"
    await ok(
        client,
        "POST",
        "/v1/users",
        json={
            "email": email,
            "password": PASSWORD,
            "role": "HR_MANAGER",
            "scope_type": "LEGAL_ENTITY",
            "legal_entity_ids": [company_a],
        },
    )
    hr_a = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {
        "apps": apps,
        "hr_a": {"Authorization": "Bearer " + hr_a["access_token"]},
        "tenant_id": to_uuid(admin["user"]["tenant_id"]),
        "company_b": company_b,
    }


async def test_keyset_pages_match_the_full_list(api):
    client, engine = api
    world = await _world(client, engine)
    full = await ok(client, "GET", "/v1/leave/applications?limit=200")
    assert len(full) == 8
    # Drafts (never applied) first, then newest applied.
    statuses = [r["status"] for r in full]
    assert statuses == ["DRAFT"] * 3 + ["PENDING_L1"] * 5
    applied = [r["applied_at"] for r in full[3:]]
    assert applied == sorted(applied, reverse=True)

    paged, after = [], None
    while True:
        page = await ok(
            client,
            "GET",
            "/v1/leave/applications?limit=3" + (f"&after={after}" if after else ""),
        )
        paged += page
        if len(page) < 3:
            break
        after = page[-1]["id"]
    assert [r["id"] for r in paged] == [r["id"] for r in full]

    bad = await client.get(f"/v1/leave/applications?after={world['company_b']}")
    assert bad.status_code == 422


async def test_status_filter_accepts_several(api):
    client, engine = api
    await _world(client, engine)
    both = await ok(client, "GET", "/v1/leave/applications?status=DRAFT,PENDING_L1")
    drafts = await ok(client, "GET", "/v1/leave/applications?status=DRAFT")
    assert len(both) == 8 and len(drafts) == 3


async def test_list_and_summary_respect_company_scope(api):
    client, engine = api
    world = await _world(client, engine)
    seen = await ok(client, "GET", "/v1/leave/applications", headers=world["hr_a"])
    assert {r["id"] for r in seen} == set(world["apps"]["a"])

    summary = await ok(client, "GET", "/v1/leave/applications/summary", headers=world["hr_a"])
    assert summary["by_status"] == {"DRAFT": 2, "PENDING_L1": 3}
    assert summary["approved_days_by_type"] == []  # nothing approved yet

    everyone = await ok(client, "GET", "/v1/leave/applications/summary")
    assert everyone["by_status"] == {"DRAFT": 3, "PENDING_L1": 5}


async def test_approved_days_by_type(api):
    client, engine = api
    world = await _world(client, engine)
    # Approve one of A's pending applications directly (approval routing is tested elsewhere).
    app_id = to_uuid(world["apps"]["a"][0])
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE leave_applications SET status = 'APPROVED' WHERE id = :id"),
            {"id": app_id},
        )
    summary = await ok(client, "GET", "/v1/leave/applications/summary")
    [casual] = summary["approved_days_by_type"]
    assert (casual["name"], casual["days"]) == ("Casual", 1)
    assert summary["by_status"]["APPROVED"] == 1


async def test_list_query_count_does_not_grow_with_rows(api):
    """The list used to run one approval-history query per application (N+1)."""
    client, engine = api
    await _world(client, engine)
    perf.instrument_engine(database.AsyncSessionLocal.kw["bind"])

    async def statements(url):
        tally = perf.start_tally()
        await ok(client, "GET", url)
        return tally.count

    small = await statements("/v1/leave/applications?limit=2")
    large = await statements("/v1/leave/applications?limit=200")
    assert 0 < small == large, (small, large)
