"""
One definition of "present" for every attendance count in the app.

The same predicate used to be copy-pasted, in slightly different forms, into the
employee, manager and HR dashboards and the daily analysis — and the copies
disagreed (someone on approved leave who still punched in was counted as both
present and on leave, so the buckets summed to more than the headcount).
Everything now classifies a day through classify() / present_sql(), which put
each employee-day into exactly one bucket.
"""

from datetime import datetime
from typing import Literal

# Statuses that mean the person turned up. PENDING is what an open session used
# to be recorded as; rows written before that changed may still carry it.
PRESENT_STATUSES = ("PRESENT", "LATE", "HALF_DAY", "PENDING")

Bucket = Literal["present", "on_leave", "absent", "other"]


def classify(status: str | None, first_punch_in: datetime | None, on_leave: bool = False) -> Bucket:
    """
    present  — punched in, or the day is recorded as present/late/half-day. This wins
               over leave: someone on approved leave who came in is at work.
    on_leave — approved leave and no punch.
    absent   — recorded absent, no punch, no leave.
    other    — holiday, weekend, or nothing recorded yet.
    """
    if first_punch_in is not None or status in PRESENT_STATUSES:
        return "present"
    if on_leave or status == "ON_LEAVE":
        return "on_leave"
    if status == "ABSENT":
        return "absent"
    return "other"


def is_late(status: str | None, late_by_minutes: int | None) -> bool:
    return status == "LATE" or (late_by_minutes or 0) > 0


def present_sql(alias: str = "ad") -> str:
    """SQL twin of classify() == 'present', for aggregate queries over attendance_days."""
    statuses = ",".join(f"'{s}'" for s in PRESENT_STATUSES)
    return f"({alias}.first_punch_in IS NOT NULL OR {alias}.status IN ({statuses}))"
