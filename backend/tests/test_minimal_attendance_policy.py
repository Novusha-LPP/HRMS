"""Behavior of a start-time/working-hours policy with optional rules disabled."""

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from hrms.modules.policy.engine import _merge
from hrms.modules.policy.models import PolicyTemplate
from hrms.modules.policy.schemas import PolicyTemplateCreate
from hrms.modules.time.models import AttendanceDay
from hrms.modules.time.service import recompute_day


def policy(**overrides):
    # UI derives end = start + working hours + configured break.
    values = dict(
        name="Minimal 8 hours",
        timezone="Asia/Kolkata",
        expected_start_time=time(9),
        expected_end_time=time(17),
        break_minutes=0,
        break_auto_deduct=False,
        grace_late_minutes=0,
        grace_early_departure_minutes=0,
        ot_enabled=False,
        punch_rounding_minutes=0,
        punch_rounding_direction="NONE",
    )
    values.update(overrides)
    return _merge(PolicyTemplate(tenant_id=uuid4(), id=uuid4(), **values), None)


def stamp(clock, day=date(2026, 9, 28)):
    return datetime.combine(day, time.fromisoformat(clock), ZoneInfo("Asia/Kolkata")).astimezone(
        UTC
    )


@pytest.mark.parametrize(
    "check_in,check_out,worked,late,early,status",
    [
        ("09:00", "17:00", 480, 0, 0, "PRESENT"),
        ("08:30", "17:00", 510, 0, 0, "PRESENT"),
        ("09:01", "17:00", 479, 1, 0, "LATE"),
        ("09:30", "17:30", 480, 30, 0, "LATE"),
        ("09:00", "16:59", 479, 0, 1, "EARLY_DEPARTURE"),
        ("08:00", "16:00", 480, 0, 60, "EARLY_DEPARTURE"),
        ("09:30", "16:30", 420, 30, 30, "LATE"),
        ("09:00", "12:59", 239, 0, 241, "HALF_DAY"),
        ("09:00", "13:00", 240, 0, 240, "EARLY_DEPARTURE"),
        ("09:00", "19:00", 600, 0, 0, "PRESENT"),
        ("09:00", None, 0, 0, 0, "PRESENT"),
        ("09:01", None, 0, 1, 0, "LATE"),
        # Calculations use whole minutes, even when grace is zero.
        ("09:00:59", "17:00", 479, 0, 0, "PRESENT"),
        ("09:00", "16:59:01", 479, 0, 0, "PRESENT"),
    ],
)
async def test_minimal_policy_recomputed_attendance(
    monkeypatch, check_in, check_out, worked, late, early, status
):
    from hrms.modules.time import service

    events = [SimpleNamespace(punch_type="IN", punched_at=stamp(check_in))]
    if check_out:
        events.append(SimpleNamespace(punch_type="OUT", punched_at=stamp(check_out)))
    monkeypatch.setattr(service, "events_for_day", AsyncMock(return_value=events))
    # Judged on the work day: an open session becomes a missed punch only 24 hours later.
    monkeypatch.setattr(service, "now_utc", lambda: stamp("20:00"))
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    tenant, employment = uuid4(), uuid4()
    ad = AttendanceDay(
        tenant_id=tenant, id=uuid4(), employment_id=employment, work_date=date(2026, 9, 28)
    )
    resolved = policy()
    assert resolved.standard_minutes == 480
    result = await recompute_day(session, tenant, employment, ad.work_date, resolved, ad)
    assert result.effective_minutes == worked
    assert result.gross_minutes == worked
    assert result.break_minutes == 0
    assert result.late_by_minutes == late
    assert result.early_departure_minutes == early
    assert result.status == status
    assert result.ot_minutes == 0 and result.ot_status == "NONE"
    assert result.first_punch_in == stamp(check_in)
    assert result.last_punch_out == (stamp(check_out) if check_out else None)


def test_omitting_optional_fields_keeps_defaults():
    request = PolicyTemplateCreate(
        name="Only schedule", expected_start_time=time(9), expected_end_time=time(17)
    )
    resolved = _merge(PolicyTemplate(tenant_id=uuid4(), id=uuid4(), **request.model_dump()), None)
    assert resolved.grace_late_minutes == 0
    assert resolved.grace_early_departure_minutes == 0
    assert resolved.break_minutes == 60
    assert resolved.break_auto_deduct is False
    assert resolved.standard_minutes == 420
    assert resolved.ot_enabled is True
    assert resolved.half_day_threshold_pct == 50
    assert resolved.timezone == "UTC"


async def test_no_punches_are_absent_when_recomputed(monkeypatch):
    from hrms.modules.time import service

    monkeypatch.setattr(service, "events_for_day", AsyncMock(return_value=[]))
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    tenant, employment = uuid4(), uuid4()
    ad = AttendanceDay(
        tenant_id=tenant, id=uuid4(), employment_id=employment, work_date=date(2026, 9, 28)
    )
    result = await recompute_day(session, tenant, employment, ad.work_date, policy(), ad)
    assert result.status == "ABSENT"
    assert result.effective_minutes == result.ot_minutes == 0
    assert result.first_punch_in is result.last_punch_out is None


async def test_minimal_overnight_schedule(monkeypatch):
    from hrms.modules.time import service

    events = [
        SimpleNamespace(punch_type="IN", punched_at=stamp("22:00")),
        SimpleNamespace(punch_type="OUT", punched_at=stamp("06:00", date(2026, 9, 29))),
    ]
    monkeypatch.setattr(service, "events_for_day", AsyncMock(return_value=events))
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    tenant, employment = uuid4(), uuid4()
    ad = AttendanceDay(
        tenant_id=tenant, id=uuid4(), employment_id=employment, work_date=date(2026, 9, 28)
    )
    resolved = policy(expected_start_time=time(22), expected_end_time=time(6))
    result = await recompute_day(session, tenant, employment, ad.work_date, resolved, ad)
    assert result.effective_minutes == 480
    assert result.status == "PRESENT"
    assert result.late_by_minutes == result.early_departure_minutes == result.ot_minutes == 0
