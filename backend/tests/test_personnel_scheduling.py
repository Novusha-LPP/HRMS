"""Scheduled personnel actions: conflicts refused, failures contained, actions cancellable."""

import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import (
    bearer,
    hire,
    make_user,
    ok,
    org_basics,
    person_and_employment,
    tenant,
)

pytestmark = pytest.mark.database

TODAY = date.today()


def days(n):
    return str(TODAY + timedelta(days=n))


async def _placed(client, le, placement):
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    return emp


def _schedule(client, emp, kind, when, changes=None, **kw):
    body = {"employment_id": emp["id"], "type": kind, "effective_date": when}
    if changes:
        body["changes"] = changes
    return client.post("/v1/personnel-actions", json=body, **kw)


async def test_conflicting_schedules_are_refused_up_front(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)

    leaving = await _placed(client, le, placement)
    assert (await _schedule(client, leaving, "SEPARATION", days(10))).status_code == 201
    # Nothing but a rehire can follow a scheduled separation …
    after = await _schedule(client, leaving, "TRANSFER", days(20), placement)
    assert after.status_code == 409 and "separation is already scheduled" in after.json()["detail"]
    assert (await _schedule(client, leaving, "PROMOTION", days(10), placement)).status_code == 409
    # … but an earlier change, and a rehire, are fine.
    assert (await _schedule(client, leaving, "TRANSFER", days(5), placement)).status_code == 201
    assert (await _schedule(client, leaving, "REHIRE", days(30), placement)).status_code == 201

    moving = await _placed(client, le, placement)
    assert (await _schedule(client, moving, "TRANSFER", days(5), placement)).status_code == 201
    # A separation can't be entered ahead of an action it would strand.
    early = await _schedule(client, moving, "SEPARATION", days(3))
    assert early.status_code == 409 and "on or after this separation" in early.json()["detail"]
    assert (await _schedule(client, moving, "SEPARATION", days(6))).status_code == 201


async def _fast_forward(engine, tenant_id, **new_dates):
    """Pretend the calendar reached these actions' dates (keyed by type)."""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE assignments SET effective_from = :d WHERE tenant_id = :t"),
            {"d": TODAY - timedelta(days=60), "t": tenant_id},
        )
        for kind, offset in new_dates.items():
            await conn.execute(
                text("""UPDATE personnel_actions SET effective_date = :d
                        WHERE tenant_id = :t AND type = :k AND status = 'SCHEDULED'"""),
                {"d": TODAY + timedelta(days=offset), "t": tenant_id, "k": kind},
            )


async def test_an_action_that_cannot_apply_is_parked_and_never_breaks_requests(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    leaver = await _placed(client, le, placement)
    mover = await _placed(client, le, placement)
    bystander = await _placed(client, le, placement)
    by_email, by_pw, _ = await make_user(client, bystander["id"])
    bystander_token = bearer(
        (
            await ok(
                client, "POST", "/v1/auth/login", json={"identifier": by_email, "password": by_pw}
            )
        )["access_token"]
    )
    new_unit = (
        await ok(
            client,
            "POST",
            "/v1/org/org-units",
            json={
                "name": "Sales",
                "type": "DEPARTMENT",
                "legal_entity_id": le,
                "effective_from": "2020-01-01",
            },
        )
    )["id"]

    assert (await _schedule(client, leaver, "SEPARATION", days(10))).status_code == 201
    assert (
        await _schedule(client, mover, "TRANSFER", days(10), {**placement, "org_unit_id": new_unit})
    ).status_code == 201
    # A TRANSFER after a SEPARATION is refused by the API now — insert it the way old data
    # (or a race) could have, to prove the applier survives it regardless.
    async with engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO personnel_actions
                    (tenant_id, id, employment_id, type, effective_date, changes, status,
                     submitted_at, recorded_at, version)
                    VALUES (:t, :id, :e, 'TRANSFER', :d, CAST(:c AS jsonb), 'SCHEDULED',
                            now(), now(), 0)"""),
            {
                "t": tid,
                "id": uuid4(),
                "e": to_uuid(leaver["id"]),
                "d": TODAY + timedelta(days=20),
                "c": json.dumps(placement),
            },
        )
    await _fast_forward(engine, tid, SEPARATION=-2, TRANSFER=-1)

    # The day arrives. Unrelated users' requests must be unaffected …
    for headers in ({}, bystander_token):
        r = await client.get("/v1/auth/me", headers=headers)
        assert r.status_code == 200, r.text
    # … the impossible action is parked with its reason, the rest were applied.
    actions = {
        a["type"]: a
        for a in await ok(client, "GET", f"/v1/personnel-actions?employment_id={leaver['id']}")
    }
    assert actions["SEPARATION"]["status"] == "APPLIED"
    assert actions["TRANSFER"]["status"] == "FAILED"
    assert "No active assignment" in actions["TRANSFER"]["failure_reason"]
    assert (await ok(client, "GET", f"/v1/employees/{leaver['id']}"))[
        "employment_state"
    ] == "SEPARATED"
    moved = await ok(client, "GET", f"/v1/employees/{mover['id']}")
    assert moved["org_unit_id"] == new_unit  # a healthy action in the same batch still applied

    # HR can see it, cancel it, and cannot cancel history.
    cancelled = await ok(
        client, "POST", f"/v1/personnel-actions/{actions['TRANSFER']['id']}/cancel"
    )
    assert cancelled["status"] == "CANCELLED"
    for action_id in (actions["TRANSFER"]["id"], actions["SEPARATION"]["id"]):
        again = await client.post(f"/v1/personnel-actions/{action_id}/cancel")
        assert again.status_code == 409


async def test_cancelling_a_scheduled_action_stops_it_and_respects_scope(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "B", "country_code": "IN"})
    )["id"]
    placement = await org_basics(client, company_a)
    emp = await _placed(client, company_a, placement)
    scheduled = await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={"employment_id": emp["id"], "type": "SEPARATION", "effective_date": days(10)},
    )

    hr_b_email, hr_b_pw, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_b]
    )
    hr_b = bearer(
        (
            await ok(
                client,
                "POST",
                "/v1/auth/login",
                json={"identifier": hr_b_email, "password": hr_b_pw},
            )
        )["access_token"]
    )
    assert (
        await client.post(f"/v1/personnel-actions/{scheduled['id']}/cancel", headers=hr_b)
    ).status_code == 403

    cancelled = await ok(client, "POST", f"/v1/personnel-actions/{scheduled['id']}/cancel")
    assert cancelled["status"] == "CANCELLED"
    async with engine.begin() as conn:  # even once its date has passed, it must not apply
        await conn.execute(
            text("UPDATE personnel_actions SET effective_date = :d WHERE tenant_id = :t"),
            {"d": TODAY - timedelta(days=1), "t": tid},
        )
    assert (await ok(client, "GET", f"/v1/employees/{emp['id']}"))[
        "employment_state"
    ] != "SEPARATED"
