"""Employee sync: create, update, ordering, ownership, mappings, matching, codes, bulk, link."""

from datetime import date, timedelta
from uuid import uuid4

import bcrypt
import pytest

from tests.helpers import client_from, ok, person_and_employment, sign_in
from tests.integration_support import world

pytestmark = pytest.mark.database


async def _employee(client, w, employment_id):
    return await ok(client, "GET", f"/v1/employees/{employment_id}", headers=w.admin)


async def test_create_places_the_employee_and_gives_them_a_login(api):
    client, _ = api
    w = await world(client)
    email = f"asha.{uuid4().hex[:8]}@example.com"
    body = w.new_hire(email=email, mobile="98765" + uuid4().hex[:5])
    created = (await w.put("ERP-1", expect=201, **body)).json()
    assert created["outcome"] == "CREATED" and created["employee_code"] == body["employee_code"]

    emp = await _employee(client, w, created["employment_id"])
    assert (emp["department"], emp["location"], emp["designation"]) == ("Ops", "HQ", "Executive")
    assert emp["employment_state"] == "PROBATION"

    # No password from the app: the default pattern, to be changed at the first direct sign-in.
    async with client_from("10.0.0.1") as fresh:
        login = await sign_in(fresh, email, "Asha@1234")
    assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True

    # The same record again changes nothing.
    again = (await w.put("ERP-1", expect=200, **body)).json()
    assert again["outcome"] == "NO_CHANGE"
    log = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/requests",
                   headers=w.admin)
    assert [r["outcome"] for r in log[:2]] == ["NO_CHANGE", "CREATED"]
    # Contact details are masked in the log.
    assert email not in str(log)


async def test_the_apps_bcrypt_password_is_kept_and_other_formats_are_refused(api):
    client, _ = api
    w = await world(client)
    hashed = bcrypt.hashpw(b"Erp-pass-9", bcrypt.gensalt(rounds=10)).decode()
    email = f"b.{uuid4().hex[:8]}@example.com"
    await w.put("ERP-2", expect=201, **w.new_hire(email=email, password_hash=hashed))
    async with client_from("10.0.0.2") as fresh:
        login = await sign_in(fresh, email, "Erp-pass-9")
    assert login.status_code == 200 and login.json()["user"]["must_change_password"] is False

    pbkdf2 = "pbkdf2_sha256$260000$abc$def"
    refused = await w.put("ERP-3", **w.new_hire(password_hash=pbkdf2))
    assert refused.status_code == 422 and refused.json()["code"] == "UNSUPPORTED_PASSWORD_HASH"


async def test_updates_are_partial_ordered_and_job_changes_keep_history(api):
    client, _ = api
    w = await world(client)
    created = (await w.put("ERP-4", expect=201, **w.new_hire())).json()
    await ok(client, "POST", "/v1/org/org-units", headers=w.admin,
             json={"name": "Sales", "type": "DEPARTMENT", "legal_entity_id": w.legal_entity,
                   "effective_from": "2020-01-01"})

    later = "2026-10-01T10:00:00+05:30"
    moved = (await w.put("ERP-4", expect=200, department="Sales", source_updated_at=later)).json()
    assert moved["outcome"] == "UPDATED" and "department" in moved["changes"]
    emp = await _employee(client, w, created["employment_id"])
    assert emp["department"] == "Sales" and emp["designation"] == "Executive"
    actions = await ok(client, "GET",
                       f"/v1/personnel-actions?employment_id={created['employment_id']}",
                       headers=w.admin)
    assert {a["type"] for a in actions} == {"HIRE", "TRANSFER"}

    # An older update arriving late can't undo the newer one.
    stale = (await w.put("ERP-4", department="Ops",
                         source_updated_at="2026-09-30T10:00:00+05:30")).json()
    assert stale["outcome"] == "STALE_IGNORED"
    assert (await _employee(client, w, created["employment_id"]))["department"] == "Sales"


