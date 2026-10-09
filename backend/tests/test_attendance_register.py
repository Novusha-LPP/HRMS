"""
The attendance register: one employee day by day, and HR correcting a day directly.

Same base policy as test_attendance_cases.py: 09:30–18:30 IST, 60-min break, grace 15/15,
overtime from 40 min past the shift. Clock set per punch.
"""

from datetime import date

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, make_user, ok, person_and_employment
from tests.test_attendance_cases import at, company, punch, review_state, set_clock, staff, stored

pytestmark = pytest.mark.database


async def setup(client, monkeypatch, number):
    admin, le, placement, template = await company(client, {})
    emp, headers = await staff(client, le, placement, number)
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    # "Today" for the register: Friday 14 Aug 2026, evening.
    from hrms.modules.time import register

    today = at(date(2026, 8, 14), "21:00")
    monkeypatch.setattr(register, "now_utc", lambda: today)
    monkeypatch.setattr(register, "business_today", lambda tz=None: today.date())
    set_clock(monkeypatch, today)
    return admin, le, placement, emp, headers, tid, eid


def edit_url(emp, day):
    return f"/v1/time/register/{emp['id']}/{day}"


def punches(day, *pairs):
    return [
        {"punch_type": kind, "punched_at": at(day, clock, offset).isoformat()}
        for kind, clock, *rest in pairs
        for offset in [rest[0] if rest else 0]
    ]


async def test_register_lists_every_day_with_its_punches(api, monkeypatch):
    client, _ = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "REG-1")
    await ok(
        client, "POST", "/v1/time/holidays", json={"holiday_date": "2026-08-12", "name": "Fest"}
    )
    for kind, clock in [("IN", "09:30"), ("OUT", "13:00"), ("IN", "14:00"), ("OUT", "18:30")]:
        await punch(client, monkeypatch, headers, kind, at(date(2026, 8, 10), clock))
    await punch(client, monkeypatch, headers, "IN", at(date(2026, 8, 11), "10:05"))
    await punch(client, monkeypatch, headers, "OUT", at(date(2026, 8, 11), "18:30"))
    set_clock(monkeypatch, at(date(2026, 8, 14), "21:00"))

    reg = await ok(
        client,
        "GET",
        f"/v1/time/register/{emp['id']}?from_date=2026-08-08&to_date=2026-08-16",
    )
    by_day = {d["work_date"]: d for d in reg["days"]}
    assert {d: v["status"] for d, v in by_day.items()} == {
        "2026-08-08": "WEEKEND",
        "2026-08-09": "WEEKEND",
        "2026-08-10": "PRESENT",
        "2026-08-11": "LATE",
        "2026-08-12": "HOLIDAY",
        "2026-08-13": "ABSENT",
        "2026-08-14": "ABSENT",
        "2026-08-15": "WEEKEND",
        "2026-08-16": "WEEKEND",
    }
    monday = by_day["2026-08-10"]
    assert [p["punch_type"] for p in monday["punches"]] == ["IN", "OUT", "IN", "OUT"]
    assert (monday["effective_minutes"], monday["break_minutes"]) == (480, 60)
    assert (monday["shift_start"], monday["shift_end"]) == ("09:30", "18:30")
    assert by_day["2026-08-11"]["late_by_minutes"] == 20
    assert by_day["2026-08-12"]["holiday_name"] == "Fest"
    assert by_day["2026-08-12"]["is_off_day"] is True

    # The employee can read their own register; a range over 62 days is refused.
    own = await ok(
        client,
        "GET",
        f"/v1/time/register/{emp['id']}?from_date=2026-08-10&to_date=2026-08-10",
        headers=headers,
    )
    assert own["days"][0]["status"] == "PRESENT"
    too_long = await client.get(
        f"/v1/time/register/{emp['id']}?from_date=2026-01-01&to_date=2026-03-15"
    )
    assert too_long.status_code == 422

    found = await ok(client, "GET", "/v1/time/register/employees?search=reg-1")
    assert [e["employment_id"] for e in found] == [emp["id"]]


