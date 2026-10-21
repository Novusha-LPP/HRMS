"""Real HTTP/RLS coverage for configurable hierarchies and delegated authority."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, employee, hire, make_user, ok, org_basics, tenant

pytestmark = pytest.mark.database


async def setup(client):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    worker, login = await employee(client, company, "WORKER")
    await hire(client, worker["id"], placement)
    actors = []
    for name in ["LEAD", "HOD", "HR", "ADMIN", "ALTERNATE"]:
        emp, account = await employee(client, company, name)
        actors.append(
            dict(employee=emp, id=account["user"]["id"], headers=bearer(account["access_token"]))
        )
    return admin, placement, worker, bearer(login["access_token"]), actors


async def flow(client, unit, actors, kind="CORRECTION", stages=4):
    created = await ok(
        client,
        "POST",
        "/v1/approvals/flows",
        json=dict(
            name="Engineering approval",
            request_type=kind,
            reusable=True,
            steps=[
                dict(name=names, approver_ids=[actor["id"]])
                for names, actor in zip(
                    ["Team lead / PM", "HOD", "HR", "Admin"], actors[:stages], strict=False
                )
            ],
        ),
    )

    # Explicit selections replace implicit department/team inheritance.
    employees = await ok(client, "GET", "/v1/employees?limit=200")
    for member in employees:
        if member.get("org_unit_id") == unit:
            await select_flow(client, member["id"], created)
    return created


async def select_flow(client, employment_id, selected):
    current = await ok(client, "GET", f"/v1/approvals/employees/{employment_id}/flows")
    previous = next(
        (a for a in current["assignments"] if a["request_type"] == selected["request_type"]), None
    )
    return await ok(
        client,
        "PUT",
        f"/v1/approvals/employees/{employment_id}/flows/{selected['request_type']}",
        json=dict(flow_id=selected["id"], version=previous["version"] if previous else 0),
    )


async def correction(client, headers, day="2026-09-28"):
    return await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=headers,
        json=dict(
            work_date=day,
            correction_type="REGULARIZE",
            requested_punch_in=day + "T09:30:00+05:30",
            requested_punch_out=day + "T18:30:00+05:30",
            reason="Workflow test",
        ),
    )


async def instance_for(client, headers, request_id):
    return next(
        r
        for r in await ok(client, "GET", "/v1/approvals/inbox", headers=headers)
        if r["request_id"] == request_id
    )


async def decide(client, instance, actor, action="APPROVE"):
    return await client.post(
        f"/v1/approvals/requests/{instance['id']}/decision",
        headers=actor["headers"],
        json=dict(action=action, comments="Reviewed"),
    )


async def test_four_level_corrections_and_snapshot(api):
    client, engine = api
    _, placement, worker, worker_headers, actors = await setup(client)
    route = await flow(client, placement["org_unit_id"], actors)
    cor = await correction(client, worker_headers)
    assert cor["total_levels"] == 4 and cor["status"] == "PENDING_L1"
    instance = await instance_for(client, actors[0]["headers"], cor["id"])
    assert instance["can_act"] and instance["employee_number"] == "WORKER"
    denied = await decide(client, instance, actors[1])
    assert denied.status_code == 403
    denied = await client.post(
        f"/v1/corrections/{cor['id']}/approve", headers=worker_headers, json={"action": "APPROVE"}
    )
    assert denied.status_code == 403
    # Editing future requests does not change the snapshot of this request.
    route["steps"] = route["steps"][:1]
    await ok(client, "PUT", f"/v1/approvals/flows/{route['id']}", json=route)
    for index, actor in enumerate(actors[:4]):
        response = await decide(client, instance, actor)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == ("APPROVED" if index == 3 else "PENDING")
    detail = await ok(
        client, "GET", f"/v1/approvals/requests/{instance['id']}", headers=worker_headers
    )
    assert len(detail["steps"]) == 4 and len(detail["history"]) == 4
    today = await ok(
        client,
        "GET",
        f"/v1/time/today?employment_id={worker['id']}&work_date=2026-09-28",
        headers=worker_headers,
    )
    assert today["effective_minutes"] == 540
    new = await correction(client, worker_headers, "2026-09-29")
    assert new["total_levels"] == 1
    twice = await decide(client, instance, actors[3])
    assert twice.status_code == 409
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text(
                    "SELECT count(*) FROM approval_events WHERE instance_id=:i AND action='APPROVE'"
                ),
                dict(i=to_uuid(instance["id"])),
            )
        ).scalar() == 4


async def test_delegation_upper_authority_expiry_revoke_and_audit(api):
    client, _ = api
    _, placement, _, worker_headers, actors = await setup(client)
    await flow(client, placement["org_unit_id"], actors)
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[1]["headers"], cor["id"])
    now = datetime.now(UTC)
    body = dict(
        instance_id=instance["id"],
        level=1,
        original_user_id=actors[0]["id"],
        delegate_user_id=actors[4]["id"],
        valid_from=(now - timedelta(minutes=1)).isoformat(),
        valid_until=(now + timedelta(days=1)).isoformat(),
        reason="Team lead on leave",
    )
    denied = await client.post("/v1/approvals/delegations", headers=actors[0]["headers"], json=body)
    assert denied.status_code == 403
    denied = await client.post(
        "/v1/approvals/delegations", headers=actors[1]["headers"], json={**body, "flow_wide": True}
    )
    assert denied.status_code == 403
    delegation = await ok(
        client, "POST", "/v1/approvals/delegations", headers=actors[1]["headers"], json=body
    )
    inbox = await instance_for(client, actors[4]["headers"], cor["id"])
    assert inbox["can_act"]
    await ok(
        client,
        "POST",
        f"/v1/approvals/delegations/{delegation['id']}/revoke",
        headers=actors[1]["headers"],
    )
    denied = await decide(client, instance, actors[4])
    assert denied.status_code == 403
    future = await ok(
        client,
        "POST",
        "/v1/approvals/delegations",
        headers=actors[1]["headers"],
        json={**body, "valid_from": (now + timedelta(hours=1)).isoformat()},
    )
    denied = await decide(client, instance, actors[4])
    assert denied.status_code == 403
    await ok(
        client,
        "POST",
        f"/v1/approvals/delegations/{future['id']}/revoke",
        headers=actors[1]["headers"],
    )
    delegation = await ok(
        client, "POST", "/v1/approvals/delegations", headers=actors[1]["headers"], json=body
    )
    approved = await decide(client, instance, actors[4])
    assert approved.status_code == 200, approved.text
    audit = approved.json()["history"][-1]
    assert audit["actor_id"] == actors[4]["id"] and audit["details"]["delegation_id"]
    assert audit["details"]["original_user_id"] == actors[0]["id"]
    denied = await decide(client, instance, actors[4])
    assert denied.status_code == 409  # Delegate cannot act at another level.


async def test_employee_selection_survives_team_transfer(api):
    client, _ = api
    admin, placement, worker, worker_headers, actors = await setup(client)
    department = placement["org_unit_id"]
    company = admin["user"]["legal_entities"][0]["id"]
    teams = []
    for name in ["Team A", "Team B"]:
        teams.append(
            await ok(
                client,
                "POST",
                "/v1/org/org-units",
                json=dict(
                    name=name,
                    type="TEAM",
                    parent_id=department,
                    legal_entity_id=company,
                    effective_from="2020-01-01",
                ),
            )
        )
    original = await flow(client, department, actors, stages=4)
    team_flow = await flow(client, teams[0]["id"], [actors[1]], stages=1)
    # A second worker in another team explicitly selects a different workflow.
    other, other_login = await employee(client, company, "OTHER")
    await hire(client, other["id"], {**placement, "org_unit_id": teams[1]["id"]})
    await select_flow(client, other["id"], team_flow)
    # Placement changes leave the original worker’s selection unchanged.
    await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json=dict(
            employment_id=worker["id"],
            type="TRANSFER",
            effective_date="2026-01-01",
            changes={"org_unit_id": teams[0]["id"]},
        ),
    )
    a = await correction(client, worker_headers)
    b = await correction(client, bearer(other_login["access_token"]))
    assert a["total_levels"] == 4 and b["total_levels"] == 1
    request = await instance_for(client, actors[1]["headers"], a["id"])
    assert request["flow_id"] == original["id"]


async def test_configuration_validation_and_concurrent_approval(api):
    client, _ = api
    _, placement, _, worker_headers, actors = await setup(client)
    body = dict(
        name="Bad",
        request_type="CORRECTION",
        steps=[
            dict(name="A", approver_ids=[actors[0]["id"]]),
            dict(name="B", approver_ids=[actors[0]["id"]]),
        ],
    )
    invalid = await client.post("/v1/approvals/flows", json=body)
    assert invalid.status_code == 422
    denied = await client.post("/v1/approvals/flows", headers=worker_headers, json=body)
    assert denied.status_code == 403
    route = await flow(client, placement["org_unit_id"], actors)
    duplicate = await client.post(
        "/v1/approvals/flows",
        json={
            **route,
            "name": "Duplicate",
            "steps": [
                {"name": s["name"], "approver_ids": s["approver_ids"]} for s in route["steps"]
            ],
        },
    )
    assert duplicate.status_code == 201  # Reusable chains of the same type are independent.
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[0]["headers"], cor["id"])
    replies = await asyncio.gather(
        decide(client, instance, actors[0]), decide(client, instance, actors[0])
    )
    assert sorted(r.status_code for r in replies) == [200, 409], [
        (r.status_code, r.text) for r in replies
    ]


async def test_leave_and_cancellation_follow_separate_four_stage_routes(api):
    client, _ = api
    _, placement, _, worker_headers, actors = await setup(client)
    await flow(client, placement["org_unit_id"], actors, kind="LEAVE")
    await flow(client, placement["org_unit_id"], actors, kind="LEAVE_CANCELLATION")
    leave_type = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json=dict(
            name="Annual",
            code="AN",
            days_per_year=120,
            accrual_enabled=True,
            requires_approval=False,
            cancel_requires_approval=False,
        ),
    )
    await ok(client, "POST", "/v1/leave/accrual/run")
    day = date.today() + timedelta(days=3)
    while day.weekday() > 4:
        day += timedelta(days=1)
    app = await ok(
        client,
        "POST",
        "/v1/leave/applications",
        headers=worker_headers,
        json=dict(
            leave_type_id=leave_type["id"],
            from_date=str(day),
            to_date=str(day),
            reason="Dynamic chain",
        ),
    )
    submitted = await ok(
        client,
        "POST",
        f"/v1/leave/applications/{app['id']}/submit",
        headers=worker_headers,
        json={},
    )
    assert submitted["status"] == "PENDING_L1" and submitted["total_levels"] == 4
    instance = await instance_for(client, actors[0]["headers"], app["id"])
    for actor in actors[:4]:
        result = await decide(client, instance, actor)
        assert result.status_code == 200, result.text
    leave = next(
        row
        for row in await ok(client, "GET", "/v1/leave/applications", headers=worker_headers)
        if row["id"] == app["id"]
    )
    assert leave["status"] == "APPROVED" and len(leave["approval_history"]) == 4
    cancellation = await ok(
        client,
        "POST",
        f"/v1/leave/applications/{app['id']}/cancel",
        headers=worker_headers,
        json={"cancel_reason": "Plans changed"},
    )
    assert cancellation["status"] == "CANCEL_PENDING_L1" and cancellation["total_levels"] == 4
    instance = await instance_for(client, actors[0]["headers"], app["id"])
    assert instance["request_type"] == "LEAVE_CANCELLATION"
    for actor in actors[:4]:
        result = await decide(client, instance, actor)
        assert result.status_code == 200, result.text
    leave = next(
        row
        for row in await ok(client, "GET", "/v1/leave/applications", headers=worker_headers)
        if row["id"] == app["id"]
    )
    assert leave["status"] == "CANCELLED" and len(leave["approval_history"]) == 8


async def test_overtime_requires_each_stage_and_restarts_after_changed_minutes(api, monkeypatch):
    from zoneinfo import ZoneInfo

    from hrms.modules.time import router as clock

    client, _ = api
    _, placement, worker, worker_headers, actors = await setup(client)
    await flow(client, placement["org_unit_id"], actors, kind="OVERTIME")
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json=dict(
            name="8h",
            is_default=True,
            timezone="Asia/Kolkata",
            expected_start_time="09:30",
            expected_end_time="18:30",
            break_minutes=60,
            break_auto_deduct=True,
            ot_enabled=True,
            ot_qualifying_minutes=40,
            correction_requires_approval=False,
        ),
    )
    day = date(2026, 9, 28)
    # Overtime starts after the 09:30-18:30 shift: 19:10 is 40 minutes over.
    for kind, h, m in [("IN", 9, 30), ("OUT", 19, 10)]:
        stamp = datetime(2026, 9, 28, h, m, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC)
        monkeypatch.setattr(clock, "now_utc", lambda stamp=stamp: stamp)
        await ok(
            client, "POST", "/v1/time/punches", headers=worker_headers, json={"punch_type": kind}
        )
    inbox = await ok(client, "GET", "/v1/approvals/inbox", headers=actors[0]["headers"])
    instance = next(r for r in inbox if r["request_type"] == "OVERTIME")
    assert instance["request"]["ot_minutes"] == 40
    for index, actor in enumerate(actors[:4]):
        result = await decide(client, instance, actor)
        assert result.status_code == 200, result.text
        days = await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?employment_id={worker['id']}&from_date={day}&to_date={day}",
        )
        assert days[0]["ot_status"] == ("APPROVED" if index == 3 else "PENDING")
    cor = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=worker_headers,
        json=dict(
            work_date=str(day),
            correction_type="PUNCH_OUT",
            requested_punch_out=f"{day}T19:20:00+05:30",
            reason="OT changed",
        ),
    )
    assert cor["status"] == "APPROVED"
    newer = await instance_for(client, actors[0]["headers"], instance["request_id"])
    assert newer["id"] != instance["id"] and newer["request"]["ot_minutes"] == 50
    old_detail = await ok(client, "GET", f"/v1/approvals/requests/{instance['id']}")
    assert old_detail["request"]["ot_minutes"] == 40
    assert old_detail["history"][0]["actor_id"] is None
    old = await decide(client, instance, actors[0])
    assert old.status_code == 409
    for actor in actors[:4]:
        result = await decide(client, newer, actor)
        assert result.status_code == 200, result.text
    for end, expected in [("18:30", 0), ("19:20", 50)]:
        await ok(
            client,
            "POST",
            "/v1/corrections",
            headers=worker_headers,
            json=dict(
                work_date=str(day),
                correction_type="PUNCH_OUT",
                requested_punch_out=f"{day}T{end}:00+05:30",
                reason="OT recomputation",
            ),
        )
        days = await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?employment_id={worker['id']}&from_date={day}&to_date={day}",
        )
        assert days[0]["ot_minutes"] == expected
        if not expected:
            assert days[0]["ot_status"] == "NONE"
        else:
            third = await instance_for(client, actors[0]["headers"], instance["request_id"])
            assert third["id"] not in (instance["id"], newer["id"])
            rejected = await decide(client, third, actors[0], "REJECT")
            assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
            days = await ok(
                client,
                "GET",
                f"/v1/time/attendance-days?employment_id={worker['id']}&from_date={day}&to_date={day}",
            )
            assert days[0]["ot_status"] == "REJECTED"


async def test_tenant_isolation_and_flow_wide_delegation(api):
    client, engine = api
    admin, placement, _, worker_headers, actors = await setup(client)
    route = await flow(client, placement["org_unit_id"], actors)
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[0]["headers"], cor["id"])
    now = datetime.now(UTC)
    body = dict(
        instance_id=instance["id"],
        level=1,
        original_user_id=actors[0]["id"],
        delegate_user_id=actors[4]["id"],
        flow_wide=True,
        valid_from=(now - timedelta(minutes=1)).isoformat(),
        valid_until=(now + timedelta(days=1)).isoformat(),
        reason="Temporary department cover",
    )
    delegation = await ok(client, "POST", "/v1/approvals/delegations", json=body)
    new = await correction(client, worker_headers, "2026-09-29")
    delegated = await instance_for(client, actors[4]["headers"], new["id"])
    assert delegated["can_act"]
    # Expiration is enforced on the server, not just the UI.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE approval_delegations SET valid_until=:d WHERE id=:i"),
            dict(d=now - timedelta(seconds=1), i=to_uuid(delegation["id"])),
        )
    denied = await decide(client, delegated, actors[4])
    assert denied.status_code == 403
    other = await tenant(client)
    denied = await client.get(f"/v1/approvals/requests/{instance['id']}")
    assert denied.status_code == 404
    denied = await client.put(f"/v1/approvals/flows/{route['id']}", json=route)
    assert denied.status_code == 404
    directory = await ok(client, "GET", "/v1/approvals/directory")
    assert all(u["id"] != admin["user"]["id"] for u in directory)
    assert other["user"]["tenant_id"] != admin["user"]["tenant_id"]


async def test_disabled_selection_requires_explicit_replacement_and_rejection(api):
    client, _ = api
    _, placement, worker, worker_headers, actors = await setup(client)
    default = await ok(
        client,
        "POST",
        "/v1/approvals/flows",
        json=dict(
            name="Default",
            request_type="CORRECTION",
            steps=[
                dict(name="Either lead", approver_ids=[a["id"] for a in actors[:2]]),
                dict(name="HR", approver_ids=[actors[2]["id"]]),
            ],
        ),
    )
    department = await flow(client, placement["org_unit_id"], actors)
    await ok(
        client,
        "PUT",
        f"/v1/approvals/flows/{department['id']}",
        json={**department, "enabled": False},
    )
    stale = await client.put(f"/v1/approvals/flows/{department['id']}", json=department)
    assert stale.status_code == 409
    blocked = await client.post(
        "/v1/corrections",
        headers=worker_headers,
        json=dict(
            work_date="2026-09-28",
            correction_type="REGULARIZE",
            requested_punch_in="2026-09-28T09:30:00+05:30",
            requested_punch_out="2026-09-28T18:30:00+05:30",
            reason="Disabled workflow",
        ),
    )
    assert blocked.status_code == 409
    await select_flow(client, worker["id"], default)
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[1]["headers"], cor["id"])
    assert instance["flow_id"] == default["id"] and len(instance["steps"]) == 2
    approved = await decide(client, instance, actors[1])
    assert approved.status_code == 200 and approved.json()["current_level"] == 2
    rejected = await decide(client, instance, actors[2], "REJECT")
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert (await decide(client, instance, actors[0])).status_code == 409
    rows = await ok(client, "GET", "/v1/corrections", headers=worker_headers)
    assert next(row for row in rows if row["id"] == cor["id"])["status"] == "REJECTED"


async def test_inactive_original_can_be_covered_and_cancelled_request_cannot_be_reviewed(api):
    client, engine = api
    _, placement, _, worker_headers, actors = await setup(client)
    await flow(client, placement["org_unit_id"], actors)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE user_accounts SET status='INACTIVE' WHERE id=:id"),
            dict(id=to_uuid(actors[0]["id"])),
        )
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[1]["headers"], cor["id"])
    now = datetime.now(UTC)
    await ok(
        client,
        "POST",
        "/v1/approvals/delegations",
        headers=actors[1]["headers"],
        json=dict(
            instance_id=instance["id"],
            level=1,
            original_user_id=actors[0]["id"],
            delegate_user_id=actors[4]["id"],
            valid_from=(now - timedelta(minutes=1)).isoformat(),
            valid_until=(now + timedelta(days=1)).isoformat(),
            reason="Absent original",
        ),
    )
    assert (await decide(client, instance, actors[4])).status_code == 200
    cancelled = await ok(
        client, "POST", f"/v1/corrections/{cor['id']}/cancel", headers=worker_headers
    )
    assert cancelled["status"] == "CANCELLED"
    assert (await decide(client, instance, actors[1])).status_code == 409


async def test_person_cannot_hold_multiple_levels_using_different_accounts(api):
    client, _ = api
    admin, placement, _, worker_headers, actors = await setup(client)
    # One login per employment is enforced by the database, but one person can hold two
    # employments (and so two logins); they still must not approve at two levels.
    second_job = await ok(
        client,
        "POST",
        "/v1/employees",
        json={
            "person_id": actors[0]["employee"]["person_id"],
            "legal_entity_id": admin["user"]["legal_entities"][0]["id"],
            "employee_number": "ALIAS-" + uuid4().hex[:6],
            "hire_date": "2020-01-01",
            "confirm_new_employment": True,  # deliberately a second employment for the person
        },
    )
    _, _, alias = await make_user(client, second_job["id"])
    body = dict(
        name="Alias chain",
        request_type="CORRECTION",
        steps=[
            dict(name="Lead", approver_ids=[actors[0]["id"]]),
            dict(name="Alias", approver_ids=[alias["id"]]),
        ],
    )
    assert (await client.post("/v1/approvals/flows", json=body)).status_code == 422
    await flow(client, placement["org_unit_id"], actors)
    cor = await correction(client, worker_headers)
    instance = await instance_for(client, actors[1]["headers"], cor["id"])
    now = datetime.now(UTC)
    response = await client.post(
        "/v1/approvals/delegations",
        json=dict(
            instance_id=instance["id"],
            level=2,
            original_user_id=actors[1]["id"],
            delegate_user_id=alias["id"],
            valid_from=(now - timedelta(minutes=1)).isoformat(),
            valid_until=(now + timedelta(days=1)).isoformat(),
            reason="Duplicate person",
        ),
    )
    assert response.status_code == 422


async def test_company_hr_can_create_reusable_flow_but_not_edit_group_flow(api):
    client, _ = api
    admin, placement, _, _, actors = await setup(client)
    group_flow = await flow(client, placement["org_unit_id"], actors)
    company = admin["user"]["legal_entities"][0]["id"]
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company]
    )
    login = await ok(client, "POST", "/v1/auth/login", json=dict(email=email, password=password))
    client.headers.update(bearer(login["access_token"]))
    visible = await ok(client, "GET", "/v1/approvals/flows")
    assert next(f for f in visible if f["id"] == group_flow["id"])["can_manage"] is False
    assert (
        await client.put(f"/v1/approvals/flows/{group_flow['id']}", json=group_flow)
    ).status_code == 403
    body = dict(
        name="Company flow",
        request_type="OVERTIME",
        reusable=True,
        steps=[dict(name="Review", approver_ids=[actors[0]["id"]])],
    )
    own = await ok(client, "POST", "/v1/approvals/flows", json=body)
    assert own["reusable"] is True
    assert (await client.put(f"/v1/approvals/flows/{own['id']}", json=own)).status_code == 200
