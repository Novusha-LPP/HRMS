"""Independent arithmetic oracle plus real punch/correction/report policy matrix.

Set HRMS_POLICY_MATRIX_OUTPUT to save anonymized API observations as JSON.
The API clock alone is controlled; authorization, policy resolution, transactions,
RLS, immutable punches, correction approval and report SQL run normally.
"""

import itertools
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from hrms.core.ids import to_uuid
from hrms.modules.policy.engine import _merge
from hrms.modules.policy.models import PolicyTemplate
from hrms.modules.time.models import AttendanceDay
from hrms.modules.time.service import recompute_day

HOURS = [4, 6, 8, 9, 10, 12]
BREAKS = ["none", "configured_only", "auto", "explicit_30", "explicit_60", "explicit_90"]
# start offset in seconds, duration in seconds or a named boundary.
SCENARIOS = [
    ("zero", 0, 0),
    ("one_minute", 0, 60),
    ("below_half", 0, "half-1"),
    ("at_half", 0, "half"),
    ("below_standard", 0, "standard-1"),
    ("at_standard", 0, "standard"),
    ("ot_below", 0, "ot-1"),
    ("ot_exact", 0, "ot"),
    ("ot_above", 0, "ot+1"),
    ("late_14", 14 * 60, "scheduled"),
    ("late_15", 15 * 60, "scheduled"),
    ("late_15m59s", 15 * 60 + 59, "scheduled"),
    ("late_16", 16 * 60, "scheduled"),
    ("early_14", 0, "early14"),
    ("early_15", 0, "early15"),
    ("early_16", 0, "early16"),
    ("early_arrival", -60 * 60, "scheduled"),
    ("missing_out", 0, None),
]


def config(hours, mode, grace, ot, approval=True):
    brk = 0 if mode == "none" else 60
    end = datetime(2026, 1, 1, 9, 30) + timedelta(hours=hours, minutes=brk)
    return dict(
        name="Matrix",
        timezone="Asia/Kolkata",
        is_default=True,
        expected_start_time="09:30:00",
        expected_end_time=end.time().isoformat(),
        work_days="1111111",
        break_minutes=brk,
        break_auto_deduct=mode == "auto",
        grace_late_minutes=grace,
        grace_early_departure_minutes=grace,
        half_day_threshold_pct=50,
        ot_enabled=ot,
        ot_qualifying_minutes=40,
        ot_rate=1.5,
        ot_daily_cap_minutes=None,
        punch_rounding_minutes=0,
        punch_rounding_direction="NONE",
        correction_requires_approval=approval,
        correction_approval_levels=1,
    )


def example(day, hours, mode, scenario):
    name, offset, duration = scenario
    start = datetime.combine(day, time(9, 30), ZoneInfo("Asia/Kolkata")).astimezone(UTC)
    scheduled = hours * 60 + (0 if mode == "none" else 60)
    deduction = (
        int(mode.split("_")[1]) if mode.startswith("explicit_") else (60 if mode == "auto" else 0)
    )
    named = {
        "half-1": hours * 30 - 1 + deduction,
        "half": hours * 30 + deduction,
        "standard-1": hours * 60 - 1 + deduction,
        "standard": hours * 60 + deduction,
        "ot-1": hours * 60 + 39 + deduction,
        "ot": hours * 60 + 40 + deduction,
        "ot+1": hours * 60 + 41 + deduction,
        "scheduled": scheduled - offset / 60,
        "early14": scheduled - 14,
        "early15": scheduled - 15,
        "early16": scheduled - 16,
    }
    seconds = named[duration] * 60 if isinstance(duration, str) else duration
    pin = start + timedelta(seconds=offset)
    events = [("IN", pin)]
    if seconds is not None:
        pout = pin + timedelta(seconds=seconds)
        if mode.startswith("explicit_"):
            actual_break = min(seconds, deduction * 60)
            mid = pin + timedelta(seconds=(seconds - actual_break) / 2)
            events.extend(
                [("BREAK_START", mid), ("BREAK_END", mid + timedelta(seconds=actual_break))]
            )
        events.append(("OUT", pout))
    return events, start, start + timedelta(minutes=scheduled)


