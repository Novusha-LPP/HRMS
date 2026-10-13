"""
Attendance edge cases, end to end through the real API (row-level security on, API clock set to
each punch). Every expected value below is worked out by hand from the rules in
docs/ATTENDANCE_RULES.md — not taken from the code.

Base policy: shift 09:30–18:30 (9 h), 60-min break → 8 h standard, half day under 4 h,
grace 15/15 min, overtime enabled from 40 min past the shift, no cap, IST.
Expected tuple: (worked, total, away, late, early, status, ot, ot_status).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, employee, hire, ok, org_basics, tenant

pytestmark = pytest.mark.database
IST = ZoneInfo("Asia/Kolkata")

BASE = dict(
    name="Base",
    timezone="Asia/Kolkata",
    is_default=False,
    expected_start_time="09:30:00",
    expected_end_time="18:30:00",
    work_days="1111100",
    break_minutes=60,
    break_auto_deduct=False,
    grace_late_minutes=15,
    grace_early_departure_minutes=15,
    half_day_threshold_pct=50,
    ot_enabled=True,
    ot_qualifying_minutes=40,
    ot_rate=1.5,
    ot_daily_cap_minutes=None,
    punch_rounding_minutes=0,
    punch_rounding_direction="NONE",
    correction_requires_approval=True,
    correction_approval_levels=1,
)
NIGHT = {"expected_start_time": "22:00:00", "expected_end_time": "06:00:00"}  # 8 h, 7 h standard
NEAREST15 = {"punch_rounding_minutes": 15, "punch_rounding_direction": "NEAREST"}
UP15 = {"punch_rounding_minutes": 15, "punch_rounding_direction": "UP"}
DOWN15 = {"punch_rounding_minutes": 15, "punch_rounding_direction": "DOWN"}

P, L, H, E, A, M = "PRESENT", "LATE", "HALF_DAY", "EARLY_DEPARTURE", "ABSENT", "MISSED_PUNCH"
OFF = "OFF_DAY_WORKED"
COMP_OFF = {"off_day_work": "COMP_OFF"}
SAT, SUN = 5, 6
BREAK_FLAG, LONG_FLAG = "BREAK_NOT_ENDED", "LONG_DAY"


@dataclass
class Case:
    name: str
    punches: list[tuple]  # (type, "HH:MM[:SS]"[, day offset][, "refused" | "confirm"])
    expect: tuple  # on the case's work date
    policy: dict = field(default_factory=dict)
    other_days: dict[int, tuple] = field(default_factory=dict)  # day offset → expected
    on: int = 0  # days after the Monday the case runs in (SAT, SUN for weekly offs)
    flags: str | None = None  # review flags expected on the work date
    comp_off: float = 0.0  # comp-off days expected to be credited for the work date


def x(worked, total, away, late, early, status, ot=0, ot_status="NONE"):
    return (worked, total, away, late, early, status, ot, ot_status)


CASES = [
    # ── Sessions and breaks ────────────────────────────────────────────────────────
    Case("A1 one-minute session", [("IN", "09:30"), ("OUT", "09:31")], x(1, 1, 0, 0, 524, H)),
    Case(
        "A2 break never ended: counted as the 60-min policy break, HR to review",
        [("IN", "09:30"), ("BREAK_START", "13:00"), ("OUT", "18:30")],
        x(480, 540, 60, 0, 0, P),
        flags=BREAK_FLAG,
    ),
    Case(
        "A3 two recorded breaks",
        [
            ("IN", "09:30"),
            ("BREAK_START", "11:00"),
            ("BREAK_END", "11:15"),
            ("BREAK_START", "13:00"),
            ("BREAK_END", "13:45"),
            ("OUT", "18:30"),
        ],
        x(480, 540, 60, 0, 0, P),
    ),
    Case(
        "A4 recorded break + lunch check-out + stayed late",
        [
            ("IN", "09:30"),
            ("BREAK_START", "11:00"),
            ("BREAK_END", "11:15"),
            ("OUT", "13:00"),
            ("IN", "14:00"),
            ("OUT", "19:45"),
        ],
        x(540, 615, 75, 0, 0, P),
    ),
    Case(
        "A5 zero-length break",
        [("IN", "09:30"), ("BREAK_START", "12:00"), ("BREAK_END", "12:00"), ("OUT", "18:30")],
        x(540, 540, 0, 0, 0, P),
    ),
    Case(
        "A6 six short sessions",
        [
            ("IN", "09:30"),
            ("OUT", "10:00"),
            ("IN", "10:10"),
            ("OUT", "10:40"),
            ("IN", "10:50"),
            ("OUT", "11:20"),
            ("IN", "11:30"),
            ("OUT", "12:00"),
            ("IN", "12:10"),
            ("OUT", "12:40"),
            ("IN", "12:50"),
            ("OUT", "13:20"),
        ],
        x(180, 230, 50, 0, 295, H),
    ),
    Case(
        "A7 back from lunch, still at work (not early)",
        [("IN", "09:30"), ("OUT", "13:00"), ("IN", "14:00")],
        x(210, 210, 0, 0, 0, P),
    ),
    # ── Late / early boundaries ───────────────────────────────────────────────────
    Case(
        "B1 in at 09:45 (inside grace)",
        [("IN", "09:45"), ("OUT", "18:30")],
        x(525, 525, 0, 0, 0, P),
    ),
    Case(
        "B2 in at 09:46 (1 min late)", [("IN", "09:46"), ("OUT", "18:30")], x(524, 524, 0, 1, 0, L)
    ),
    Case(
        "B3 in at 09:45:59 (seconds ignored)",
        [("IN", "09:45:59"), ("OUT", "18:30")],
        x(524, 524, 0, 0, 0, P),
    ),
    Case(
        "B4 out at 18:15 (inside grace)",
        [("IN", "09:30"), ("OUT", "18:15")],
        x(525, 525, 0, 0, 0, P),
    ),
    Case(
        "B5 out at 18:14 (1 min early)",
        [("IN", "09:30"), ("OUT", "18:14")],
        x(524, 524, 0, 0, 1, E),
    ),
    Case(
        "B6 late and short: half day wins",
        [("IN", "12:00"), ("OUT", "15:00")],
        x(180, 180, 0, 135, 195, H),
    ),
    Case(
        "B7 came early, left on time",
        [("IN", "08:00"), ("OUT", "18:30")],
        x(630, 630, 0, 0, 0, P, 90, "PENDING"),
    ),
    Case(
        "B8 came late, stayed late", [("IN", "10:30"), ("OUT", "19:30")], x(540, 540, 0, 45, 0, L)
    ),
    Case(
        "B9 late and left early: late shown",
        [("IN", "10:00"), ("OUT", "17:00")],
        x(420, 420, 0, 15, 75, L),
    ),
    # ── Half-day boundary ─────────────────────────────────────────────────────────
    Case("C1 3 h 59 m", [("IN", "09:30"), ("OUT", "13:29")], x(239, 239, 0, 0, 286, H)),
    Case("C2 exactly 4 h", [("IN", "09:30"), ("OUT", "13:30")], x(240, 240, 0, 0, 285, E)),
    # ── Overtime ──────────────────────────────────────────────────────────────────
    Case("D1 39 min past the shift", [("IN", "09:30"), ("OUT", "19:09")], x(579, 579, 0, 0, 0, P)),
    Case(
        "D2 40 min past the shift",
        [("IN", "09:30"), ("OUT", "19:10")],
        x(580, 580, 0, 0, 0, P, 40, "PENDING"),
    ),
    Case(
        "D3 daily cap 60",
        [("IN", "09:30"), ("OUT", "21:30")],
        x(720, 720, 0, 0, 0, P, 60, "PENDING"),
        {"ot_daily_cap_minutes": 60},
    ),
    Case(
        "D4 daily cap 0",
        [("IN", "09:30"), ("OUT", "21:30")],
        x(720, 720, 0, 0, 0, P),
        {"ot_daily_cap_minutes": 0},
    ),
    Case(
        "D5 no minimum: 1 min counts",
        [("IN", "09:30"), ("OUT", "18:31")],
        x(541, 541, 0, 0, 0, P, 1, "PENDING"),
        {"ot_qualifying_minutes": 0},
    ),
    Case(
        "D6 no OT policy: shown only",
        [("IN", "09:30"), ("OUT", "19:09")],
        x(579, 579, 0, 0, 0, P, 39, "INFO"),
        {"ot_enabled": False},
    ),
    Case(
        "D7 no OT policy, full shift",
        [("IN", "09:30"), ("OUT", "18:30")],
        x(540, 540, 0, 0, 0, P),
        {"ot_enabled": False},
    ),
    Case(
        "D8 lunch check-out and stayed late",
        [("IN", "09:30"), ("OUT", "13:30"), ("IN", "14:30"), ("OUT", "19:40")],
        x(550, 610, 60, 0, 0, P),
    ),
    Case(
        "D9 recorded 1 h break, long day",
        [("IN", "09:30"), ("BREAK_START", "13:00"), ("BREAK_END", "14:00"), ("OUT", "20:30")],
        x(600, 660, 60, 0, 0, P, 60, "PENDING"),
    ),
    # ── Midnight and the 24-hour window ───────────────────────────────────────────
    Case(
        "E1 worked until 02:00: over 16 h, confirmed, overtime held for HR",
        [("IN", "09:30"), ("OUT", "02:00", 1, "refused"), ("OUT", "02:00", 1, "confirm")],
        x(990, 990, 0, 0, 0, P),
        flags=LONG_FLAG,
    ),
    Case(
        "E2 started 22:00 on a day shift",
        [("IN", "22:00"), ("OUT", "06:00", 1)],
        x(480, 480, 0, 735, 0, L),
    ),
    Case(
        "E3 check-out exactly 24 h later: confirmed, HR to review",
        [("IN", "09:30"), ("OUT", "09:30", 1, "refused"), ("OUT", "09:30", 1, "confirm")],
        x(1440, 1440, 0, 0, 0, P),
        flags=LONG_FLAG,
    ),
    Case(
        "E4 24 h + 1 min: refused, missed punch",
        [("IN", "09:30"), ("OUT", "09:31", 1, "refused"), ("IN", "09:32", 1)],
        x(0, 0, 0, 0, 0, M),
        other_days={1: x(0, 0, 0, 0, 0, P)},
    ),
    Case("E5 23:59 to 00:01", [("IN", "23:59"), ("OUT", "00:01", 1)], x(2, 2, 0, 854, 0, H)),
    Case(
        "E6 late night, then a new day after midnight",
        [("IN", "09:30"), ("OUT", "01:00", 1), ("IN", "02:00", 1), ("OUT", "05:00", 1)],
        x(930, 930, 0, 0, 0, P, 390, "PENDING"),
        other_days={1: x(180, 180, 0, 0, 795, H)},
    ),
    # ── Night shift 22:00–06:00 ───────────────────────────────────────────────────
    Case(
        "F1 night shift, normal",
        [("IN", "21:55"), ("OUT", "06:05", 1)],
        x(490, 490, 0, 0, 0, P),
        NIGHT,
    ),
    Case(
        "F2 night shift, 20 min late",
        [("IN", "22:20"), ("OUT", "06:00", 1)],
        x(460, 460, 0, 5, 0, L),
        NIGHT,
    ),
    Case(
        "F3 night shift, arrived after midnight",
        [("IN", "00:30", 1), ("OUT", "06:00", 1)],
        x(330, 330, 0, 135, 0, L),
        NIGHT,
    ),
    Case(
        "F4 night shift, overtime",
        [("IN", "22:00"), ("OUT", "07:00", 1)],
        x(540, 540, 0, 0, 0, P, 60, "PENDING"),
        NIGHT,
    ),
    Case(
        "F5 night shift, left at 02:00",
        [("IN", "22:00"), ("OUT", "02:00", 1)],
        x(240, 240, 0, 0, 225, E),
        NIGHT,
    ),
    Case(
        "F6 night shift, arrived after midnight, still at work",
        [("IN", "00:30", 1)],
        x(0, 0, 0, 135, 0, L),
        NIGHT,
    ),
    # ── Rounding (15 min) ─────────────────────────────────────────────────────────
    Case(
        "G1 nearest: 09:37→09:30, 18:38→18:45",
        [("IN", "09:37"), ("OUT", "18:38")],
        x(555, 555, 0, 0, 0, P),
        NEAREST15,
    ),
    Case(
        "G2 up: 09:31→09:45, 18:29→18:30",
        [("IN", "09:31"), ("OUT", "18:29")],
        x(525, 525, 0, 0, 0, P),
        UP15,
    ),
    Case(
        "G3 down: 09:59→09:45, 18:44→18:30",
        [("IN", "09:59"), ("OUT", "18:44")],
        x(525, 525, 0, 0, 0, P),
        DOWN15,
    ),
    Case("G4 up: 09:46→10:00, still at work", [("IN", "09:46")], x(0, 0, 0, 15, 0, L), UP15),
    Case("G5 up: 09:46→10:00", [("IN", "09:46"), ("OUT", "18:30")], x(510, 510, 0, 15, 0, L), UP15),
    # ── Weekly off and holiday work (Mon–Fri policy) ─────────────────────────────
    Case(
        "K1 Saturday, overtime policy: all of it is overtime",
        [("IN", "10:00"), ("OUT", "14:00")],
        x(240, 240, 0, 0, 0, OFF, 240, "PENDING"),
        on=SAT,
    ),
    Case(
        "K2 Sunday, no overtime policy: shown only",
        [("IN", "10:00"), ("OUT", "13:00")],
        x(180, 180, 0, 0, 0, OFF, 180, "INFO"),
        {"ot_enabled": False},
        on=SUN,
    ),
    Case(
        "K3 Saturday, 20 min: below the overtime minimum",
        [("IN", "10:00"), ("OUT", "10:20")],
        x(20, 20, 0, 0, 0, OFF),
        on=SAT,
    ),
    Case(
        "K4 Saturday, daily cap 120",
        [("IN", "09:30"), ("OUT", "18:30")],
        x(540, 540, 0, 0, 0, OFF, 120, "PENDING"),
        {"ot_daily_cap_minutes": 120},
        on=SAT,
    ),
    Case(
        "K5 Saturday with a lunch check-out",
        [("IN", "10:00"), ("OUT", "13:00"), ("IN", "14:00"), ("OUT", "17:00")],
        x(360, 420, 60, 0, 0, OFF, 360, "PENDING"),
        on=SAT,
    ),
    Case(
        "K6 Saturday, still at work",
        [("IN", "11:00")],
        x(0, 0, 0, 0, 0, OFF),
        on=SAT,
    ),
    Case(
        "K7 comp-off policy, full day: 1 day credited",
        [("IN", "09:30"), ("OUT", "18:30")],
        x(540, 540, 0, 0, 0, OFF),
        COMP_OFF,
        on=SAT,
        comp_off=1.0,
    ),
    Case(
        "K8 comp-off policy, 4 h 30 m: half day credited",
        [("IN", "10:00"), ("OUT", "14:30")],
        x(270, 270, 0, 0, 0, OFF),
        COMP_OFF,
        on=SUN,
        comp_off=0.5,
    ),
    Case(
        "K9 comp-off policy, 3 h 59 m: nothing credited",
        [("IN", "10:00"), ("OUT", "13:59")],
        x(239, 239, 0, 0, 0, OFF),
        COMP_OFF,
        on=SAT,
    ),
    Case(
        "K10 comp-off policy, 12 h: 1 day, no overtime",
        [("IN", "09:30"), ("OUT", "21:30")],
        x(720, 720, 0, 0, 0, OFF),
        COMP_OFF,
        on=SAT,
        comp_off=1.0,
    ),
    Case(
        "K11 six-day week: Saturday is a normal day",
        [("IN", "09:30"), ("OUT", "18:30")],
        x(540, 540, 0, 0, 0, P),
        {"work_days": "1111110"},
        on=SAT,
    ),
    Case(
        "K12 Friday night into Saturday: still Friday's day",
        [("IN", "09:30"), ("OUT", "01:00", 1)],
        x(930, 930, 0, 0, 0, P, 390, "PENDING"),
        on=4,
    ),
    # ── Days held for HR review ───────────────────────────────────────────────────
    Case(
        "L1 break never ended, stayed late: overtime held",
        [("IN", "09:30"), ("BREAK_START", "13:00"), ("OUT", "20:30")],
        x(600, 660, 60, 0, 0, P),
        flags=BREAK_FLAG,
    ),
    Case(
        "L2 break never ended, 30-min policy break",
        [("IN", "09:30"), ("BREAK_START", "13:00"), ("OUT", "18:30")],
        x(510, 540, 30, 0, 0, P),
        {"break_minutes": 30},
        flags=BREAK_FLAG,
    ),
    Case(
        "L3 break never ended on a short day",
        [("IN", "09:30"), ("BREAK_START", "12:00"), ("OUT", "13:00")],
        x(150, 210, 60, 0, 315, H),
        flags=BREAK_FLAG,
    ),
    Case(
        "L4 exactly 16 h: no confirmation, not flagged",
        [("IN", "09:30"), ("OUT", "01:30", 1)],
        x(960, 960, 0, 0, 0, P, 420, "PENDING"),
    ),
    Case(
        "L5 16 h 1 m: needs confirming, then flagged",
        [("IN", "09:30"), ("OUT", "01:31", 1, "refused"), ("OUT", "01:31", 1, "confirm")],
        x(961, 961, 0, 0, 0, P),
        flags=LONG_FLAG,
    ),
    Case(
        "L6 night shift 22:00 to 15:00: flagged",
        [("IN", "22:00"), ("OUT", "15:00", 1, "confirm")],
        x(1020, 1020, 0, 0, 0, P),
        NIGHT,
        flags=LONG_FLAG,
    ),
    # ── Refused punches change nothing ───────────────────────────────────────────
    Case(
        "H1 double break start",
        [
            ("IN", "09:30"),
            ("BREAK_START", "12:00"),
            ("BREAK_START", "12:05", 0, "refused"),
            ("BREAK_END", "12:30"),
            ("OUT", "18:30"),
        ],
        x(510, 540, 30, 0, 0, P),
    ),
    Case(
        "H2 break and check-out after leaving",
        [
            ("IN", "09:30"),
            ("OUT", "18:30"),
            ("BREAK_START", "18:40", 0, "refused"),
            ("BREAK_END", "18:50", 0, "refused"),
            ("OUT", "18:55", 0, "refused"),
        ],
        x(540, 540, 0, 0, 0, P),
    ),
    Case(
        "H3 check-out and break end before check-in",
        [
            ("OUT", "09:00", 0, "refused"),
            ("BREAK_END", "09:10", 0, "refused"),
            ("IN", "09:30"),
            ("OUT", "18:30"),
        ],
        x(540, 540, 0, 0, 0, P),
    ),
]

FIELDS = (
    "effective_minutes",
    "gross_minutes",
    "break_minutes",
    "late_by_minutes",
    "early_departure_minutes",
    "status",
    "ot_minutes",
    "ot_status",
)


def at(day: date, clock: str, offset: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=offset), time.fromisoformat(clock), IST)


def set_clock(monkeypatch, instant: datetime):
    from hrms.jobs import runner
    from hrms.modules.time import router as time_router
    from hrms.modules.time import service as time_service

    utc = instant.astimezone(UTC)
    for module in (time_router, time_service, runner):
        monkeypatch.setattr(module, "now_utc", lambda utc=utc: utc)


async def punch(client, monkeypatch, headers, kind, instant, confirm=False):
    set_clock(monkeypatch, instant)
    body = {"punch_type": kind, **({"confirm_long_day": True} if confirm else {})}
    return await client.post("/v1/time/punches", headers=headers, json=body)


async def review_state(engine, tid, eid, day):
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT review_flags, comp_off_days FROM attendance_days"
                    " WHERE tenant_id=:t AND employment_id=:e AND work_date=:d"
                ),
                dict(t=tid, e=eid, d=day),
            )
        ).first()
    return tuple(row) if row else (None, 0.0)


async def stored(engine, tid, eid, day):
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT * FROM attendance_days"
                        " WHERE tenant_id=:t AND employment_id=:e AND work_date=:d"
                    ),
                    dict(t=tid, e=eid, d=day),
                )
            )
            .mappings()
            .first()
        )
    return tuple(row[f] for f in FIELDS) if row else None


async def company(client, policy=None):
    """A company with a placement and, optionally, a default policy."""
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    template = None
    if policy is not None:
        template = await ok(
            client, "POST", "/v1/policies/templates", json={**BASE, **policy, "is_default": True}
        )
    return admin, le, placement, template


async def staff(client, le, placement, number):
    emp, login = await employee(client, le, number)
    await hire(client, emp["id"], placement)
    return emp, bearer(login["access_token"])


async def test_attendance_case_catalog(api, monkeypatch):
    client, engine = api
    admin, le, placement, _ = await company(client)
    emp, headers = await staff(client, le, placement, "CASES-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    templates: dict[str, dict] = {}
    report, failures = [], []
    for i, case in enumerate(CASES):
        # Each case gets its own fortnight, starting on a Monday (plus `on` days).
        day = date(2026, 3, 2) + timedelta(weeks=2 * i, days=case.on)
        key = json.dumps(case.policy, sort_keys=True)
        if key not in templates:
            templates[key] = await ok(
                client,
                "POST",
                "/v1/policies/templates",
                json={**BASE, **case.policy, "name": f"Case policy {i}"},
            )
        await ok(
            client,
            "POST",
            "/v1/policies/assignments",
            json=dict(
                employment_id=emp["id"],
                policy_template_id=templates[key]["id"],
                effective_from=str(day),
                effective_to=str(day + timedelta(days=2)),
            ),
        )
        problems = []
        for kind, clock, *rest in case.punches:
            offset = rest[0] if rest else 0
            refused = len(rest) > 1 and rest[1] == "refused"
            confirm = len(rest) > 1 and rest[1] == "confirm"
            response = await punch(
                client, monkeypatch, headers, kind, at(day, clock, offset), confirm
            )
            if response.status_code != (409 if refused else 201):
                problems.append(f"{kind} {clock}+{offset}d → {response.status_code}")
        extras = await review_state(engine, tid, eid, day)
        if extras != (case.flags, case.comp_off):
            problems.append(
                f"review flags, comp-off got {extras} want {(case.flags, case.comp_off)}"
            )
        for offset, want in {0: case.expect, **case.other_days}.items():
            got = await stored(engine, tid, eid, day + timedelta(days=offset))
            if got != want:
                diff = {
                    f: (g, w)
                    for f, g, w in zip(FIELDS, got or [None] * 8, want, strict=True)
                    if g != w
                }
                problems.append(
                    f"day+{offset}: "
                    + ", ".join(f"{f} got {g!r} want {w!r}" for f, (g, w) in diff.items())
                )
        report.append(f"{'FAIL' if problems else 'pass'}  {case.name}")
        failures += [f"{case.name}: {p}" for p in problems]
    print("\n" + "\n".join(report))
    assert not failures, f"{len(failures)} problems:\n" + "\n".join(failures)


async def test_simultaneous_check_in_taps_record_one(api, monkeypatch):
    client, _ = api
    admin, le, placement, _ = await company(client, {})
    emp, headers = await staff(client, le, placement, "TAP-1")
    set_clock(monkeypatch, at(date(2026, 8, 3), "09:30"))
    first, second = await asyncio.gather(
        client.post("/v1/time/punches", headers=headers, json={"punch_type": "IN"}),
        client.post("/v1/time/punches", headers=headers, json={"punch_type": "IN"}),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    today = await ok(client, "GET", "/v1/time/today?work_date=2026-08-03", headers=headers)
    assert [p["punch_type"] for p in today["punches"]] == ["IN"]


async def test_the_clock_offers_check_out_of_a_session_open_since_yesterday(api, monkeypatch):
    """Checked in yesterday afternoon, never out: until 24 hours have passed the clock shows
    that session, so the employee can check out of it; after that, today and a fresh check-in."""
    client, _ = api
    admin, le, placement, _ = await company(client, {})
    day = date(2026, 8, 3)

    emp, headers = await staff(client, le, placement, "OPEN-1")
    assert (await punch(client, monkeypatch, headers, "IN", at(day, "16:30"))).status_code == 201
    set_clock(monkeypatch, at(day, "09:30", 1))
    clock = await ok(client, "GET", "/v1/time/today", headers=headers)
    assert (clock["work_date"], clock["is_punched_in"]) == (str(day), True)
    # Checking out closes yesterday (a long day, confirmed); today is then fresh.
    out = await punch(client, monkeypatch, headers, "OUT", at(day, "09:30", 1), confirm=True)
    assert out.status_code == 201
    clock = await ok(client, "GET", "/v1/time/today", headers=headers)
    assert (clock["work_date"], clock["is_punched_in"]) == (str(day + timedelta(days=1)), False)

    _, late = await staff(client, le, placement, "OPEN-2")
    assert (await punch(client, monkeypatch, late, "IN", at(day, "16:30"))).status_code == 201
    set_clock(monkeypatch, at(day, "16:31", 1))  # over 24 hours: a missed punch
    clock = await ok(client, "GET", "/v1/time/today", headers=late)
    assert (clock["work_date"], clock["is_punched_in"]) == (str(day + timedelta(days=1)), False)


async def test_company_without_any_policy_uses_the_fallback(api, monkeypatch):
    """No policy at all: the built-in 09:30–18:30 shift, grace 15, and overtime off —
    extra time is shown only."""
    from hrms.core.config import settings

    client, engine = api
    admin, le, placement, _ = await company(client)
    emp, headers = await staff(client, le, placement, "NOPOL-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    start = time.fromisoformat(settings.default_work_start)
    end = time.fromisoformat(settings.default_work_end)
    shift = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    day = date(2026, 8, 4)
    await punch(client, monkeypatch, headers, "IN", at(day, start.isoformat()))
    leave = (datetime.combine(day, end) + timedelta(minutes=60)).time().isoformat()
    await punch(client, monkeypatch, headers, "OUT", at(day, leave))
    got = await stored(engine, tid, eid, day)
    assert got == (shift + 60, shift + 60, 0, 0, 0, "PRESENT", 60, "INFO")


async def test_corrections_repair_and_recalculate(api, monkeypatch):
    client, engine = api
    admin, le, placement, template = await company(client, {})
    emp, headers = await staff(client, le, placement, "COR-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])

    async def correct(day, kind, **times):
        body = dict(
            work_date=str(day),
            correction_type=kind,
            reason="Case test",
            **{k: v.isoformat() for k, v in times.items()},
        )
        cor = await ok(client, "POST", "/v1/corrections", headers=headers, json=body)
        await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})

    # J1 missed punch, then fixed with the real check-out time.
    d1 = date(2026, 8, 3)
    await punch(client, monkeypatch, headers, "IN", at(d1, "09:30"))
    await punch(client, monkeypatch, headers, "IN", at(d1, "10:00", 1))  # flags d1
    assert (await stored(engine, tid, eid, d1))[5] == "MISSED_PUNCH"
    await correct(d1, "PUNCH_OUT", requested_punch_out=at(d1, "18:30"))
    assert await stored(engine, tid, eid, d1) == (540, 540, 0, 0, 0, "PRESENT", 0, "NONE")

    # J2 multi-session day: only the last check-out is replaced.
    d2 = date(2026, 8, 6)
    for kind, clock in [("IN", "09:30"), ("OUT", "13:00"), ("IN", "14:00"), ("OUT", "18:00")]:
        await punch(client, monkeypatch, headers, kind, at(d2, clock))
    assert await stored(engine, tid, eid, d2) == (450, 510, 60, 0, 15, "EARLY_DEPARTURE", 0, "NONE")
    await correct(d2, "PUNCH_OUT", requested_punch_out=at(d2, "18:30"))
    assert await stored(engine, tid, eid, d2) == (480, 540, 60, 0, 0, "PRESENT", 0, "NONE")

    # J3 mark absent removes every punch.
    d3 = date(2026, 8, 7)
    await punch(client, monkeypatch, headers, "IN", at(d3, "09:30"))
    await punch(client, monkeypatch, headers, "OUT", at(d3, "18:30"))
    await correct(d3, "MARK_ABSENT")
    assert await stored(engine, tid, eid, d3) == (0, 0, 0, 0, 0, "ABSENT", 0, "NONE")

    # J4 regularise a day with no punches at all.
    d4 = date(2026, 8, 10)
    await correct(
        d4, "REGULARIZE", requested_punch_in=at(d4, "09:30"), requested_punch_out=at(d4, "18:30")
    )
    assert await stored(engine, tid, eid, d4) == (540, 540, 0, 0, 0, "PRESENT", 0, "NONE")

    # J5 corrected check-in removes the lateness.
    d5 = date(2026, 8, 11)
    await punch(client, monkeypatch, headers, "IN", at(d5, "10:30"))
    await punch(client, monkeypatch, headers, "OUT", at(d5, "18:30"))
    assert (await stored(engine, tid, eid, d5))[3:6] == (45, 0, "LATE")
    await correct(d5, "PUNCH_IN", requested_punch_in=at(d5, "09:30"))
    assert await stored(engine, tid, eid, d5) == (540, 540, 0, 0, 0, "PRESENT", 0, "NONE")

    # J6 shown-only overtime becomes payable when the policy turns overtime on.
    d6 = date(2026, 8, 12)
    template_url = f"/v1/policies/templates/{template['id']}"
    await ok(client, "PATCH", template_url, json={"ot_enabled": False})
    await punch(client, monkeypatch, headers, "IN", at(d6, "09:30"))
    await punch(client, monkeypatch, headers, "OUT", at(d6, "19:09"))
    assert (await stored(engine, tid, eid, d6))[6:] == (39, "INFO")
    await ok(client, "PATCH", template_url, json={"ot_enabled": True})
    await correct(d6, "PUNCH_OUT", requested_punch_out=at(d6, "19:20"))
    assert (await stored(engine, tid, eid, d6))[6:] == (50, "PENDING")
    pending = await ok(client, "GET", "/v1/time/overtime/pending")
    assert [p["ot_minutes"] for p in pending if p["work_date"] == str(d6)] == [50]


async def test_locked_day_refuses_punches_and_corrections(api, monkeypatch):
    client, engine = api
    admin, le, placement, _ = await company(client, {})
    emp, headers = await staff(client, le, placement, "LOCK-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    day = date(2026, 8, 5)
    await punch(client, monkeypatch, headers, "IN", at(day, "09:30"))
    await punch(client, monkeypatch, headers, "OUT", at(day, "18:30"))
    before = await stored(engine, tid, eid, day)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE attendance_days SET is_locked=true WHERE tenant_id=:t "
                "AND employment_id=:e AND work_date=:d"
            ),
            dict(t=tid, e=eid, d=day),
        )
    assert (await punch(client, monkeypatch, headers, "IN", at(day, "19:00"))).status_code == 409
    cor = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=headers,
        json=dict(
            work_date=str(day),
            correction_type="PUNCH_OUT",
            reason="Locked",
            requested_punch_out=at(day, "20:00").isoformat(),
        ),
    )
    approve = await client.post(f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert approve.status_code == 409
    assert await stored(engine, tid, eid, day) == before


async def test_daily_analysis_totals_with_mixed_days_and_two_shifts(api, monkeypatch):
    """One date, six employees: present, late, half day, absent, missed punch, night shift."""
    from hrms.core import database
    from hrms.jobs import runner

    client, engine = api
    admin, le, placement, _ = await company(client, {})
    tid = to_uuid(admin["user"]["tenant_id"])
    night = await ok(
        client, "POST", "/v1/policies/templates", json={**BASE, **NIGHT, "name": "Night"}
    )
    day = date(2026, 8, 12)  # a Wednesday
    people = {}
    for key in ("present", "late", "half", "absent", "missed", "night"):
        people[key] = await staff(client, le, placement, f"DA-{key}")
    await ok(
        client,
        "POST",
        "/v1/policies/assignments",
        json=dict(
            employment_id=people["night"][0]["id"],
            policy_template_id=night["id"],
            effective_from="2026-08-01",
        ),
    )
    plan = {
        "present": [("IN", "09:30", 0), ("OUT", "18:30", 0)],
        "late": [("IN", "10:00", 0), ("OUT", "18:30", 0)],
        "half": [("IN", "09:30", 0), ("OUT", "12:00", 0)],
        "missed": [("IN", "09:30", 0)],
        "night": [("IN", "22:00", 0), ("OUT", "06:00", 1)],
    }
    for key, punches in plan.items():
        for kind, clock, offset in punches:
            response = await punch(
                client, monkeypatch, people[key][1], kind, at(day, clock, offset)
            )
            assert response.status_code == 201, (key, kind, response.text)
    set_clock(monkeypatch, at(day, "12:00", 2))
    async with database.AsyncSessionLocal() as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        await runner._missed_punches(session, tid)

    analysis = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={day}")
    by_id = {e["employment_id"]: e for e in analysis["employees"]}
    statuses = {key: by_id[emp["id"]]["status"] for key, (emp, _) in people.items()}
    assert statuses == {
        "present": "PRESENT",
        "late": "LATE",
        "half": "HALF_DAY",
        "absent": "ABSENT",
        "missed": "MISSED_PUNCH",
        "night": "PRESENT",
    }
    assert by_id[people["night"][0]["id"]]["effective_minutes"] == 480
    assert by_id[people["missed"][0]["id"]]["is_currently_in"] is True
    m = analysis["metrics"]
    assert (
        m["total_headcount"],
        m["present_count"],
        m["late_count"],
        m["on_time_count"],
        m["half_day_count"],
        m["absent_count"],
        m["total_overtime_minutes"],
    ) == (6, 5, 1, 4, 1, 1, 0)


async def test_flagged_day_waits_for_hr_review(api, monkeypatch):
    """An over-long day holds its overtime until HR accepts it; a correction clears the flag."""
    client, engine = api
    admin, le, placement, _ = await company(client, {})
    emp, headers = await staff(client, le, placement, "REV-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    day = date(2026, 8, 3)  # a Monday
    await punch(client, monkeypatch, headers, "IN", at(day, "09:30"))
    refused = await punch(client, monkeypatch, headers, "OUT", at(day, "02:00", 1))
    assert refused.status_code == 409
    assert refused.json()["code"] == "LONG_DAY_CONFIRM"
    assert "16-hour" in refused.json()["detail"]
    confirmed = await punch(client, monkeypatch, headers, "OUT", at(day, "02:00", 1), True)
    assert confirmed.status_code == 201
    assert await stored(engine, tid, eid, day) == (990, 990, 0, 0, 0, "PRESENT", 0, "NONE")

    days = await ok(
        client, "GET", f"/v1/time/attendance-days?from_date={day}&to_date={day}", headers=headers
    )
    assert (days[0]["review_flags"], days[0]["needs_review"]) == (["LONG_DAY"], True)
    analysis = await ok(
        client, "GET", f"/v1/time/daily-analysis?work_date={day}&status=NEEDS_REVIEW"
    )
    assert [e["employment_id"] for e in analysis["employees"]] == [emp["id"]]
    day_id = analysis["employees"][0]["attendance_day_id"]
    assert day_id == days[0]["id"]

    # The employee cannot accept their own day; HR can, once.
    own = await client.post(f"/v1/time/attendance-days/{day_id}/review", headers=headers)
    assert own.status_code == 403
    reviewed = await ok(client, "POST", f"/v1/time/attendance-days/{day_id}/review")
    assert (reviewed["needs_review"], reviewed["ot_minutes"], reviewed["ot_status"]) == (
        False,
        450,
        "PENDING",
    )
    assert reviewed["reviewed_at"] and reviewed["reviewed_by"]
    again = await client.post(f"/v1/time/attendance-days/{day_id}/review")
    assert again.status_code == 400
    pending = await ok(client, "GET", "/v1/time/overtime/pending")
    assert [p["ot_minutes"] for p in pending if p["work_date"] == str(day)] == [450]

    # The real check-out was 19:30: the correction clears the flag and the overtime follows.
    cor = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=headers,
        json=dict(
            work_date=str(day),
            correction_type="PUNCH_OUT",
            reason="Forgot to check out",
            requested_punch_out=at(day, "19:30").isoformat(),
        ),
    )
    await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert await stored(engine, tid, eid, day) == (600, 600, 0, 0, 0, "PRESENT", 60, "PENDING")
    assert await review_state(engine, tid, eid, day) == (None, 0.0)
    nothing = await client.post(f"/v1/time/attendance-days/{day_id}/review")
    assert nothing.status_code == 400


async def test_holiday_work_counts_as_off_day_work(api, monkeypatch):
    """Company holidays make a weekday an off day; optional and other companies' holidays don't."""
    client, engine = api
    admin, le, placement, _ = await company(client, {})
    emp, headers = await staff(client, le, placement, "HOL-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    other = await ok(
        client,
        "POST",
        "/v1/org/legal-entities",
        json=dict(name="Other Co", country_code="IN"),
    )
    holidays = {
        date(2026, 8, 5): dict(name="Company holiday"),
        date(2026, 8, 6): dict(name="Optional holiday", is_optional=True),
        date(2026, 8, 7): dict(name="Other company's holiday", legal_entity_id=other["id"]),
        date(2026, 8, 10): dict(name="Our company's holiday", legal_entity_id=le),
    }
    for day, body in holidays.items():
        await ok(client, "POST", "/v1/time/holidays", json={"holiday_date": str(day), **body})
    for day in holidays:
        await punch(client, monkeypatch, headers, "IN", at(day, "10:00"))
        await punch(client, monkeypatch, headers, "OUT", at(day, "14:00"))
    got = {day: (await stored(engine, tid, eid, day))[5:] for day in holidays}
    assert got == {
        date(2026, 8, 5): ("OFF_DAY_WORKED", 240, "PENDING"),
        date(2026, 8, 6): ("LATE", 0, "NONE"),  # an ordinary day: in at 10:00 is late
        date(2026, 8, 7): ("LATE", 0, "NONE"),
        date(2026, 8, 10): ("OFF_DAY_WORKED", 240, "PENDING"),
    }
    analysis = await ok(client, "GET", "/v1/time/daily-analysis?work_date=2026-08-05")
    row = analysis["employees"][0]
    assert (row["status"], row["late_by_minutes"], row["overtime_minutes"]) == (
        "OFF_DAY_WORKED",
        0,
        240,
    )
    assert analysis["metrics"]["present_count"] == 1


async def test_comp_off_is_credited_and_follows_corrections(api, monkeypatch):
    client, engine = api
    admin, le, placement, template = await company(client, {"off_day_work": "COMP_OFF"})
    emp, headers = await staff(client, le, placement, "CMP-1")
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    saturday, sunday = date(2026, 8, 8), date(2026, 8, 9)
    assert template["off_day_work"] == "COMP_OFF"

    async def comp_off_balance():
        rows = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}&year=2026")
        return sum(r["available_days"] for r in rows if r["leave_type_code"] == "COMPOFF")

    async def ledger():
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT transaction_type, quantity FROM leave_balance_transactions"
                    " WHERE tenant_id=:t AND employment_id=:e AND reference_type='COMP_OFF'"
                    " ORDER BY recorded_at"
                ),
                dict(t=tid, e=eid),
            )
            return [tuple(r) for r in rows]

    await punch(client, monkeypatch, headers, "IN", at(saturday, "09:30"))
    await punch(client, monkeypatch, headers, "OUT", at(saturday, "18:30"))
    assert await review_state(engine, tid, eid, saturday) == (None, 1.0)
    assert await comp_off_balance() == 1.0

    # Corrected to a 4 h 30 m day: half a day comes back off the balance.
    cor = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=headers,
        json=dict(
            work_date=str(saturday),
            correction_type="PUNCH_OUT",
            reason="Left at 14:00",
            requested_punch_out=at(saturday, "14:00").isoformat(),
        ),
    )
    await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert await review_state(engine, tid, eid, saturday) == (None, 0.5)
    assert await comp_off_balance() == 0.5
    assert await ledger() == [("GRANT", 1.0), ("ADJUSTMENT", -0.5)]

    # A comp-off HR granted by hand for Sunday is left alone by Sunday's attendance.
    await ok(
        client,
        "POST",
        "/v1/leave/comp-off",
        json=dict(employment_id=emp["id"], work_date=str(sunday), days_granted=1.0),
    )
    await punch(client, monkeypatch, headers, "IN", at(sunday, "10:00"))
    await punch(client, monkeypatch, headers, "OUT", at(sunday, "12:00"))
    assert await review_state(engine, tid, eid, sunday) == (None, 0.0)
    assert await comp_off_balance() == 1.5

    # A forgotten break end holds the credit until HR accepts the day.
    later = date(2026, 8, 15)  # the next Saturday
    for kind, clock in [("IN", "09:30"), ("BREAK_START", "13:00"), ("OUT", "18:30")]:
        await punch(client, monkeypatch, headers, kind, at(later, clock))
    assert await review_state(engine, tid, eid, later) == ("BREAK_NOT_ENDED", 0.0)
    days = await ok(
        client,
        "GET",
        f"/v1/time/attendance-days?employment_id={emp['id']}&from_date={later}&to_date={later}",
    )
    await ok(client, "POST", f"/v1/time/attendance-days/{days[0]['id']}/review")
    assert await review_state(engine, tid, eid, later) == ("BREAK_NOT_ENDED", 1.0)
    assert await comp_off_balance() == 2.5
