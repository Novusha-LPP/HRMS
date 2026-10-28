"""The events feed: what apps hear about, in order, filtered per app, with nothing skipped."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from tests.helpers import hire, ok, org_basics, person_and_employment
from tests.integration_support import make_app, world

pytestmark = [pytest.mark.database, pytest.mark.serial]


async def _feed(client, headers, after=None):
    path = "/v1/integrations/events" + (f"?after={after}" if after else "")
    return await ok(client, "GET", path, headers=headers)


async def test_a_hire_in_hrms_reaches_the_erp_and_the_erp_links_it(api):
    client, _ = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="HR-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    feed = await _feed(client, w.erp)
    assert [e["event"] for e in feed["events"]] == ["employee.hired"]
    event = feed["events"][0]
    assert event["employment_id"] == emp["id"] and event["external_id"] is None
    assert event["employee"]["department"]["name"] == "Ops"
    assert event["employee"]["employee_code"] == "HR-1"

    # The ERP creates its record and links it back.
    linked = (await w.put("ERP-HR-1", expect=200, employment_id=emp["id"])).json()
    assert linked["outcome"] == "LINKED"
    assert (await _feed(client, w.erp, feed["next_cursor"]))["events"] == []


async def test_the_erp_does_not_hear_its_own_changes_but_other_apps_do(api):
    client, _ = api
    w = await world(client)
    _, bi_key = await make_app(client, w.admin, code="BI", kind="READ_ONLY",
                               scopes=["events.read", "employees.read"])
    bi = {"X-API-Key": bi_key["key"]}
    await w.put("S-1", expect=201, **w.new_hire())
    assert (await _feed(client, w.erp))["events"] == []
    bi_feed = await _feed(client, bi)
    assert [e["event"] for e in bi_feed["events"]] == ["employee.hired"]


async def test_hr_changes_arrive_as_updates_with_the_changed_fields(api):
    client, _ = api
    w = await world(client)
    created = (await w.put("U-1", expect=201, **w.new_hire())).json()
    sales = await ok(client, "POST", "/v1/org/org-units", headers=w.admin,
                     json={"name": "Sales", "type": "DEPARTMENT",
                           "legal_entity_id": w.legal_entity, "effective_from": "2020-01-01"})
    await ok(client, "POST", "/v1/personnel-actions", headers=w.admin, json={
        "employment_id": created["employment_id"], "type": "TRANSFER",
        "effective_date": str(date.today()), "changes": {"org_unit_id": sales["id"]},
        "override_reason": "reorganisation"})
    events = (await _feed(client, w.erp))["events"]
    assert [e["event"] for e in events] == ["employee.updated"]
    assert events[0]["changes"]["department"] == {"old": "Ops", "new": "Sales"}
    assert events[0]["external_id"] == "U-1"


async def test_each_app_sees_only_its_fields_and_people(api):
    client, _ = api
    w = await world(client)
    bi_app, bi_key = await make_app(client, w.admin, code="BI", kind="READ_ONLY",
                                    scopes=["events.read", "employees.read"])
    bi = {"X-API-Key": bi_key["key"]}
    draft = await ok(client, "POST", f"/v1/admin/integrations/apps/{bi_app['id']}/profiles",
                     json={}, headers=w.admin)
    settings = draft["settings"]
    settings["outbound"]["data_classes"] = ["BASIC"]
    await ok(client, "PUT", f"/v1/admin/integrations/profiles/{draft['id']}",
             json={"settings": settings}, headers=w.admin)
    await ok(client, "POST", f"/v1/admin/integrations/profiles/{draft['id']}/publish",
             json={"effective_from": str(date.today())}, headers=w.admin)
    await w.put("P-1", expect=201, **w.new_hire(email=f"p1.{id(w)}@example.com",
                                               date_of_birth="1990-01-01"))
    employee = (await _feed(client, bi))["events"][0]["employee"]
    assert "email" not in employee and "date_of_birth" not in employee
    assert employee["first_name"] == "Asha"
    report = await ok(client, "GET", f"/v1/admin/integrations/apps/{bi_app['id']}/report",
                      headers=w.admin)
    assert "email" not in report["fields"] and report["data_classes"] == ["BASIC"]


async def test_a_new_joiner_is_held_until_the_apps_timing(api):
    client, _ = api
    w = await world(client)
    bi_app, bi_key = await make_app(client, w.admin, code="LMS", kind="RECEIVE_ONLY",
                                    scopes=["events.read"])
    lms = {"X-API-Key": bi_key["key"]}
    draft = await ok(client, "POST", f"/v1/admin/integrations/apps/{bi_app['id']}/profiles",
                     json={}, headers=w.admin)
    settings = draft["settings"]
    settings["outbound"]["timing"] = {"mode": "ON_JOIN", "days": 0}
    await ok(client, "PUT", f"/v1/admin/integrations/profiles/{draft['id']}",
             json={"settings": settings}, headers=w.admin)
    await ok(client, "POST", f"/v1/admin/integrations/profiles/{draft['id']}/publish",
             json={"effective_from": str(date.today())}, headers=w.admin)
    # Joins in ten days: the LMS hears nothing yet (but the ERP's own feed is unaffected).
    await w.put("J-1", expect=201,
                **w.new_hire(hire_date=str(date.today() + timedelta(days=10))))
    assert (await _feed(client, lms))["events"] == []
    # Joining moved to yesterday: released at once.
    await w.put("J-1", expect=200, hire_date=str(date.today() - timedelta(days=1)))
    events = (await _feed(client, lms))["events"]
    assert [e["event"] for e in events][0] == "employee.hired"


async def test_the_feed_never_skips_an_event_committed_out_of_order(api):
    """
    Transaction A takes feed position N and stays open; transaction B takes N+1 and commits.
    A reader that saw N+1 and moved past it would never see N. The feed must hold back until
    A commits, then return N before N+1.
    """
    client, admin_engine = api
    w = await world(client)
    tenant_id, app_id = await _ids(admin_engine, w)
    async with admin_engine.connect() as slow:
        tx = await slow.begin()
        await slow.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        event_id = (await slow.execute(text("""
            INSERT INTO integration_events (tenant_id, event_type, payload)
            VALUES (:t, 'employee.updated', CAST(:p AS jsonb)) RETURNING id"""),
            {"t": tenant_id, "p": json.dumps(_payload(w))})).scalar_one()
        await slow.execute(text("""
            INSERT INTO integration_app_events
                (tenant_id, app_id, event_id, seq, assigned_txid, available_at)
            VALUES (:t, :a, :e, nextval('integration_feed_seq'), pg_current_xact_id(), now())"""),
            {"t": tenant_id, "a": app_id, "e": event_id})

        # Meanwhile a later change commits (an HRMS hire, announced to the ERP).
        emp = await person_and_employment(client, w.legal_entity, number="OO-1")
        await hire(client, emp["id"], w.placement, when=date.today())
        held_back = await _feed(client, w.erp)
        assert held_back["events"] == []  # the committed one waits behind the open one

        await tx.commit()
    feed = await _feed(client, w.erp)
    assert [e["event"] for e in feed["events"]] == ["employee.updated", "employee.hired"]


async def _ids(engine, w):
    async with engine.connect() as conn:
        row = (await conn.execute(text("""
            SELECT ca.tenant_id, ca.id FROM connected_apps ca
            JOIN legal_entities le ON le.tenant_id = ca.tenant_id
            WHERE ca.code = 'ERP' AND le.name = :n ORDER BY ca.created_at DESC LIMIT 1"""),
            {"n": w.names["company"]})).one()
    return str(row[0]), str(row[1])


def _payload(w):
    return {"employment_id": "emp_x", "_legal_entity_id": _uuid(w.legal_entity),
            "first_name": "Out", "last_name": "Of order", "external_ids": {}}


def _uuid(typed):
    from hrms.core.ids import to_uuid

    return str(to_uuid(typed))


async def test_a_reader_too_far_behind_is_told_to_resync(api):
    client, admin_engine = api
    w = await world(client)
    tenant_id, app_id = await _ids(admin_engine, w)
    async with admin_engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO integration_cursors (tenant_id, app_id, purged_through)
            VALUES (:t, :a, 50)
            ON CONFLICT (tenant_id, app_id) DO UPDATE SET purged_through = 50"""),
            {"t": tenant_id, "a": app_id})
    response = await client.get("/v1/integrations/events?after=c_000000000010", headers=w.erp)
    assert response.status_code == 410 and response.json()["code"] == "RESYNC_REQUIRED"
    assert response.headers["x-resync-cursor"].startswith("c_")
    full = await ok(client, "GET", "/v1/integrations/employees", headers=w.erp)
    assert full["events_cursor"].startswith("c_")


