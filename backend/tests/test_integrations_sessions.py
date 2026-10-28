"""Employee sessions a connected app obtains: self-service through the app's screens."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy import text

from hrms.main import app as hrms_app
from hrms.modules.integrations.session_policy import SESSION_ROUTES
from tests.helpers import client_from, ok
from tests.integration_support import world

pytestmark = pytest.mark.database


async def _session(client, w, external_id):
    issued = await ok(client, "POST", "/v1/integrations/sessions",
                      json={"external_id": external_id}, headers=w.erp)
    return {"Authorization": "Bearer " + issued["access_token"]}, issued


async def test_an_employee_punches_through_the_app(api):
    client, admin_engine = api
    w = await world(client)
    await w.put("S-1", expect=201, **w.new_hire(email=f"s1.{uuid4().hex[:8]}@example.com"))
    me, issued = await _session(client, w, "S-1")
    assert issued["roles"] == ["EMPLOYEE"] and issued["expires_in"] == 3600
    async with client_from("10.5.0.1") as erp_server:
        # The employee was given the default password and must change it before signing in to
        # HRMS directly, but authenticated in the ERP, so the session works.
        punch = await ok(erp_server, "POST", "/v1/time/punches",
                         json={"punch_type": "IN", "source": "WEB"}, headers=me)
        profile = await ok(erp_server, "GET", "/v1/persons/me", headers=me)
    assert profile["legal_first_name"] == "Asha"
    from hrms.core.ids import to_uuid

    async with admin_engine.connect() as conn:
        row = (await conn.execute(text("SELECT source, source_system FROM punches WHERE id = :id"),
                                  {"id": to_uuid(punch["id"])})).one()
    # Recorded as made through the app, whatever the request body claimed.
    assert tuple(row) == ("INTEGRATION", "ERP")


async def test_an_app_session_only_reaches_self_service(api):
    client, _ = api
    w = await world(client)
    await w.put("S-2", expect=201, **w.new_hire())
    me, _ = await _session(client, w, "S-2")
    async with client_from("10.5.0.2") as erp_server:
        for method, path in (("GET", "/v1/employees"), ("GET", "/v1/users"),
                             ("POST", "/v1/auth/mfa/enroll")):
            response = await erp_server.request(method, path, headers=me)
            assert response.status_code == 403, (method, path)
            assert response.json()["code"] == "NOT_AVAILABLE_VIA_INTEGRATION"


async def test_an_app_session_never_carries_hr_or_admin_rights(api):
    client, admin_engine = api
    w = await world(client)
    created = (await w.put("S-3", expect=201, **w.new_hire(role="MANAGER"))).json()
    # Someone also granted this login HR rights in HRMS.
    async with admin_engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO role_assignments (tenant_id, id, user_account_id, role_id, scope_type)
            SELECT ua.tenant_id, gen_random_uuid(), ua.id, r.id, 'ALL'
            FROM user_accounts ua JOIN roles r ON r.tenant_id = ua.tenant_id
            WHERE ua.employee_code = :code AND r.name = 'HR_MANAGER'"""),
            {"code": created["employee_code"]})
    me, issued = await _session(client, w, "S-3")
    assert issued["roles"] == ["MANAGER"]
    async with client_from("10.5.0.3") as erp_server:
        who = await ok(erp_server, "GET", "/v1/auth/me", headers=me)
    assert "HR_MANAGER" not in who["roles"] and "people.write" not in who["permissions"]


async def test_revoking_the_key_or_switching_a_feature_off_ends_access(api):
    client, _ = api
    w = await world(client)
    await w.put("S-4", expect=201, **w.new_hire())
    me, _ = await _session(client, w, "S-4")
    settings = await w.current_settings()
    settings["self_service"]["punch"] = False
    await w.publish(settings)
    async with client_from("10.5.0.4") as erp_server:
        off = await erp_server.post("/v1/time/punches", json={"punch_type": "IN"}, headers=me)
        assert off.status_code == 403 and off.json()["code"] == "NOT_AVAILABLE_VIA_INTEGRATION"
        keys = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/keys",
                        headers=w.admin)
        await ok(client, "POST",
                 f"/v1/admin/integrations/apps/{w.app['id']}/keys/{keys[0]['id']}/revoke",
                 json={"reason": "test"}, headers=w.admin)
        ended = await erp_server.get("/v1/persons/me", headers=me)
        assert ended.status_code == 401 and ended.json()["code"] == "APP_SESSION_REVOKED"