async def test_unknown_values_are_refused_until_mapped(api):
    client, _ = api
    w = await world(client)
    refused = await w.put("ERP-5", **w.new_hire(department="Operations Dept"))
    assert refused.status_code == 422 and refused.json()["code"] == "UNKNOWN_DEPARTMENT"
    unmapped = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/unmapped",
                        headers=w.admin)
    assert unmapped[0]["kind"] == "DEPARTMENT" and unmapped[0]["value"] == "Operations Dept"

    await ok(client, "POST", f"/v1/admin/integrations/apps/{w.app['id']}/mappings",
             headers=w.admin, json={"kind": "DEPARTMENT", "external_value": "Operations Dept",
                                    "target_id": w.placement["org_unit_id"]})
    await w.put("ERP-5", expect=201, **w.new_hire(department="Operations Dept"))
    assert await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/unmapped",
                    headers=w.admin) == []


async def test_an_email_used_by_any_company_is_refused_cleanly(api):
    client, _ = api
    first = await world(client)
    email = f"shared.{uuid4().hex[:8]}@example.com"
    await first.put("E-1", expect=201, **first.new_hire(email=email))
    client.headers.pop("Authorization")
    second = await world(client)
    refused = await second.put("E-1", **second.new_hire(email=email))
    assert refused.status_code == 409 and refused.json()["code"] == "EMAIL_IN_USE"


async def test_sync_never_grants_more_than_employee_or_manager(api):
    client, _ = api
    w = await world(client)
    refused = await w.put("ERP-6", **w.new_hire(role="SUPER_ADMIN"))
    assert refused.status_code == 422 and refused.json()["code"] == "ROLE_NOT_ALLOWED"
    created = (await w.put("ERP-6", expect=201, **w.new_hire(role="manager"))).json()
    assert (await _employee(client, w, created["employment_id"]))["role"] == "MANAGER"


async def test_fields_the_app_does_not_own_are_ignored(api):
    client, _ = api
    w = await world(client)
    created = (await w.put("ERP-7", expect=201, **w.new_hire(first_name="Ravi"))).json()
    settings = await w.current_settings()
    settings["field_ownership"]["first_name"] = "HRMS"
    await w.publish(settings)
    result = (await w.put("ERP-7", expect=200, first_name="Rav")).json()
    assert result["outcome"] == "NO_CHANGE"
    assert any("FIELD_OWNED_BY_HRMS" in warning for warning in result["warnings"])
    assert (await _employee(client, w, created["employment_id"]))["first_name"] == "Ravi"


async def test_an_hrms_employee_is_linked_not_duplicated(api):
    client, _ = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="SF-0100",
                                      legal_first_name="Meena", legal_last_name="Rao",
                                      date_of_birth="1990-05-01")
    body = w.new_hire(first_name="Meena", last_name="Rao", date_of_birth="1990-05-01",
                      employee_code="SF-0100")
    linked = (await w.put("ERP-8", expect=200, **body)).json()
    assert linked["outcome"] == "LINKED" and linked["employment_id"] == emp["id"]


async def test_a_partial_match_is_queued_for_hr(api):
    client, _ = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="SF-0200",
                                      legal_first_name="Meena", legal_last_name="Rao")
    body = w.new_hire(first_name="Mina", last_name="Iyer", employee_code="SF-0200")
    queued = await w.put("ERP-9", **body)
    assert queued.status_code == 409 and queued.json()["code"] == "POSSIBLE_DUPLICATE"
    dups = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/duplicates",
                    headers=w.admin)
    assert dups[0]["hrms_employee"]["employment_id"] == emp["id"]
    await ok(client, "POST", f"/v1/admin/integrations/duplicates/{dups[0]['id']}/resolve",
             json={"decision": "SAME_PERSON"}, headers=w.admin)
    updated = (await w.put("ERP-9", expect=200, **body)).json()
    assert updated["employment_id"] == emp["id"] and updated["outcome"] == "UPDATED"


async def test_a_report_waits_for_their_manager(api):
    client, _ = api
    w = await world(client)
    report = (await w.put("R-1", expect=201, **w.new_hire(manager_external_id="M-1"))).json()
    assert any("MANAGER_PENDING" in x for x in report["warnings"])
    manager = (await w.put("M-1", expect=201, **w.new_hire(role="MANAGER"))).json()
    emp = await _employee(client, w, report["employment_id"])
    assert emp["manager_employment_id"] == manager["employment_id"]