async def test_retention_job_purges_old_events_and_readers_behind_it_resync(api):
    from hrms.jobs import runner

    client, admin_engine = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="RET-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    tenant_id, _ = await _ids(admin_engine, w)
    async with admin_engine.begin() as conn:
        await conn.execute(text("""UPDATE integration_events SET occurred_at = now() - interval
                                   '40 days' WHERE tenant_id = :t"""), {"t": tenant_id})
    assert await runner.run_job("integrations")
    behind = await client.get("/v1/integrations/events", headers=w.erp)
    assert behind.status_code == 410 and behind.json()["code"] == "RESYNC_REQUIRED"
    resumed = await _feed(client, w.erp, behind.headers["x-resync-cursor"])
    assert resumed["events"] == []


async def test_health_gauges_report_lag_and_unlinked_hires(api):
    from hrms.core.metrics import _integration_health, _IntegrationHealth

    client, admin_engine = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="GAUGE-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    tenant_id, _ = await _ids(admin_engine, w)
    async with admin_engine.begin() as conn:
        await conn.execute(text("""UPDATE integration_events SET occurred_at = now() - interval
                                   '2 days' WHERE tenant_id = :t"""), {"t": tenant_id})
    rows = [r for r in await _integration_health() if r["app"] == "ERP" and r["feed_lag"]]
    mine = [r for r in rows if r["unlinked_hires"] == 1]
    assert mine and mine[0]["next_key_expiry"] is not None
    names = {family.name for family in _IntegrationHealth(mine).collect()}
    assert "hrms_integration_feed_lag_events" in names


