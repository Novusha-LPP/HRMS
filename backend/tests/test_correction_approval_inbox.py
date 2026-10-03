"""The common inbox covers policy corrections without bypassing domain authority."""

from datetime import datetime

import pytest

from tests.helpers import bearer, make_user, ok, tenant
from tests.test_configurable_approvals import correction, flow, instance_for, setup

pytestmark = pytest.mark.database


async def policy(client, levels=1):
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json=dict(
            name="Correction policy",
            is_default=True,
            timezone="Asia/Kolkata",
            correction_requires_approval=True,
            correction_approval_levels=levels,
        ),
    )


@pytest.mark.parametrize("action", ["APPROVE", "REJECT"])
async def test_policy_correction_review_in_shared_inbox(api, action):
    client, _ = api
    _, _, worker, worker_headers, actors = await setup(client)
    await policy(client)
    cor = await correction(client, worker_headers)
    request = await instance_for(client, client.headers, cor["id"])
    assert request["approval_mode"] == "POLICY" and request["id"] == cor["id"]
    assert request["can_act"] and request["delegable_levels"] == []
    owned = await instance_for(client, worker_headers, cor["id"])
    assert not owned["can_act"]
    assert await ok(client, "GET", "/v1/approvals/inbox", headers=actors[0]["headers"]) == []
    foreign_detail = await client.get(
        f"/v1/approvals/requests/{request['id']}", headers=actors[0]["headers"]
    )
    assert foreign_detail.status_code == 403
    own_decision = await client.post(
        f"/v1/approvals/requests/{request['id']}/decision",
        headers=worker_headers,
        json=dict(action=action),
    )
    assert own_decision.status_code == 403
    reviewed = await ok(
        client,
        "POST",
        f"/v1/approvals/requests/{request['id']}/decision",
        json=dict(action=action, comments="Shared inbox review"),
    )
    assert reviewed["status"] == ("APPROVED" if action == "APPROVE" else "REJECTED")
    assert reviewed["history"][0]["details"]["comments"] == "Shared inbox review"
    assert not reviewed["can_act"]
    assert await ok(client, "GET", "/v1/approvals/inbox") == []
    records = await ok(client, "GET", f"/v1/corrections?employment_id={worker['id']}")
    assert records[0]["status"] == reviewed["status"]
    attendance = await ok(
        client,
        "GET",
        f"/v1/time/attendance-days?employment_id={worker['id']}&from_date=2026-09-28&to_date=2026-09-28",
    )
    if action == "APPROVE":
        assert attendance
        assert datetime.fromisoformat(attendance[0]["first_punch_in"]) == datetime.fromisoformat(
            cor["requested_punch_in"]
        )
    else:
        assert attendance == []
    repeated = await client.post(
        f"/v1/approvals/requests/{request['id']}/decision", json=dict(action=action)
    )
    assert repeated.status_code in (400, 409)


async def test_policy_correction_levels_cancellation_and_tenant_isolation(api):
    client, _ = api
    _, _, _, worker_headers, _ = await setup(client)
    await policy(client, levels=2)
    email, password, _ = await make_user(client, role="HR_MANAGER", scope_type="ALL")
    reviewer = await ok(client, "POST", "/v1/auth/login", json=dict(email=email, password=password))
    reviewer_headers = bearer(reviewer["access_token"])
    cor = await correction(client, worker_headers)
    request = await instance_for(client, client.headers, cor["id"])
    first = await ok(
        client,
        "POST",
        f"/v1/approvals/requests/{request['id']}/decision",
        json=dict(action="APPROVE"),
    )
    assert first["status"] == "PENDING" and first["current_level"] == 2
    assert not first["can_act"]
    repeated = await client.post(
        f"/v1/approvals/requests/{request['id']}/decision", json=dict(action="APPROVE")
    )
    assert repeated.status_code == 409
    final = await ok(
        client,
        "POST",
        f"/v1/approvals/requests/{request['id']}/decision",
        headers=reviewer_headers,
        json=dict(action="APPROVE"),
    )
    assert final["status"] == "APPROVED" and len(final["history"]) == 2
    cancelled = await correction(client, worker_headers, "2026-09-29")
    await ok(client, "POST", f"/v1/corrections/{cancelled['id']}/cancel", headers=worker_headers)
    assert await ok(client, "GET", "/v1/approvals/inbox") == []
    await tenant(client)
    foreign = await client.get(f"/v1/approvals/requests/{request['id']}")
    assert foreign.status_code == 404
    foreign_decision = await client.post(
        f"/v1/approvals/requests/{request['id']}/decision", json=dict(action="APPROVE")
    )
    assert foreign_decision.status_code == 404


async def test_configured_correction_appears_once_and_cannot_use_policy_path(api):
    client, _ = api
    _, placement, _, worker_headers, actors = await setup(client)
    await policy(client)
    await flow(client, placement["org_unit_id"], actors)
    cor = await correction(client, worker_headers)
    requests = await ok(client, "GET", "/v1/approvals/inbox")
    matching = [r for r in requests if r["request_id"] == cor["id"]]
    assert len(matching) == 1 and matching[0]["approval_mode"] == "FLOW"
    policy_detail = await client.get(f"/v1/approvals/requests/{cor['id']}")
    assert policy_detail.status_code == 404
    bypass = await client.post(
        f"/v1/approvals/requests/{cor['id']}/decision", json=dict(action="APPROVE")
    )
    assert bypass.status_code == 404
    review = await ok(
        client,
        "POST",
        f"/v1/approvals/requests/{matching[0]['id']}/decision",
        headers=actors[0]["headers"],
        json=dict(action="APPROVE"),
    )
    assert review["current_level"] == 2
