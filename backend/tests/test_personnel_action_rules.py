"""
Personnel actions behave like HR expects: a status change only applies from a state where
it makes sense, a designation change is its own action, and the employee record shows the
grade and position they now hold.
"""

from datetime import date, timedelta

import pytest

from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today().isoformat()


async def _setup(client):
    await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    return le, placement, emp


async def _act(client, emp_id, kind, changes=None, when=TODAY, reason=None):
    body = {"employment_id": emp_id, "type": kind, "effective_date": when}
    if changes:
        body["changes"] = changes
    if reason:
        body["reason_code"] = reason
    return await client.post("/v1/personnel-actions", json=body)


async def _state(client, emp_id):
    return (await ok(client, "GET", f"/v1/employees/{emp_id}"))["employment_state"]


async def test_confirmation_only_from_probation(api):
    client, _ = api
    _, _, emp = await _setup(client)
    assert await _state(client, emp["id"]) == "PROBATION"

    assert (await _act(client, emp["id"], "CONFIRM")).status_code == 201
    assert await _state(client, emp["id"]) == "ACTIVE"

    again = await _act(client, emp["id"], "CONFIRM")
    assert again.status_code == 409
    assert "confirmed" in again.json()["detail"]

    extend = await _act(client, emp["id"], "EXTEND_PROBATION")
    assert extend.status_code == 409  # nothing to extend once confirmed


async def test_separation_then_rehire(api):
    client, _ = api
    _, placement, emp = await _setup(client)

    assert (
        await _act(client, emp["id"], "PLACE_ON_NOTICE", reason="RESIGNATION")
    ).status_code == 201
    assert await _state(client, emp["id"]) == "NOTICE"
    assert (await _act(client, emp["id"], "PLACE_ON_NOTICE")).status_code == 409

    assert (await _act(client, emp["id"], "SEPARATION", reason="RESIGNATION")).status_code == 201
    assert await _state(client, emp["id"]) == "SEPARATED"

    # A separated employee can't be confirmed or put on notice back into employment.
    assert (await _act(client, emp["id"], "CONFIRM")).status_code == 409
    assert (await _act(client, emp["id"], "SEPARATION")).status_code == 409

    rehired = await _act(client, emp["id"], "REHIRE", changes=placement)
    assert rehired.status_code == 201, rehired.text
    assert await _state(client, emp["id"]) == "PROBATION"
    assert (await _act(client, emp["id"], "REHIRE", changes=placement)).status_code == 409


async def test_designation_change_keeps_the_department(api):
    client, _ = api
    _, placement, emp = await _setup(client)
    lead = await ok(client, "POST", "/v1/org/jobs", json={"title": "Team Lead"})

    moved = await _act(client, emp["id"], "CHANGE_JOB", changes={"job_id": lead["id"]})
    assert moved.status_code == 201, moved.text

    after = await ok(client, "GET", f"/v1/employees/{emp['id']}")
    assert after["designation"] == "Team Lead"
    assert after["org_unit_id"] == placement["org_unit_id"]  # carried forward


async def test_promotion_shows_new_grade_and_position(api):
    client, _ = api
    _, placement, emp = await _setup(client)
    grade = await ok(client, "POST", "/v1/org/grades", json={"code": "M1", "name": "Manager"})
    seat = await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={"title": "Ops Manager", "org_unit_id": placement["org_unit_id"], "max_headcount": 1},
    )
    promoted = await _act(
        client,
        emp["id"],
        "PROMOTION",
        changes={"grade_id": grade["id"], "position_id": seat["id"]},
        reason="MERIT",
    )
    assert promoted.status_code == 201, promoted.text

    after = await ok(client, "GET", f"/v1/employees/{emp['id']}")
    assert (after["grade"], after["position_title"]) == ("Manager", "Ops Manager")
    assert after["grade_id"] == grade["id"] and after["position_id"] == seat["id"]


async def test_future_actions_are_still_scheduled(api):
    """State rules apply on the effective date, so planning ahead stays possible."""
    client, _ = api
    _, _, emp = await _setup(client)
    later = (date.today() + timedelta(days=30)).isoformat()
    scheduled = await _act(client, emp["id"], "CONFIRM", when=later)
    assert scheduled.status_code == 201
    assert scheduled.json()["status"] == "SCHEDULED"