def expected(events, scheduled_start, scheduled_end, hours, mode, grace, ot):
    pin = events[0][1]
    pout = events[-1][1] if events[-1][0] == "OUT" else None
    late = max(0, int((pin - scheduled_start).total_seconds() // 60) - grace)
    if pout is None:
        return dict(
            gross_minutes=0,
            break_minutes=0,
            effective_minutes=0,
            late_by_minutes=late,
            early_departure_minutes=0,
            ot_minutes=0,
            status="LATE" if late else "PRESENT",
        )
    gross = int((pout - pin).total_seconds() // 60)
    early = max(0, int((scheduled_end - pout).total_seconds() // 60) - grace)
    if mode.startswith("explicit_"):
        brk = int((events[2][1] - events[1][1]).total_seconds() // 60)
    else:
        brk = min(gross, 60) if mode == "auto" else 0
    effective = max(0, gross - brk)
    excess = effective - hours * 60
    overtime = excess if ot and excess >= 40 else 0
    status = (
        "ABSENT"
        if effective == 0
        else "HALF_DAY"
        if effective < hours * 30
        else "LATE"
        if late
        else "EARLY_DEPARTURE"
        if early
        else "PRESENT"
    )
    return dict(
        gross_minutes=gross,
        break_minutes=brk,
        effective_minutes=effective,
        late_by_minutes=late,
        early_departure_minutes=early,
        ot_minutes=overtime,
        status=status,
    )


CORE_CASES = list(itertools.product(HOURS, BREAKS, [0, 15], [False, True], SCENARIOS))


@pytest.mark.parametrize("hours,mode,grace,ot,scenario", CORE_CASES)
async def test_policy_arithmetic_matrix(monkeypatch, hours, mode, grace, ot, scenario):
    from hrms.modules.time import service

    monkeypatch.setattr(service.approval_flow, "finish", AsyncMock())
    monkeypatch.setattr(service.approval_flow, "start", AsyncMock())

    day = date(2026, 9, 28)
    events, start, end = example(day, hours, mode, scenario)
    oracle = expected(events, start, end, hours, mode, grace, ot)
    monkeypatch.setattr(
        service,
        "events_for_day",
        AsyncMock(return_value=[SimpleNamespace(punch_type=k, punched_at=v) for k, v in events]),
    )
    values = config(hours, mode, grace, ot)
    values["expected_start_time"] = time.fromisoformat(values["expected_start_time"])
    values["expected_end_time"] = time.fromisoformat(values["expected_end_time"])
    resolved = _merge(PolicyTemplate(tenant_id=uuid4(), id=uuid4(), **values), None)
    assert resolved.standard_minutes == hours * 60
    assert resolved.ot_rate == 1.5
    tenant, employment = uuid4(), uuid4()
    ad = AttendanceDay(tenant_id=tenant, id=uuid4(), employment_id=employment, work_date=day)
    result = await recompute_day(
        SimpleNamespace(add=Mock(), flush=AsyncMock()), tenant, employment, day, resolved, ad
    )
    for field, value in oracle.items():
        assert getattr(result, field) == value, (hours, mode, grace, ot, scenario[0], field, value)
    assert result.ot_status == ("PENDING" if oracle["ot_minutes"] else "NONE")


@pytest.mark.database
async def test_real_api_policy_matrix(api, monkeypatch):
    from hrms.modules.time import router as time_router
    from tests.helpers import bearer, employee, ok, tenant

    client, engine = api
    admin = await tenant(client)
    emp, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    token = bearer(login["access_token"])
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    tpl = await ok(client, "POST", "/v1/policies/templates", json=config(8, "auto", 15, True))
    fields = [
        "work_date",
        "status",
        "first_punch_in",
        "last_punch_out",
        "effective_minutes",
        "late_by_minutes",
        "early_departure_minutes",
    ]
    report = await ok(
        client,
        "POST",
        "/v1/reports",
        json=dict(
            name="Policy matrix",
            module="ATTENDANCE",
            columns=[dict(field=f, label=f, visible=True) for f in fields],
            filters=[],
        ),
    )
    observations = []
    modes = ["none", "configured_only", "auto", "explicit_60"]
    cases = list(itertools.product(HOURS, modes, [0, 15], [False, True], [False, True]))
    for index, (hours, mode, grace, ot, approval) in enumerate(cases):
        values = config(hours, mode, grace, ot, approval)
        await ok(client, "PATCH", f"/v1/policies/templates/{tpl['id']}", json=values)
        day = date(2026, 1, 1) + timedelta(days=index)
        # Boundary after 40 extra minutes, with a late arrival; correction then
        # removes the late arrival and reduces work to exactly the standard.
        scenario = ("ot_exact_late", 16 * 60, "ot")
        events, start, end = example(day, hours, mode, scenario)
        oracle = expected(events, start, end, hours, mode, grace, ot)
        for kind, stamp in events:
            monkeypatch.setattr(time_router, "now_utc", lambda stamp=stamp: stamp)
            await ok(client, "POST", "/v1/time/punches", headers=token, json={"punch_type": kind})

        async def snapshot(day=day, index=index):
            rows = await ok(
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
            assert len(rows["rows"]) == 1 and not rows["truncated"]
            row = rows["rows"][0]
            async with engine.connect() as conn:
                stored = (
                    (
                        await conn.execute(
                            text(
                                "SELECT * FROM attendance_days WHERE tenant_id=:t "
                                "AND employment_id=:e AND work_date=:d"
                            ),
                            dict(t=tid, e=eid, d=day),
                        )
                    )
                    .mappings()
                    .one()
                )
            for f in fields:
                actual = stored[f]
                if isinstance(actual, (datetime, date)):
                    actual = actual.isoformat()
                if isinstance(stored[f], datetime):
                    assert datetime.fromisoformat(row[f].replace("Z", "+00:00")) == stored[f]
                else:
                    assert row[f] == actual, (index, f, row[f], actual)
            return row, dict(stored)

        before, stored = await snapshot()
        for f, v in oracle.items():
            assert stored[f] == v, (index, "before", f, stored[f], v)
        # Keep explicit break events inside the corrected interval.
        corrected_out = start + timedelta(
            minutes=hours * 60 + (60 if mode in ("auto", "explicit_60") else 0)
        )
        cor = await ok(
            client,
            "POST",
            "/v1/corrections",
            headers=token,
            json=dict(
                work_date=str(day),
                correction_type="REGULARIZE",
                requested_punch_in=start.isoformat(),
                requested_punch_out=corrected_out.isoformat(),
                reason="Matrix corrected endpoints",
            ),
        )
        if approval:
            assert cor["status"] == "PENDING_L1"
            pending, _ = await snapshot()
            assert pending == before
            cor = await ok(
                client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"}
            )
            assert len(cor["approval_history"]) == 1
        assert cor["status"] == "APPROVED"
        corrected_events = [
            (k, start if k == "IN" else corrected_out if k == "OUT" else v) for k, v in events
        ]
        corrected_oracle = expected(corrected_events, start, end, hours, mode, grace, ot)
        after, stored = await snapshot()
        for f, v in corrected_oracle.items():
            assert stored[f] == v, (index, "after", f, stored[f], v)
        observations.append(
            dict(
                hours=hours,
                break_mode=mode,
                grace_minutes=grace,
                overtime_enabled=ot,
                approval_required=approval,
                before=oracle,
                after=corrected_oracle,
                report_matches_storage=True,
                pending_unchanged=approval,
            )
        )
    output = os.getenv("HRMS_POLICY_MATRIX_OUTPUT")
    if output:
        Path(output).write_text(json.dumps(observations, indent=2) + "\n")


@pytest.mark.database
async def test_policy_edge_workflows(api, monkeypatch):
    from hrms.core.ids import to_typed_id
    from hrms.modules.time import router as time_router
    from tests.helpers import bearer, employee, ok, tenant

    client, engine = api
    admin = await tenant(client)
    emp, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    token = bearer(login["access_token"])
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    tpl = await ok(client, "POST", "/v1/policies/templates", json=config(8, "auto", 15, True))
    report = await ok(
        client,
        "POST",
        "/v1/reports",
        json=dict(
            name="Edge cases",
            module="ATTENDANCE",
            columns=[
                dict(field=f, label=f, visible=True)
                for f in [
                    "work_date",
                    "first_punch_in",
                    "last_punch_out",
                    "effective_minutes",
                    "status",
                ]
            ],
            filters=[],
        ),
    )

    async def punch(day, clock, kind, expected_code=201):
        instant = datetime.combine(
            day, time.fromisoformat(clock), ZoneInfo("Asia/Kolkata")
        ).astimezone(UTC)
        monkeypatch.setattr(time_router, "now_utc", lambda: instant)
        response = await client.post("/v1/time/punches", headers=token, json={"punch_type": kind})
        assert response.status_code == expected_code, response.text

    async def rows(day):
        data = await ok(
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
        return data["rows"]

    async def correction(day, kind="REGULARIZE", **overrides):
        body = dict(work_date=str(day), correction_type=kind, reason="Edge test")
        if kind == "REGULARIZE":
            body.update(
                requested_punch_in=datetime.combine(
                    day, time(9, 30), ZoneInfo("Asia/Kolkata")
                ).isoformat(),
                requested_punch_out=datetime.combine(
                    day, time(18, 30), ZoneInfo("Asia/Kolkata")
                ).isoformat(),
            )
        body.update(overrides)
        return await ok(client, "POST", "/v1/corrections", headers=token, json=body)

    day = date(2026, 8, 3)
    assert await rows(day) == []  # A missing stored row is omitted, not generated as absent.
    await punch(day, "09:30", "OUT", 409)
    await punch(day, "09:30", "BREAK_START", 409)
    await punch(day, "09:30", "IN")
    await punch(day, "09:31", "IN", 409)
    await punch(day, "09:32", "BREAK_END", 409)
    opened = (await rows(day))[0]
    assert opened["effective_minutes"] == 0 and opened["last_punch_out"] is None
    await punch(day, "18:30", "OUT")
    await punch(day, "18:31", "OUT", 409)
    original = await rows(day)
    for action in ["reject", "cancel"]:
        cor = await correction(day)
        assert cor["status"] == "PENDING_L1" and await rows(day) == original
        await ok(client, "POST", f"/v1/corrections/{cor['id']}/{action}", json={"action": "REJECT"})
        assert await rows(day) == original
    cor = await correction(day)
    denial = await client.post(
        f"/v1/corrections/{cor['id']}/approve", headers=token, json={"action": "APPROVE"}
    )
    assert denial.status_code in (400, 403)
    assert await rows(day) == original
    await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    twice = await client.post(f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert twice.status_code == 400

    # Missing OUT is only materialized after the one approval.
    day += timedelta(days=1)
    await punch(day, "09:30", "IN")
    before = await rows(day)
    out = datetime.combine(day, time(18, 30), ZoneInfo("Asia/Kolkata")).isoformat()
    cor = await correction(day, "PUNCH_OUT", requested_punch_out=out)
    assert await rows(day) == before
    await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert (await rows(day))[0]["effective_minutes"] == 480

    # Reviewed overtime becomes invalid when a correction changes its minutes.
    day += timedelta(days=1)
    await punch(day, "09:30", "IN")
    await punch(day, "19:10", "OUT")
    async with engine.connect() as conn:
        stored = (
            (
                await conn.execute(
                    text(
                        "SELECT id,ot_minutes,ot_status FROM attendance_days "
                        "WHERE tenant_id=:t AND employment_id=:e AND work_date=:d"
                    ),
                    dict(t=tid, e=eid, d=day),
                )
            )
            .mappings()
            .one()
        )
    assert stored["ot_minutes"] == 40 and stored["ot_status"] == "PENDING"
    reviewed = await ok(
        client,
        "PATCH",
        f"/v1/time/overtime/{to_typed_id('attendance_day', stored['id'])}",
        json={"status": "APPROVED"},
    )
    assert reviewed["ot_status"] == "APPROVED"
    cor = await correction(day)
    await ok(client, "POST", f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    attendance = await ok(
        client,
        "GET",
        f"/v1/time/attendance-days?employment_id={emp['id']}&from_date={day}&to_date={day}",
    )
    assert attendance[0]["ot_minutes"] == 0 and attendance[0]["ot_status"] == "NONE"
    assert (await rows(day))[0]["effective_minutes"] == 480

    # Locked attendance rejects both punches and approval without changing report.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE attendance_days SET is_locked=true WHERE tenant_id=:t "
                "AND employment_id=:e AND work_date=:d"
            ),
            dict(t=tid, e=eid, d=day),
        )
    before = await rows(day)
    await punch(day, "20:00", "IN", 409)
    cor = await correction(day)
    blocked = await client.post(f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert blocked.status_code == 409 and await rows(day) == before

    # Zero-duration punches are closed with no worked time.
    day += timedelta(days=1)
    await punch(day, "09:30", "IN")
    await punch(day, "09:30", "OUT")
    assert (await rows(day))[0]["status"] == "ABSENT"

    # A daytime policy cannot automatically pair a punch OUT on the next work date.
    day += timedelta(days=1)
    await punch(day, "09:30", "IN")
    await punch(day + timedelta(days=1), "00:30", "OUT", 409)
    assert (await rows(day))[0]["last_punch_out"] is None

    # Invalid / outside-day corrections cannot alter report rows on approval.
    before = await rows(day)
    cor = await correction(
        day,
        "PUNCH_OUT",
        requested_punch_out=datetime.combine(
            day + timedelta(days=1), time(1), ZoneInfo("Asia/Kolkata")
        ).isoformat(),
    )
    blocked = await client.post(f"/v1/corrections/{cor['id']}/approve", json={"action": "APPROVE"})
    assert blocked.status_code == 422 and await rows(day) == before
    invalid = await client.post(
        "/v1/corrections",
        headers=token,
        json=dict(
            work_date=str(day),
            correction_type="REGULARIZE",
            reason="Reversed",
            requested_punch_in=f"{day}T18:30:00+05:30",
            requested_punch_out=f"{day}T09:30:00+05:30",
        ),
    )
    assert invalid.status_code == 422
    await ok(
        client,
        "PATCH",
        f"/v1/policies/templates/{tpl['id']}",
        json={"correction_requires_approval": False},
    )
    cor = await correction(day)
    assert cor["status"] == "APPROVED"
    assert (await rows(day))[0]["effective_minutes"] == 480


@pytest.mark.database
async def test_eight_hour_api_boundaries(api, monkeypatch):
    from hrms.modules.time import router as time_router
    from tests.helpers import bearer, employee, ok, tenant

    client, engine = api
    admin = await tenant(client)
    emp, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    token = bearer(login["access_token"])
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    tpl = await ok(client, "POST", "/v1/policies/templates", json=config(8, "auto", 15, True))
    fields = [
        "status",
        "effective_minutes",
        "late_by_minutes",
        "early_departure_minutes",
        "first_punch_in",
        "last_punch_out",
        "work_date",
    ]
    report = await ok(
        client,
        "POST",
        "/v1/reports",
        json=dict(
            name="8-hour boundaries",
            module="ATTENDANCE",
            columns=[dict(field=f, label=f, visible=True) for f in fields],
            filters=[],
        ),
    )
    results = []
    cases = list(
        itertools.product(["configured_only", "auto", "explicit_30", "explicit_90"], SCENARIOS)
    )
    for index, (mode, scenario) in enumerate(cases):
        await ok(
            client, "PATCH", f"/v1/policies/templates/{tpl['id']}", json=config(8, mode, 15, True)
        )
        day = date(2026, 7, 1) + timedelta(days=index)
        events, start, end = example(day, 8, mode, scenario)
        oracle = expected(events, start, end, 8, mode, 15, True)
        for kind, stamp in events:
            monkeypatch.setattr(time_router, "now_utc", lambda stamp=stamp: stamp)
            await ok(client, "POST", "/v1/time/punches", headers=token, json={"punch_type": kind})
        report_rows = await ok(
            client,
            "POST",
            f"/v1/reports/{report['id']}/run",
            json={"filters": [dict(field="work_date", op="eq", value=str(day))]},
        )
        assert len(report_rows["rows"]) == 1
        row = report_rows["rows"][0]
        async with engine.connect() as conn:
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM attendance_days WHERE tenant_id=:t "
                            "AND employment_id=:e AND work_date=:d"
                        ),
                        dict(t=tid, e=eid, d=day),
                    )
                )
                .mappings()
                .one()
            )
        for f, v in oracle.items():
            assert stored[f] == v, (mode, scenario[0], f, stored[f], v)
            if f in row:
                assert row[f] == v
        assert datetime.fromisoformat(row["first_punch_in"].replace("Z", "+00:00")) == events[0][1]
        if events[-1][0] == "OUT":
            assert (
                datetime.fromisoformat(row["last_punch_out"].replace("Z", "+00:00"))
                == events[-1][1]
            )
        else:
            assert row["last_punch_out"] is None
        results.append(
            dict(
                break_mode=mode,
                scenario=scenario[0],
                punch_in=events[0][1].astimezone(ZoneInfo("Asia/Kolkata")).isoformat(),
                punch_out=events[-1][1].astimezone(ZoneInfo("Asia/Kolkata")).isoformat()
                if events[-1][0] == "OUT"
                else None,
                expected=oracle,
                report_matches=True,
            )
        )
    output = os.getenv("HRMS_POLICY_BOUNDARIES_OUTPUT")
    if output:
        Path(output).write_text(json.dumps(results, indent=2) + "\n")


@pytest.mark.parametrize(
    "mode,worked,deducted,open_session",
    [
        ("auto", 420, 60, False),
        ("configured_only", 480, 0, False),
        ("explicit_30", 450, 30, False),
        ("explicit_30", 180, 0, True),
    ],
)
async def test_multiple_visits_and_open_breaks(monkeypatch, mode, worked, deducted, open_session):
    from hrms.modules.time import service

    monkeypatch.setattr(service.approval_flow, "finish", AsyncMock())
    monkeypatch.setattr(service.approval_flow, "start", AsyncMock())

    day = date(2026, 9, 28)
    tz = ZoneInfo("Asia/Kolkata")
    sequence = [("IN", "09:30"), ("OUT", "12:30"), ("IN", "13:30")]
    if mode.startswith("explicit_"):
        sequence.extend([("BREAK_START", "15:00"), ("BREAK_END", "15:30")])
    if not open_session:
        sequence.append(("OUT", "18:30"))
    events = [
        SimpleNamespace(
            punch_type=k,
            punched_at=datetime.combine(day, time.fromisoformat(clock), tz).astimezone(UTC),
        )
        for k, clock in sequence
    ]
    monkeypatch.setattr(service, "events_for_day", AsyncMock(return_value=events))
    values = config(8, mode, 15, True)
    values["expected_start_time"] = time(9, 30)
    values["expected_end_time"] = time(18, 30)
    tenant, employment = uuid4(), uuid4()
    resolved = _merge(PolicyTemplate(tenant_id=tenant, id=uuid4(), **values), None)
    ad = AttendanceDay(tenant_id=tenant, id=uuid4(), employment_id=employment, work_date=day)
    actual = await recompute_day(
        SimpleNamespace(add=Mock(), flush=AsyncMock()), tenant, employment, day, resolved, ad
    )
    assert actual.effective_minutes == worked
    assert actual.break_minutes == deducted
    assert actual.gross_minutes == (180 if open_session else 480)
    assert actual.ot_minutes == 0
