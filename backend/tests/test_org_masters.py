"""
Grades, cost centres and positions: the org masters that existed as tables with no API.

What matters to HR: they can be maintained from the UI, codes don't clash, nothing is
deleted (retired with status INACTIVE), every edit is audited, and a position's vacancy
figure counts the people actually placed in it, the same way the HR dashboard does.
"""

import pytest

from tests.helpers import bearer, hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database


async def _entity(client):
    return (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]


async def test_grades_are_ordered_unique_and_retired_not_deleted(api):
    client, _ = api
    await tenant(client)
    await ok(
        client, "POST", "/v1/org/grades", json={"code": "M1", "name": "Manager", "sequence": 20}
    )
    w1 = await ok(
        client, "POST", "/v1/org/grades", json={"code": "W1", "name": "Worker", "sequence": 10}
    )

    grades = await ok(client, "GET", "/v1/org/grades")
    assert [g["code"] for g in grades] == ["W1", "M1"]  # by sequence, not by name or insert order

    dup = await client.post("/v1/org/grades", json={"code": "w1", "name": "Again"})
    assert dup.status_code == 409  # case-insensitive

    retired = await ok(client, "PATCH", f"/v1/org/grades/{w1['id']}", json={"status": "INACTIVE"})
    assert retired["status"] == "INACTIVE"
    assert len(await ok(client, "GET", "/v1/org/grades")) == 2  # still listed for old records

    history = await ok(client, "GET", f"/v1/org/grades/{w1['id']}/history")
    assert [h["action"] for h in history] == ["UPDATE", "CREATE"]
    assert history[0]["changes"] == {"status": {"old": "ACTIVE", "new": "INACTIVE"}}


async def test_renaming_a_grade_to_an_existing_code_is_refused(api):
    client, _ = api
    await tenant(client)
    await ok(client, "POST", "/v1/org/grades", json={"code": "A", "name": "A"})
    b = await ok(client, "POST", "/v1/org/grades", json={"code": "B", "name": "B"})
    clash = await client.patch(f"/v1/org/grades/{b['id']}", json={"code": "a"})
    assert clash.status_code == 409
    # Sending null for a required field leaves it alone instead of failing in the database.
    same = await ok(
        client, "PATCH", f"/v1/org/grades/{b['id']}", json={"code": None, "name": "Bee"}
    )
    assert same["code"] == "B" and same["name"] == "Bee"


async def test_cost_centres_crud_and_audit(api):
    client, _ = api
    await tenant(client)
    cc = await ok(client, "POST", "/v1/org/cost-centres", json={"code": "CC-OPS", "name": "Ops"})
    assert cc["id"].startswith("cc_") and cc["status"] == "ACTIVE"
    assert (
        await client.post("/v1/org/cost-centres", json={"code": "cc-ops", "name": "x"})
    ).status_code == 409

    updated = await ok(
        client, "PATCH", f"/v1/org/cost-centres/{cc['id']}", json={"name": " Operations "}
    )
    assert updated["name"] == "Operations"  # trimmed
    history = await ok(client, "GET", f"/v1/org/cost-centres/{cc['id']}/history")
    assert history[0]["changes"] == {"name": {"old": "Ops", "new": "Operations"}}


async def test_position_counts_filled_seats_and_vacancies(api):
    client, _ = api
    await tenant(client)
    le = await _entity(client)
    placement = await org_basics(client, le)
    grade = await ok(client, "POST", "/v1/org/grades", json={"code": "S1", "name": "Supervisor"})

    position = await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={
            "title": "Shift Supervisor",
            "org_unit_id": placement["org_unit_id"],
            "job_id": placement["job_id"],
            "grade_id": grade["id"],
            "max_headcount": 2,
            "effective_from": "2020-01-01",
        },
    )
    assert position["status"] == "ACTIVE"  # counts in the dashboard's vacancies card
    assert (position["filled"], position["vacancies"]) == (0, 2)
    assert position["job_title"] == "Executive" and position["grade_name"] == "Supervisor"

    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], {**placement, "position_id": position["id"]})

    listed = await ok(
        client, "GET", "/v1/org/positions", params={"org_unit_id": placement["org_unit_id"]}
    )
    assert len(listed) == 1
    assert (listed[0]["filled"], listed[0]["vacancies"]) == (1, 1)

    # The HR dashboard's vacancies card reads the same rule (ACTIVE, with a headcount limit).
    dashboard = await ok(client, "GET", "/v1/dashboard/hr", params={"sections": "vacancies"})
    assert dashboard["vacancies"]["vacancies"] == 1


