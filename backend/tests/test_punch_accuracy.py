"""
Punch in / punch out at any time, several times a day, and whether every report agrees.

Real HTTP with row-level security: an employee punches through POST /v1/time/punches with the
API clock set to each instant. An independent oracle computes what each day should be, and the
result is compared with every place attendance is reported:

  stored attendance_days · GET /v1/time/attendance-days (employee) · GET /v1/time/today ·
  POST /v1/reports/{id}/run (report builder) · GET /v1/time/daily-analysis (HR) ·
  GET /v1/dashboard month summary (employee)

Business rules the oracle encodes (shift 09:30–18:30 with a 60-minute break, so 8 h standard):
  * total = first IN to last OUT; deducted = only time actually away — checked out between
    sessions, or on a recorded BREAK — never an automatic break; worked = total − deducted;
  * lateness from the first IN, early departure from the last OUT, after grace; present /
    half-day / late / early and overtime follow from worked time;
  * a session still open 24 hours after its check-in is a MISSED_PUNCH (flagged by the next
    check-in or the daily job); within 24 hours a check-out after midnight still closes it.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from tests.helpers import bearer, employee, hire, ok, org_basics, tenant

pytestmark = pytest.mark.database
IST = ZoneInfo("Asia/Kolkata")

POLICY = dict(
    name="Standard IST",
    timezone="Asia/Kolkata",
    is_default=True,
    expected_start_time="09:30:00",
    expected_end_time="18:30:00",
    work_days="1111111",
    break_minutes=60,
    break_auto_deduct=True,
    grace_late_minutes=15,
    grace_early_departure_minutes=15,
    half_day_threshold_pct=50,
    ot_enabled=True,
    ot_qualifying_minutes=30,
    ot_rate=1.5,
    ot_daily_cap_minutes=None,
    punch_rounding_minutes=0,
    punch_rounding_direction="NONE",
    correction_requires_approval=True,
    correction_approval_levels=1,
)
START, END, BREAK, GRACE = time(9, 30), time(18, 30), 60, 15
STANDARD = 9 * 60 - BREAK  # 8 h: the half-day threshold is half of this
SHIFT = 9 * 60  # 09:30-18:30: overtime only after the whole shift


def at(day: date, clock: str, plus_days: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=plus_days), time.fromisoformat(clock), IST)


# Each scenario: work date → punches as (type, "HH:MM" [, +days]).
SCENARIOS: dict[str, tuple[date, list[tuple]]] = {
    "single session": (date(2026, 9, 14), [("IN", "09:20"), ("OUT", "18:40")]),
    "lunch by punching out": (
        date(2026, 9, 15),
        [("IN", "09:25"), ("OUT", "13:00"), ("IN", "14:00"), ("OUT", "18:35")],
    ),
    "four field visits": (
        date(2026, 9, 16),
        [
            ("IN", "09:28"),
            ("OUT", "11:00"),
            ("IN", "11:45"),
            ("OUT", "13:10"),
            ("IN", "13:40"),
            ("OUT", "16:00"),
            ("IN", "16:30"),
            ("OUT", "19:15"),
        ],
    ),
    "late with explicit break and overtime": (
        date(2026, 9, 17),
        [("IN", "10:05"), ("BREAK_START", "13:00"), ("BREAK_END", "13:45"), ("OUT", "19:30")],
    ),
    "very early start, early leave": (date(2026, 9, 21), [("IN", "03:00"), ("OUT", "11:00")]),
    "forgot to punch out": (date(2026, 9, 22), [("IN", "09:45")]),
    "short day in two sessions": (
        date(2026, 9, 23),
        [("IN", "09:30"), ("OUT", "12:00"), ("IN", "12:30"), ("OUT", "14:00")],
    ),
    "just after midnight start": (date(2026, 9, 25), [("IN", "00:30"), ("OUT", "09:00")]),
    "reopened after leaving": (
        date(2026, 9, 28),
        [("IN", "09:30"), ("OUT", "18:30"), ("IN", "20:00")],
    ),
}
NO_PUNCH_DAY = date(2026, 9, 24)


@dataclass
class Expected:
    first_in: datetime | None
    last_out: datetime | None
    gross: int
    deducted: int
    effective: int
    late: int
    early: int
    ot: int
    status: str
    punches: int
    open: bool
    notes: list[str] = field(default_factory=list)


def oracle(day: date, punches: list[tuple]) -> Expected:
    events = [(kind, at(day, clock, *extra)) for kind, clock, *extra in punches]
    sessions, breaks, started, brk_start = [], 0, None, None
    for kind, stamp in events:
        if kind == "IN":
            started = stamp
        elif kind == "BREAK_START":
            brk_start = stamp
        elif kind == "BREAK_END":
            breaks += int((stamp - brk_start).total_seconds() // 60)
            brk_start = None
        elif kind == "OUT":
            sessions.append((started, stamp))
            started = None
    worked = sum(int((b - a).total_seconds() // 60) for a, b in sessions)
    effective = max(0, worked - breaks)
    gross = int((sessions[-1][1] - sessions[0][0]).total_seconds() // 60) if sessions else 0
    deducted = gross - effective
    ins = [s for k, s in events if k == "IN"]
    outs = [s for k, s in events if k == "OUT"]
    first_in, last_out = (min(ins) if ins else None), (max(outs) if outs else None)
    is_open = started is not None
    late = max(0, int((first_in - at(day, START.isoformat())).total_seconds() // 60) - GRACE)
    early = 0
    if last_out and not is_open:
        early = max(0, int((at(day, END.isoformat()) - last_out).total_seconds() // 60) - GRACE)
    if is_open:
        # Checked a full day later (see the test), the open session is a missed punch.
        status = "MISSED_PUNCH"
        effective_for_status = effective
    else:
        effective_for_status = effective
        if effective_for_status == 0:
            status = "ABSENT"
        elif effective_for_status < STANDARD * 50 // 100:
            status = "HALF_DAY"
        elif late:
            status = "LATE"
        elif early:
            status = "EARLY_DEPARTURE"
        else:
            status = "PRESENT"
    excess = effective - SHIFT
    ot = excess if (not is_open and excess >= 30) else 0
    return Expected(
        first_in,
        last_out,
        gross,
        deducted,
        effective,
        late,
        early,
        ot,
        status,
        len(events),
        is_open,
    )


async def _setup(client):
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emp, login = await employee(client, le, "PUNCH-1")
    await hire(client, emp["id"], placement)
    await ok(client, "POST", "/v1/policies/templates", json=POLICY)
    return admin, emp, bearer(login["access_token"])


async def _punch(client, monkeypatch, headers, kind, stamp):
    from hrms.modules.time import router as time_router
    from hrms.modules.time import service as time_service

    instant = stamp.astimezone(UTC)
    monkeypatch.setattr(time_router, "now_utc", lambda: instant)
    monkeypatch.setattr(time_service, "now_utc", lambda: instant)
    return await client.post("/v1/time/punches", headers=headers, json={"punch_type": kind})


def _t(value):
    """API datetimes → aware UTC datetimes (or None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utc(value):
    return value.astimezone(UTC) if value else None


async def test_multiple_punches_any_time_and_every_report_agrees(api, monkeypatch):
    client, engine = api
    admin, emp, headers = await _setup(client)
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])

    expected: dict[date, tuple[str, Expected]] = {}
    for name, (day, punches) in SCENARIOS.items():
        for kind, clock, *extra in punches:
            response = await _punch(client, monkeypatch, headers, kind, at(day, clock, *extra))
            assert response.status_code == 201, (name, kind, clock, response.text)
        expected[day] = (name, oracle(day, punches))

    # The daily job, run on 1 October, flags sessions still open 24 hours on.
    from hrms.core import database
    from hrms.jobs import runner
    from hrms.modules.time import service as time_service

    october = datetime(2026, 10, 1, 6, 0, tzinfo=IST).astimezone(UTC)
    monkeypatch.setattr(time_service, "now_utc", lambda: october)
    monkeypatch.setattr(runner, "now_utc", lambda: october)
    async with database.AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)}
        )
        summary = await runner._missed_punches(session, tid)
    # The 22nd was already flagged by the next check-in made over 24 h after it; the job
    # catches the 28th, after which the employee never punched again.
    assert summary == "1 missed punch flagged"

    report = await ok(
        client,
        "POST",
        "/v1/reports",
        json=dict(
            name="Punch accuracy",
            module="ATTENDANCE",
            filters=[],
            columns=[
                dict(field=f, label=f, visible=True)
                for f in (
                    "work_date",
                    "status",
                    "first_punch_in",
                    "last_punch_out",
                    "effective_minutes",
                    "late_by_minutes",
                    "early_departure_minutes",
                )
            ],
        ),
    )
    history = {
        r["work_date"]: r
        for r in await ok(
            client,
            "GET",
            "/v1/time/attendance-days?from_date=2026-09-01&to_date=2026-09-30",
            headers=headers,
        )
    }
    mismatches: list[str] = []

    def check(where, name, got, want):
        if got != want:
            mismatches.append(f"{name:<38} {where:<34} got {got!r:<28} expected {want!r}")

    for day, (name, exp) in sorted(expected.items()):
        async with engine.connect() as conn:
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM attendance_days WHERE tenant_id=:t AND employment_id=:e "
                            "AND work_date=:d"
                        ),
                        dict(t=tid, e=eid, d=day),
                    )
                )
                .mappings()
                .one()
            )
        for col, want in (
            ("gross_minutes", exp.gross),
            ("break_minutes", exp.deducted),
            ("effective_minutes", exp.effective),
            ("late_by_minutes", exp.late),
            ("early_departure_minutes", exp.early),
            ("ot_minutes", exp.ot),
            ("status", exp.status),
        ):
            check(f"stored.{col}", name, stored[col], want)
        check("stored.first_punch_in", name, _utc(stored["first_punch_in"]), _utc(exp.first_in))
        check("stored.last_punch_out", name, _utc(stored["last_punch_out"]), _utc(exp.last_out))

        h = history.get(day.isoformat())
        check("employee history row", name, h is not None, True)
        if h:
            for key, want in (
                ("effective_minutes", exp.effective),
                ("status", exp.status),
                ("late_by_minutes", exp.late),
                ("ot_minutes", exp.ot),
            ):
                check(f"history.{key}", name, h[key], want)

        today = await ok(client, "GET", f"/v1/time/today?work_date={day}", headers=headers)
        check("today.punches", name, len(today["punches"]), exp.punches)
        check("today.is_punched_in", name, today["is_punched_in"], exp.open)
        check("today.effective_minutes", name, today["effective_minutes"], exp.effective)

        rows = (
            await ok(
                client,
                "POST",
                f"/v1/reports/{report['id']}/run",
                json={
                    "filters": [
                        dict(field="work_date", op="eq", value=str(day)),
                        dict(field="employment_id", op="eq", value=emp["id"]),
                    ]
                },
            )
        )["rows"]
        check("report builder rows", name, len(rows), 1)
        if rows:
            r = rows[0]
            for key, want in (
                ("effective_minutes", exp.effective),
                ("status", exp.status),
                ("late_by_minutes", exp.late),
                ("early_departure_minutes", exp.early),
            ):
                check(f"report.{key}", name, r[key], want)

        da = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={day}")
        rec = next((e for e in da["employees"] if e["employment_id"] == emp["id"]), None)
        check("daily-analysis has employee", name, rec is not None, True)
        if rec:
            for key, want in (
                ("status", exp.status),
                ("effective_minutes", exp.effective),
                ("gross_minutes", exp.gross),
                ("break_minutes", exp.deducted),
                ("late_by_minutes", exp.late),
                ("early_departure_minutes", exp.early),
                ("overtime_minutes", exp.ot),
                ("punches_count", exp.punches),
                ("is_currently_in", exp.open),
            ):
                check(f"daily.{key}", name, rec[key], want)
            check("daily.first_punch_in", name, _t(rec["first_punch_in"]), _utc(exp.first_in))
            check("daily.last_punch_out", name, _t(rec["last_punch_out"]), _utc(exp.last_out))

    # A day with no punches is absent in Daily Analysis and has no attendance row.
    da = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={NO_PUNCH_DAY}")
    rec = next(e for e in da["employees"] if e["employment_id"] == emp["id"])
    check("daily.status", "no punches", rec["status"], "ABSENT")

    # Month summary on the employee dashboard (as of 30 Sep).
    from hrms.modules.dashboard import router as dashboard_router

    monkeypatch.setattr(dashboard_router, "business_today", lambda *a, **k: date(2026, 9, 30))
    dash = await ok(client, "GET", "/v1/dashboard/employee", headers=headers)
    month = dash["month_summary"]
    days = [e for _, e in expected.values()]
    check("dashboard.present", "September", month["present"], len(days))
    check("dashboard.late", "September", month["late"], sum(1 for e in days if e.late))

    print("\n" + ("\n".join(mismatches) if mismatches else "Every report matched the oracle."))
    assert not mismatches, f"{len(mismatches)} mismatches:\n" + "\n".join(mismatches)


