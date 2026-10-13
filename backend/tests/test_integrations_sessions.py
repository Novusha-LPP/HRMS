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