async def test_employee_codes_follow_the_companys_id_scheme(api):
    client, _ = api
    w = await world(client)
    await ok(client, "POST", "/v1/org/employee-id-schemes", headers=w.admin,
             json={"legal_entity_id": w.legal_entity, "prefix": "SF", "number_digits": 4})
    first = (await w.put("C-1", expect=201, **w.new_hire(employee_code=None))).json()
    assert first["employee_code"] == "SF-0001"
    # A code in the scheme's pattern from the app moves the counter past it...
    await w.put("C-2", expect=201, **w.new_hire(employee_code="SF-0005"))
    third = (await w.put("C-3", expect=201, **w.new_hire(employee_code=None))).json()
    assert third["employee_code"] == "SF-0006"
    # ...and the generator skips a number typed in by hand.
    await person_and_employment(client, w.legal_entity, number="SF-0007")
    fourth = (await w.put("C-4", expect=201, **w.new_hire(employee_code=None))).json()
    assert fourth["employee_code"] == "SF-0008"
    dup = await w.put("C-5", **w.new_hire(employee_code="SF-0001"))
    assert dup.status_code == 409 and dup.json()["code"] == "EMPLOYEE_CODE_IN_USE"


async def test_dry_run_saves_nothing(api):
    client, _ = api
    w = await world(client)
    preview = await client.put("/v1/integrations/employees/D-1?dry_run=true",
                               json=w.new_hire(), headers=w.erp)
    assert preview.status_code == 201 and preview.json()["dry_run"] is True
    assert (await client.get("/v1/integrations/employees/D-1", headers=w.erp)).status_code == 404


async def test_bulk_reports_each_record(api):
    client, _ = api
    w = await world(client)
    records = [
        {"external_id": "B-1", **w.new_hire()},
        {"external_id": "B-2", **w.new_hire(department="Nowhere")},
        {"external_id": "B-3", **w.new_hire()},
    ]
    result = await ok(client, "POST", "/v1/integrations/employees/bulk",
                      json={"records": records}, headers={**w.erp, "Idempotency-Key": "b1"})
    assert [r["status"] for r in result["results"]] == [201, 422, 201]
    assert (result["created"], result["failed"]) == (2, 1)
    replay = await client.post("/v1/integrations/employees/bulk", json={"records": records},
                               headers={**w.erp, "Idempotency-Key": "b1"})
    assert replay.headers.get("idempotent-replay") == "true" and replay.json() == result


async def test_link_existing_employees_by_code(api):
    client, _ = api
    w = await world(client)
    emp = await person_and_employment(client, w.legal_entity, number="L-001")
    body = {"records": [{"external_id": "X-1", "employee_code": "L-001"},
                        {"external_id": "X-2", "employee_code": "L-404"}]}
    preview = await ok(client, "POST", "/v1/integrations/employees/link", json=body,
                       headers=w.erp)
    assert preview["dry_run"] and preview["matched"][0]["employment_id"] == emp["id"]
    assert preview["not_in_hrms"] == ["X-2"]
    assert (await client.get("/v1/integrations/employees/X-1", headers=w.erp)).status_code == 404
    await ok(client, "POST", "/v1/integrations/employees/link",
             json={**body, "dry_run": False}, headers=w.erp)
    linked = await ok(client, "GET", "/v1/integrations/employees/X-1", headers=w.erp)
    assert linked["employment_id"] == emp["id"] and linked["external_id"] == "X-1"


async def test_reconcile_reports_differences_only(api):
    client, _ = api
    w = await world(client)
    await w.put("A-1", expect=201, **w.new_hire())
    await w.put("A-2", expect=201, **w.new_hire())
    report = await ok(client, "POST", "/v1/integrations/reconcile",
                      json={"active_external_ids": ["A-1", "A-3"]}, headers=w.erp)
    assert report["in_app_not_in_hrms"] == ["A-3"]
    assert report["active_in_hrms_not_in_app"] == ["A-2"]
    assert report["matched"] == 1


