"""Live attendance must be based on an actual, unexpired check-in."""

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from hrms.modules.time.service import is_live_punched_in

NOW = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)


def event(kind, hours_ago):
    return SimpleNamespace(punch_type=kind, punched_at=NOW - timedelta(hours=hours_ago))


@pytest.mark.parametrize(
    "events, expected",
    [
        ([], False),
        ([event("IN", 1)], True),
        ([event("IN", 24)], True),
        ([event("IN", 25)], False),
        ([event("IN", 25), event("BREAK_START", 24), event("BREAK_END", 1)], False),
        ([event("IN", 2), event("OUT", 1)], False),
        ([event("IN", 2), event("BREAK_START", 1)], False),
        ([event("IN", 2), event("BREAK_END", 1)], True),
        ([event("BREAK_END", 1)], False),
        ([event("IN", -1)], False),
        ([event("IN", 1), event("BREAK_END", -1)], False),
        ([event("IN", 25), event("OUT", 24), event("IN", 1)], True),
    ],
)
def test_live_punch_status(events, expected):
    assert is_live_punched_in(events, NOW) is expected


@pytest.mark.parametrize("night_shift", [False, True])
async def test_today_does_not_carry_a_previous_work_date(monkeypatch, night_shift):
    from hrms.modules.time import router
    from hrms.modules.time.models import Punch

    employment_id, tenant_id = uuid4(), uuid4()
    previous_date = NOW.date() - timedelta(days=1)
    policy = SimpleNamespace(
        timezone="Asia/Kolkata",
        expected_start_time=time(22) if night_shift else time(9, 30),
        expected_end_time=time(6) if night_shift else time(18, 30),
    )
    previous_punch = Punch(
        id=uuid4(), tenant_id=tenant_id, employment_id=employment_id,
        punched_at=NOW - timedelta(hours=12 if night_shift else 25), work_date=previous_date,
        punch_type="IN", source="WEB",
    )

    async def events_for_day(session, tenant, employee, day, policy):
        return [previous_punch] if day == previous_date else []

    monkeypatch.setattr(router, "now_utc", lambda: NOW)
    monkeypatch.setattr(router, "read_scope", lambda scope, *args: scope)
    monkeypatch.setattr(router, "resolve_acting_employment_id", lambda *args: employment_id)
    monkeypatch.setattr(router, "authorize_employment", AsyncMock())
    monkeypatch.setattr(router, "resolve_policy", AsyncMock(return_value=policy))
    monkeypatch.setattr(router, "events_for_day", events_for_day)
    monkeypatch.setattr("hrms.modules.time.service.events_for_day", events_for_day)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(first=lambda: None),
    )))

    result = await router.today_status(None, None, tenant_id, session, work_date=None)
    assert result.work_date == (previous_date if night_shift else NOW.date())
    assert result.is_punched_in is night_shift
    assert len(result.punches) == (1 if night_shift else 0)
