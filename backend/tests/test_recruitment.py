"""Recruitment over real HTTP with row-level security: requisitions, pipeline, resumes."""

import pytest

from tests.helpers import bearer, employee, hire, ok, org_basics, tenant

pytestmark = pytest.mark.database

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def opening_body(unit, **extra):
    body = dict(
        title="Senior Backend Engineer",
        org_unit_id=unit,
        employment_type="FULL_TIME",
        work_mode="HYBRID",
        positions=1,
        priority="HIGH",
        reason="NEW_ROLE",
        min_experience_years=4,
        max_experience_years=8,
        salary_min=1800000,
        salary_max=2600000,
        description="Own the payments platform end to end.",
        skills=["Python", "PostgreSQL", "python"],
    )
    return {**body, **extra}


async def setup(client):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    hod, hod_login = await employee(client, company, "HOD")
    await hire(client, hod["id"], placement)
    await ok(
        client,
        "PATCH",
        f"/v1/org/org-units/{placement['org_unit_id']}",
        json={"head_employment_id": hod["id"]},
    )
    other, other_login = await employee(client, company, "OTHER")
    await hire(client, other["id"], placement)
    return dict(
        admin=admin,
        company=company,
        unit=placement["org_unit_id"],
        placement=placement,
        hod=hod,
        hod_headers=bearer(hod_login["access_token"]),
        other_headers=bearer(other_login["access_token"]),
    )


async def open_opening(client, ctx, **extra):
    created = await ok(
        client,
        "POST",
        "/v1/recruitment/openings?submit=true",
        headers=ctx["hod_headers"],
        json=opening_body(ctx["unit"], **extra),
    )
    assert created["status"] == "PENDING_APPROVAL" and created["approval_mode"] == "HR"
    approved = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{created['id']}/decision",
        json={"action": "APPROVE", "comments": "Budgeted"},
    )
    assert approved["status"] == "OPEN"
    return approved


async def test_department_head_raises_and_hr_approves(api):
    client, _ = api
    ctx = await setup(client)
    me = await ok(client, "GET", "/v1/auth/me", headers=ctx["hod_headers"])
    assert "recruitment.request" in me["permissions"]
    other_me = await ok(client, "GET", "/v1/auth/me", headers=ctx["other_headers"])
    assert "recruitment.request" not in other_me["permissions"]

    access = await ok(client, "GET", "/v1/recruitment/access", headers=ctx["hod_headers"])
    assert access["can_request"] and not access["can_manage"]
    assert [d["id"] for d in access["departments"]] == [ctx["unit"]]

    denied = await client.post(
        "/v1/recruitment/openings",
        headers=ctx["other_headers"],
        json=opening_body(ctx["unit"]),
    )
    assert denied.status_code == 403

    draft = await ok(
        client,
        "POST",
        "/v1/recruitment/openings",
        headers=ctx["hod_headers"],
        json=opening_body(ctx["unit"]),
    )
    assert draft["status"] == "DRAFT" and draft["code"].startswith("REQ-")
    assert draft["skills"] == ["Python", "PostgreSQL"]
    assert draft["hiring_manager_employment_id"] == ctx["hod"]["id"]
    assert draft["can_edit"] and draft["can_submit"] and not draft["can_manage"]

    # Not visible to a colleague who neither raised nor leads it.
    hidden = await client.get(
        f"/v1/recruitment/openings/{draft['id']}", headers=ctx["other_headers"]
    )
    assert hidden.status_code == 404

    bad = await client.post(
        "/v1/recruitment/openings",
        headers=ctx["hod_headers"],
        json=opening_body(ctx["unit"], salary_min=10, salary_max=5),
    )
    assert bad.status_code == 422

    submitted = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{draft['id']}/submit",
        headers=ctx["hod_headers"],
    )
    assert submitted["status"] == "PENDING_APPROVAL" and submitted["approval_mode"] == "HR"
    assert not submitted["can_decide"] and submitted["can_withdraw"]
    self_approval = await client.post(
        f"/v1/recruitment/openings/{draft['id']}/decision",
        headers=ctx["hod_headers"],
        json={"action": "APPROVE"},
    )
    assert self_approval.status_code == 403
    locked = await client.put(
        f"/v1/recruitment/openings/{draft['id']}",
        headers=ctx["hod_headers"],
        json={**opening_body(ctx["unit"]), "version": submitted["version"]},
    )
    assert locked.status_code == 409

    no_reason = await client.post(
        f"/v1/recruitment/openings/{draft['id']}/decision", json={"action": "REJECT"}
    )
    assert no_reason.status_code == 422
    rejected = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{draft['id']}/decision",
        json={"action": "REJECT", "comments": "Not budgeted this quarter"},
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decision_comment"] == "Not budgeted this quarter"

    # The requester revises and resubmits; HR approves.
    revised = await ok(
        client,
        "PUT",
        f"/v1/recruitment/openings/{draft['id']}",
        headers=ctx["hod_headers"],
        json={**opening_body(ctx["unit"], positions=2), "version": rejected["version"]},
    )
    assert revised["positions"] == 2
    await ok(
        client, "POST", f"/v1/recruitment/openings/{draft['id']}/submit", headers=ctx["hod_headers"]
    )
    approved = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{draft['id']}/decision",
        json={"action": "APPROVE"},
    )
    assert approved["status"] == "OPEN" and approved["approved_by_name"]

    events = await ok(
        client, "GET", f"/v1/recruitment/openings/{draft['id']}/events", headers=ctx["hod_headers"]
    )
    actions = [e["action"] for e in events]
    assert {"CREATED", "SUBMITTED", "REJECTED", "UPDATED", "APPROVED"} <= set(actions)

    mine = await ok(client, "GET", "/v1/recruitment/openings?mine=true", headers=ctx["hod_headers"])
    assert [o["id"] for o in mine] == [draft["id"]]
    assert await ok(client, "GET", "/v1/recruitment/openings", headers=ctx["other_headers"]) == []


