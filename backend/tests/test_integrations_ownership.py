"""Field ownership, lifecycle rules and versioned settings, enforced on HRMS's own write paths."""

import inspect
from datetime import date, timedelta

import pytest

from tests.helpers import ok, person_and_employment
from tests.integration_support import world

pytestmark = pytest.mark.database


async def _linked(w, **extra):
    created = (await w.put("O-1", expect=201, **w.new_hire(**extra))).json()
    return created["employment_id"]


async def _sales(client, w):
    return await ok(client, "POST", "/v1/org/org-units", headers=w.admin,
                    json={"name": "Sales", "type": "DEPARTMENT",
                          "legal_entity_id": w.legal_entity, "effective_from": "2020-01-01"})


async def test_hr_needs_a_reason_to_change_a_field_the_erp_owns(api):
    client, _ = api
    w = await world(client)
    emp = await _linked(w)
    sales = await _sales(client, w)
    transfer = {"employment_id": emp, "type": "TRANSFER", "effective_date": str(date.today()),
                "changes": {"org_unit_id": sales["id"]}}

    control = await ok(client, "GET", f"/v1/employees/{emp}/field-control", headers=w.admin)
    department = next(f for f in control if f["field"] == "department")
    assert department["locked"] and department["owner"] == "ERP"
    assert department["override"] == "WITH_REASON"

    refused = await client.post("/v1/personnel-actions", json=transfer, headers=w.admin)
    assert refused.status_code == 403 and refused.json()["code"] == "OVERRIDE_REASON_REQUIRED"
    await ok(client, "POST", "/v1/personnel-actions", headers=w.admin,
             json={**transfer, "override_reason": "ERP down; urgent move"})
    moved = await ok(client, "GET", f"/v1/employees/{emp}", headers=w.admin)
    assert moved["department"] == "Sales"


async def test_overrides_can_be_switched_off(api):
    client, _ = api
    w = await world(client)
    emp = await _linked(w)
    sales = await _sales(client, w)
    settings = await w.current_settings()
    settings["hr_override"] = "NOT_ALLOWED"
    await w.publish(settings)
    refused = await client.post("/v1/personnel-actions", headers=w.admin, json={
        "employment_id": emp, "type": "TRANSFER", "effective_date": str(date.today()),
        "changes": {"org_unit_id": sales["id"]}, "override_reason": "please"})
    assert refused.status_code == 403 and refused.json()["code"] == "FIELD_MANAGED_EXTERNALLY"


async def test_an_employee_cannot_edit_what_the_erp_owns_but_can_edit_shared_fields(api):
    client, _ = api
    w = await world(client)
    emp = await _linked(w, email=f"own.{date.today():%f}{id(w)}@example.com")
    session = await ok(client, "POST", "/v1/integrations/sessions",
                       json={"external_id": "O-1"}, headers=w.erp)
    me = {"Authorization": "Bearer " + session["access_token"]}
    refused = await client.patch("/v1/persons/me", json={"date_of_birth": "1991-01-01"},
                                 headers=me)
    assert refused.status_code == 403 and refused.json()["code"] == "FIELD_MANAGED_EXTERNALLY"
    assert (await client.patch("/v1/persons/me", json={"mobile": "9000000001"},
                               headers=me)).is_success
    del emp


async def test_hiring_can_be_reserved_for_the_app(api):
    client, _ = api
    w = await world(client)
    settings = await w.current_settings()
    settings["lifecycle"]["hire"] = "APP"
    await w.publish(settings)
    person = await ok(client, "POST", "/v1/persons", headers=w.admin,
                      json={"legal_first_name": "A", "legal_last_name": "B"})
    refused = await client.post("/v1/employees", headers=w.admin, json={
        "person_id": person["id"], "legal_entity_id": w.legal_entity,
        "employee_number": "Z-1", "hire_date": "2026-01-01"})
    assert refused.status_code == 403 and refused.json()["code"] == "MANAGED_BY_APP"


