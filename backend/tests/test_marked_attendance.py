"""
Marked attendance (time/groups.py, time/marking.py): people in an attendance group (guards,
drivers…) have each day marked present or absent, optionally with in/out times that count like
punches, by whoever was given MARK on the group; leave is recorded as a from-to range.

Two drivers in the "Drivers" group and one office worker who punches, in the same company, all
on the base policy (09:30–18:30 IST, grace 15). "Today" is Friday 14 Aug 2026.
"""

import itertools
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, hire, make_user, ok, person_and_employment
from tests.test_attendance_cases import at, company, punch, set_clock, staff

pytestmark = pytest.mark.database

TODAY = date(2026, 8, 14)
GROUPS = "/v1/time/attendance-groups"


async def setup(client, monkeypatch):
    admin, le, placement, _ = await company(client, {})
    d1, d1_headers = await staff(client, le, placement, "DRV-1")
    d2, _ = await staff(client, le, placement, "DRV-2")
    office, office_headers = await staff(client, le, placement, "OFF-1")
    drivers = await ok(client, "POST", GROUPS, json={"name": "Drivers", "legal_entity_id": le})
    await ok(
        client,
        "POST",
        f"{GROUPS}/{drivers['id']}/members",
        json={"employment_ids": [d1["id"], d2["id"]], "effective_from": "2026-01-01"},
    )
    from hrms.modules.time import groups, marking, register

    for module in (marking, register, groups):
        monkeypatch.setattr(module, "business_today", lambda tz=None: TODAY)
    set_clock(monkeypatch, at(TODAY, "21:00"))
    # A clock that moves on a second per call, so marks keep their order.
    ticks = itertools.count()
    monkeypatch.setattr(
        marking, "now_utc", lambda: at(TODAY, "21:00") + timedelta(seconds=next(ticks))
    )
    return {
        "le": le,
        "placement": placement,
        "drivers": drivers,
        "d1": d1,
        "d1_headers": d1_headers,
        "d2": d2,
        "office": office,
        "office_headers": office_headers,
        "tid": to_uuid(admin["user"]["tenant_id"]),
    }


async def login_for(client, s, number):
    """A new person with their own EMPLOYEE login, signed in."""
    emp = await person_and_employment(client, s["le"], number)
    await hire(client, emp["id"], s["placement"])
    email, password, user = await make_user(client, emp["id"])
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    return emp, user, bearer(login["access_token"])


async def day_status(client, emp, day):
    reg = await ok(client, "GET", f"/v1/time/register/{emp['id']}?from_date={day}&to_date={day}")
    return reg["days"][0]["status"]


async def row_of(client, day, number, headers=None):
    listing = await ok(client, "GET", f"/v1/time/marking?work_date={day}", headers=headers or {})
    return next(r for r in listing["rows"] if r["employee_number"] == number)


async def mark(client, day, *entries, headers=None, remark=None):
    marks = []
    for emp, status, *times in entries:
        entry = {"employment_id": emp["id"], "status": status}
        if times:
            entry["punch_in"] = times[0]
            if len(times) > 1:
                entry["punch_out"] = times[1]
        marks.append(entry)
    body = {"marks": marks, **({"remark": remark} if remark else {})}
    return await client.put(f"/v1/time/marking/{day}", json=body, headers=headers or {})


async def marks_of(engine, emp, day):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, remark FROM attendance_marks "
                    "WHERE employment_id = :e AND work_date = :d ORDER BY marked_at, id"
                ),
                {"e": to_uuid(emp["id"]), "d": day},
            )
        ).all()


