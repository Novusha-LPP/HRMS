"""Real PostgreSQL regression tests. Only explicit *_test databases are accepted."""

import asyncio
import json
import os
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hrms.core.ids import to_uuid
from tests.helpers import employee, ok, tenant

pytestmark = pytest.mark.database


async def test_end_to_end_integrity_and_workflows(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, login = await employee(client, company)
    emp_header = {"Authorization": "Bearer " + login["access_token"]}
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])

    # Forged historical punches cannot bypass approval.
    response = await client.post(
        "/v1/time/punches",
        headers=emp_header,
        json={"punch_type": "IN", "punched_at": "2020-01-01T09:00:00Z"},
    )
    assert response.status_code == 422

    # Corrections preserve event history, including partial missing punches.
    day = date.today() - timedelta(days=1)
    correction = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=emp_header,
        json={
            "work_date": day.isoformat(),
            "correction_type": "PUNCH_IN",
            "requested_punch_in": day.isoformat() + "T09:00:00Z",
            "reason": "Missing IN",
        },
    )
    await ok(
        client, "POST", f"/v1/corrections/{correction['id']}/approve", json={"action": "APPROVE"}
    )
    today = await ok(
        client,
        "GET",
        f"/v1/time/today?employment_id={emp['id']}&work_date={day}",
        headers=emp_header,
    )
    assert (
        today["first_punch_in"]
        and len(today["punches"]) == 1
        and today["punches"][0]["is_corrected"]
    )
    out = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=emp_header,
        json={
            "work_date": day.isoformat(),
            "correction_type": "PUNCH_OUT",
            "requested_punch_out": day.isoformat() + "T18:00:00Z",
            "reason": "Missing OUT",
        },
    )
    await ok(client, "POST", f"/v1/corrections/{out['id']}/approve", json={"action": "APPROVE"})
    today = await ok(
        client,
        "GET",
        f"/v1/time/today?employment_id={emp['id']}&work_date={day}",
        headers=emp_header,
    )
    assert len(today["punches"]) == 2 and today["effective_minutes"] == 540
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE attendance_days SET is_locked = true "
                "WHERE tenant_id=:tid AND employment_id=:eid"
            ),
            {"tid": tid, "eid": eid},
        )
    correction = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=emp_header,
        json={
            "work_date": day.isoformat(),
            "correction_type": "MARK_ABSENT",
            "reason": "Locked period",
        },
    )
    response = await client.post(
        f"/v1/corrections/{correction['id']}/approve", json={"action": "APPROVE"}
    )
    assert response.status_code == 409

    # Entitlements spanning a financial-year boundary (default: April) are allocated
    # and released against both FYs, not just the calendar year the leave started in.
    year = date.today().year + 1
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        # High enough that one month's accrual (days_per_year / 12) comfortably
        # covers the handful of working days on each side of the boundary below.
        json={"name": "Annual", "code": "AL", "days_per_year": 120, "accrual_enabled": True},
    )
    # Accrual refuses a future period, so credit *this* month — the future leave
    # dates below inherit it via the ledger's prior-row lookup (nothing else
    # exists in between), proving accrual now, apply-for-later-FY works.
    await ok(client, "POST", "/v1/leave/accrual/run")
    leave = await ok(
        client,
        "POST",
        "/v1/leave/applications",
        headers=emp_header,
        json={
            "leave_type_id": lt["id"],
            "from_date": f"{year}-03-29",
            "to_date": f"{year}-04-04",
        },
    )
    await ok(
        client, "POST", f"/v1/leave/applications/{leave['id']}/submit", headers=emp_header, json={}
    )
    await ok(
        client, "POST", f"/v1/leave/applications/{leave['id']}/approve", json={"action": "APPROVE"}
    )
    # March 29-31 falls in FY(year-1) (Apr(year-1)-Mar(year)); April 1-4 falls in FY(year).
    used = []
    for fy in [year - 1, year]:
        balance = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}&year={fy}")
        assert balance[0]["pending_days"] == 0 and balance[0]["used_days"] > 0
        used.append(balance[0]["used_days"])
    assert sum(used) == leave["days_requested"]
    await ok(
        client,
        "POST",
        f"/v1/leave/applications/{leave['id']}/cancel",
        headers=emp_header,
        json={"cancel_reason": "Plans changed"},
    )
    for fy in [year - 1, year]:
        balance = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}&year={fy}")
        assert balance[0]["used_days"] == 0

    # KYC edits invalidate the verified snapshot and authenticated downloads work.
    await ok(client, "PATCH", "/v1/kyc/me", headers=emp_header, json={"account_number": "123456"})
    await ok(client, "POST", f"/v1/kyc/employees/{emp['id']}/verify", json={"status": "VERIFIED"})
    record = await ok(
        client, "PATCH", "/v1/kyc/me", headers=emp_header, json={"account_number": "654321"}
    )
    assert record["status"] == "DRAFT" and record["verified_at"] is None
    doc = await ok(
        client,
        "POST",
        "/v1/kyc/me/documents",
        headers=emp_header,
        files={"file": ("proof.pdf", b"%PDF-1.4 test", "application/pdf")},
        data={"document_type": "BANK_PROOF", "document_title": "Bank proof"},
    )
    response = await client.get(doc["download_url"], headers=emp_header)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    response = await client.post(
        "/v1/kyc/me/documents",
        headers=emp_header,
        files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")},
        data={"document_type": "BANK_PROOF", "document_title": "Invalid"},
    )
    assert response.status_code == 415

    # Future separation is scheduled and does not immediately remove the employee.
    action = await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={"employment_id": emp["id"], "type": "SEPARATION", "effective_date": "2099-01-01"},
    )
    assert action["status"] == "SCHEDULED"
    current = await ok(client, "GET", f"/v1/employees/{emp['id']}")
    assert current["employment_state"] != "SEPARATED"

    # Revocation applies to already-issued JWTs, even without changing roles.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE user_accounts SET status='SUSPENDED' WHERE tenant_id=:tid AND id=:uid"),
            {"tid": tid, "uid": to_uuid(login["user"]["id"])},
        )
    response = await client.get("/v1/auth/me", headers=emp_header)
    assert response.status_code == 401