async def test_check_out_after_midnight_on_a_day_shift(api, monkeypatch):
    """Working late: IN 09:30 Friday, OUT 01:15 Saturday belongs to Friday."""
    from hrms.modules.time import router as time_router

    client, engine = api
    admin, emp, headers = await _setup(client)
    day = date(2026, 9, 18)
    assert (await _punch(client, monkeypatch, headers, "IN", at(day, "09:30"))).status_code == 201

    # Within 24 hours of the check-in, Friday's session is still the live one: the clock and
    # the dashboard show it, so the employee can check out of it.
    clock = at(day, "00:40", 1).astimezone(UTC)
    monkeypatch.setattr(time_router, "now_utc", lambda: clock)
    today = await ok(client, "GET", "/v1/time/today", headers=headers)
    assert today["work_date"] == str(day)
    assert today["is_punched_in"] is True
    assert [p["punch_type"] for p in today["punches"]] == ["IN"]
    dash = await ok(client, "GET", "/v1/dashboard/employee", headers=headers)
    assert dash["today"]["is_punched_in"] is True

    # Logging in the following day must not make an expired session look active.
    monkeypatch.setattr(time_router, "now_utc", lambda: at(day, "10:00", 1).astimezone(UTC))
    expired = await ok(client, "GET", "/v1/time/today", headers=headers)
    assert expired["is_punched_in"] is False
    dash = await ok(client, "GET", "/v1/dashboard/employee", headers=headers)
    assert dash["today"]["is_punched_in"] is False

    out = await _punch(client, monkeypatch, headers, "OUT", at(day, "01:15", 1))
    assert out.status_code == 201, f"check-out after midnight refused: {out.status_code} {out.text}"
    # Saturday morning starts a new day as usual.
    saturday = day + timedelta(days=1)
    assert (
        await _punch(client, monkeypatch, headers, "IN", at(saturday, "10:00"))
    ).status_code == 201
    assert (
        await _punch(client, monkeypatch, headers, "OUT", at(saturday, "14:00"))
    ).status_code == 201
    rows = {
        r["work_date"]: r
        for r in await ok(
            client,
            "GET",
            "/v1/time/attendance-days?from_date=2026-09-18&to_date=2026-09-19",
            headers=headers,
        )
    }
    friday = rows["2026-09-18"]
    assert friday["effective_minutes"] == 15 * 60 + 45
    assert friday["ot_minutes"] == 15 * 60 + 45 - SHIFT
    assert friday["status"] == "PRESENT"
    assert rows["2026-09-19"]["effective_minutes"] == 4 * 60
    assert rows["2026-09-19"]["first_punch_in"].startswith("2026-09-19T04:30")

    # More than 24 hours after the check-in, a check-out is refused as a missed punch; the
    # next check-in starts the new day and flags the old one for HR to correct.
    monday = date(2026, 9, 21)
    assert (
        await _punch(client, monkeypatch, headers, "IN", at(monday, "09:30"))
    ).status_code == 201
    stale = await _punch(client, monkeypatch, headers, "OUT", at(monday, "10:00", 1))
    assert stale.status_code == 409 and "Missed punch" in stale.text
    tuesday = monday + timedelta(days=1)
    assert (
        await _punch(client, monkeypatch, headers, "IN", at(tuesday, "10:05"))
    ).status_code == 201
    days = {
        r["work_date"]: r
        for r in await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?from_date={monday}&to_date={tuesday}",
            headers=headers,
        )
    }
    assert days[str(monday)]["status"] == "MISSED_PUNCH"
    assert days[str(tuesday)]["status"] == "LATE"
    today = await ok(client, "GET", f"/v1/time/today?work_date={tuesday}", headers=headers)
    assert [p["punch_type"] for p in today["punches"]] == ["IN"]


