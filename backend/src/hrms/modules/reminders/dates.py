"""
Which dates a reminder fires on. Pure functions: no database, no clock, easy to test.

An event (a birthday, a work anniversary) happens on one day each year. A rule lists how many
days BEFORE the event it fires: 0 is the day itself, 3 is three days ahead. The presets just
fill that list:

    SAME_DAY         {0}
    ONE_DAY_BEFORE   {1}
    CONTINUOUS       every day from N days before until the day itself: {N, N-1, ..., 0}
    ALTERNATE_DAYS   every second day counting back from N, and always the day itself
    CUSTOM           the list HR typed
"""

from __future__ import annotations

from calendar import isleap
from datetime import date

from hrms.modules.reminders.models import ReminderFrequency

MAX_OFFSET = 60


def offsets_for(
    frequency: str, days_before: int, custom_offsets: list[int] | None = None
) -> frozenset[int]:
    if frequency == ReminderFrequency.SAME_DAY:
        return frozenset({0})
    if frequency == ReminderFrequency.ONE_DAY_BEFORE:
        return frozenset({1})
    if frequency == ReminderFrequency.CONTINUOUS:
        return frozenset(range(days_before + 1))
    if frequency == ReminderFrequency.ALTERNATE_DAYS:
        return frozenset({0, *range(days_before, 0, -2)})
    if frequency == ReminderFrequency.CUSTOM:
        return frozenset(o for o in (custom_offsets or []) if 0 <= o <= MAX_OFFSET)
    raise ValueError(f"unknown frequency {frequency!r}")


def occurrence_in_year(origin: date, year: int) -> date:
    """The day of `year` the event falls on. 29 February is observed on 28 February in a year
    that has no 29th."""
    if origin.month == 2 and origin.day == 29 and not isleap(year):
        return date(year, 2, 28)
    return date(year, origin.month, origin.day)


def next_occurrence(origin: date, today: date) -> date:
    """The first day on or after `today` the event falls on."""
    this_year = occurrence_in_year(origin, today.year)
    return this_year if this_year >= today else occurrence_in_year(origin, today.year + 1)


def days_until(origin: date, today: date) -> int:
    return (next_occurrence(origin, today) - today).days


def is_due(origin: date, today: date, offsets: frozenset[int]) -> bool:
    return days_until(origin, today) in offsets


def years_at(origin: date, event_day: date) -> int:
    """Whole years from the origin date to the event day (age, or years of service)."""
    return event_day.year - origin.year
