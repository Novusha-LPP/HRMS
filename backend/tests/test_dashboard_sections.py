"""
The newer HR dashboard sections, against a company built so every figure is known:
trends, exits, vacancies, statutory IDs, worker types, lifecycle, today's highlights,
scheduled changes and the action centre — and that a company-scoped HR manager sees only
their company.
"""

import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

PASSWORD = "Test-password-123"
SECTIONS = (
    "trends,exits,vacancies,statutory,worker_types,lifecycle,highlights_today,"
    "scheduled_changes,action_centre,attendance_30d,leave_by_department"
)


def _years_ago(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


async def _company(client, engine):
    today = date.today()
    month_start = today.replace(day=1)
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    place = await org_basics(client, company)
    emp = {}
    for label in ("joiner", "prober", "leaver", "gone", "past", "birthday"):
        emp[label] = to_uuid((await person_and_employment(client, company))["id"])
    other_company = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "B", "country_code": "IN"})
    )["id"]
    other_emp = to_uuid((await person_and_employment(client, other_company))["id"])

    async with engine.begin() as conn:
        q = conn.execute
        await q(
            text("UPDATE employments SET employment_state = 'ACTIVE' WHERE id = :e"),
            {"e": other_emp},
        )
        for label, state, hire, separated in (
            ("joiner", "ACTIVE", today, None),
            ("prober", "PROBATION", today - timedelta(days=400), None),
            ("leaver", "NOTICE", _years_ago(today, 3), None),
            ("gone", "SEPARATED", date(2020, 1, 1), today),
            ("past", "SEPARATED", date(2020, 1, 1), month_start - timedelta(days=1)),
            ("birthday", "ACTIVE", date(2020, 2, 3), None),
        ):
            await q(
                text("""UPDATE employments SET employment_state = :s, hire_date = :h,
                            separation_date = :sep WHERE id = :e"""),
                {"s": state, "h": hire, "sep": separated, "e": emp[label]},
            )
            await q(
                text("""UPDATE persons SET legal_first_name = :n, legal_last_name = 'Case'
                        WHERE id = (SELECT person_id FROM employments WHERE id = :e)"""),
                {"n": label.title(), "e": emp[label]},
            )
        await q(
            text("""UPDATE persons SET date_of_birth = :dob
                    WHERE id = (SELECT person_id FROM employments WHERE id = :e)"""),
            {"dob": _years_ago(today, 30), "e": emp["birthday"]},
        )
        position = uuid4()
        await q(
            text("""INSERT INTO positions (tenant_id, id, title, org_unit_id, max_headcount,
                        status, effective_from)
                    VALUES (:t, :id, 'Operator', :ou, 3, 'ACTIVE', '2020-01-01')"""),
            {"t": tid, "id": position, "ou": to_uuid(place["org_unit_id"])},
        )
        await q(
            text("""INSERT INTO assignments (tenant_id, id, employment_id, effective_from,
                        org_unit_id, location_id, job_id, position_id, worker_type)
                    VALUES (:t, :id, :e, '2020-01-01', :ou, :loc, :job, :pos, 'CONTRACT')"""),
            {
                "t": tid,
                "id": uuid4(),
                "e": emp["joiner"],
                "ou": to_uuid(place["org_unit_id"]),
                "loc": to_uuid(place["location_id"]),
                "job": to_uuid(place["job_id"]),
                "pos": position,
            },
        )
        await q(
            text("""INSERT INTO employee_kyc_records (tenant_id, id, employment_id, uan_number,
                        pf_number, esi_number, passport_expiry)
                    VALUES (:t, :id, :e, '100200300400', 'PF123', 'ESI123', :exp)"""),
            {"t": tid, "id": uuid4(), "e": emp["birthday"], "exp": today + timedelta(days=30)},
        )
        for label, kind, status, effective in (
            ("leaver", "SEPARATION", "SCHEDULED", today + timedelta(days=10)),
            ("joiner", "CONFIRM", "APPLIED", today),
        ):
            await q(
                text("""INSERT INTO personnel_actions (tenant_id, id, employment_id, type,
                            effective_date, changes, status)
                        VALUES (:t, :id, :e, :type, :eff, CAST(:changes AS jsonb), :status)"""),
                {
                    "t": tid,
                    "id": uuid4(),
                    "e": emp[label],
                    "type": kind,
                    "eff": effective,
                    "changes": json.dumps({}),
                    "status": status,
                },
            )
    return other_company