async def test_rounding_happens_on_the_local_clock(api, monkeypatch):
    """60-minute NEAREST rounding in IST: 09:10 → 09:00, so a 09:00 start isn't late."""
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    emp, login = await employee(client, le, "ROUND-1")
    headers = bearer(login["access_token"])
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json={
            **POLICY,
            "expected_start_time": "09:00:00",
            "expected_end_time": "18:00:00",
            "break_auto_deduct": False,
            "grace_late_minutes": 0,
            "grace_early_departure_minutes": 0,
            "punch_rounding_minutes": 60,
            "punch_rounding_direction": "NEAREST",
        },
    )
    day = date(2026, 9, 14)
    await _punch(client, monkeypatch, headers, "IN", at(day, "09:10"))
    await _punch(client, monkeypatch, headers, "OUT", at(day, "18:05"))
    row = (
        await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?from_date={day}&to_date={day}",
            headers=headers,
        )
    )[0]
    assert (row["late_by_minutes"], row["effective_minutes"], row["status"]) == (0, 540, "PRESENT")
    placement = await org_basics(client, le)
    await hire(client, emp["id"], placement)
    da = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={day}")
    rec = next(e for e in da["employees"] if e["employment_id"] == emp["id"])
    assert (rec["late_by_minutes"], rec["status"]) == (0, "PRESENT")
    assert da["metrics"]["late_count"] == 0


