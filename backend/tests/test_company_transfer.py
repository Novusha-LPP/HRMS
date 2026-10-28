"""
Moving a person to another company of the group: the old employment ends, a new one starts the
same day, leave is carried or settled, and their login, identity record and documents follow.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _group(client):
    """A tenant with two companies, an employee in the first with 10 days of leave."""
    admin = await tenant(client)
    first = admin["user"]["legal_entities"][0]["id"]
    second = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": f"Sister {uuid4().hex[:5]}", "country": "IN"},
        )
    )["id"]
    placement_a = await org_basics(client, first)
    placement_b = await org_basics(client, second)
    emp = await person_and_employment(client, first)
    await hire(client, emp["id"], placement_a)
    leave_type = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12, "encashable": True},
    )
    await ok(
        client,
        "POST",
        "/v1/leave/balances/adjust",
        json={
            "employment_id": emp["id"],
            "leave_type_id": leave_type["id"],
            "quantity": 10,
            "kind": "OPENING",
            "reason": "Test balance",
            "effective_date": (TODAY - timedelta(days=60)).isoformat(),
        },
    )
    return first, second, placement_b, emp, leave_type


async def _transfer(client, emp, second, placement, **extra):
    return await client.post(
        "/v1/people/transfers",
        json={
            "employment_id": emp["id"],
            "legal_entity_id": second,
            "effective_date": TODAY.isoformat(),
            "placement": placement,
            **extra,
        },
    )


async def _available(client, employment_id, leave_type):
    rows = await ok(client, "GET", f"/v1/leave/balances?employment_id={employment_id}")
    match = [b for b in rows if b["leave_type_id"] == leave_type["id"]]
    return match[0]["available_days"] if match else 0


async def test_a_transfer_ends_one_employment_and_starts_another(api):
    client, admin = api
    first, second, placement, emp, _ = await _group(client)
    done = await _transfer(client, emp, second, placement, employee_number="B-001")
    assert done.status_code == 201, done.text
    result = done.json()
    old = await ok(client, "GET", f"/v1/employees/{emp['id']}")
    new = await ok(client, "GET", f"/v1/employees/{result['to_employment_id']}")
    assert old["employment_state"] == "SEPARATED" and old["separation_date"] == TODAY.isoformat()
    assert new["legal_entity_id"] == second and new["employee_number"] == "B-001"
    assert new["hire_date"] == TODAY.isoformat() and new["person_id"] == emp["person_id"]
    assert new["department"] is not None  # placed in the new company straight away
    async with admin.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT leave_mode FROM company_transfers WHERE from_employment_id = :e"),
                {"e": to_uuid(emp["id"])},
            )
        ).one()
        spells = await conn.scalar(
            text("SELECT count(*) FROM employment_spells WHERE employment_id = :e"),
            {"e": to_uuid(result["to_employment_id"])},
        )
    assert row.leave_mode == "CARRY" and spells == 1


async def test_carrying_moves_the_leave_and_keeps_service(api):
    client, admin = api
    _, second, placement, emp, leave_type = await _group(client)
    done = (await _transfer(client, emp, second, placement, employee_number="B-002")).json()
    assert await _available(client, emp["id"], leave_type) == 0
    assert await _available(client, done["to_employment_id"], leave_type) == 10
    async with admin.connect() as conn:
        service = (
            await conn.execute(
                text("SELECT hire_date, continuity_start_date FROM employments WHERE id = :e"),
                {"e": to_uuid(done["to_employment_id"])},
            )
        ).one()
        old_start = await conn.scalar(
            text("SELECT continuity_start_date FROM employments WHERE id = :e"),
            {"e": to_uuid(emp["id"])},
        )
    assert service.continuity_start_date == old_start != service.hire_date


async def test_settling_applies_the_leave_rules_and_starts_empty(api):
    client, _ = api
    _, second, placement, emp, leave_type = await _group(client)
    await ok(
        client,
        "POST",
        "/v1/leave/separation-rules",
        json={"on_separation": "LAPSE", "effective_from": "2020-01-01"},
    )
    done = (
        await _transfer(
            client, emp, second, placement, employee_number="B-003", leave_mode="SETTLE"
        )
    ).json()
    assert await _available(client, emp["id"], leave_type) == 0  # lapsed by the company rule
    assert await _available(client, done["to_employment_id"], leave_type) == 0
    settlements = await ok(
        client, "GET", f"/v1/leave/separation-settlements?employment_id={emp['id']}"
    )
    assert settlements[0]["action"] == "LAPSE"


async def test_the_login_and_identity_follow_the_person(api):
    client, admin = api
    first, second, placement, emp, _ = await _group(client)
    email, password, _ = await make_user(client, emp["id"])
    saved = await client.patch(
        f"/v1/kyc/employees/{emp['id']}", json={"uan_number": "100200300400"}
    )
    assert saved.status_code == 200, saved.text
    done = (await _transfer(client, emp, second, placement, employee_number="B-004")).json()
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    me = await ok(
        client, "GET", "/v1/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert me["employment_id"] == done["to_employment_id"]
    # The UAN is the same on both employments (it follows the person), and the first company
    # keeps its own copy of the record.
    old_kyc = await ok(client, "GET", f"/v1/kyc/employees/{emp['id']}")
    new_kyc = await ok(client, "GET", f"/v1/kyc/employees/{done['to_employment_id']}")
    assert old_kyc["uan_number"] == new_kyc["uan_number"] and old_kyc["uan_number"]


async def test_refused_when_it_cannot_be_done(api):
    client, _ = api
    first, second, placement, emp, _ = await _group(client)
    same = await _transfer(client, emp, first, placement, employee_number="X-1")
    assert same.status_code == 422 and "already work" in same.json()["detail"]
    future = await client.post(
        "/v1/people/transfers",
        json={
            "employment_id": emp["id"],
            "legal_entity_id": second,
            "effective_date": (TODAY + timedelta(days=3)).isoformat(),
            "placement": placement,
            "employee_number": "X-2",
        },
    )
    assert future.status_code == 422
    nothing = await _transfer(client, emp, second, {**placement, "org_unit_id": "ou_unknown"})
    assert nothing.status_code in (404, 422)
    # Nothing was started by any of the refusals.
    assert (await ok(client, "GET", f"/v1/employees/{emp['id']}"))[
        "employment_state"
    ] != "SEPARATED"
    done = await _transfer(client, emp, second, placement, employee_number="X-3")
    assert done.status_code == 201
    again = await _transfer(client, emp, second, placement, employee_number="X-4")
    assert again.status_code == 422 and "left" in again.json()["detail"]


async def test_the_preview_shows_the_leave_and_blocks_what_cannot_happen(api):
    client, _ = api
    first, second, _, emp, _ = await _group(client)
    ok_preview = await ok(
        client,
        "GET",
        f"/v1/people/transfer-preview?employment_id={emp['id']}&legal_entity_id={second}",
    )
    assert ok_preview["can_proceed"] is True
    assert [line["days"] for line in ok_preview["leave"]] == [10]
    settle = await ok(
        client,
        "GET",
        f"/v1/people/transfer-preview?employment_id={emp['id']}&legal_entity_id={second}&leave_mode=SETTLE",
    )
    assert settle["leave"] == [] and "rules for leavers" in settle["warnings"][0]
    blocked = await ok(
        client,
        "GET",
        f"/v1/people/transfer-preview?employment_id={emp['id']}&legal_entity_id={first}",
    )
    assert blocked["can_proceed"] is False


async def test_hr_for_one_company_cannot_move_people_into_another(api):
    client, _ = api
    first, second, placement, emp, _ = await _group(client)
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[first]
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    refused = await client.post(
        "/v1/people/transfers",
        headers=headers,
        json={
            "employment_id": emp["id"],
            "legal_entity_id": second,
            "effective_date": TODAY.isoformat(),
            "placement": placement,
            "employee_number": "S-1",
        },
    )
    assert refused.status_code == 403
    assert (await ok(client, "GET", f"/v1/employees/{emp['id']}"))[
        "employment_state"
    ] != "SEPARATED"


async def test_a_taken_employee_id_is_refused_cleanly_and_nothing_is_half_done(api):
    client, _ = api
    _, second, placement, emp, leave_type = await _group(client)
    other = await person_and_employment(client, second)
    clash = await _transfer(
        client, emp, second, placement, employee_number=other["employee_number"]
    )
    assert clash.status_code in (409, 422), clash.text
    # The refusal rolled everything back: still employed, leave untouched.
    assert (await ok(client, "GET", f"/v1/employees/{emp['id']}"))[
        "employment_state"
    ] != "SEPARATED"
    assert await _available(client, emp["id"], leave_type) == 10