async def test_hr_edits_a_day_directly(api, monkeypatch):
    client, engine = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "REG-2")
    day = date(2026, 8, 10)
    for kind, clock in [("IN", "09:30"), ("BREAK_START", "13:00"), ("OUT", "18:30")]:
        await punch(client, monkeypatch, headers, kind, at(day, clock))
    set_clock(monkeypatch, at(date(2026, 8, 14), "21:00"))
    assert await review_state(engine, tid, eid, day) == ("BREAK_NOT_ENDED", 0.0)
    before = await ok(client, "GET", f"/v1/time/register/{emp['id']}?from_date={day}&to_date={day}")
    original = before["days"][0]["punches"]

    # Add the missing break end; the employee's own punches stay as they were.
    body = {
        "punches": [
            {"punch_type": p["punch_type"], "punched_at": p["punched_at"]} for p in original
        ]
        + punches(day, ("BREAK_END", "13:45")),
        "reason": "Break end confirmed with the supervisor",
    }
    edited = await ok(client, "PUT", edit_url(emp, day), json=body)
    assert [p["punch_type"] for p in edited["punches"]] == ["IN", "BREAK_START", "BREAK_END", "OUT"]
    assert [p["source"] for p in edited["punches"]] == ["WEB", "WEB", "MANUAL", "WEB"]
    assert (edited["effective_minutes"], edited["break_minutes"], edited["status"]) == (
        495,
        45,
        "PRESENT",
    )
    assert (edited["review_flags"], edited["needs_review"]) == ([], False)

    # The employee sees who changed their day and why.
    history = await ok(client, "GET", "/v1/corrections", headers=headers)
    assert [(c["correction_type"], c["status"], c["reason"]) for c in history] == [
        ("DIRECT_EDIT", "APPROVED", "Break end confirmed with the supervisor")
    ]

    # A whole missing day, then marking a day absent (an empty list).
    missing = date(2026, 8, 11)
    filled = await ok(
        client,
        "PUT",
        edit_url(emp, missing),
        json={
            "punches": punches(missing, ("IN", "09:30"), ("OUT", "19:30")),
            "reason": "Biometric machine was down",
        },
    )
    assert (filled["status"], filled["effective_minutes"], filled["ot_minutes"]) == (
        "PRESENT",
        600,
        60,
    )
    assert filled["ot_status"] == "PENDING"
    absent = await ok(
        client, "PUT", edit_url(emp, missing), json={"punches": [], "reason": "Was not at work"}
    )
    assert (absent["status"], absent["punches"], absent["ot_minutes"]) == ("ABSENT", [], 0)
    assert await stored(engine, tid, eid, missing) == (0, 0, 0, 0, 0, "ABSENT", 0, "NONE")

    # An over-16-hour day entered by HR counts as reviewed: its overtime is raised at once.
    long_day = date(2026, 8, 12)
    long = await ok(
        client,
        "PUT",
        edit_url(emp, long_day),
        json={
            "punches": punches(long_day, ("IN", "09:30"), ("OUT", "02:00", 1)),
            "reason": "Stock count overnight",
        },
    )
    assert (long["review_flags"], long["needs_review"], long["ot_minutes"]) == (
        ["LONG_DAY"],
        False,
        450,
    )


async def test_direct_edit_is_validated_and_restricted(api, monkeypatch):
    client, engine = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "REG-3")
    day = date(2026, 8, 10)

    async def refused(body, code=422, url=None, **kw):
        response = await client.put(url or edit_url(emp, day), json=body, **kw)
        assert response.status_code == code, response.text
        return response.json()["detail"]

    reason = "Testing"
    assert "out of order" in await refused(
        {"punches": punches(day, ("OUT", "09:30"), ("IN", "18:30")), "reason": reason}
    )
    assert "out of order" in await refused(
        {"punches": punches(day, ("IN", "09:30"), ("IN", "10:30")), "reason": reason}
    )
    assert "share the same time" in await refused(
        {"punches": punches(day, ("IN", "09:30"), ("OUT", "09:30")), "reason": reason}
    )
    assert "doesn't fall on" in await refused(
        {"punches": punches(day, ("IN", "09:30", 1), ("OUT", "18:30", 1)), "reason": reason}
    )
    assert "more than 24 hours" in await refused(
        {"punches": punches(day, ("IN", "09:30"), ("OUT", "09:31", 1)), "reason": reason}
    )
    assert "in the future" in await refused(
        {"punches": punches(day, ("IN", "09:30"), ("OUT", "18:30", 7)), "reason": reason}
    )
    future = date(2026, 8, 17)
    assert "future day" in await refused(
        {"punches": [], "reason": reason}, url=edit_url(emp, future)
    )
    assert await refused({"punches": [], "reason": reason}, code=400) == "Nothing changed"
    assert (
        await client.put(edit_url(emp, day), json={"punches": [], "reason": ""})
    ).status_code == 422

    # Only HR edits: the employee can't, and an HR manager can't edit their own day.
    assert await refused({"punches": [], "reason": reason}, code=403, headers=headers)
    hr_emp = await person_and_employment(client, le, "REG-HR")
    email, password, _ = await make_user(
        client, hr_emp["id"], role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    hr = bearer(
        (await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password}))[
            "access_token"
        ]
    )
    body = {"punches": punches(day, ("IN", "09:30"), ("OUT", "18:30")), "reason": reason}
    own = await refused(body, code=403, url=edit_url(hr_emp, day), headers=hr)
    assert "your own attendance" in own
    edited = await ok(client, "PUT", edit_url(emp, day), json=body, headers=hr)
    assert edited["status"] == "PRESENT"

    # A locked period can't be edited.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE attendance_days SET is_locked=true WHERE tenant_id=:t AND employment_id=:e"
            ),
            dict(t=tid, e=eid),
        )
    assert "locked" in await refused({"punches": [], "reason": reason}, code=409)
    assert (await stored(engine, tid, eid, day))[5] == "PRESENT"