async def test_invalid_sequences_are_refused_and_change_nothing(api, monkeypatch):
    client, _ = api
    admin, emp, headers = await _setup(client)
    day = date(2026, 9, 14)
    assert (await _punch(client, monkeypatch, headers, "OUT", at(day, "08:59"))).status_code == 409
    assert (await _punch(client, monkeypatch, headers, "IN", at(day, "09:00"))).status_code == 201
    # A double-tap on Check in.
    assert (await _punch(client, monkeypatch, headers, "IN", at(day, "09:00"))).status_code == 409
    bad_end = await _punch(client, monkeypatch, headers, "BREAK_END", at(day, "12:00"))
    assert bad_end.status_code == 409
    assert (await _punch(client, monkeypatch, headers, "OUT", at(day, "18:30"))).status_code == 201
    assert (await _punch(client, monkeypatch, headers, "OUT", at(day, "18:31"))).status_code == 409
    today = await ok(client, "GET", f"/v1/time/today?work_date={day}", headers=headers)
    assert [p["punch_type"] for p in today["punches"]] == ["IN", "OUT"]
    assert today["effective_minutes"] == 9 * 60 + 30


async def test_overtime_starts_after_the_shift_and_is_visible_only_without_a_policy(
    api, monkeypatch
):
    """09:30-18:30 with no break is not overtime. Without an overtime policy the extra time is
    shown (INFO) but never goes for approval, so it can't reach payroll."""
    client, _ = api
    admin, emp, headers = await _setup(client)
    day = date(2026, 9, 14)
    await _punch(client, monkeypatch, headers, "IN", at(day, "09:30"))
    await _punch(client, monkeypatch, headers, "OUT", at(day, "18:30"))
    row = (
        await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?from_date={day}&to_date={day}",
            headers=headers,
        )
    )[0]
    assert (row["effective_minutes"], row["ot_minutes"], row["ot_status"]) == (540, 0, "NONE")

    # With the overtime policy (threshold 30 min): 19:15 is 45 min past the shift.
    tuesday = date(2026, 9, 15)
    await _punch(client, monkeypatch, headers, "IN", at(tuesday, "09:30"))
    await _punch(client, monkeypatch, headers, "OUT", at(tuesday, "19:15"))
    row = (
        await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?from_date={tuesday}&to_date={tuesday}",
            headers=headers,
        )
    )[0]
    assert (row["ot_minutes"], row["ot_status"]) == (45, "PENDING")

    # Without an overtime policy the same 45 minutes are shown only.
    template = next(t for t in await ok(client, "GET", "/v1/policies/templates") if t["is_default"])
    await ok(
        client, "PATCH", f"/v1/policies/templates/{template['id']}", json={"ot_enabled": False}
    )
    wednesday = date(2026, 9, 16)
    await _punch(client, monkeypatch, headers, "IN", at(wednesday, "09:30"))
    await _punch(client, monkeypatch, headers, "OUT", at(wednesday, "19:15"))
    row = (
        await ok(
            client,
            "GET",
            f"/v1/time/attendance-days?from_date={wednesday}&to_date={wednesday}",
            headers=headers,
        )
    )[0]
    assert (row["ot_minutes"], row["ot_status"]) == (45, "INFO")
    pending = await ok(client, "GET", "/v1/time/overtime/pending")
    assert all(p["work_date"] != str(wednesday) for p in pending)
    refused = await client.patch(f"/v1/time/overtime/{row['id']}", json={"status": "APPROVED"})
    assert refused.status_code == 400
    da = await ok(client, "GET", f"/v1/time/daily-analysis?work_date={wednesday}")
    rec = next(e for e in da["employees"] if e["employment_id"] == emp["id"])
    assert (rec["overtime_minutes"], rec["overtime_status"]) == (45, "INFO")
