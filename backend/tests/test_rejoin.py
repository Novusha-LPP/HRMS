"""
Rejoining: continue earlier service and leave, or start fresh.

The company's rejoin policy sets the default and the longest break that may continue; HR can
record a different choice with a reason. Every choice leaves a record and the leave ledger shows
exactly what happened. With no policy, rejoining works as it always has.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from hrms.modules.people.rejoin import pick_policy
from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _setup(client, *, opening=10):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    emp = await person_and_employment(client, company)
    await hire(client, emp["id"], placement)
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12, "encashable": True},
    )
    if opening:
        await ok(
            client,
            "POST",
            "/v1/leave/balances/adjust",
            json={
                "employment_id": emp["id"],
                "leave_type_id": lt["id"],
                "quantity": opening,
                "kind": "OPENING",
                "reason": "Test balance",
                "effective_date": (TODAY - timedelta(days=60)).isoformat(),
            },
        )
    return company, placement, emp, lt


async def _policy(client, **body):
    body.setdefault("effective_from", "2020-01-01")
    return await client.post("/v1/people/rejoin-policies", json=body)


async def _leave_rule(client, **body):
    body.setdefault("effective_from", "2020-01-01")
    return await client.post("/v1/leave/separation-rules", json=body)


async def _separate(client, emp, days_ago):
    response = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "SEPARATION",
            "effective_date": (TODAY - timedelta(days=days_ago)).isoformat(),
            "reason_code": "RESIGNATION",
        },
    )
    assert response.status_code == 201, response.text


async def _rehire(client, emp, placement, rejoin=None, when=TODAY):
    body = {
        "employment_id": emp["id"],
        "type": "REHIRE",
        "effective_date": when.isoformat(),
        "changes": placement,
    }
    if rejoin is not None:
        body["rejoin"] = rejoin
    return await client.post("/v1/personnel-actions", json=body)


async def _available(client, emp, lt):
    rows = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}")
    return next(b for b in rows if b["leave_type_id"] == lt["id"])["available_days"]


async def _record(admin, emp):
    async with admin.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT mode, break_condoned, reason, restored_leave FROM rejoin_records "
                "WHERE employment_id = :e ORDER BY created_at DESC"
            ),
            {"e": to_uuid(emp["id"])},
        )
        return rows.first()


async def _continuity(admin, emp):
    async with admin.connect() as conn:
        return (
            await conn.execute(
                text("SELECT hire_date, continuity_start_date FROM employments WHERE id = :e"),
                {"e": to_uuid(emp["id"])},
            )
        ).one()


async def test_with_no_policy_rejoining_continues_exactly_as_before(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    await _separate(client, emp, 10)
    assert (await _rehire(client, emp, placement)).status_code == 201
    assert await _available(client, emp, lt) == 10
    record = await _record(admin, emp)
    assert record.mode == "CONTINUE" and record.break_condoned is True
    hire_date, continuity = await _continuity(admin, emp)
    assert continuity == hire_date


async def test_starting_fresh_lapses_the_leave_and_restarts_service(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    await _separate(client, emp, 10)
    refused = await _rehire(client, emp, placement, {"mode": "FRESH"})
    assert refused.status_code == 422 and "reason" in refused.json()["detail"].lower()
    done = await _rehire(client, emp, placement, {"mode": "FRESH", "reason": "New contract"})
    assert done.status_code == 201, done.text
    assert await _available(client, emp, lt) == 0
    record = await _record(admin, emp)
    assert record.mode == "FRESH" and record.break_condoned is False
    assert record.reason == "New contract"
    assert record.restored_leave["lapsed"][0]["days"] == 10
    _, continuity = await _continuity(admin, emp)
    assert continuity == TODAY
    async with admin.connect() as conn:
        lapse = await conn.scalar(
            text(
                "SELECT quantity FROM leave_balance_transactions "
                "WHERE employment_id = :e AND reference_type = 'REJOIN'"
            ),
            {"e": to_uuid(emp["id"])},
        )
    assert lapse == 10


async def test_continuing_restores_held_leave_but_not_what_was_paid_out(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    await _leave_rule(client, on_separation="HOLD", hold_days=90)
    await _separate(client, emp, 10)
    assert (await _rehire(client, emp, placement, {"mode": "CONTINUE"})).status_code == 201
    assert await _available(client, emp, lt) == 10
    settlements = await ok(
        client, "GET", f"/v1/leave/separation-settlements?employment_id={emp['id']}"
    )
    assert settlements[0]["resolution"] == "RESTORED"
    assert (await _record(admin, emp)).restored_leave["kept"][0]["days"] == 10


async def test_continuing_after_leave_was_lapsed_at_exit_brings_nothing_back(api):
    client, _ = api
    _, placement, emp, lt = await _setup(client)
    await _leave_rule(client, on_separation="LAPSE")
    await _separate(client, emp, 10)
    assert await _available(client, emp, lt) == 0
    assert (await _rehire(client, emp, placement)).status_code == 201
    assert await _available(client, emp, lt) == 0


async def test_the_policy_default_and_the_longest_break_that_may_continue(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    assert (
        await _policy(client, default_mode="CONTINUE", force_fresh_after_days=30)
    ).status_code == 201
    await _separate(client, emp, 100)  # a 100 day break

    preview = await ok(client, "GET", f"/v1/employees/{emp['id']}/rejoin-preview")
    assert preview["gap_days"] == 100 and preview["allowed_modes"] == ["FRESH"]
    assert preview["mode"] == "FRESH" and preview["automatic"] is True

    # Asking to continue anyway is refused unless the break is condoned, with a reason.
    refused = await _rehire(client, emp, placement, {"mode": "CONTINUE"})
    assert refused.status_code == 422 and "30 days" in refused.json()["detail"]
    still = await _rehire(client, emp, placement, {"mode": "CONTINUE", "break_condoned": True})
    assert still.status_code == 422
    allowed = await _rehire(
        client,
        emp,
        placement,
        {"mode": "CONTINUE", "break_condoned": True, "reason": "Approved by director"},
    )
    assert allowed.status_code == 201, allowed.text
    record = await _record(admin, emp)
    assert record.mode == "CONTINUE" and record.reason == "Approved by director"
    assert await _available(client, emp, lt) == 10


async def test_a_default_that_cannot_continue_starts_fresh_on_its_own(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    await _policy(client, default_mode="CONTINUE", force_fresh_after_days=30)
    await _separate(client, emp, 100)
    assert (await _rehire(client, emp, placement)).status_code == 201  # no choice given
    record = await _record(admin, emp)
    assert record.mode == "FRESH" and "automatically" in record.reason
    assert await _available(client, emp, lt) == 0


async def test_gratuity_paid_at_exit_means_service_restarts(api):
    client, admin = api
    _, placement, emp, _ = await _setup(client)
    await _separate(client, emp, 10)
    preview = await ok(
        client,
        "GET",
        f"/v1/employees/{emp['id']}/rejoin-preview?mode=CONTINUE&gratuity_paid_at_exit=true",
    )
    assert preview["can_proceed"] is False and "Gratuity" in preview["blocked"][0]
    refused = await _rehire(
        client, emp, placement, {"mode": "CONTINUE", "gratuity_paid_at_exit": True}
    )
    assert refused.status_code == 422
    fresh = await _rehire(client, emp, placement, {"gratuity_paid_at_exit": True})
    assert fresh.status_code == 201, fresh.text
    assert (await _record(admin, emp)).mode == "FRESH"
    async with admin.connect() as conn:
        paid = await conn.scalar(
            text(
                "SELECT gratuity_paid FROM employment_spells "
                "WHERE employment_id = :e AND spell_no = 1"
            ),
            {"e": to_uuid(emp["id"])},
        )
    assert paid is True


async def test_start_fresh_restarts_leave_eligibility(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client, opening=0)
    await ok(
        client,
        "PATCH",
        f"/v1/leave/types/{lt['id']}",
        json={"accrual_enabled": True, "version": lt["version"]},
    )
    await _separate(client, emp, 10)
    await _rehire(client, emp, placement, {"mode": "FRESH", "reason": "New contract"})
    async with admin.connect() as conn:
        continuity = await conn.scalar(
            text("SELECT continuity_start_date FROM employments WHERE id = :e"),
            {"e": to_uuid(emp["id"])},
        )
    assert continuity == TODAY  # accrual measures service from here, not from 2020


async def test_the_preview_is_read_only_and_only_for_someone_who_left(api):
    client, admin = api
    _, placement, emp, lt = await _setup(client)
    not_left = await client.get(f"/v1/employees/{emp['id']}/rejoin-preview")
    assert not_left.status_code == 409
    await _separate(client, emp, 10)
    preview = await ok(
        client, "GET", f"/v1/employees/{emp['id']}/rejoin-preview?mode=FRESH&reason=New"
    )
    assert preview["leave"] == [
        {
            "leave_type_id": lt["id"],
            "leave_type_name": "Annual",
            "days": 10,
            "outcome": "LAPSE",
        }
    ]
    assert await _available(client, emp, lt) == 10  # the preview changed nothing
    assert await _record(admin, emp) is None


async def test_a_scheduled_rejoin_is_checked_when_entered_and_when_it_comes_due(api):
    client, admin = api
    _, placement, emp, _ = await _setup(client)
    await _policy(client, default_mode="CONTINUE", force_fresh_after_days=5)
    await _separate(client, emp, 10)
    soon = TODAY + timedelta(days=3)  # a 13 day break by then
    refused = await _rehire(client, emp, placement, {"mode": "CONTINUE"}, when=soon)
    assert refused.status_code == 422
    scheduled = await _rehire(client, emp, placement, {"mode": "FRESH", "reason": "New"}, when=soon)
    assert scheduled.status_code == 201
    assert scheduled.json()["status"] == "SCHEDULED"


async def test_rejoin_is_only_for_a_rehire(api):
    client, _ = api
    _, _, emp, _ = await _setup(client)
    response = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "CONFIRM",
            "effective_date": TODAY.isoformat(),
            "rejoin": {"mode": "FRESH"},
        },
    )
    assert response.status_code == 422


async def test_policy_rules_duplicates_archiving_and_access(api):
    client, _ = api
    company, _, emp, _ = await _setup(client)
    assert (await _policy(client, default_mode="SOMETIMES")).status_code == 422
    assert (
        await _policy(client, default_mode="FRESH", legal_entity_id="le_unknown")
    ).status_code in (404, 422)
    first = await _policy(client, default_mode="CONTINUE")
    assert first.status_code == 201
    assert (await _policy(client, default_mode="FRESH")).status_code == 409
    own = await _policy(client, default_mode="FRESH", legal_entity_id=company)
    assert own.status_code == 201  # a company's own policy sits beside the general one
    assert len(await ok(client, "GET", "/v1/people/rejoin-policies")) == 2
    assert (
        await client.delete(f"/v1/people/rejoin-policies/{first.json()['id']}")
    ).status_code == 204
    assert len(await ok(client, "GET", "/v1/people/rejoin-policies")) == 1
    assert (
        await client.delete(f"/v1/people/rejoin-policies/{first.json()['id']}")
    ).status_code == 404


def _policy_obj(entity, start, mode="CONTINUE"):
    return SimpleNamespace(
        id=uuid4(),
        legal_entity_id=entity,
        effective_from=start,
        default_mode=mode,
        archived_at=None,
    )


def test_a_companys_own_policy_beats_the_general_one_and_the_latest_start_wins():
    mine, other = uuid4(), uuid4()
    day = date(2026, 6, 1)
    general = _policy_obj(None, date(2020, 1, 1))
    own = _policy_obj(mine, date(2021, 1, 1), "FRESH")
    newer_general = _policy_obj(None, date(2025, 1, 1), "FRESH")
    future = _policy_obj(mine, date(2030, 1, 1))
    policies = [general, own, newer_general, future]
    assert pick_policy(policies, mine, day) is own
    assert pick_policy(policies, other, day) is newer_general
    assert pick_policy([future], mine, day) is None
