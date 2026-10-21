"""
Guards around rejoining: hiring someone who already has an employment, a second scheduled
rejoin, and a person's single UAN.
"""

from datetime import date, timedelta

import pytest

from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _setup(client):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    emp = await person_and_employment(client, company)
    await hire(client, emp["id"], placement)
    return company, placement, emp


async def _hire_again(client, company, emp, **extra):
    return await client.post(
        "/v1/employees",
        json={
            "person_id": emp["person_id"],
            "legal_entity_id": company,
            "hire_date": TODAY.isoformat(),
            **extra,
        },
    )


async def _act(client, emp, kind, when=TODAY, **extra):
    return await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": kind,
            "effective_date": when.isoformat(),
            **extra,
        },
    )


async def test_hiring_someone_who_already_has_an_employment_is_refused_until_confirmed(api):
    client, _ = api
    company, _, emp = await _setup(client)
    refused = await _hire_again(client, company, emp, employee_number="DUP-1")
    assert refused.status_code == 409 and refused.json()["code"] == "PAST_EMPLOYMENT_EXISTS"
    assert "Rehire" in refused.json()["detail"]
    allowed = await _hire_again(
        client, company, emp, employee_number="DUP-1", confirm_new_employment=True
    )
    assert allowed.status_code == 201, allowed.text


async def test_the_person_can_be_checked_before_hiring_and_a_leaver_offers_a_rejoin(api):
    client, _ = api
    _, _, emp = await _setup(client)
    (current,) = await ok(client, "GET", f"/v1/persons/{emp['person_id']}/employments")
    assert current["employment_id"] == emp["id"] and current["can_rejoin"] is False
    await _act(client, emp, "SEPARATION", when=TODAY - timedelta(days=3), reason_code="RESIGNATION")
    (left,) = await ok(client, "GET", f"/v1/persons/{emp['person_id']}/employments")
    assert left["can_rejoin"] is True and left["separation_date"] is not None


async def test_a_brand_new_person_is_hired_as_before(api):
    client, _ = api
    company, _, _ = await _setup(client)
    newcomer = await person_and_employment(client, company)
    assert newcomer["id"]


async def test_a_second_scheduled_rejoin_is_refused_and_a_rejoin_while_employed_is_too(api):
    client, _ = api
    _, placement, emp = await _setup(client)
    assert (await _act(client, emp, "REHIRE", changes=placement)).status_code == 409  # employed
    await _act(client, emp, "SEPARATION", when=TODAY - timedelta(days=5), reason_code="RESIGNATION")
    future = TODAY + timedelta(days=10)
    first = await _act(client, emp, "REHIRE", when=future, changes=placement)
    assert first.status_code == 201 and first.json()["status"] == "SCHEDULED"
    second = await _act(client, emp, "REHIRE", when=future + timedelta(days=1), changes=placement)
    assert second.status_code == 409 and "already scheduled" in second.json()["detail"]


async def test_a_person_keeps_one_uan_across_employments(api):
    client, _ = api
    company, _, first = await _setup(client)
    saved = await client.patch(
        f"/v1/kyc/employees/{first['id']}", json={"uan_number": "100200300400"}
    )
    assert saved.status_code == 200, saved.text
    second = await _hire_again(
        client, company, first, employee_number="UAN-2", confirm_new_employment=True
    )
    assert second.status_code == 201
    other = second.json()
    different = await client.patch(
        f"/v1/kyc/employees/{other['id']}", json={"uan_number": "999888777666"}
    )
    assert different.status_code == 409
    assert different.json()["code"] == "UAN_ALREADY_ASSIGNED"
    assert "0400" in different.json()["detail"] and "100200300400" not in different.json()["detail"]
    same = await client.patch(
        f"/v1/kyc/employees/{other['id']}", json={"uan_number": "100200300400"}
    )
    assert same.status_code == 200, same.text


async def test_the_history_lists_each_stint_and_how_a_rejoin_was_decided(api):
    client, _ = api
    _, placement, emp = await _setup(client)
    await _act(client, emp, "SEPARATION", when=TODAY - timedelta(days=9), reason_code="RESIGNATION")
    done = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "REHIRE",
            "effective_date": TODAY.isoformat(),
            "changes": placement,
            "rejoin": {"mode": "FRESH", "reason": "New contract"},
        },
    )
    assert done.status_code == 201, done.text
    history = await ok(client, "GET", f"/v1/employees/{emp['id']}/employment-history")
    assert history["continuity_start_date"] == TODAY.isoformat()
    newest, first = history["spells"]
    assert (newest["spell_no"], newest["left_on"]) == (2, None)
    assert newest["rejoin"]["mode"] == "FRESH" and newest["rejoin"]["reason"] == "New contract"
    assert first["spell_no"] == 1 and first["exit_reason"] == "RESIGNATION"
    assert first["rejoin"] is None