async def test_pipeline_resume_feedback_and_hire(api):
    client, _ = api
    ctx = await setup(client)
    opening = await open_opening(client, ctx)
    stages = await ok(client, "GET", "/v1/recruitment/stages")
    by_name = {s["name"]: s for s in stages}
    assert by_name["Onboarding"]["category"] == "HIRED"

    candidate = dict(
        first_name="Asha",
        last_name="Verma",
        email="Asha.Verma@example.com",
        phone="+91 90000 00000",
        current_company="Acme",
        total_experience_years=6,
        current_ctc=1500000,
        expected_ctc=2200000,
        notice_period_days=30,
        source="LINKEDIN",
        links=[
            {"type": "LINKEDIN", "url": "linkedin.com/in/asha"},
            {"type": "GITHUB", "url": "https://github.com/asha"},
        ],
        skills=["Go", "Kubernetes"],
    )
    bad_link = await client.post(
        f"/v1/recruitment/openings/{opening['id']}/applications",
        json={"candidate": {**candidate, "links": [{"type": "OTHER", "url": "ftp://x"}]}},
    )
    assert bad_link.status_code == 422
    app = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{opening['id']}/applications",
        json={"candidate": candidate, "note": "Strong referral"},
    )
    assert app["stage_name"] == "Applied" and app["notes_count"] == 1
    assert app["candidate"]["email"] == "asha.verma@example.com"
    assert app["candidate"]["links"][0]["url"] == "https://linkedin.com/in/asha"
    duplicate = await client.post(
        f"/v1/recruitment/openings/{opening['id']}/applications",
        json={"candidate": candidate},
    )
    assert duplicate.status_code == 409
    candidate_id = app["candidate"]["id"]

    # Resume: type sniffed, stored encrypted, served back intact.
    rejected_type = await client.post(
        f"/v1/recruitment/candidates/{candidate_id}/resume",
        files={"file": ("resume.txt", b"plain text", "text/plain")},
    )
    assert rejected_type.status_code == 415
    uploaded = await ok(
        client,
        "POST",
        f"/v1/recruitment/candidates/{candidate_id}/resume",
        files={"file": ("Asha CV.pdf", PDF, "application/pdf")},
    )
    assert uploaded["resume"]["file_name"] == "Asha_CV.pdf"
    resume = await client.get(f"/v1/recruitment/candidates/{candidate_id}/resume?inline=true")
    assert resume.status_code == 200 and resume.content == PDF
    assert resume.headers["content-disposition"].startswith("inline")

    # The department head follows the pipeline, without pay history, and leaves feedback.
    hod_view = await ok(
        client,
        "GET",
        f"/v1/recruitment/openings/{opening['id']}/applications",
        headers=ctx["hod_headers"],
    )
    assert hod_view[0]["candidate"]["expected_ctc"] is None
    assert hod_view[0]["candidate"]["links"]
    hod_resume = await client.get(
        f"/v1/recruitment/candidates/{candidate_id}/resume", headers=ctx["hod_headers"]
    )
    assert hod_resume.status_code == 200
    noted = await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/notes",
        headers=ctx["hod_headers"],
        json={"body": "Great system design round"},
    )
    assert noted["notes_count"] == 2 and not noted["can_manage"]
    hod_move = await client.post(
        f"/v1/recruitment/applications/{app['id']}/move",
        headers=ctx["hod_headers"],
        json={"stage_id": by_name["Shortlisted"]["id"]},
    )
    assert hod_move.status_code == 403

    # Others can see neither the candidate nor their resume.
    for path in (
        f"/v1/recruitment/applications/{app['id']}",
        f"/v1/recruitment/candidates/{candidate_id}/resume",
    ):
        response = await client.get(path, headers=ctx["other_headers"])
        assert response.status_code == 404, path
    pool = await client.get("/v1/recruitment/candidates", headers=ctx["hod_headers"])
    assert pool.status_code == 403

    # HR moves the candidate through the pipeline.
    moved = await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Shortlisted"]["id"], "expected_version": app["version"]},
    )
    assert moved["stage_name"] == "Shortlisted"
    stale = await client.post(
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Interview"]["id"], "expected_version": app["version"]},
    )
    assert stale.status_code == 409
    no_reason = await client.post(
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Rejected"]["id"]},
    )
    assert no_reason.status_code == 422
    rated = await ok(
        client, "PATCH", f"/v1/recruitment/applications/{app['id']}", json={"rating": 4}
    )
    assert rated["rating"] == 4

    hired = await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Onboarding"]["id"]},
    )
    assert hired["can_hire"] and hired["hire_defaults"]["org_unit_id"] == ctx["unit"]
    detail = await ok(client, "GET", f"/v1/recruitment/openings/{opening['id']}")
    assert detail["status"] == "FILLED" and detail["hired"] == 1

    # Linking the employee created from the candidate.
    emp, _ = await employee(client, ctx["company"], "NEWHIRE")
    linked = await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/hire",
        json={"employment_id": emp["id"]},
    )
    assert linked["hired_employment_id"] == emp["id"] and not linked["can_hire"]
    final = await client.post(
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Interview"]["id"]},
    )
    assert final.status_code == 409

    pool = await ok(client, "GET", "/v1/recruitment/candidates?q=kubernetes")
    assert pool["total"] == 1 and pool["items"][0]["applications"][0]["stage_name"] == "Onboarding"
    timeline = await ok(client, "GET", f"/v1/recruitment/applications/{app['id']}")
    actions = {e["action"] for e in timeline["events"]}
    assert {"APPLICATION_ADDED", "NOTE", "STAGE_CHANGED", "RESUME_UPLOADED", "HIRED"} <= actions