async def test_no_session_for_someone_who_has_left_or_is_unknown(api):
    client, _ = api
    w = await world(client)
    await w.put("S-5", expect=201, **w.new_hire())
    me, _ = await _session(client, w, "S-5")
    await ok(client, "POST", "/v1/integrations/employees/S-5/exit",
             json={"last_working_day": str(date.today() - timedelta(days=1))},
             headers={**w.erp, "Idempotency-Key": "s5"})
    gone = await client.post("/v1/integrations/sessions", json={"external_id": "S-5"},
                             headers=w.erp)
    unknown = await client.post("/v1/integrations/sessions", json={"external_id": "NOPE"},
                                headers=w.erp)
    assert gone.status_code == unknown.status_code == 403
    assert gone.json()["detail"] == unknown.json()["detail"]
    async with client_from("10.5.0.5") as erp_server:
        assert (await erp_server.get("/v1/persons/me", headers=me)).status_code == 401


async def test_a_supervisor_marks_a_group_through_the_app_once_switched_on(api):
    client, admin_engine = api
    w = await world(client)
    await w.put("SUP-1", expect=201, **w.new_hire(email=f"sup.{uuid4().hex[:8]}@example.com"))
    await w.put("DRV-1", expect=201, **w.new_hire())
    sup, sup_issued = await _session(client, w, "SUP-1")
    _, drv_issued = await _session(client, w, "DRV-1")
    driver = drv_issued["employment_id"]
    groups = "/v1/time/attendance-groups"
    group = await ok(client, "POST", groups, json={"name": "Drivers"}, headers=w.admin)
    await ok(client, "POST", f"{groups}/{group['id']}/members",
             json={"employment_ids": [driver],
                   "effective_from": str(date.today() - timedelta(days=10))},
             headers=w.admin)
    from hrms.core.ids import to_typed_id, to_uuid

    async with admin_engine.connect() as conn:
        sup_user = (await conn.execute(
            text("SELECT id FROM user_accounts WHERE employment_id = :e"),
            {"e": to_uuid(sup_issued["employment_id"])})).scalar_one()
    await ok(client, "PUT", f"{groups}/{group['id']}/access/{to_typed_id('user', sup_user)}",
             json={"access_level": "MARK"}, headers=w.admin)
    day = str(date.today() - timedelta(days=1))
    async with client_from("10.5.0.6") as erp_server:
        # Off by default: the app's sessions can't reach marking until the admin switches it on.
        off = await erp_server.get("/v1/time/marking", params={"work_date": day}, headers=sup)
        assert off.status_code == 403 and off.json()["code"] == "NOT_AVAILABLE_VIA_INTEGRATION"
        settings = await w.current_settings()
        assert settings["self_service"]["marking"] is False
        settings["self_service"]["marking"] = True
        await w.publish(settings)
        sheet = await ok(erp_server, "GET", "/v1/time/marking", params={"work_date": day},
                         headers=sup)
        assert [(r["employment_id"], r["access"]) for r in sheet["rows"]] == [(driver, "MARK")]
        saved = await ok(erp_server, "PUT", f"/v1/time/marking/{day}", headers=sup,
                         json={"marks": [{"employment_id": driver, "status": "PRESENT",
                                          "punch_in": "08:30", "punch_out": "17:00"}]})
        assert saved["changed"] == 1 and saved["rows"][0]["mark"]["source"] == "INTEGRATION"
        again = await ok(erp_server, "PUT", f"/v1/time/marking/{day}", headers=sup,
                         json={"marks": [{"employment_id": driver, "status": "PRESENT",
                                          "punch_in": "08:30", "punch_out": "17:00"}]})
        assert (again["changed"], again["unchanged"]) == (0, 1)
        # Recording leave is part of marking (this company has no leave types yet).
        assert await ok(erp_server, "GET", "/v1/time/marking/leave-types", headers=sup) == []
        # The driver's own app session has no access to any group: it sees nobody.
        drv = {"Authorization": "Bearer " + drv_issued["access_token"]}
        empty = await ok(erp_server, "GET", "/v1/time/marking", params={"work_date": day},
                         headers=drv)
        assert empty["rows"] == []
    async with admin_engine.connect() as conn:
        mark = (await conn.execute(
            text("SELECT source, marked_by FROM attendance_marks WHERE employment_id = :e"),
            {"e": to_uuid(driver)})).one()
        times = (await conn.execute(
            text("SELECT DISTINCT source, source_system FROM punches WHERE employment_id = :e"),
            {"e": to_uuid(driver)})).all()
    assert tuple(mark) == ("INTEGRATION", sup_user)
    # The times are kept as marked punches that name the app they came through.
    assert [tuple(t) for t in times] == [("MARKED", "ERP")]


