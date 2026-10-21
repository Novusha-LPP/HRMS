"""Reference paid-day conventions and read-only, scoped attendance report behavior."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hrms.modules.reports.attendance_schemas import (
    AttendanceSummaryDay,
    AttendanceSummaryEmployee,
    AttendanceSummaryMetrics,
)
from hrms.modules.reports.attendance_service import (
    aggregate_metrics,
    apply_ledger_balances,
    is_privilege_leave,
    leave_covers_date,
    summarize_days,
    validate_period,
)


def day(status="PRESENT", **overrides):
    values = dict(
        work_date=date(2026, 9, 1),
        day_name="Tuesday",
        shift_start="10:00",
        shift_end="19:00",
        timezone="Asia/Kolkata",
        status=status,
        is_working_day=status not in {"WEEKEND", "HOLIDAY"},
    )
    values.update(overrides)
    return AttendanceSummaryDay(**values)


def test_reference_paid_days_and_fractional_presence():
    days = [day() for _ in range(22)] + [
        day("HALF_DAY", paid_leave_days=0.5, half_day_pl=1),
        day("ON_LEAVE", paid_leave_days=1, full_day_pl=1, leave_type="Privilege Leave"),
    ]
    days += [day("WEEKEND") for _ in range(5)] + [day("HOLIDAY")]
    metrics = summarize_days(days)
    assert metrics.present_days == 22.5
    assert metrics.total_pl_taken == 1.5
    assert (metrics.half_day_pl, metrics.full_day_pl) == (1, 1)
    assert metrics.total_working_days == 30
    assert metrics.absent_days == 0


def test_half_absent_and_lwp_are_not_paid():
    metrics = summarize_days(
        [day("HALF_DAY"), day("ON_LEAVE", lwp_days=1, leave_type="Leave Without Pay")]
    )
    assert metrics.present_days == 0.5
    assert metrics.absent_days == 0.5
    assert metrics.total_working_days == 0.5
    assert metrics.lwp_taken == 1


def test_work_time_uses_actual_worked_dates_and_preserves_minutes():
    metrics = summarize_days([day(effective_minutes=540), day("HALF_DAY", effective_minutes=180)])
    assert metrics.present_days == 1.5
    assert metrics.worked_days == 2
    assert metrics.total_work_minutes == 720
    assert metrics.average_hours_per_day == 6
    upcoming = summarize_days([day("UPCOMING")])
    assert upcoming.absent_days == 0
    assert upcoming.average_hours_per_day is None


def test_worked_holiday_and_weekend_are_counted_once():
    punched = datetime(2026, 9, 1, 4, tzinfo=UTC)
    m = summarize_days(
        [day("HOLIDAY", first_punch_in=punched), day("WEEKEND", first_punch_in=punched)]
    )
    assert m.total_working_days == 2
    assert m.present_days == 2
    assert (m.week_off_days, m.holiday_days) == (0, 0)


def test_recorded_leave_without_approved_entitlement_is_not_inferred_absent():
    m = summarize_days([day("ON_LEAVE")])
    assert (m.absent_days, m.total_pl_taken, m.lwp_taken) == (0, 0, 0)
    assert m.present_days == 0


def test_known_approved_half_day_leave_without_work_has_half_absent():
    m = summarize_days(
        [day("ON_LEAVE", paid_leave_days=0.5, half_day_pl=1, leave_type="Privilege Leave")]
    )
    assert m.total_pl_taken == 0.5
    assert m.absent_days == 0.5
    assert m.present_days == 0


def test_future_approved_half_leave_retains_leave_without_accruing_absence(monkeypatch):
    from hrms.modules.reports import attendance_service as attendance

    monkeypatch.setattr(attendance, "business_today", lambda tz=None: date(2026, 9, 1))
    m = summarize_days(
        [
            day(
                "ON_LEAVE",
                work_date=date(2026, 9, 2),
                paid_leave_days=0.5,
                half_day_pl=1,
                leave_type="Privilege Leave",
            )
        ]
    )
    assert m.total_pl_taken == 0.5
    assert m.absent_days == 0


def test_persisted_holiday_without_current_calendar_row_is_not_absent():
    m = summarize_days([day("HOLIDAY", is_working_day=True)])
    assert m.absent_days == 0
    assert m.holiday_days == 1
    assert m.total_working_days == 1


def test_explicit_calendar_allocation_preserves_sandwich_leave():
    source = {
        "from_date": date(2026, 9, 5),
        "to_date": date(2026, 9, 7),
        "half_day_option": "NONE",
        "days_by_month": {"2026-09": 3},
    }
    assert leave_covers_date(source, date(2026, 9, 6), False, None)
    assert leave_covers_date(source, date(2026, 9, 7), True, "Holiday")
    working_only = {**source, "days_by_month": {"2026-09": 1}}
    assert not leave_covers_date(working_only, date(2026, 9, 6), False, None)


@pytest.mark.parametrize(
    "code,name,paid,comp,expected",
    [
        ("PL", "Annual entitlement", True, False, True),
        ("EXIMPL", "Privilege Leave (Suraj Group)", True, False, True),
        ("EXPL123ABC", "Old entitlement", True, False, True),
        ("LEGACY", "Privilege Leave — Company", True, False, True),
        ("CL", "Casual Leave", True, False, False),
        ("SL", "Sick Leave", True, False, False),
        ("PL", "Privilege Leave", False, False, False),
        ("PL", "Privilege Leave", True, True, False),
    ],
)
def test_only_explicit_privilege_leave_is_pl(code, name, paid, comp, expected):
    assert is_privilege_leave(code, name, paid, comp) is expected


def ledger(**overrides):
    values = dict(
        bucket_id=uuid4(),
        bucket_code="PL",
        bucket_name="Privilege Leave",
        type_code="PL",
        type_name="Privilege Leave",
        is_paid=True,
        is_comp_off=False,
        calendar_year=2026,
        calendar_month=9,
        opening=8,
        taken=1.5,
        closing=7.5,
        held=0.5,
    )
    values.update(overrides)
    return values


def test_ledger_preserves_opening_credits_and_holds_without_inventing_zero():
    m = AttendanceSummaryMetrics()
    apply_ledger_balances(m, [ledger()], date(2026, 9, 1), date(2026, 9, 30))
    assert (m.opening_balance, m.pl_taken, m.available_balance) == (8, 1.5, 7)
    missing = AttendanceSummaryMetrics()
    apply_ledger_balances(missing, [], date(2026, 9, 1), date(2026, 9, 30))
    assert missing.opening_balance is None


def test_shared_pl_and_casual_bucket_is_ambiguous():
    pl = ledger()
    cl = ledger(bucket_id=pl["bucket_id"], type_code="CL", type_name="Casual Leave")
    m = AttendanceSummaryMetrics()
    apply_ledger_balances(m, [pl, cl], date(2026, 9, 1), date(2026, 9, 30))
    assert m.opening_balance is None


def test_missing_month_and_partial_totals_remain_missing():
    m = AttendanceSummaryMetrics()
    apply_ledger_balances(m, [ledger()], date(2026, 9, 1), date(2026, 10, 31))
    assert m.opening_balance is None
    base = dict(
        employment_id="emp_a",
        employee_number="001",
        name="Test",
        legal_entity_id="le_a",
        company="Company",
    )
    employees = [
        AttendanceSummaryEmployee(**base, opening_balance=2),
        AttendanceSummaryEmployee(**{**base, "employment_id": "emp_b"}),
    ]
    assert aggregate_metrics(employees).opening_balance is None


@pytest.mark.parametrize(
    "first,last", [(date(2026, 9, 2), date(2026, 9, 1)), (date(2026, 1, 1), date(2026, 3, 4))]
)
def test_invalid_period_rejected(first, last):
    with pytest.raises(HTTPException) as caught:
        validate_period(first, last)
    assert caught.value.status_code == 422


def test_exactly_62_days_is_allowed():
    validate_period(date(2026, 1, 1), date(2026, 3, 3))


def specs(*items):
    return [dict(field=field, op=operator, value=value) for field, operator, value in items]


def period(first="2026-09-01", last="2026-09-30"):
    return specs(("work_date", "gte", first), ("work_date", "lte", last))


def test_export_merges_runtime_filter_groups_exactly_as_run():
    from hrms.modules.reports.router import FilterSpec, _merged_run_filters

    saved = period() + specs(("department", "eq", "Ops"))
    runtime = [
        FilterSpec(field="work_date", op="gte", value="2026-09-10"),
        FilterSpec(field="work_date", op="gte", value="2026-09-15"),
    ]
    merged = _merged_run_filters(saved, runtime)
    assert merged == saved[1:] + [f.model_dump() for f in runtime]


def test_export_date_operators_intersect_without_default_or_expansion():
    from hrms.modules.reports.router import _attendance_export_filters

    first, last, population = _attendance_export_filters(
        period() + specs(("work_date", "between", ["2026-09-10", "2026-09-20"]))
    )
    assert (first, last, population) == (date(2026, 9, 10), date(2026, 9, 20), [])
    first, last, _ = _attendance_export_filters(specs(("work_date", "eq", "2026-09-17")))
    assert first == last == date(2026, 9, 17)


@pytest.mark.parametrize(
    "filters",
    [
        [],
        specs(("work_date", "gte", "2026-09-01")),
        specs(("work_date", "gte", ""), ("work_date", "lte", "")),
        period("2026-01-01", "2026-03-04"),
        period("2026-09-30", "2026-09-01"),
        specs(("work_date", "eq", "2026-02-30")),
        period() + specs(("status", "eq", "PRESENT")),
        period() + specs(("department", "contains", "Ops")),
        period() + specs(("department", "in", [])),
        period() + specs(("unknown_field", "eq", "whatever")),
        period() + specs(("employment_id", "eq", "invalid")),
    ],
)
def test_export_rejects_unbounded_or_unrepresentable_filters(filters):
    from hrms.modules.reports.router import _attendance_export_filters

    with pytest.raises(HTTPException) as caught:
        _attendance_export_filters(filters)
    assert caught.value.status_code == 422


def test_export_population_keeps_every_constraint_as_bound_parameters():
    from hrms.core.ids import to_typed_id
    from hrms.modules.reports.attendance_service import (
        day_matches_population_filters,
        population_filter_sql,
    )
    from hrms.modules.reports.router import _attendance_export_filters

    eid = uuid4()
    requested = specs(
        ("employment_id", "eq", to_typed_id("employment", eid)),
        ("department", "in", ["Ops", "Finance' OR 1=1 --"]),
        ("location", "eq", "HQ"),
    )
    _, _, population = _attendance_export_filters(period() + requested)
    assert population == requested
    clause, params = population_filter_sql(population)
    assert "Finance' OR 1=1 --" not in clause
    assert str(eid) in params.values()
    assert "Finance' OR 1=1 --" in params.values()
    assert "filter_assignment.effective_to" in clause
    assert day_matches_population_filters(
        population, {"assignment_unit_name": "Ops", "location_name": "HQ"}
    )
    assert not day_matches_population_filters(
        population, {"assignment_unit_name": "Ops", "location_name": "Remote"}
    )


async def test_employee_cap_returns_error_instead_of_a_partial_register(monkeypatch):
    from hrms.core.authz import Scope
    from hrms.modules.reports import attendance_service

    async def rows(session, sql, params):
        assert params["limit"] == 2
        return [{"id": uuid4()}, {"id": uuid4()}]

    monkeypatch.setattr(attendance_service, "_rows", rows)
    scope = Scope(True, frozenset(), None, frozenset({"reports.read"}), None, frozenset())
    with pytest.raises(HTTPException) as caught:
        await attendance_service.report_people(
            None, uuid4(), scope, date(2026, 9, 1), date(2026, 9, 30), limit=1
        )
    assert caught.value.status_code == 422
    assert "More than 1 employees" in caught.value.detail


async def saved_report(client, filters=None, module="ATTENDANCE", headers=None):
    from tests.helpers import ok

    return await ok(
        client,
        "POST",
        "/v1/reports",
        json={
            "name": "Attendance Excel",
            "module": module,
            "columns": [{"field": "employee_number", "label": "Employee No.", "visible": True}],
            "filters": period() if filters is None else filters,
        },
        **({"headers": headers} if headers else {}),
    )


def capture_workbook(monkeypatch):
    from hrms.modules.reports import attendance_xlsx

    calls = []
    original = attendance_xlsx.attendance_workbook

    def create(report):
        calls.append(report)
        return original(report)

    monkeypatch.setattr(attendance_xlsx, "attendance_workbook", create)
    return calls


@pytest.mark.database
async def test_existing_report_download_preserves_data_and_runtime_filters(api, monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.core.ids import to_uuid
    from hrms.modules.reports import attendance_service
    from hrms.modules.reports.attendance_xlsx import MIME
    from hrms.modules.time.models import AttendanceDay
    from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

    client, engine = api
    admin = await tenant(client)
    company = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Report Company"})
    placement = await org_basics(client, company["id"])
    employee = await person_and_employment(client, company["id"], "RPT-001")
    await hire(client, employee["id"], placement)
    await person_and_employment(client, company["id"], "OTHER")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(employee["id"])
    monkeypatch.setattr(attendance_service, "business_today", lambda tz=None: date(2026, 10, 17))
    async with AsyncSession(engine) as session:
        session.add(
            AttendanceDay(
                tenant_id=tid,
                id=uuid4(),
                employment_id=eid,
                work_date=date(2026, 9, 1),
                status="HALF_DAY",
                first_punch_in=datetime(2026, 9, 1, 4, tzinfo=UTC),
                last_punch_out=datetime(2026, 9, 1, 7, tzinfo=UTC),
                effective_minutes=180,
                gross_minutes=180,
                break_minutes=0,
                late_by_minutes=12,
            )
        )
        await session.commit()
    report = await saved_report(client, period() + specs(("employment_id", "eq", employee["id"])))
    captured = capture_workbook(monkeypatch)

    async def counts():
        async with engine.connect() as conn:
            return [
                (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tid"), {"tid": tid}
                    )
                ).scalar()
                for table in ("attendance_days", "punches", "leave_monthly_ledger")
            ]

    before = await counts()
    response = await client.post(
        f"/v1/reports/{report['id']}/export-attendance",
        json={"filters": period("2026-09-01", "2026-09-02")},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == MIME
    assert response.headers["cache-control"] == "no-store"
    assert "content-disposition" in response.headers["access-control-expose-headers"].lower()
    assert (
        "AttendanceReport_2026-09-01_to_2026-09-02.xlsx" in response.headers["content-disposition"]
    )
    with ZipFile(BytesIO(response.content)) as workbook:
        assert "xl/worksheets/sheet3.xml" in workbook.namelist()
        assert "xl/charts/chart1.xml" in workbook.namelist()
    data = captured[-1]
    assert len(data["employees"]) == 1
    employee_data = data["employees"][0]
    assert len(employee_data["days"]) == 2
    assert employee_data["present_days"] == 0.5
    assert employee_data["absent_days"] == 1.5
    assert employee_data["total_work_minutes"] == 180
    assert employee_data["opening_balance"] is None
    assert employee_data["days"][0]["department_id"] == placement["org_unit_id"]
    assert await counts() == before
    bad = await client.post(
        f"/v1/reports/{report['id']}/export-attendance",
        json={"filters": specs(("status", "eq", "PRESENT"))},
    )
    assert bad.status_code == 422
    assert "Remove the status filter" in bad.json()["detail"]
    unbounded = await saved_report(client, [])
    bad = await client.post(
        f"/v1/reports/{unbounded['id']}/export-attendance", json={"filters": []}
    )
    assert bad.status_code == 422
    not_attendance = await saved_report(client, [], "EMPLOYEE")
    bad = await client.post(
        f"/v1/reports/{not_attendance['id']}/export-attendance", json={"filters": period()}
    )
    assert bad.status_code == 422


@pytest.mark.database
async def test_export_applies_department_location_per_date_and_retains_historical_staff(
    api, monkeypatch
):
    from sqlalchemy import text

    from hrms.core.ids import to_uuid
    from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

    client, engine = api
    admin = await tenant(client)
    company = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Transfers"})
    placement = await org_basics(client, company["id"])
    employee = await person_and_employment(client, company["id"], "FORMER-TRANSFER")
    await hire(client, employee["id"], placement)
    finance = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Finance",
            "type": "DEPARTMENT",
            "legal_entity_id": company["id"],
            "effective_from": "2020-01-01",
        },
    )
    remote = await ok(
        client,
        "POST",
        "/v1/org/locations",
        json={"name": "Remote", "type": "OFFICE", "legal_entity_id": company["id"]},
    )
    await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={
            "employment_id": employee["id"],
            "type": "TRANSFER",
            "effective_date": "2026-09-16",
            "changes": {**placement, "org_unit_id": finance["id"], "location_id": remote["id"]},
        },
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE employments SET separation_date='2026-09-20',employment_state='SEPARATED' "
                "WHERE tenant_id=:tid AND id=:eid"
            ),
            {"tid": to_uuid(admin["user"]["tenant_id"]), "eid": to_uuid(employee["id"])},
        )
    report = await saved_report(client)
    captured = capture_workbook(monkeypatch)
    path = f"/v1/reports/{report['id']}/export-attendance"
    response = await client.post(
        path, json={"filters": specs(("department", "eq", "Ops"), ("location", "in", ["HQ"]))}
    )
    assert response.status_code == 200, response.text
    assert len(captured[-1]["employees"]) == 1
    assert [d["work_date"].day for d in captured[-1]["employees"][0]["days"]] == list(range(1, 16))
    assert captured[-1]["employees"][0]["department"] == "Ops"
    assert captured[-1]["employees"][0]["department_id"] == placement["org_unit_id"]
    response = await client.post(
        path, json={"filters": specs(("department", "eq", "Finance"), ("location", "eq", "Remote"))}
    )
    assert response.status_code == 200, response.text
    assert [d["work_date"].day for d in captured[-1]["employees"][0]["days"]] == list(range(16, 21))
    assert captured[-1]["employees"][0]["department"] == "Finance"
    assert captured[-1]["employees"][0]["department_id"] == finance["id"]
    response = await client.post(
        path, json={"filters": specs(("department", "eq", "Ops"), ("location", "eq", "Remote"))}
    )
    assert response.status_code == 200, response.text
    assert captured[-1]["employees"] == []


@pytest.mark.database
async def test_export_scope_cannot_expand_company_or_leave_ledger_access(api, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.core.ids import to_uuid
    from hrms.modules.leave.models import (
        LeaveBalanceBucket,
        LeaveMonthlyLedger,
        LeaveType,
        LeaveTypeBucketMapping,
    )
    from tests.helpers import bearer, make_user, ok, person_and_employment, tenant

    client, engine = api
    admin = await tenant(client)
    visible = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Visible"})
    hidden = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Hidden"})
    employee = await person_and_employment(client, visible["id"], "VISIBLE")
    other = await person_and_employment(client, hidden["id"], "HIDDEN")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(employee["id"])
    type_id, bucket_id = uuid4(), uuid4()
    async with AsyncSession(engine) as session:
        session.add(
            LeaveType(
                tenant_id=tid, id=type_id, name="Privilege Leave", code="PL", days_per_year=12
            )
        )
        session.add(
            LeaveBalanceBucket(tenant_id=tid, id=bucket_id, name="Privilege Leave", code="PL")
        )
        await session.flush()
        session.add(
            LeaveTypeBucketMapping(
                tenant_id=tid, id=uuid4(), leave_type_id=type_id, bucket_id=bucket_id
            )
        )
        session.add(
            LeaveMonthlyLedger(
                tenant_id=tid,
                id=uuid4(),
                employment_id=eid,
                bucket_id=bucket_id,
                calendar_year=2026,
                calendar_month=9,
                fy_year=2026,
                opening=8,
                closing=7,
                taken=1,
            )
        )
        await session.commit()
    report = await saved_report(client)
    email, password, _ = await make_user(
        client, role="ACCOUNTANT", scope_type="LEGAL_ENTITY", legal_entity_ids=[visible["id"]]
    )
    auth = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = bearer(auth["access_token"])
    captured = capture_workbook(monkeypatch)
    path = f"/v1/reports/{report['id']}/export-attendance"
    response = await client.post(path, json={"filters": []}, headers=headers)
    assert response.status_code == 200, response.text
    assert [e["employment_id"] for e in captured[-1]["employees"]] == [employee["id"]]
    assert captured[-1]["employees"][0]["opening_balance"] is None
    response = await client.post(
        path, json={"filters": specs(("employment_id", "eq", other["id"]))}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert captured[-1]["employees"] == []
    response = await client.post(path, json={"filters": []}, headers=bearer(admin["access_token"]))
    assert response.status_code == 200, response.text
    scoped = next(e for e in captured[-1]["employees"] if e["employment_id"] == employee["id"])
    assert scoped["opening_balance"] == 8
    email, password, _ = await make_user(
        client, role="PAYROLL_REVIEWER", scope_type="LEGAL_ENTITY", legal_entity_ids=[visible["id"]]
    )
    auth = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    response = await client.post(path, json={"filters": []}, headers=bearer(auth["access_token"]))
    assert response.status_code == 403