async def test_filled_reopens_and_stage_configuration(api):
    client, _ = api
    ctx = await setup(client)
    opening = await open_opening(client, ctx)
    stages = await ok(client, "GET", "/v1/recruitment/stages")
    by_name = {s["name"]: s for s in stages}
    app = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{opening['id']}/applications",
        json={"candidate": {"first_name": "Ravi", "last_name": "K", "source": "REFERRAL"}},
    )
    await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Onboarding"]["id"]},
    )
    assert (await ok(client, "GET", f"/v1/recruitment/openings/{opening['id']}"))[
        "status"
    ] == "FILLED"
    await ok(
        client,
        "POST",
        f"/v1/recruitment/applications/{app['id']}/move",
        json={"stage_id": by_name["Withdrawn"]["id"], "reason": "Accepted a counter-offer"},
    )
    reopened = await ok(client, "GET", f"/v1/recruitment/openings/{opening['id']}")
    assert reopened["status"] == "OPEN" and reopened["hired"] == 0

    held = await ok(
        client,
        "POST",
        f"/v1/recruitment/openings/{opening['id']}/status",
        json={"status": "ON_HOLD", "reason": "Budget review"},
    )
    assert held["status"] == "ON_HOLD" and held["close_reason"] == "Budget review"
    blocked = await client.post(
        f"/v1/recruitment/openings/{opening['id']}/applications",
        json={"candidate": {"first_name": "Late", "last_name": "Comer"}},
    )
    assert blocked.status_code == 409

    # Rename, add, reorder and drop stages; outcome of a used stage is fixed.
    edited = [
        {**s, "name": "Phone screen" if s["name"] == "Screening" else s["name"]}
        for s in stages
        if s["name"] != "Offer released"
    ]
    edited.insert(4, {"name": "Assignment", "category": "ACTIVE", "color": "info"})
    saved = await ok(client, "PUT", "/v1/recruitment/stages", json={"stages": edited})
    active = [s["name"] for s in saved if s["is_active"]]
    assert active[:5] == ["Applied", "Phone screen", "Shortlisted", "Interview", "Assignment"]
    archived = [s for s in saved if not s["is_active"]]
    assert len(archived) == 1 and archived[0]["name"].startswith("Offer released")
    used = [
        {**s, "category": "ACTIVE" if s["name"] == "Withdrawn" else s["category"]}
        for s in saved
        if s["is_active"]
    ]
    conflict = await client.put("/v1/recruitment/stages", json={"stages": used})
    assert conflict.status_code in (409, 422)
    hod_edit = await client.put(
        "/v1/recruitment/stages", headers=ctx["hod_headers"], json={"stages": edited}
    )
    assert hod_edit.status_code == 403