async def test_exit_is_idempotent_and_locks_the_employee_out(api):
    client, _ = api
    w = await world(client)
    email = f"x1.{uuid4().hex[:8]}@example.com"
    await w.put("X-1", expect=201, **w.new_hire(email=email))
    body = {"last_working_day": str(date.today() - timedelta(days=1))}
    headers = {**w.erp, "Idempotency-Key": "exit-x1"}
    done = await ok(client, "POST", "/v1/integrations/employees/X-1/exit", json=body,
                    headers=headers)
    assert done["outcome"] == "APPLIED"
    again = await client.post("/v1/integrations/employees/X-1/exit", json=body, headers=headers)
    assert again.json() == done
    reused = await client.post("/v1/integrations/employees/X-1/exit",
                               json={"last_working_day": str(date.today())}, headers=headers)
    assert reused.status_code == 422 and reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    async with client_from("10.0.0.3") as fresh:
        assert (await sign_in(fresh, email, "Asha@1234")).status_code in (401, 403)
    refused = await client.post("/v1/integrations/sessions", json={"external_id": "X-1"},
                                headers=w.erp)
    assert refused.status_code == 403


async def test_too_many_exits_are_held_for_hr(api):
    client, _ = api
    w = await world(client)
    for i in range(5):
        await w.put(f"H-{i}", expect=201, **w.new_hire())
    settings = await w.current_settings()
    settings["safety"]["max_exits_per_day"] = 3
    await w.publish(settings)
    yesterday = str(date.today() - timedelta(days=1))
    outcomes = []
    for i in range(4):
        r = await client.post(f"/v1/integrations/employees/H-{i}/exit",
                              json={"last_working_day": yesterday},
                              headers={**w.erp, "Idempotency-Key": f"h{i}"})
        outcomes.append((r.status_code, r.json()["outcome"]))
    assert outcomes[-1] == (202, "HELD_FOR_REVIEW")
    held = await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/held-exits",
                    headers=w.admin)
    assert len(held) == 1
    released = await ok(client, "POST", f"/v1/admin/integrations/held-exits/{held[0]['id']}",
                        json={"decision": "RELEASE"}, headers=w.admin)
    assert released["outcome"] == "APPLIED"
    assert await ok(client, "GET", f"/v1/admin/integrations/apps/{w.app['id']}/held-exits",
                    headers=w.admin) == []


async def test_rehire_reuses_the_last_placement(api):
    client, _ = api
    w = await world(client)
    created = (await w.put("RH-1", expect=201, **w.new_hire())).json()
    await ok(client, "POST", "/v1/integrations/employees/RH-1/exit",
             json={"last_working_day": str(date.today() - timedelta(days=2))},
             headers={**w.erp, "Idempotency-Key": "rh-exit"})
    rehired = await ok(client, "POST", "/v1/integrations/employees/RH-1/rehire",
                       json={"hire_date": str(date.today())},
                       headers={**w.erp, "Idempotency-Key": "rh-in"})
    assert rehired["outcome"] == "APPLIED"
    emp = await _employee(client, w, created["employment_id"])
    assert emp["employment_state"] == "PROBATION" and emp["department"] == "Ops"


async def test_rehire_through_the_sync_api_can_start_fresh_and_refuses_a_bad_choice(api):
    client, admin_engine = api
    w = await world(client)
    created = (await w.put("RH-2", expect=201, **w.new_hire())).json()
    await ok(client, "POST", "/v1/integrations/employees/RH-2/exit",
             json={"last_working_day": str(date.today() - timedelta(days=2))},
             headers={**w.erp, "Idempotency-Key": "rh2-exit"})
    # Starting fresh needs a reason, and the app is told why it was refused.
    refused = await client.post(
        "/v1/integrations/employees/RH-2/rehire",
        json={"hire_date": str(date.today()), "rejoin_mode": "FRESH"},
        headers={**w.erp, "Idempotency-Key": "rh2-bad"},
    )
    assert refused.status_code == 422 and refused.json()["code"] == "REJOIN_NOT_ALLOWED"
    rehired = await ok(client, "POST", "/v1/integrations/employees/RH-2/rehire",
                       json={"hire_date": str(date.today()), "rejoin_mode": "FRESH",
                             "reason": "New contract"},
                       headers={**w.erp, "Idempotency-Key": "rh2-ok"})
    assert rehired["outcome"] == "APPLIED"
    from sqlalchemy import text

    from hrms.core.ids import to_uuid

    async with admin_engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT mode, reason FROM rejoin_records WHERE employment_id = :e"),
            {"e": to_uuid(created["employment_id"])},
        )).one()
    assert tuple(row) == ("FRESH", "New contract")


