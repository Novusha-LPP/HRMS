"""
A status carried over from another system (migration 0066).

A day normally follows its punches. A legacy correction that only changed the status has no
punches to recompute from, so the day carries `status_override`: recalculation keeps it, and
anything a person records afterwards replaces it.
"""

from datetime import date

import pytest
from sqlalchemy import text

from tests.helpers import ok
from tests.test_attendance_cases import at, punch, set_clock
from tests.test_attendance_register import edit_url, punches, setup

pytestmark = pytest.mark.database


async def day_row(engine, tid, eid, day):
    async with engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT status, status_override, override_note, ot_minutes, comp_off_days"
                        " FROM attendance_days"
                        " WHERE tenant_id=:t AND employment_id=:e AND work_date=:d"
                    ),
                    dict(t=tid, e=eid, d=day),
                )
            )
            .mappings()
            .one()
        )


async def carry_over(engine, tid, eid, day, status):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE attendance_days SET status_override=:s, override_note='Imported from EXIM'"
                " WHERE tenant_id=:t AND employment_id=:e AND work_date=:d"
            ),
            dict(s=status, t=tid, e=eid, d=day),
        )


async def recalculate(engine, tid, eid, day):
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.modules.policy.engine import resolve_policy
    from hrms.modules.time.service import recompute_day

    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        policy = await resolve_policy(eid, day, session, tid)
        return await recompute_day(session, tid, eid, day, policy)


async def test_recalculation_keeps_a_carried_over_status(api, monkeypatch):
    client, engine = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "OVR-1")
    day = date(2026, 8, 10)
    await punch(client, monkeypatch, headers, "IN", at(day, "09:30"))
    set_clock(monkeypatch, at(date(2026, 8, 14), "21:00"))
    # Days later, a day with no check-out is a missed punch ...
    assert (await recalculate(engine, tid, eid, day)).status == "MISSED_PUNCH"

    # ... unless another system said otherwise: recalculation keeps that status.
    await carry_over(engine, tid, eid, day, "PRESENT")
    row = await recalculate(engine, tid, eid, day)
    assert (row.status, row.status_override) == ("PRESENT", "PRESENT")
    stored = await day_row(engine, tid, eid, day)
    assert (stored["status"], stored["override_note"]) == ("PRESENT", "Imported from EXIM")


async def test_a_carried_over_status_earns_no_overtime_or_comp_off(api, monkeypatch):
    client, engine = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "OVR-2")
    day = date(2026, 8, 10)
    for kind, clock in [("IN", "09:30"), ("OUT", "20:30")]:  # well past the shift
        await punch(client, monkeypatch, headers, kind, at(day, clock))
    set_clock(monkeypatch, at(date(2026, 8, 14), "21:00"))
    assert (await day_row(engine, tid, eid, day))["ot_minutes"] > 0

    await carry_over(engine, tid, eid, day, "PRESENT")
    await recalculate(engine, tid, eid, day)
    stored = await day_row(engine, tid, eid, day)
    assert (stored["status"], stored["ot_minutes"], stored["comp_off_days"]) == ("PRESENT", 0, 0)


async def test_an_hr_edit_replaces_the_carried_over_status(api, monkeypatch):
    client, engine = api
    admin, le, placement, emp, headers, tid, eid = await setup(client, monkeypatch, "OVR-3")
    day = date(2026, 8, 10)
    await punch(client, monkeypatch, headers, "IN", at(day, "09:30"))
    set_clock(monkeypatch, at(date(2026, 8, 14), "21:00"))
    await carry_over(engine, tid, eid, day, "PRESENT")

    edited = await ok(
        client,
        "PUT",
        edit_url(emp, day),
        json={
            "punches": punches(day, ("IN", "09:30"), ("OUT", "13:00")),
            "reason": "Corrected after the old status was imported",
        },
    )
    stored = await day_row(engine, tid, eid, day)
    assert (stored["status_override"], stored["override_note"]) == (None, None)
    assert edited["status"] == stored["status"] != "MISSED_PUNCH"