async def test_a_company_override_beats_the_tenant_default(api):
    client, _ = api
    w = await world(client)
    settings = await w.current_settings()
    settings["lifecycle"]["hire"] = "APP"
    await w.publish(settings)
    # This company lets HR hire again.
    await w.publish({"lifecycle": {"hire": "BOTH"}}, legal_entity_id=w.legal_entity)
    company = await ok(client, "GET",
                       f"/v1/admin/integrations/apps/{w.app['id']}/settings"
                       f"?legal_entity_id={w.legal_entity}", headers=w.admin)
    assert company["settings"]["lifecycle"]["hire"] == "BOTH"
    assert company["overridden"] == ["lifecycle.hire"]
    await person_and_employment(client, w.legal_entity, number="Z-2")


async def test_settings_versions_preview_and_future_publishing(api):
    client, _ = api
    w = await world(client)
    base = f"/v1/admin/integrations/apps/{w.app['id']}"
    draft = await ok(client, "POST", f"{base}/profiles", json={"preset": "HRMS_MASTER"},
                     headers=w.admin)
    preview = await ok(client, "POST", f"/v1/admin/integrations/profiles/{draft['id']}/preview",
                       headers=w.admin)
    assert "department" in preview["fields_becoming_unlocked"]
    assert preview["fields_becoming_locked"] == []

    bad = await client.put(f"/v1/admin/integrations/profiles/{draft['id']}",
                           json={"settings": {"self_service": {"session_minutes": 9999}}},
                           headers=w.admin)
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_SETTINGS"
    past = await client.post(f"/v1/admin/integrations/profiles/{draft['id']}/publish",
                             json={"effective_from": str(date.today() - timedelta(days=1))},
                             headers=w.admin)
    assert past.status_code == 422

    tomorrow = str(date.today() + timedelta(days=1))
    await ok(client, "POST", f"/v1/admin/integrations/profiles/{draft['id']}/publish",
             json={"effective_from": tomorrow}, headers=w.admin)
    # Not in force until its date.
    assert (await w.current_settings())["field_ownership"]["department"] == "APP"
    again = await client.put(f"/v1/admin/integrations/profiles/{draft['id']}",
                             json={"settings": {}}, headers=w.admin)
    assert again.status_code == 409 and again.json()["code"] == "NOT_A_DRAFT"
    versions = await ok(client, "GET", f"{base}/profiles", headers=w.admin)
    assert [v["status"] for v in versions] == ["PUBLISHED"]


async def test_health_warnings_flag_contradictory_settings(api):
    client, _ = api
    w = await world(client)
    settings = await w.current_settings()
    settings["outbound"]["events"] = ["employee.updated"]
    await w.publish(settings)
    current = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/settings",
                       headers=w.admin)
    assert any("employee.hired" in warning for warning in current["warnings"])


def test_every_hrms_write_path_for_owned_fields_checks_ownership():
    """A write path for a catalogue field that stops calling the check fails here."""
    from hrms.modules.kernel.users import router as users
    from hrms.modules.people import router as people

    checked = {
        people.create_personnel_action: "_check_integration_rules",
        people._check_integration_rules: "assert_fields_editable",
        people.update_my_profile: "assert_fields_editable",
        people.create_employment: "assert_lifecycle_allowed",
        users.create_user: "assert_fields_editable",
    }
    for function, call in checked.items():
        assert call in inspect.getsource(function), function.__name__


async def test_resending_the_current_placement_needs_no_override(api):
    client, _ = api
    w = await world(client)
    emp = await _linked(w)
    current = await ok(client, "GET", f"/v1/employees/{emp}", headers=w.admin)
    # The HR transfer form sends every placement field; only the date changes here.
    await ok(client, "POST", "/v1/personnel-actions", headers=w.admin, json={
        "employment_id": emp, "type": "TRANSFER",
        "effective_date": str(date.today() + timedelta(days=1)),
        "changes": {"org_unit_id": current["org_unit_id"], "job_id": current["job_id"],
                    "location_id": current["location_id"]}})