async def test_position_history_reads_like_the_screen(api):
    """HR reads department, job and grade names in the history, never internal IDs."""
    client, _ = api
    await tenant(client)
    placement = await org_basics(client, await _entity(client))
    junior = await ok(client, "POST", "/v1/org/grades", json={"code": "J", "name": "Junior"})
    senior = await ok(client, "POST", "/v1/org/grades", json={"code": "S", "name": "Senior"})
    pos = await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={
            "title": "Analyst",
            "org_unit_id": placement["org_unit_id"],
            "grade_id": junior["id"],
        },
    )
    await ok(client, "PATCH", f"/v1/org/positions/{pos['id']}", json={"grade_id": senior["id"]})

    history = await ok(client, "GET", f"/v1/org/positions/{pos['id']}/history")
    assert history[0]["changes"] == {"grade": {"old": "Junior", "new": "Senior"}}
    created = history[1]["changes"]
    assert created["department"] == {"old": None, "new": "Ops"}
    assert created["grade"] == {"old": None, "new": "Junior"}
    assert not any(key.endswith("_id") for key in created)


async def test_position_validation(api):
    client, _ = api
    await tenant(client)
    le = await _entity(client)
    placement = await org_basics(client, le)

    bad_grade = await client.post(
        "/v1/org/positions",
        json={
            "title": "X",
            "org_unit_id": placement["org_unit_id"],
            "grade_id": "grd_aaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
    )
    assert bad_grade.status_code == 422

    bad_dates = await client.post(
        "/v1/org/positions",
        json={
            "title": "X",
            "org_unit_id": placement["org_unit_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2025-12-31",
        },
    )
    assert bad_dates.status_code == 422

    template = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Shared Finance",
            "type": "DEPARTMENT_TEMPLATE",
            "effective_from": "2020-01-01",
        },
    )
    on_template = await client.post(
        "/v1/org/positions", json={"title": "X", "org_unit_id": template["id"]}
    )
    assert on_template.status_code == 422

    pos = await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={"title": "Clerk", "org_unit_id": placement["org_unit_id"]},
    )
    cleared = await ok(
        client, "PATCH", f"/v1/org/positions/{pos['id']}", json={"max_headcount": 4, "code": "CLK"}
    )
    assert cleared["max_headcount"] == 4 and cleared["code"] == "CLK"
    cleared = await ok(client, "PATCH", f"/v1/org/positions/{pos['id']}", json={"code": None})
    assert cleared["code"] is None  # nullable fields can be cleared
    history = await ok(client, "GET", f"/v1/org/positions/{pos['id']}/history")
    assert [h["action"] for h in history] == ["UPDATE", "UPDATE", "CREATE"]


async def test_positions_follow_company_scope(api):
    client, _ = api
    await tenant(client)
    first = await _entity(client)
    other = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Other Co"})
    mine = await org_basics(client, first)
    theirs = await org_basics(client, other["id"])
    await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={"title": "Mine", "org_unit_id": mine["org_unit_id"]},
    )
    foreign = await ok(
        client,
        "POST",
        "/v1/org/positions",
        json={"title": "Theirs", "org_unit_id": theirs["org_unit_id"]},
    )

    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[first]
    )
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    hr = bearer(login["access_token"])

    visible = await ok(client, "GET", "/v1/org/positions", headers=hr)
    assert [p["title"] for p in visible] == ["Mine"]
    denied = await client.patch(
        f"/v1/org/positions/{foreign['id']}", json={"title": "Taken"}, headers=hr
    )
    assert denied.status_code == 403
    create_elsewhere = await client.post(
        "/v1/org/positions",
        json={"title": "Sneaky", "org_unit_id": theirs["org_unit_id"]},
        headers=hr,
    )
    assert create_elsewhere.status_code == 403


async def test_employees_cannot_edit_masters(api):
    client, _ = api
    await tenant(client)
    le = await _entity(client)
    emp = await person_and_employment(client, le)
    email, password, _ = await make_user(client, emp["id"])
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    staff = bearer(login["access_token"])

    assert (
        await client.post("/v1/org/grades", json={"code": "X", "name": "X"}, headers=staff)
    ).status_code == 403
    assert (
        await client.post("/v1/org/cost-centres", json={"code": "X", "name": "X"}, headers=staff)
    ).status_code == 403
    assert (
        await ok(client, "GET", "/v1/org/positions", headers=staff) == []
    )  # SELF scope sees no seats