async def _marking_world(client, admin_engine):
    """A supervisor in company A with Mark on a Drivers group that holds a driver from company A
    and one from company B, and a second key of the same app limited to company A."""
    from hrms.core.ids import to_typed_id, to_uuid
    from tests.helpers import hire, org_basics, person_and_employment

    w = await world(client)
    other = await ok(client, "POST", "/v1/org/legal-entities", headers=w.admin,
                     json={"name": "Fleet Co " + uuid4().hex[:4], "country_code": "IN"})
    await w.put("SUP-A", expect=201, **w.new_hire(role="MANAGER"))
    await w.put("DRV-A", expect=201, **w.new_hire())
    # Someone to hold HR rights, made before company B adds a second "Executive" job title.
    w.hr_code = (await w.put("HR-1", expect=201, **w.new_hire())).json()["employee_code"]
    sup, sup_issued = await _session(client, w, "SUP-A")
    _, drv_issued = await _session(client, w, "DRV-A")
    started = date.today() - timedelta(days=20)
    foreign = await person_and_employment(client, other["id"], number="DRV-B")
    await hire(client, foreign["id"], await org_basics(client, other["id"]), when=started)
    groups = "/v1/time/attendance-groups"
    group = await ok(client, "POST", groups, json={"name": "Drivers"}, headers=w.admin)
    await ok(client, "POST", f"{groups}/{group['id']}/members", headers=w.admin,
             json={"employment_ids": [drv_issued["employment_id"], foreign["id"]],
                   "effective_from": str(started)})
    async with admin_engine.connect() as conn:
        sup_user = (await conn.execute(
            text("SELECT id FROM user_accounts WHERE employment_id = :e"),
            {"e": to_uuid(sup_issued["employment_id"])})).scalar_one()
    await ok(client, "PUT", f"{groups}/{group['id']}/access/{to_typed_id('user', sup_user)}",
             json={"access_level": "MARK"}, headers=w.admin)
    limited = await ok(client, "POST", f"/v1/admin/integrations/apps/{w.app['id']}/keys",
                       headers=w.admin,
                       json={"name": "company A only", "scopes": ["sessions.issue"],
                             "legal_entity_ids": [w.legal_entity]})
    issued = await ok(client, "POST", "/v1/integrations/sessions",
                      json={"external_id": "SUP-A"}, headers={"X-API-Key": limited["key"]})
    sup_limited = {"Authorization": "Bearer " + issued["access_token"]}
    return w, other, sup, sup_limited, drv_issued["employment_id"], foreign["id"]


async def _sheet(server, headers):
    day = str(date.today() - timedelta(days=1))
    listing = await ok(server, "GET", "/v1/time/marking", params={"work_date": day},
                       headers=headers)
    return {r["employment_id"] for r in listing["rows"]}


