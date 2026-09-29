"""Pending overtime is listed for exactly the people a reviewer is responsible for."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database


async def test_pending_overtime_is_scoped_to_the_reviewers_people(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "B", "country_code": "IN"})
    )["id"]
    place_a, place_b = await org_basics(client, company_a), await org_basics(client, company_b)

    boss = await person_and_employment(client, company_a, "BOSS")
    await hire(client, boss["id"], place_a)
    other_boss = await person_and_employment(client, company_a, "BOSS2")
    await hire(client, other_boss["id"], place_a)
    worker_a = await person_and_employment(client, company_a, "WA")
    await hire(client, worker_a["id"], {**place_a, "manager_employment_id": boss["id"]})
    worker_b = await person_and_employment(client, company_b, "WB")
    await hire(client, worker_b["id"], place_b)

    for worker in (worker_a, worker_b):
        async with engine.begin() as conn:
            await conn.execute(
                text("""INSERT INTO attendance_days
                        (tenant_id, id, employment_id, work_date, status, ot_minutes, ot_status)
                        VALUES (:t, :i, :e, :d, 'PRESENT', 90, 'PENDING')"""),
                {"t": tid, "i": uuid4(), "e": to_uuid(worker["id"]), "d": date(2026, 9, 28)},
            )

    async def pending_as(email, password):
        token = bearer(
            (
                await ok(
                    client,
                    "POST",
                    "/v1/auth/login",
                    json={"identifier": email, "password": password},
                )
            )["access_token"]
        )
        return [
            row["employee_number"]
            for row in await ok(client, "GET", "/v1/time/overtime/pending", headers=token)
        ]

    hr_a = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_a]
    )
    mgr = await make_user(client, boss["id"], role="MANAGER", scope_type="DIRECT_REPORTS")
    stranger_mgr = await make_user(
        client, other_boss["id"], role="MANAGER", scope_type="DIRECT_REPORTS"
    )

    assert sorted(
        r["employee_number"] for r in await ok(client, "GET", "/v1/time/overtime/pending")
    ) == ["WA", "WB"]
    assert await pending_as(hr_a[0], hr_a[1]) == ["WA"]  # was a 500
    assert await pending_as(mgr[0], mgr[1]) == ["WA"]  # was silently empty
    assert await pending_as(stranger_mgr[0], stranger_mgr[1]) == []