async def test_a_corrected_hire_date_moves_service_unless_it_was_restarted(api):
    client, admin_engine = api
    from sqlalchemy import text

    from hrms.core.ids import to_uuid

    w = await world(client)
    body = w.new_hire()
    created = (await w.put("HD-1", expect=201, **body)).json()
    employment = to_uuid(created["employment_id"])

    async def service_dates():
        async with admin_engine.connect() as conn:
            return tuple((await conn.execute(
                text("SELECT hire_date, continuity_start_date FROM employments WHERE id = :e"),
                {"e": employment},
            )).one())

    hired, counted_from = await service_dates()
    assert hired == counted_from
    corrected = date(2019, 5, 6)
    await w.put("HD-1", **{**body, "hire_date": corrected.isoformat()})
    assert await service_dates() == (corrected, corrected)  # service follows the correction

    async with admin_engine.begin() as conn:  # a "start fresh" rejoin moved service forward
        await conn.execute(
            text("UPDATE employments SET continuity_start_date = :d WHERE id = :e"),
            {"d": date(2025, 1, 1), "e": employment},
        )
    await w.put("HD-1", **{**body, "hire_date": "2018-02-03"})
    assert await service_dates() == (date(2018, 2, 3), date(2025, 1, 1))  # and stays there


async def test_simultaneous_creates_for_one_person_make_one_employee(api):
    import asyncio

    client, admin_engine = api
    w = await world(client)
    body = w.new_hire()
    responses = await asyncio.gather(*(w.put("SAME-1", **body) for _ in range(10)))
    outcomes = sorted(r.json()["outcome"] for r in responses)
    assert outcomes.count("CREATED") == 1, outcomes
    assert set(outcomes) <= {"CREATED", "NO_CHANGE"}
    from sqlalchemy import text

    async with admin_engine.connect() as conn:
        count = (await conn.execute(
            text("SELECT count(*) FROM employments WHERE employee_number = :c"),
            {"c": body["employee_code"]},
        )).scalar_one()
    assert count == 1


async def test_an_app_cannot_take_over_an_hr_or_admin_login(api):
    """Linking an HR employee and then setting their password must be refused."""
    from tests.helpers import make_user

    client, _ = api
    w = await world(client)
    hr = await person_and_employment(client, w.legal_entity, number="HR-77")
    email, _, _ = await make_user(client, hr["id"], role="HR_MANAGER", scope_type="ALL")
    hashed = bcrypt.hashpw(b"Taken-over-1", bcrypt.gensalt(rounds=10)).decode()
    refused = await w.put("TAKE-1", employment_id=hr["id"], password_hash=hashed)
    assert refused.status_code == 403
    assert refused.json()["code"] == "PRIVILEGED_ACCOUNT_PROTECTED"
    moved = await w.put("TAKE-1", employment_id=hr["id"], email=f"x.{uuid4().hex[:6]}@example.com")
    assert moved.json()["code"] == "PRIVILEGED_ACCOUNT_PROTECTED"
    # Linking alone (and ordinary fields) is fine; the login is untouched.
    linked = await w.put("TAKE-1", expect=200, employment_id=hr["id"], first_name="Hari")
    assert linked.json()["outcome"] == "LINKED"
    async with client_from("10.0.0.9") as fresh:
        assert (await sign_in(fresh, email, "Taken-over-1")).status_code == 401


async def test_a_mapping_to_another_companys_department_is_refused(api):
    client, _ = api
    w = await world(client)
    other = await ok(client, "POST", "/v1/org/legal-entities", headers=w.admin,
                     json={"name": "Other Co " + uuid4().hex[:4], "country_code": "IN"})
    foreign = await ok(client, "POST", "/v1/org/org-units", headers=w.admin,
                       json={"name": "Foreign Ops", "type": "DEPARTMENT",
                             "legal_entity_id": other["id"], "effective_from": "2020-01-01"})
    await ok(client, "POST", f"/v1/admin/integrations/apps/{w.app['id']}/mappings",
             headers=w.admin, json={"kind": "DEPARTMENT", "external_value": "FX",
                                    "target_id": foreign["id"]})
    refused = await w.put("MX-1", **w.new_hire(department="FX"))
    assert refused.status_code == 422
    assert refused.json()["code"] == "MAPPING_OTHER_COMPANY_DEPARTMENT"
