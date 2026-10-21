"""
Unused leave when someone leaves: lapse, encash (up to a cap) or hold, by company and leave
type. With no rule nothing changes. Every outcome is a ledger entry and a settlement row.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.ids import to_uuid
from hrms.modules.leave.models import LeaveSeparationRule
from hrms.modules.leave.separation import pick_rule, resolve_holds
from tests.helpers import hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _setup(client, *, encashable=True, opening=10):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    emp = await person_and_employment(client, company)
    await hire(client, emp["id"], placement)
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12, "encashable": encashable},
    )
    await _opening(client, emp, lt, opening)
    return company, placement, emp, lt


async def _opening(client, emp, lt, days):
    await ok(
        client,
        "POST",
        "/v1/leave/balances/adjust",
        json={
            "employment_id": emp["id"],
            "leave_type_id": lt["id"],
            "quantity": days,
            "kind": "OPENING",
            "reason": "Test balance",
            "effective_date": TODAY.isoformat(),
        },
    )


async def _available(client, emp, lt):
    rows = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}")
    return next(b for b in rows if b["leave_type_id"] == lt["id"])["available_days"]


async def _rule(client, **body):
    body.setdefault("effective_from", "2020-01-01")
    return await client.post("/v1/leave/separation-rules", json=body)


async def _separate(client, emp, when=TODAY):
    response = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "SEPARATION",
            "effective_date": when.isoformat(),
            "reason_code": "RESIGNATION",
        },
    )
    assert response.status_code == 201, response.text


async def _settlements(client, emp):
    return await ok(client, "GET", f"/v1/leave/separation-settlements?employment_id={emp['id']}")


async def test_with_no_rule_nothing_happens_to_the_balance(api):
    client, _ = api
    _, _, emp, lt = await _setup(client)
    await _separate(client, emp)
    assert await _available(client, emp, lt) == 10
    assert await _settlements(client, emp) == []


async def test_a_lapse_rule_removes_the_unused_balance(api):
    client, _ = api
    _, _, emp, lt = await _setup(client)
    assert (await _rule(client, on_separation="LAPSE")).status_code == 201
    await _separate(client, emp)
    assert await _available(client, emp, lt) == 0
    (row,) = await _settlements(client, emp)
    assert (row["action"], row["days"], row["lapsed_days"], row["encashed_days"]) == (
        "LAPSE",
        10,
        10,
        0,
    )


async def test_encashment_pays_up_to_the_cap_and_the_rest_lapses(api):
    client, admin = api
    _, _, emp, lt = await _setup(client)
    created = await _rule(client, on_separation="ENCASH", max_encash_days=4, leave_type_id=lt["id"])
    assert created.status_code == 201, created.text
    await _separate(client, emp)
    assert await _available(client, emp, lt) == 0
    (row,) = await _settlements(client, emp)
    assert (row["encashed_days"], row["lapsed_days"], row["days"]) == (4, 6, 10)
    async with admin.connect() as conn:
        paid = await conn.scalar(
            text("SELECT sum(days) FROM leave_encashments WHERE employment_id = :e"),
            {"e": to_uuid(emp["id"])},
        )
    assert paid == 4


async def test_encashment_is_only_for_types_marked_encashable(api):
    client, _ = api
    _, _, emp, lt = await _setup(client, encashable=False)
    refused = await _rule(client, on_separation="ENCASH", leave_type_id=lt["id"])
    assert refused.status_code == 400
    # A rule for every type holds the ones that can't be encashed instead of paying them.
    assert (await _rule(client, on_separation="ENCASH")).status_code == 201
    preview = await ok(client, "GET", f"/v1/leave/separation-preview?employment_id={emp['id']}")
    (item,) = preview["items"]
    assert item["action"] == "HOLD" and item["held_days"] == 10 and "encashable" in item["note"]


async def test_the_preview_changes_nothing_and_matches_what_happens(api):
    client, _ = api
    _, _, emp, lt = await _setup(client)
    await _rule(client, on_separation="LAPSE")
    preview = await ok(client, "GET", f"/v1/leave/separation-preview?employment_id={emp['id']}")
    assert [(i["unused_days"], i["lapse_days"]) for i in preview["items"]] == [(10, 10)]
    assert await _available(client, emp, lt) == 10
    assert await _settlements(client, emp) == []
    await _separate(client, emp)
    assert (await _settlements(client, emp))[0]["lapsed_days"] == 10


async def test_a_hold_keeps_the_balance_then_lapses_after_the_hold_days(api):
    client, admin = api
    _, _, emp, lt = await _setup(client)
    await _rule(client, on_separation="HOLD", hold_days=30)
    await _separate(client, emp)
    (row,) = await _settlements(client, emp)
    assert row["action"] == "HOLD" and row["resolution"] is None
    assert row["hold_expires_on"] == (TODAY + timedelta(days=30)).isoformat()
    assert await _available(client, emp, lt) == 10

    tenant_id = await _tenant_of(admin, emp)
    async with AsyncSession(admin) as session:
        early = await resolve_holds(session, tenant_id, TODAY + timedelta(days=29))
        assert early == {"lapsed": 0, "restored": 0}
        late = await resolve_holds(session, tenant_id, TODAY + timedelta(days=31))
        await session.commit()
    assert late == {"lapsed": 1, "restored": 0}
    assert await _available(client, emp, lt) == 0
    (row,) = await _settlements(client, emp)
    assert row["resolution"] == "LAPSED" and row["lapsed_days"] == 10


async def test_a_hold_is_restored_when_the_person_rejoins(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    await _rule(client, on_separation="HOLD", hold_days=30)
    await _separate(client, emp, when=TODAY - timedelta(days=5))
    rejoined = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "REHIRE",
            "effective_date": TODAY.isoformat(),
            "changes": placement,
        },
    )
    assert rejoined.status_code == 201, rejoined.text
    # The rejoin itself restores the hold, so the daily job has nothing left to do.
    tenant_id = await _tenant_of(admin, emp)
    async with AsyncSession(admin) as session:
        result = await resolve_holds(session, tenant_id, TODAY + timedelta(days=60))
        await session.commit()
    assert result == {"lapsed": 0, "restored": 0}
    assert await _available(client, emp, lt) == 10  # nothing lapsed
    assert (await _settlements(client, emp))[0]["resolution"] == "RESTORED"


async def test_settling_twice_changes_nothing(api):
    client, admin = api
    _, _, emp, lt = await _setup(client)
    await _rule(client, on_separation="LAPSE")
    await _separate(client, emp)
    from sqlmodel import col, select

    from hrms.modules.leave.separation import settle_on_separation
    from hrms.modules.people.models import Employment, EmploymentSpell

    async with AsyncSession(admin) as session:
        employment = (
            (
                await session.execute(
                    select(Employment).where(col(Employment.id) == to_uuid(emp["id"]))
                )
            )
            .scalars()
            .one()
        )
        spell = (
            (
                await session.execute(
                    select(EmploymentSpell).where(
                        col(EmploymentSpell.employment_id) == employment.id
                    )
                )
            )
            .scalars()
            .one()
        )
        again = await settle_on_separation(session, employment.tenant_id, employment, spell, TODAY)
        await session.commit()
    assert again == []
    assert len(await _settlements(client, emp)) == 1
    assert await _available(client, emp, lt) == 0


def _rule_obj(entity, leave_type, start, action="LAPSE"):
    return SimpleNamespace(
        id=uuid4(),
        legal_entity_id=entity,
        leave_type_id=leave_type,
        effective_from=start,
        on_separation=action,
        archived_at=None,
    )


def test_the_most_specific_rule_in_force_wins():
    entity, other, kind = uuid4(), uuid4(), uuid4()
    day = date(2026, 6, 1)
    everything = _rule_obj(None, None, date(2020, 1, 1), "HOLD")
    company = _rule_obj(entity, None, date(2020, 1, 1), "ENCASH")
    type_only = _rule_obj(None, kind, date(2020, 1, 1), "LAPSE")
    exact = _rule_obj(entity, kind, date(2020, 1, 1), "HOLD")
    future = _rule_obj(entity, kind, date(2027, 1, 1), "LAPSE")
    rules: list[LeaveSeparationRule] = [everything, company, type_only, exact, future]  # type: ignore[list-item]
    assert pick_rule(rules, entity, kind, day) is exact  # company and type beat the rest
    assert pick_rule(rules, entity, uuid4(), day) is company  # company beats "everything"
    assert pick_rule(rules, other, kind, day) is type_only  # other company: the type rule
    assert pick_rule(rules, other, uuid4(), day) is everything
    assert pick_rule(rules, entity, kind, date(2027, 2, 1)) is future  # later start wins
    assert pick_rule([future], entity, kind, day) is None  # not in force yet


async def test_rule_validation_duplicates_archiving_and_access(api):
    client, _ = api
    _, _, emp, lt = await _setup(client)
    assert (await _rule(client, on_separation="LAPSE", hold_days=5)).status_code == 422
    assert (await _rule(client, on_separation="HOLD", max_encash_days=2)).status_code == 422
    assert (
        await _rule(client, on_separation="LAPSE", leave_type_id="lt_nonexistent")
    ).status_code in (404, 422)
    first = await _rule(client, on_separation="LAPSE")
    assert first.status_code == 201
    assert (await _rule(client, on_separation="HOLD")).status_code == 409  # same scope and date
    assert len(await ok(client, "GET", "/v1/leave/separation-rules")) == 1

    # An employee can read nothing of this and change nothing.
    email, password, _ = await make_user(client, emp["id"])
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    denied = await client.post(
        "/v1/leave/separation-rules",
        headers=headers,
        json={"on_separation": "LAPSE", "effective_from": "2021-01-01"},
    )
    assert denied.status_code == 403
    assert (await client.get("/v1/leave/separation-rules", headers=headers)).status_code == 403

    assert (
        await client.delete(f"/v1/leave/separation-rules/{first.json()['id']}")
    ).status_code == 204
    assert await ok(client, "GET", "/v1/leave/separation-rules") == []
    assert (await _rule(client, on_separation="HOLD")).status_code == 201  # slot is free again
    await _separate(client, emp)
    assert (await _settlements(client, emp))[0]["action"] == "HOLD"


async def _tenant_of(admin, emp):
    async with admin.connect() as conn:
        return await conn.scalar(
            text("SELECT tenant_id FROM employments WHERE id = :e"), {"e": to_uuid(emp["id"])}
        )


async def test_the_daily_job_is_registered_and_reports_what_it_did(api):
    from hrms.jobs import runner

    client, admin = api
    _, _, emp, _ = await _setup(client)
    await _rule(client, on_separation="HOLD", hold_days=0)  # due immediately
    await _separate(client, emp)
    assert "leave-holds" in runner.JOBS
    tenant_id = await _tenant_of(admin, emp)
    async with AsyncSession(admin) as session:
        summary = await runner.JOBS["leave-holds"](session, tenant_id)
        await session.commit()
    assert summary == "1 lapsed, 0 restored"
    async with AsyncSession(admin) as session:
        again = await runner.JOBS["leave-holds"](session, tenant_id)
    assert again == "0 lapsed, 0 restored"  # running it every day is safe