async def test_configured_flow_routes_requisition_to_approvers(api):
    client, _ = api
    ctx = await setup(client)
    approver, approver_login = await employee(client, ctx["company"], "APPROVER")
    approver_headers = bearer(approver_login["access_token"])
    me = await ok(client, "GET", "/v1/auth/me", headers=approver_headers)
    flow = await ok(
        client,
        "POST",
        "/v1/approvals/flows",
        json=dict(
            name="Hiring approval",
            request_type="JOB_REQUISITION",
            reusable=True,
            steps=[dict(name="Finance", approver_ids=[me["id"]])],
        ),
    )
    current = await ok(client, "GET", f"/v1/approvals/employees/{ctx['hod']['id']}/flows")
    previous = next(
        (a for a in current["assignments"] if a["request_type"] == "JOB_REQUISITION"), None
    )
    await ok(
        client,
        "PUT",
        f"/v1/approvals/employees/{ctx['hod']['id']}/flows/JOB_REQUISITION",
        json=dict(flow_id=flow["id"], version=previous["version"] if previous else 0),
    )
    created = await ok(
        client,
        "POST",
        "/v1/recruitment/openings?submit=true",
        headers=ctx["hod_headers"],
        json=opening_body(ctx["unit"]),
    )
    assert created["approval_mode"] == "FLOW" and created["approval_instance_id"]
    # HR's direct approval doesn't bypass the configured route.
    bypass = await client.post(
        f"/v1/recruitment/openings/{created['id']}/decision", json={"action": "APPROVE"}
    )
    assert bypass.status_code == 403

    inbox = await ok(client, "GET", "/v1/approvals/inbox", headers=approver_headers)
    item = next(r for r in inbox if r["request_id"] == created["id"])
    assert item["request_type"] == "JOB_REQUISITION" and item["request"]["code"] == created["code"]
    # The approver can read the opening they are deciding on.
    seen = await ok(
        client, "GET", f"/v1/recruitment/openings/{created['id']}", headers=approver_headers
    )
    assert seen["can_decide"]
    await ok(
        client,
        "POST",
        f"/v1/approvals/requests/{item['id']}/decision",
        headers=approver_headers,
        json={"action": "APPROVE", "comments": "Within budget"},
    )
    final = await ok(client, "GET", f"/v1/recruitment/openings/{created['id']}")
    assert final["status"] == "OPEN" and final["approval_mode"] == "FLOW"