async def test_database_rls_and_composite_references(api):
    client, engine = api
    first = await tenant(client)
    emp, _ = await employee(client, first["user"]["legal_entities"][0]["id"])
    second = await tenant(client)
    # RLS hides the first tenant, even if SQL omits an application tenant filter.
    runtime_url = make_url(os.environ["HRMS_TEST_DATABASE_URL"]).set(
        username="hrms_app", password="hrms_app_dev_password"
    )
    runtime = create_async_engine(runtime_url, poolclass=NullPool)
    async with runtime.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(to_uuid(second["user"]["tenant_id"]))},
        )
        rows = (await conn.execute(text("SELECT id FROM employments"))).all()
        assert to_uuid(emp["id"]) not in {r[0] for r in rows}
    await runtime.dispose()
    response = await client.post(
        "/v1/employees",
        json={
            "person_id": emp["person_id"],
            "legal_entity_id": second["user"]["legal_entities"][0]["id"],
            "employee_number": "FORGED",
            "hire_date": "2020-01-01",
        },
    )
    assert response.status_code == 422


async def test_concurrent_leave_and_read_only_writes(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, login = await employee(client, company)
    emp_header = {"Authorization": "Bearer " + login["access_token"]}
    year = date.today().year + 1
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        # 12/12 = exactly 1 day/month accrued — one clean, exact day available,
        # so the two 1-day applications below really are racing for the same day.
        json={"name": "Limited", "code": "LTD", "days_per_year": 12, "accrual_enabled": True},
    )
    # Accrual refuses a future period; credit this month and let the future
    # applications below inherit it via the ledger's prior-row lookup.
    await ok(client, "POST", "/v1/leave/accrual/run")
    first = date(year, 2, 1)
    while first.weekday() >= 5:
        first += timedelta(days=1)
    second = first + timedelta(days=7)
    ids = []
    for day in [first, second]:
        row = await ok(
            client,
            "POST",
            "/v1/leave/applications",
            headers=emp_header,
            json={"leave_type_id": lt["id"], "from_date": str(day), "to_date": str(day)},
        )
        ids.append(row["id"])
    responses = await asyncio.gather(
        *(
            client.post(f"/v1/leave/applications/{i}/submit", headers=emp_header, json={})
            for i in ids
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    # January/February fall in FY(year-1) under the default April-start financial year.
    balances = await ok(
        client, "GET", f"/v1/leave/balances?employment_id={emp['id']}&year={year - 1}"
    )
    assert balances[0]["pending_days"] == 1

    email = uuid4().hex + "@example.com"
    await ok(
        client,
        "POST",
        "/v1/users",
        json={
            "email": email,
            "password": "Test-password-123",
            "role": "ACCOUNTANT",
            "scope_type": "LEGAL_ENTITY",
            "legal_entity_ids": [company],
        },
    )
    account = await ok(
        client, "POST", "/v1/auth/login", json={"email": email, "password": "Test-password-123"}
    )
    headers = {"Authorization": "Bearer " + account["access_token"]}
    response = await client.post(
        f"/v1/time/punches?employment-id={emp['id']}", headers=headers, json={"punch_type": "IN"}
    )
    assert response.status_code == 403
    response = await client.post(
        f"/v1/corrections?employment_id={emp['id']}",
        headers=headers,
        json={
            "work_date": str(first),
            "correction_type": "MARK_ABSENT",
            "reason": "Not authorized",
        },
    )
    assert response.status_code == 403


async def test_mixed_role_write_scope_over_http(api):
    client, engine = api
    admin = await tenant(client)
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": "Company B", "country_code": "IN"},
        )
    )["id"]
    a, _ = await employee(client, company_a)
    b, _ = await employee(client, company_b)
    email = uuid4().hex + "@example.com"
    account = await ok(
        client,
        "POST",
        "/v1/users",
        json={
            "email": email,
            "password": "Test-password-123",
            "role": "HR_MANAGER",
            "scope_type": "LEGAL_ENTITY",
            "legal_entity_ids": [company_a],
        },
    )
    async with engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO role_assignments
                (tenant_id,id,user_account_id,role_id,scope_type,scope_value)
                SELECT :tid,:id,:uid,id,'LEGAL_ENTITY',:scope FROM roles
                WHERE tenant_id=:tid AND name='ACCOUNTANT'"""),
            {
                "tid": to_uuid(admin["user"]["tenant_id"]),
                "id": uuid4(),
                "uid": to_uuid(account["id"]),
                "scope": json.dumps([company_b]),
            },
        )
    login = await ok(
        client, "POST", "/v1/auth/login", json={"email": email, "password": "Test-password-123"}
    )
    headers = {"Authorization": "Bearer " + login["access_token"]}
    assert (await client.get(f"/v1/employees/{b['id']}", headers=headers)).status_code == 200
    for emp, expected in [(a, 201), (b, 403)]:
        response = await client.post(
            "/v1/personnel-actions",
            headers=headers,
            json={
                "employment_id": emp["id"],
                "type": "CONFIRM",
                "effective_date": str(date.today()),
            },
        )
        assert response.status_code == expected, response.text