async def test_an_override_can_require_approval(api):
    from tests.helpers import make_user, sign_in

    client, _ = api
    w = await world(client)
    emp = await _linked(w)
    sales = await _sales(client, w)
    settings = await w.current_settings()
    settings["hr_override"] = "WITH_APPROVAL"
    await w.publish(settings)
    transfer = {"employment_id": emp, "type": "TRANSFER", "effective_date": str(date.today()),
                "changes": {"org_unit_id": sales["id"]}, "override_reason": "Reorganisation"}

    # No field-override flow assigned to the employee yet: refused, with the fix named.
    missing = await client.post("/v1/personnel-actions", json=transfer, headers=w.admin)
    assert missing.status_code == 409 and "approval flow" in missing.json()["detail"]

    approver_emp = await person_and_employment(client, w.legal_entity, number="APPR-1")
    email, password, approver = await make_user(client, approver_emp["id"], role="HR_MANAGER",
                                                scope_type="ALL")
    flow = await ok(client, "POST", "/v1/approvals/flows", headers=w.admin, json={
        "name": "ERP overrides", "request_type": "FIELD_OVERRIDE", "reusable": True,
        "steps": [{"name": "HR head", "approver_ids": [approver["id"]]}]})
    await ok(client, "PUT", f"/v1/approvals/employees/{emp}/flows/FIELD_OVERRIDE",
             headers=w.admin, json={"flow_id": flow["id"], "version": 0})

    held = await ok(client, "POST", "/v1/personnel-actions", json=transfer, headers=w.admin)
    assert held["status"] == "PENDING_APPROVAL"
    assert (await ok(client, "GET", f"/v1/employees/{emp}", headers=w.admin))["department"] == "Ops"

    login = await sign_in(client, email, password)
    approver_headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    inbox = await ok(client, "GET", "/v1/approvals/inbox", headers=approver_headers)
    request = next(r for r in inbox if r["request_type"] == "FIELD_OVERRIDE")
    detail = await ok(client, "GET", f"/v1/approvals/requests/{request['id']}",
                      headers=approver_headers)
    assert detail["request"]["reason"] == "Reorganisation"
    await ok(client, "POST", f"/v1/approvals/requests/{request['id']}/decision",
             headers=approver_headers, json={"action": "APPROVE", "comments": "OK"})
    moved = await ok(client, "GET", f"/v1/employees/{emp}", headers=w.admin)
    assert moved["department"] == "Sales"

    # A held change can be withdrawn.
    back = await ok(client, "POST", "/v1/personnel-actions", headers=w.admin, json={
        **transfer, "changes": {"org_unit_id": w.placement["org_unit_id"]},
        "effective_date": str(date.today() + timedelta(days=2))})
    cancelled = await ok(client, "POST", f"/v1/personnel-actions/{back['id']}/cancel",
                         headers=w.admin)
    assert cancelled["status"] == "CANCELLED"


async def test_saving_the_profile_form_unchanged_fields_is_fine(api):
    """The profile form resends every field; only real changes to ERP-owned ones are refused."""
    client, _ = api
    w = await world(client)
    await _linked(w, date_of_birth="1990-02-03", gender="FEMALE")
    session = await ok(client, "POST", "/v1/integrations/sessions",
                       json={"external_id": "O-1"}, headers=w.erp)
    me = {"Authorization": "Bearer " + session["access_token"]}
    saved = await ok(client, "PATCH", "/v1/persons/me", headers=me, json={
        "preferred_name": None, "date_of_birth": "1990-02-03", "gender": "FEMALE",
        "nationality": None, "mobile": "9000000002"})
    assert saved["mobile"] == "9000000002"