async def test_app_marking_stays_within_the_keys_companies_and_their_settings(api):
    client, admin_engine = api
    w, other, sup, sup_limited, mine, theirs = await _marking_world(client, admin_engine)
    settings = await w.current_settings()
    settings["self_service"]["marking"] = True
    await w.publish(settings)
    day = str(date.today() - timedelta(days=1))
    async with client_from("10.5.0.7") as erp_server:
        assert await _sheet(erp_server, sup) == {mine, theirs}
        # Through a key limited to company A the supervisor neither sees nor marks company B.
        assert await _sheet(erp_server, sup_limited) == {mine}
        refused = await erp_server.put(
            f"/v1/time/marking/{day}", headers=sup_limited,
            json={"marks": [{"employment_id": theirs, "status": "PRESENT"}]})
        assert refused.status_code == 422, refused.text
        # Company B switches app marking off: its people drop out for every key of the app.
        settings_b = await w.current_settings()
        settings_b["self_service"]["marking"] = False
        await w.publish(settings_b, legal_entity_id=other["id"])
        assert await _sheet(erp_server, sup) == {mine}
        leave = await erp_server.post(
            "/v1/time/marking/leave", headers=sup,
            json={"employment_id": theirs, "leave_type_id": "lt_x", "from_date": day,
                  "to_date": day})
        assert leave.status_code == 422, leave.text


async def test_the_app_is_told_about_marking_only_when_it_is_switched_on(api):
    client, admin_engine = api
    w, _, sup, _, _, _ = await _marking_world(client, admin_engine)
    async with client_from("10.5.0.8") as erp_server:
        off = await ok(erp_server, "GET", "/v1/auth/me", headers=sup)
        assert not {"attendance.view", "attendance.mark"} & set(off["permissions"])
        settings = await w.current_settings()
        settings["self_service"]["marking"] = True
        await w.publish(settings)
        on = await ok(erp_server, "GET", "/v1/auth/me", headers=sup)
        assert {"attendance.view", "attendance.mark"} <= set(on["permissions"])


async def test_hr_rights_dont_reach_marking_through_the_app(api):
    client, admin_engine = api
    w, _, _, _, mine, theirs = await _marking_world(client, admin_engine)
    async with admin_engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO role_assignments (tenant_id, id, user_account_id, role_id, scope_type)
            SELECT ua.tenant_id, gen_random_uuid(), ua.id, r.id, 'ALL'
            FROM user_accounts ua JOIN roles r ON r.tenant_id = ua.tenant_id
            WHERE ua.employee_code = :code AND r.name = 'HR_MANAGER'"""),
            {"code": w.hr_code})
    settings = await w.current_settings()
    settings["self_service"]["marking"] = True
    await w.publish(settings)
    hr, _ = await _session(client, w, "HR-1")
    async with client_from("10.5.0.9") as erp_server:
        # HR marks every group in HRMS; through the app only the access HR was given counts.
        assert await _sheet(erp_server, hr) == set()
        refused = await erp_server.put(
            f"/v1/time/marking/{date.today() - timedelta(days=1)}", headers=hr,
            json={"marks": [{"employment_id": mine, "status": "PRESENT"}]})
        assert refused.status_code == 403, refused.text
    del theirs


def test_every_session_route_is_a_real_route():
    routes = set()
    for ctx in iter_route_contexts(hrms_app.routes):
        route = ctx.original_route
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.add((method, ctx.path_format or route.path_format))
    assert sorted(set(SESSION_ROUTES) - routes) == []


async def test_someone_hired_in_hrms_without_a_login_can_use_the_app(api):
    from tests.helpers import hire, person_and_employment

    client, admin_engine = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="NOLOGIN-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    await w.put("NL-1", expect=200, employment_id=emp["id"])
    me, issued = await _session(client, w, "NL-1")
    assert issued["roles"] == ["EMPLOYEE"]
    async with client_from("10.5.0.9") as erp_server:
        assert (await erp_server.get("/v1/persons/me", headers=me)).is_success
    async with admin_engine.connect() as conn:
        hashed = (await conn.execute(text(
            "SELECT password_hash FROM user_accounts WHERE employee_code = 'NOLOGIN-1'"))).scalar()
    assert hashed is None  # no direct HRMS sign-in until HR issues credentials