async def test_a_key_limited_to_one_company_hears_nothing_about_another(api):
    client, _ = api
    w = await world(client)
    other = await ok(client, "POST", "/v1/org/legal-entities", headers=w.admin,
                     json={"name": "Second Co " + str(id(w))[-4:], "country_code": "IN"})
    other_place = await org_basics(client, other["id"])
    _, limited_key = await make_app(client, w.admin, code="CRM", kind="READ_ONLY",
                                    scopes=["events.read"], legal_entity_ids=[w.legal_entity])
    crm = {"X-API-Key": limited_key["key"]}
    mine = await person_and_employment(client, w.legal_entity, number="LIM-1")
    theirs = await person_and_employment(client, other["id"], number="LIM-2")
    await hire(client, mine["id"], w.placement, when=date.today())
    await hire(client, theirs["id"], other_place, when=date.today())
    events = (await _feed(client, crm))["events"]
    assert [e["employment_id"] for e in events] == [mine["id"]]


async def test_onboarding_shows_each_app_and_ticks_itself(api):
    client, _ = api
    w = await world(client)
    _, bi_key = await make_app(client, w.admin, code="LMS", kind="READ_ONLY",
                               scopes=["events.read"])
    lms = {"X-API-Key": bi_key["key"]}
    emp = await person_and_employment(client, w.legal_entity, number="ONB-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    case = await ok(client, "POST", "/v1/onboarding/cases", headers=w.admin,
                    json={"employment_id": emp["id"], "hire_date": str(date.today())})

    def app_tasks(c):
        return {i["title"]: i["status"] for i in c["items"] if i["title"].startswith("Set up in")}

    assert app_tasks(case) == {"Set up in ERP system": "PENDING", "Set up in LMS system": "PENDING"}

    await w.put("ONB-ERP-1", expect=200, employment_id=emp["id"])  # the ERP links them
    first = await _feed(client, lms)                                  # the LMS reads the hire
    await _feed(client, lms, first["next_cursor"])                    # ...and confirms it
    case = await ok(client, "GET", f"/v1/onboarding/cases/{case['id']}", headers=w.admin)
    assert app_tasks(case) == {"Set up in ERP system": "COMPLETED",
                               "Set up in LMS system": "COMPLETED"}