async def test_a_group_members_day_is_not_marked_until_someone_marks_it(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1, d2, office = s["d1"], s["d2"], s["office"]

    listing = await ok(client, "GET", "/v1/time/marking?work_date=2026-08-13")
    assert sorted(r["employee_number"] for r in listing["rows"]) == ["DRV-1", "DRV-2"]
    assert {(r["status"], r["group_name"], r["access"]) for r in listing["rows"]} == {
        ("NOT_MARKED", "Drivers", "MARK")
    }
    assert listing["counts"] == {"NOT_MARKED": 2}
    # Only group members change: the office worker's empty day is still absent.
    assert await day_status(client, d1, "2026-08-13") == "NOT_MARKED"
    assert await day_status(client, office, "2026-08-13") == "ABSENT"

    saved = await mark(client, "2026-08-13", (d1, "PRESENT"), (d2, "ABSENT"), remark="Roll call")
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert (result["changed"], result["unchanged"]) == (2, 0)
    by_number = {r["employee_number"]: r for r in result["rows"]}
    assert (by_number["DRV-1"]["status"], by_number["DRV-2"]["status"]) == ("PRESENT", "ABSENT")
    assert by_number["DRV-1"]["mark"]["remark"] == "Roll call"
    assert await day_status(client, d2, "2026-08-13") == "ABSENT"

    again = (await mark(client, "2026-08-13", (d1, "PRESENT"), (d2, "ABSENT"))).json()
    assert (again["changed"], again["unchanged"]) == (0, 2)

    cleared = (await mark(client, "2026-08-13", (d1, None))).json()
    assert cleared["rows"][0]["status"] == "NOT_MARKED"
    assert await marks_of(engine, d1, date(2026, 8, 13)) == [("PRESENT", "Roll call"), (None, None)]

    # The attendance report counts the gap as not marked, never as an absence.
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.core.authz import Scope
    from hrms.modules.reports.attendance_service import build_attendance_summary

    scope = Scope(True, frozenset(), None, frozenset({"reports.read"}), None, frozenset())
    async with AsyncSession(engine) as session:
        report = await build_attendance_summary(
            session, s["tid"], scope, date(2026, 8, 10), date(2026, 8, 14)
        )
    people = {e.employee_number: e for e in report.employees}
    assert (people["DRV-1"].not_marked_days, people["DRV-1"].absent_days) == (5, 0)
    assert (people["DRV-2"].not_marked_days, people["DRV-2"].absent_days) == (4, 1)
    assert (people["OFF-1"].not_marked_days, people["OFF-1"].absent_days) == (0, 5)


async def test_times_count_like_punches(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1, d2 = s["d1"], s["d2"]

    timed = await mark(client, "2026-08-13", (d1, "PRESENT", "10:00", "18:30"))
    assert timed.status_code == 200, timed.text
    row = timed.json()["rows"][0]
    assert (row["status"], row["late_by_minutes"], row["worked_minutes"]) == ("LATE", 15, 510)
    assert row["punch_in"].startswith("2026-08-13T04:30")  # 10:00 IST
    assert row["has_punches"] is False  # a marker's times, not the person's own punches
    assert await day_status(client, d1, "2026-08-13") == "LATE"
    # The same times again change nothing.
    same = (await mark(client, "2026-08-13", (d1, "PRESENT", "10:00", "18:30"))).json()
    assert (same["changed"], same["unchanged"]) == (0, 1)

    # A night shift ends the next morning.
    night = (await mark(client, "2026-08-12", (d2, "PRESENT", "22:00", "06:00"))).json()
    assert night["rows"][0]["punch_out"].startswith("2026-08-13T00:30")  # 06:00 IST on the 13th
    assert night["rows"][0]["worked_minutes"] == 480

    # Changing the mark voids the earlier times; absent has no hours.
    absent = (await mark(client, "2026-08-13", (d1, "ABSENT"))).json()["rows"][0]
    assert (absent["status"], absent["worked_minutes"], absent["punch_in"]) == ("ABSENT", 0, None)
    async with engine.connect() as conn:
        live = (
            await conn.execute(
                text("""
                    SELECT count(*) FROM punches p WHERE p.employment_id = :e
                      AND p.source = 'MARKED' AND p.punch_type <> 'VOID'
                      AND NOT EXISTS (SELECT 1 FROM punches v
                                      WHERE v.original_punch_id = p.id AND v.punch_type = 'VOID')
                """),
                {"e": to_uuid(d1["id"])},
            )
        ).scalar()
    assert live == 0

    # Times later than now are refused, and times only go with present.
    late = await mark(client, "2026-08-14", (d1, "PRESENT", "22:30"))
    assert late.status_code == 422 and "later than now" in late.json()["detail"]
    bad = await client.put(
        "/v1/time/marking/2026-08-13",
        json={"marks": [{"employment_id": d1["id"], "status": "ABSENT", "punch_in": "09:00"}]},
    )
    assert bad.status_code == 422


async def test_rights_come_from_each_group(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1, d2, office = s["d1"], s["d2"], s["office"]
    group = s["drivers"]["id"]

    # A supervisor with no HR role, given MARK on Drivers, and a viewer given VIEW.
    _, marker_user, marker = await login_for(client, s, "SUP-1")
    _, viewer_user, viewer = await login_for(client, s, "VIEW-1")
    for user, level in ((marker_user, "MARK"), (viewer_user, "VIEW")):
        await ok(
            client, "PUT", f"{GROUPS}/{group}/access/{user['id']}", json={"access_level": level}
        )
    access = await ok(client, "GET", f"{GROUPS}/{group}/access")
    assert sorted(a["access_level"] for a in access) == ["MARK", "VIEW"]

    me = await ok(client, "GET", "/v1/auth/me", headers=marker)
    assert {"attendance.view", "attendance.mark"} <= set(me["permissions"])
    me = await ok(client, "GET", "/v1/auth/me", headers=viewer)
    assert "attendance.view" in me["permissions"]
    assert "attendance.mark" not in me["permissions"]

    assert (await mark(client, "2026-08-13", (d2, "ABSENT"), headers=marker)).status_code == 200
    seen = await row_of(client, "2026-08-13", "DRV-2", headers=viewer)
    assert (seen["status"], seen["access"], seen["can_mark"]) == ("ABSENT", "VIEW", False)
    assert (await mark(client, "2026-08-13", (d1, "PRESENT"), headers=viewer)).status_code == 422
    # The marker's group covers the group only: not the office worker.
    outside = await mark(client, "2026-08-13", (office, "PRESENT"), headers=marker)
    assert outside.status_code == 422
    # Someone with no group sees nothing, and only HR manages groups.
    listing = await ok(
        client, "GET", "/v1/time/marking?work_date=2026-08-13", headers=s["office_headers"]
    )
    assert listing["rows"] == []
    assert (await client.post(GROUPS, json={"name": "X"}, headers=marker)).status_code == 403

    # Withdrawn access is gone at once.
    await client.delete(f"{GROUPS}/{group}/access/{marker_user['id']}")
    gone = await mark(client, "2026-08-13", (d2, "PRESENT"), headers=marker)
    assert gone.status_code == 403

    # The usual rules: a whole save refused for one bad row, days off, own punches.
    mixed = await mark(client, "2026-08-13", (d1, "PRESENT"), (office, "PRESENT"))
    assert mixed.status_code == 422 and "Nothing was saved" in mixed.json()["detail"]
    assert await day_status(client, d1, "2026-08-13") == "NOT_MARKED"
    assert (await mark(client, "2026-08-17", (d1, "PRESENT"))).status_code == 422
    assert (await mark(client, "2026-08-08", (d1, "ABSENT"))).status_code == 422
    worked = (await mark(client, "2026-08-08", (d1, "PRESENT"))).json()["rows"][0]
    assert worked["status"] == "OFF_DAY_WORKED"
    await punch(client, monkeypatch, s["d1_headers"], "IN", at(date(2026, 8, 11), "09:30"))
    await punch(client, monkeypatch, s["d1_headers"], "OUT", at(date(2026, 8, 11), "18:30"))
    set_clock(monkeypatch, at(TODAY, "21:00"))
    own = await row_of(client, "2026-08-11", "DRV-1")
    assert (own["has_punches"], own["can_mark"]) == (True, False)


async def test_members_join_and_leave_on_dates(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1, office = s["d1"], s["office"]
    guards = await ok(client, "POST", GROUPS, json={"name": "Guards"})
    assert (await client.post(GROUPS, json={"name": "guards"})).status_code == 409

    # One group at a time: DRV-1 must leave Drivers before joining Guards.
    clash = await client.post(
        f"{GROUPS}/{guards['id']}/members",
        json={"employment_ids": [d1["id"]], "effective_from": "2026-08-10"},
    )
    assert clash.status_code == 409 and "already in Drivers" in clash.json()["detail"]
    removed = await client.delete(
        f"{GROUPS}/{s['drivers']['id']}/members/{d1['id']}?last_day=2026-08-11"
    )
    assert removed.status_code == 204
    await ok(
        client,
        "POST",
        f"{GROUPS}/{guards['id']}/members",
        json={"employment_ids": [d1["id"], office["id"]], "effective_from": "2026-08-12"},
    )
    assert (await row_of(client, "2026-08-11", "DRV-1"))["group_name"] == "Drivers"
    assert (await row_of(client, "2026-08-12", "DRV-1"))["group_name"] == "Guards"
    # The office worker is marked from the day they joined, punched before.
    assert await day_status(client, office, "2026-08-11") == "ABSENT"
    assert await day_status(client, office, "2026-08-12") == "NOT_MARKED"

    groups = {g["name"]: g for g in await ok(client, "GET", GROUPS)}
    assert (groups["Drivers"]["member_count"], groups["Guards"]["member_count"]) == (1, 2)
    assert (await client.delete(f"{GROUPS}/{guards['id']}")).status_code == 409  # members first


async def test_leave_is_recorded_as_a_range_through_the_leave_engine(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1, office = s["d1"], s["office"]
    annual = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12, "advance_notice_days": 7},
    )
    sick = await ok(
        client, "POST", "/v1/leave/types", json={"name": "Sick", "code": "SL", "days_per_year": 6}
    )
    await ok(
        client,
        "POST",
        "/v1/leave/balances/adjust",
        json={
            "employment_id": d1["id"],
            "leave_type_id": annual["id"],
            "quantity": 10,
            "kind": "OPENING",
            "reason": "Test balance",
            "effective_date": "2026-01-01",
        },
    )
    codes = {t["code"] for t in await ok(client, "GET", "/v1/time/marking/leave-types")}
    assert codes >= {"AL", "SL"}
    await mark(client, "2026-08-11", (d1, "ABSENT"))
    await mark(client, "2026-08-12", (d1, "PRESENT"))

    def leave(emp, lt, first, last):
        return client.post(
            "/v1/time/marking/leave",
            json={
                "employment_id": emp["id"],
                "leave_type_id": lt["id"],
                "from_date": first,
                "to_date": last,
                "reason": "Family function",
            },
        )

    over_present = await leave(d1, annual, "2026-08-10", "2026-08-12")
    assert over_present.status_code == 409 and "12 Aug" in over_present.json()["detail"]
    # Past leave is recorded even though the type asks for 7 days' notice.
    recorded = await leave(d1, annual, "2026-08-10", "2026-08-11")
    assert recorded.status_code == 201, recorded.text
    assert (recorded.json()["status"], recorded.json()["days_requested"]) == ("APPROVED", 2)
    balances = await ok(client, "GET", f"/v1/leave/balances?employment_id={d1['id']}")
    assert next(b for b in balances if b["leave_type_id"] == annual["id"])["available_days"] == 8
    assert await day_status(client, d1, "2026-08-11") == "ON_LEAVE"
    assert (await marks_of(engine, d1, date(2026, 8, 11)))[-1] == (
        None,
        "Cleared: leave recorded for this day",
    )
    row = await row_of(client, "2026-08-11", "DRV-1")
    assert (row["status"], row["can_mark"]) == ("ON_LEAVE", False)
    assert (await leave(d1, annual, "2026-08-11", "2026-08-11")).status_code == 409
    no_balance = await leave(d1, sick, "2026-08-13", "2026-08-13")
    assert no_balance.status_code == 409 and "Insufficient" in no_balance.json()["detail"]
    assert (await leave(office, annual, "2026-08-13", "2026-08-13")).status_code == 422
