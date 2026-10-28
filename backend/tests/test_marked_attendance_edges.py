"""
Trying to break marked attendance: odd times, night shifts against the next day, people moving
in and out of groups, scoped HR, view-only users, retired groups, and people who left.

Same setup as test_marked_attendance.py: "today" is Friday 14 Aug 2026, 21:00 IST.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, hire, make_user, ok, org_basics, person_and_employment
from tests.test_marked_attendance import (
    GROUPS,
    day_status,
    login_for,
    mark,
    row_of,
    setup,
)

pytestmark = pytest.mark.database


async def test_an_out_time_equal_to_the_in_time_is_not_a_24_hour_shift(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    same = await mark(client, "2026-08-13", (s["d1"], "PRESENT", "09:00", "09:00"))
    assert same.status_code == 422, same.text


async def test_a_night_shift_does_not_spill_into_the_next_day(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    d2 = s["d2"]
    night = await mark(client, "2026-08-12", (d2, "PRESENT", "22:00", "06:00"))
    assert night.status_code == 200, night.text
    day = await mark(client, "2026-08-13", (d2, "PRESENT", "09:30", "18:30"))
    assert day.status_code == 200, day.text
    assert day.json()["rows"][0]["worked_minutes"] == 540
    assert (await row_of(client, "2026-08-12", "DRV-2"))["worked_minutes"] == 480
    # A next-day start before the night shift ended can't both be true.
    clash = await mark(client, "2026-08-13", (d2, "PRESENT", "05:00", "12:00"))
    assert clash.status_code == 422, clash.text


async def test_rejoining_the_same_group_fills_the_gap(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    group, d1 = s["drivers"]["id"], s["d1"]
    out = await client.delete(f"{GROUPS}/{group}/members/{d1['id']}?last_day=2026-08-11")
    assert out.status_code == 204
    back = await client.post(
        f"{GROUPS}/{group}/members",
        json={"employment_ids": [d1["id"]], "effective_from": "2026-08-10"},
    )
    assert back.status_code == 200, back.text
    # Still (again) in the group after the day they had left.
    assert (await row_of(client, "2026-08-13", "DRV-1"))["group_name"] == "Drivers"


async def test_a_day_before_joining_or_after_leaving_cannot_be_marked(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    group, d1 = s["drivers"]["id"], s["d1"]
    await client.delete(f"{GROUPS}/{group}/members/{d1['id']}?last_day=2026-08-11")
    assert (await mark(client, "2026-08-12", (d1, "PRESENT"))).status_code == 422
    assert (await mark(client, "2026-08-11", (d1, "PRESENT"))).status_code == 200
    # The day they left is still theirs in the register, and the next is punched again.
    assert await day_status(client, d1, "2026-08-11") == "PRESENT"
    assert await day_status(client, d1, "2026-08-12") == "ABSENT"


async def test_hr_sees_only_members_in_their_own_scope(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    sister = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": f"Sister {uuid4().hex[:5]}", "country": "IN"},
        )
    )["id"]
    placement = await org_basics(client, sister)
    outsider = await person_and_employment(client, sister, "SIS-1")
    await hire(client, outsider["id"], placement)
    insider = await person_and_employment(client, s["le"], "CLN-1")
    await hire(client, insider["id"], s["placement"])
    mixed = await ok(client, "POST", GROUPS, json={"name": "Cleaners"})
    await ok(
        client,
        "POST",
        f"{GROUPS}/{mixed['id']}/members",
        json={"employment_ids": [insider["id"], outsider["id"]], "effective_from": "2026-01-01"},
    )
    # An HR manager of the first company only.
    hr = await person_and_employment(client, s["le"], "HR-1")
    await hire(client, hr["id"], s["placement"])
    email, password, _ = await make_user(
        client, hr["id"], role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[s["le"]]
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = bearer(login["access_token"])
    members = await ok(client, "GET", f"{GROUPS}/{mixed['id']}/members", headers=headers)
    assert [m["employee_number"] for m in members] == ["CLN-1"]
    sheet = await ok(client, "GET", "/v1/time/marking?work_date=2026-08-13", headers=headers)
    assert "SIS-1" not in {r["employee_number"] for r in sheet["rows"]}


async def test_view_only_users_cannot_record_leave(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    _, viewer_user, viewer = await login_for(client, s, "VIEW-2")
    await ok(
        client,
        "PUT",
        f"{GROUPS}/{s['drivers']['id']}/access/{viewer_user['id']}",
        json={"access_level": "VIEW"},
    )
    assert (await client.get("/v1/time/marking/leave-types", headers=viewer)).status_code == 403
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "LWP", "code": "LWP", "days_per_year": 0, "is_paid": False},
    )
    leave = await client.post(
        "/v1/time/marking/leave",
        headers=viewer,
        json={
            "employment_id": s["d1"]["id"],
            "leave_type_id": lt["id"],
            "from_date": "2026-08-13",
            "to_date": "2026-08-13",
        },
    )
    assert leave.status_code in (403, 422), leave.text
    # And they can't read the access list or change a group.
    assert (
        await client.get(f"{GROUPS}/{s['drivers']['id']}/access", headers=viewer)
    ).status_code == 403
    assert (
        await client.patch(f"{GROUPS}/{s['drivers']['id']}", json={"name": "X"}, headers=viewer)
    ).status_code == 403


async def test_a_retired_group_keeps_its_past_the_same_everywhere(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    group = s["drivers"]["id"]
    for emp in (s["d1"], s["d2"]):
        await client.delete(f"{GROUPS}/{group}/members/{emp['id']}?last_day=2026-08-11")
    monkeypatch.setattr(
        "hrms.modules.time.groups.business_today", lambda tz=None: date(2026, 8, 14)
    )
    assert (await client.delete(f"{GROUPS}/{group}")).status_code == 204
    # 10 Aug was a marked day while they were in the group: the register and the daily
    # analysis must agree it was not marked (not an absence).
    assert await day_status(client, s["d1"], "2026-08-10") == "NOT_MARKED"
    analysis = await ok(client, "GET", "/v1/time/daily-analysis?work_date=2026-08-10")
    record = next(r for r in analysis["employees"] if r["employee_number"] == "DRV-1")
    assert record["status"] == "NOT_MARKED"


async def test_clearing_times_leaves_nothing_behind(api, monkeypatch):
    client, engine = api
    s = await setup(client, monkeypatch)
    d1 = s["d1"]
    await mark(client, "2026-08-13", (d1, "PRESENT", "09:30", "18:30"))
    cleared = (await mark(client, "2026-08-13", (d1, None))).json()["rows"][0]
    assert (cleared["status"], cleared["punch_in"], cleared["worked_minutes"]) == (
        "NOT_MARKED",
        None,
        0,
    )
    async with engine.connect() as conn:
        days = (
            await conn.execute(
                text("SELECT count(*) FROM attendance_days WHERE employment_id = :e"),
                {"e": to_uuid(d1["id"])},
            )
        ).scalar()
    assert days == 0
    assert await day_status(client, d1, "2026-08-13") == "NOT_MARKED"


async def test_someone_who_left_the_company_cannot_be_marked_after(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    async with api[1].begin() as conn:
        await conn.execute(
            text("UPDATE employments SET separation_date = '2026-08-12' WHERE id = :e"),
            {"e": to_uuid(s["d1"]["id"])},
        )
    assert (await mark(client, "2026-08-13", (s["d1"], "PRESENT"))).status_code == 422
    assert (await mark(client, "2026-08-11", (s["d1"], "PRESENT"))).status_code == 200


async def test_leave_must_fall_in_a_group_the_marker_can_mark_on_every_day(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    drivers, d1 = s["drivers"]["id"], s["d1"]
    guards = await ok(client, "POST", GROUPS, json={"name": "Guards"})
    # DRV-1: Drivers until 10 Aug, Guards on 11 Aug, Drivers again from 12 Aug.
    await client.delete(f"{GROUPS}/{drivers}/members/{d1['id']}?last_day=2026-08-10")
    await ok(
        client,
        "POST",
        f"{GROUPS}/{guards['id']}/members",
        json={"employment_ids": [d1["id"]], "effective_from": "2026-08-11"},
    )
    await client.delete(f"{GROUPS}/{guards['id']}/members/{d1['id']}?last_day=2026-08-11")
    await ok(
        client,
        "POST",
        f"{GROUPS}/{drivers}/members",
        json={"employment_ids": [d1["id"]], "effective_from": "2026-08-12"},
    )
    _, marker_user, marker = await login_for(client, s, "SUP-3")
    await ok(
        client,
        "PUT",
        f"{GROUPS}/{drivers}/access/{marker_user['id']}",
        json={"access_level": "MARK"},
    )
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "LWP", "code": "LWP", "days_per_year": 0, "is_paid": False},
    )
    body = {
        "employment_id": d1["id"],
        "leave_type_id": lt["id"],
        "from_date": "2026-08-10",
        "to_date": "2026-08-12",
    }
    across = await client.post("/v1/time/marking/leave", json=body, headers=marker)
    assert across.status_code == 422 and "11 Aug" in across.json()["detail"], across.text


async def test_leave_approved_after_the_sheet_loaded_blocks_the_save(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    from hrms.modules.time import marking

    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "LWP", "code": "LWP", "days_per_year": 0, "is_paid": False},
    )
    recorded = await client.post(
        "/v1/time/marking/leave",
        json={
            "employment_id": s["d1"]["id"],
            "leave_type_id": lt["id"],
            "from_date": "2026-08-13",
            "to_date": "2026-08-13",
        },
    )
    assert recorded.status_code == 201, recorded.text
    # A sheet read before the leave existed still offers the day.
    original = marking._rows

    async def stale(*args, **kwargs):
        rows = await original(*args, **kwargs)
        for row in rows:
            row.can_mark, row.blocked_reason = True, None
        return rows

    monkeypatch.setattr(marking, "_rows", stale)
    late = await mark(client, "2026-08-13", (s["d1"], "PRESENT"))
    assert late.status_code == 409 and "Leave was approved" in late.json()["detail"], late.text


async def test_hr_can_still_correct_a_retired_groups_past(api, monkeypatch):
    client, _ = api
    s = await setup(client, monkeypatch)
    group = s["drivers"]["id"]
    _, marker_user, marker = await login_for(client, s, "SUP-4")
    await ok(
        client, "PUT", f"{GROUPS}/{group}/access/{marker_user['id']}", json={"access_level": "MARK"}
    )
    for emp in (s["d1"], s["d2"]):
        await client.delete(f"{GROUPS}/{group}/members/{emp['id']}?last_day=2026-08-11")
    assert (await client.delete(f"{GROUPS}/{group}")).status_code == 204
    # The group is gone from lists, the supervisor's grant ended with it…
    assert all(g["id"] != group for g in await ok(client, "GET", GROUPS))
    assert (
        await mark(client, "2026-08-10", (s["d1"], "PRESENT"), headers=marker)
    ).status_code == 403
    # …but HR can still put a past day right.
    fixed = await mark(client, "2026-08-10", (s["d1"], "PRESENT"))
    assert fixed.status_code == 200, fixed.text
    assert await day_status(client, s["d1"], "2026-08-10") == "PRESENT"
