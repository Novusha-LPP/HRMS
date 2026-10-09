"""Dashboards and daily analysis: scoped callers see only their people, and counts add up."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core import database, perf
from hrms.core.ids import to_uuid
from hrms.modules.dashboard.router import _mmdd_window, _next_occurrence
from hrms.modules.time.presence import classify, is_late, present_sql
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


# ─── pure helpers ────────────────────────────────────────────────────────────


def test_classify_puts_every_day_in_exactly_one_bucket():
    at_work = datetime.now(UTC)
    assert classify("PRESENT", at_work) == "present"
    assert classify("LATE", None) == "present"
    assert classify("PENDING", None) == "present"  # legacy open-session rows
    assert classify("ON_LEAVE", at_work) == "present"  # came in despite approved leave
    assert classify("ABSENT", at_work) == "present"  # a punch wins over a stale ABSENT
    assert classify("ON_LEAVE", None) == "on_leave"
    assert classify("ABSENT", None, on_leave=True) == "on_leave"
    assert classify("ABSENT", None) == "absent"
    assert classify("HOLIDAY", None) == classify("WEEKEND", None) == classify(None, None) == "other"
    assert is_late("LATE", 0) and is_late("PRESENT", 5) and not is_late("PRESENT", 0)
    assert "first_punch_in IS NOT NULL" in present_sql("x") and "x.status IN" in present_sql("x")


def test_upcoming_window_and_next_occurrence_handle_leap_days_and_year_end():
    assert "02-29" in _mmdd_window(date(2027, 2, 20))  # window covers the 28th
    assert "02-29" not in _mmdd_window(date(2027, 6, 1))
    assert _mmdd_window(date(2026, 12, 20))[0] == "01-01"  # wraps into January, sorted
    assert len(_mmdd_window(date(2026, 3, 1))) == 46
    assert _next_occurrence(date(1992, 2, 29), date(2027, 2, 1)) == date(2027, 2, 28)
    assert _next_occurrence(date(1992, 2, 29), date(2028, 2, 1)) == date(2028, 2, 29)
    assert _next_occurrence(date(1990, 3, 5), date(2026, 3, 5)) == date(2026, 3, 5)  # today counts
    assert _next_occurrence(date(1990, 3, 4), date(2026, 3, 5)) == date(2027, 3, 4)


# ─── HR dashboard ────────────────────────────────────────────────────────────


async def _seed_company(client, engine, tid, legal_entity, tag, count=2, **first_person):
    placement = await org_basics(client, legal_entity)
    people = []
    for i in range(count):
        extra = first_person if i == 0 else {}
        emp = await person_and_employment(client, legal_entity, f"{tag}{i}", **extra)
        await hire(client, emp["id"], placement)
        people.append(emp)
    return people


async def _sql(engine, statement, **params):
    async with engine.begin() as conn:
        await conn.execute(text(statement), params)


async def test_hr_dashboard_never_crashes_for_scoped_callers_and_stays_inside_their_company(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": "Company B", "country_code": "IN"},
        )
    )["id"]

    birthday = (TODAY + timedelta(days=5)).replace(year=1990).isoformat()
    a_people = await _seed_company(client, engine, tid, company_a, "A", 2, date_of_birth=birthday)
    b_people = await _seed_company(client, engine, tid, company_b, "B", 2, date_of_birth=birthday)
    anniversary = (TODAY + timedelta(days=3)).replace(year=TODAY.year - 3)
    for emp in (a_people[1], b_people[1]):
        await _sql(
            engine,
            "UPDATE employments SET hire_date = :d WHERE id = :e",
            d=anniversary,
            e=to_uuid(emp["id"]),
        )
    # B has one leaver; A none.
    await _sql(
        engine,
        "UPDATE employments SET employment_state = 'SEPARATED' WHERE id = :e",
        e=to_uuid(b_people[1]["id"]),
    )

    # KYC: A has verified / submitted / not-submitted; B has one verified.
    for emp, state in (
        (a_people[0], "VERIFIED"),
        (a_people[1], "SUBMITTED"),
        (b_people[0], "VERIFIED"),
    ):
        await _sql(
            engine,
            """INSERT INTO employee_kyc_records (tenant_id, id, employment_id, status)
                              VALUES (:t, :i, :e, :s)""",
            t=tid,
            i=uuid4(),
            e=to_uuid(emp["id"]),
            s=state,
        )
    # Attendance today: A present + absent; B on leave + present.
    now = datetime.now(UTC)
    for emp, status, first_in in (
        (a_people[0], "PRESENT", now),
        (a_people[1], "ABSENT", None),
        (b_people[0], "ON_LEAVE", None),
        (b_people[1], "PRESENT", now),
    ):
        await _sql(
            engine,
            """INSERT INTO attendance_days
                              (tenant_id, id, employment_id, work_date, status, first_punch_in)
                              VALUES (:t, :i, :e, :d, :s, :f)""",
            t=tid,
            i=uuid4(),
            e=to_uuid(emp["id"]),
            d=TODAY,
            s=status,
            f=first_in,
        )

    company_hr = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_a]
    )
    accountant_b = await make_user(
        client, role="ACCOUNTANT", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_b]
    )
    hr_a = bearer(
        (
            await ok(
                client,
                "POST",
                "/v1/auth/login",
                json={"identifier": company_hr[0], "password": company_hr[1]},
            )
        )["access_token"]
    )
    acct_b = bearer(
        (
            await ok(
                client,
                "POST",
                "/v1/auth/login",
                json={"identifier": accountant_b[0], "password": accountant_b[1]},
            )
        )["access_token"]
    )

    # The group administrator sees everything (this always worked).
    everyone = await ok(client, "GET", "/v1/dashboard/hr")
    assert everyone["headcount"]["total"] == 3 and everyone["org_summary"]["total_entities"] == 2
    assert everyone["org_summary"]["separated_count"] == 1
    assert (await client.get("/v1/dashboard/super-admin")).status_code == 200

    # A company-scoped HR manager: used to be a 500. Now 200, and only company A.
    dash = await ok(client, "GET", "/v1/dashboard/hr", headers=hr_a)
    assert dash["headcount"]["total"] == 2
    assert dash["today"] == {
        "date": TODAY.isoformat(),
        "present": 1,
        "absent": 1,
        "on_leave": 0,
        "late": 0,
    }
    assert len(dash["entity_distribution"]) == 1
    assert dash["org_summary"]["total_entities"] == 1
    assert dash["org_summary"]["separated_count"] == 0  # B's leaver is not A's business
    kyc = dash["org_summary"]["kyc_compliance"]
    assert (kyc["verified"], kyc["submitted"], kyc["not_submitted"]) == (1, 1, 0)
    assert dash["actions"]["pending_kyc"] == 1
    assert dash["org_summary"]["total_locations"] == 1
    # Everyone here is on PROBATION (the default for a new hire) — they still count.
    assert len(dash["upcoming_birthdays"]) == 1 and len(dash["upcoming_anniversaries"]) == 1
    assert len(dash["recent_joiners"]) == 2
    assert {j["company"] for j in dash["recent_joiners"]} == {
        dash["entity_distribution"][0]["company"]
    }
    assert {b["company"] for b in dash["upcoming_birthdays"]} == {
        dash["entity_distribution"][0]["company"]
    }
    assert (await client.get("/v1/dashboard/super-admin", headers=hr_a)).status_code == 200

    # An accountant scoped to B gets B's numbers only — one active person, one leaver.
    dash_b = await ok(client, "GET", "/v1/dashboard/hr", headers=acct_b)
    assert dash_b["headcount"]["total"] == 1 and dash_b["org_summary"]["separated_count"] == 1
    assert dash_b["today"]["on_leave"] == 1 and dash_b["today"]["present"] == 1
    assert dash_b["org_summary"]["kyc_compliance"]["verified"] == 1
    assert dash_b["entity_distribution"][0]["company"] != dash["entity_distribution"][0]["company"]


async def test_employee_and_manager_dashboards_work_for_ordinary_users(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    email, pw, _ = await make_user(client, emp["id"])
    token = bearer(
        (await ok(client, "POST", "/v1/auth/login", json={"identifier": email, "password": pw}))[
            "access_token"
        ]
    )
    await ok(client, "POST", "/v1/time/punches", headers=token, json={"punch_type": "IN"})
    me = await ok(client, "GET", "/v1/dashboard/employee", headers=token)
    assert me["month_summary"]["present"] == 1 and me["today"]["is_punched_in"] is True
    assert (await client.get("/v1/dashboard/hr", headers=token)).status_code == 403


async def _login(client, email, password):
    response = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    return bearer(response["access_token"])


async def test_employee_dashboard_lists_upcoming_holidays(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    soon, past = TODAY + timedelta(days=10), TODAY - timedelta(days=3)
    for day, name, optional in (
        (soon, "Founders Day", False),
        (soon + timedelta(days=1), "Floating day", True),
        (past, "Yesterday's holiday", False),
    ):
        body = {"holiday_date": str(day), "name": name, "is_optional": optional}
        await ok(client, "POST", "/v1/time/holidays", json=body)
    email, pw, _ = await make_user(client, emp["id"])
    me = await ok(client, "GET", "/v1/dashboard/employee", headers=await _login(client, email, pw))
    assert me["upcoming_holidays"] == [
        {"date": soon.isoformat(), "name": "Founders Day", "is_optional": False, "days_away": 10},
        {
            "date": (soon + timedelta(days=1)).isoformat(),
            "name": "Floating day",
            "is_optional": True,
            "days_away": 11,
        },
    ]


async def test_team_overview_shows_only_the_callers_readable_line_reports(api):
    client, engine = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    boss = await person_and_employment(client, le, "BOSS")
    await hire(client, boss["id"], placement)
    report = await person_and_employment(client, le, "R1")
    await hire(client, report["id"], {**placement, "manager_employment_id": boss["id"]})
    outsider = await person_and_employment(client, le, "O1")
    await hire(client, outsider["id"], placement)

    r_email, r_pw, _ = await make_user(client, report["id"])
    report_token = await _login(client, r_email, r_pw)
    await ok(client, "POST", "/v1/time/punches", headers=report_token, json={"punch_type": "IN"})

    b_email, b_pw, _ = await make_user(
        client, boss["id"], role="MANAGER", scope_type="DIRECT_REPORTS"
    )
    boss_token = await _login(client, b_email, b_pw)
    team = await ok(client, "GET", "/v1/dashboard/team", headers=boss_token)
    assert [m["employee_number"] for m in team["members"]] == ["R1"]
    member = team["members"][0]
    assert member["designation"] == "Executive" and member["department"] == "Ops"
    assert member["today"]["is_checked_in"] is True and member["today"]["first_punch_in"]
    assert member["month"]["present"] == 1
    assert team["upcoming_leave"] == []

    # A plain employee has no reports; an admin login has no employment at all.
    assert (await ok(client, "GET", "/v1/dashboard/team", headers=report_token))["members"] == []
    assert (await client.get("/v1/dashboard/team")).status_code == 400

    # Named someone's line manager but without people.read: nothing beyond themselves.
    o_email, o_pw, _ = await make_user(client, outsider["id"])
    await _sql(
        engine,
        """INSERT INTO assignment_managers
               (tenant_id, id, assignment_id, manager_employment_id, manager_type, effective_from)
           SELECT a.tenant_id, gen_random_uuid(), a.id, :mgr, 'LINE', DATE '2020-01-01'
           FROM assignments a WHERE a.employment_id = :emp""",
        mgr=to_uuid(outsider["id"]),
        emp=to_uuid(report["id"]),
    )
    seen = await ok(
        client, "GET", "/v1/dashboard/team", headers=await _login(client, o_email, o_pw)
    )
    assert seen["members"] == []


# ─── daily analysis ──────────────────────────────────────────────────────────


async def test_daily_analysis_counts_everyone_once_and_stays_in_scope(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "B", "country_code": "IN"})
    )["id"]
    a = await _seed_company(client, engine, tid, company_a, "A", 3)
    await _seed_company(client, engine, tid, company_b, "B", 2)

    monday = date(2026, 9, 28)  # a working day under the default Monday–Friday policy
    leave_type = uuid4()
    await _sql(
        engine,
        """INSERT INTO leave_types (tenant_id, id, name, code, days_per_year)
                          VALUES (:t, :i, 'Casual', 'CL', 12)""",
        t=tid,
        i=leave_type,
    )
    at_work = datetime(2026, 9, 28, 4, 30, tzinfo=UTC)  # 10:00 IST
    # a[0]: approved leave AND came in.  a[1]: approved leave only.  a[2]: nothing (absent).
    await _sql(
        engine,
        """INSERT INTO attendance_days
                          (tenant_id, id, employment_id, work_date, status, first_punch_in)
                          VALUES (:t, :i, :e, :d, 'PRESENT', :f)""",
        t=tid,
        i=uuid4(),
        e=to_uuid(a[0]["id"]),
        d=monday,
        f=at_work,
    )
    for emp in (a[0], a[1]):
        await _sql(
            engine,
            """INSERT INTO leave_applications
                              (tenant_id, id, employment_id, leave_type_id, from_date, to_date,
                               days_requested, status)
                              VALUES (:t, :i, :e, :lt, :d, :d, 1, 'APPROVED')""",
            t=tid,
            i=uuid4(),
            e=to_uuid(emp["id"]),
            lt=leave_type,
            d=monday,
        )

    everyone = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={monday}")
    m = everyone["metrics"]
    assert m["total_headcount"] == 5
    # The person on leave who still punched in is present — and NOT also on leave.
    assert (m["present_count"], m["on_leave_count"], m["absent_count"]) == (1, 1, 3)
    assert m["present_count"] + m["on_leave_count"] + m["absent_count"] <= m["total_headcount"]
    assert m["on_time_count"] + m["late_count"] == m["present_count"]
    dept_total = sum(
        d["present"] + d["on_leave"] + d["absent"] for d in everyone["department_stats"]
    )
    assert dept_total == m["present_count"] + m["on_leave_count"] + m["absent_count"]

    # A company-scoped caller gets only their company — and only their people's data.
    hr = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_b]
    )
    hr_b = bearer(
        (await ok(client, "POST", "/v1/auth/login", json={"identifier": hr[0], "password": hr[1]}))[
            "access_token"
        ]
    )
    scoped = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={monday}", headers=hr_b)
    assert scoped["metrics"]["total_headcount"] == 2
    assert scoped["metrics"]["present_count"] == 0 and scoped["metrics"]["on_leave_count"] == 0
    present_only = await ok(
        client, "GET", f"/v1/time/daily-analysis?work_date={monday}&status=PRESENT"
    )
    assert [r["employee_number"] for r in present_only["employees"]] == ["A0"]


async def test_hr_dashboard_query_budget_stays_below_alert_threshold(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_a = admin["user"]["legal_entities"][0]["id"]
    await _seed_company(client, engine, tid, company_a, "Q", count=3)

    perf.instrument_engine(database.AsyncSessionLocal.kw["bind"])
    seen = []
    perf.REQUEST_OBSERVER = lambda scope, tally: seen.append(tally)
    try:
        # Request all 23 dashboard sections (no sections param means all sections)
        res = await ok(client, "GET", "/v1/dashboard/hr")
        assert res["headcount"]["total"] >= 3
        # Query count regression alert fires when p95 statements > 50.
        # With batched aggregation queries, the count should stay <= 25.
        query_count = seen[-1].count
        assert query_count <= 25, f"Expected <= 25 queries for full dashboard, got {query_count}"

        # Scoped overview request (e.g. from Organization page) should be <= 10
        await ok(
            client,
            "GET",
            "/v1/dashboard/hr?sections=headcount,org_summary,entity_distribution,department_distribution",
        )
        overview_queries = seen[-1].count
        assert overview_queries <= 10, (
            f"Expected <= 10 queries for org overview sections, got {overview_queries}"
        )
    finally:
        perf.REQUEST_OBSERVER = None