async def test_every_new_section_counts_the_known_cases(api):
    client, engine = api
    await _company(client, engine)
    d = await ok(client, "GET", f"/v1/dashboard/hr?sections={SECTIONS},headcount")

    # The tenant admin sees both companies. Current: joiner, prober, leaver, birthday and
    # company B's employee (gone/past are separated).
    assert d["headcount"]["total"] == 5
    # At the start of this month: prober, leaver, gone (left this month), birthday, B's.
    assert d["trends"]["headcount_last_month"] == 5
    assert (d["exits"]["exits_this_month"], d["exits"]["exits_last_month"]) == (1, 1)
    assert d["exits"]["exits_last_12_months"] == 2
    assert d["exits"]["attrition_12m_pct"] == 40.0
    assert d["exits"]["on_notice"] == 1

    assert d["vacancies"] == {"positions": 1, "capacity": 3, "filled": 1, "vacancies": 2}
    s = d["statutory"]
    assert (s["employees"], s["no_kyc_record"], s["missing_uan"], s["passports_expiring"]) == (
        5,
        4,
        4,
        1,
    )
    assert {w["worker_type"]: w["count"] for w in d["worker_types"]} == {
        "CONTRACT": 1,
        "UNASSIGNED": 4,
    }

    lc = d["lifecycle"]
    assert (lc["on_probation"], lc["on_notice"], lc["confirmed_this_month"]) == (1, 1, 1)
    [longest] = lc["longest_on_probation"]
    assert longest["name"] == "Prober Case" and longest["months"] >= 12

    h = d["highlights_today"]
    assert [p["name"] for p in h["joining"]] == ["Joiner Case"]
    assert [p["name"] for p in h["exiting"]] == ["Gone Case"]
    assert [p["name"] for p in h["birthdays"]] == ["Birthday Case"]
    assert [(p["name"], p["years"]) for p in h["anniversaries"]] == [("Leaver Case", 3)]

    [change] = d["scheduled_changes"]
    assert (change["name"], change["type"], change["days_until"]) == (
        "Leaver Case",
        "SEPARATION",
        10,
    )

    centre = {i["key"]: i["count"] for i in d["action_centre"]}
    assert centre["statutory"] == 4 and centre["passports"] == 1
    assert centre["leave_approvals"] == 0

    assert d["attendance_30d"] == {"avg_present_pct": None, "previous_pct": None, "days": 0}
    assert d["leave_by_department"] == []


async def test_a_company_scoped_manager_sees_only_their_company(api):
    client, engine = api
    other_company = await _company(client, engine)
    email, _, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[other_company]
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": "Bearer " + login["access_token"]}
    d = await ok(client, "GET", f"/v1/dashboard/hr?sections={SECTIONS}", headers=headers)

    assert d["statutory"]["employees"] == 1  # company B's one employee
    assert d["vacancies"]["positions"] == 0  # the position belongs to company A
    assert d["exits"]["exits_last_12_months"] == 0
    assert all(not people for people in d["highlights_today"].values())
    assert d["scheduled_changes"] == []
    assert d["lifecycle"]["on_probation"] == 0  # A's prober is not visible


async def test_company_focus_narrows_and_never_widens(api):
    client, engine = api
    other_company = await _company(client, engine)
    entities = await ok(client, "GET", "/v1/org/legal-entities")
    [company_a] = [e["id"] for e in entities if e["id"] != other_company]
    sections = "statutory,vacancies,exits,headcount"

    focus_b = await ok(
        client, "GET", f"/v1/dashboard/hr?sections={sections}&legal_entity_id={other_company}"
    )
    assert focus_b["statutory"]["employees"] == 1
    assert focus_b["vacancies"]["positions"] == 0
    assert focus_b["exits"]["exits_last_12_months"] == 0

    everything = await ok(client, "GET", f"/v1/dashboard/hr?sections={sections}")
    assert everything["statutory"]["employees"] == 5

    # A manager scoped to company B asking for company A gets nothing, not company A.
    email, _, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[other_company]
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": "Bearer " + login["access_token"]}
    sneaky = await ok(
        client,
        "GET",
        f"/v1/dashboard/hr?sections={sections}&legal_entity_id={company_a}",
        headers=headers,
    )
    assert sneaky["statutory"]["employees"] == 0
    assert sneaky["headcount"]["total"] == 0
    assert sneaky["vacancies"]["positions"] == 0

    bad = await client.get("/v1/dashboard/hr?sections=headcount&legal_entity_id=not-an-id")
    assert bad.status_code == 422
