"""
The daily jobs. Each runs per tenant, in its own transaction with that tenant's RLS context,
so one tenant's failure is logged and counted without stopping the others; the run is FAILED
(and the process exits non-zero) if any tenant failed.

- accrual: credits this month's leave (POST /accrual/run's logic, for every employee, as
  SYSTEM_ACTOR). Idempotent per month, so running it every day is safe and catches up a
  missed day within the month.
- scheduled-actions: applies personnel actions whose effective date has arrived. Requests
  already apply them lazily; this makes sure they land even on a day nobody signs in.
- leave-holds: lapses unused leave held after a separation once its hold period is over (or
  marks it restored if the person rejoined). Does nothing for companies with no separation rules.
- missed-punches: marks days whose session is still open 24 hours after check-in as
  MISSED_PUNCH, so reports show them for correction.
- integrations: connected-app housekeeping (held events, feed and sync-log retention).
- integrity: counts references the database can't protect with a foreign key (hrms.db.integrity);
  /metrics exports the totals and an alert fires above zero.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text

from hrms.core import database
from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.config import settings
from hrms.core.datetime_utils import business_today, now_utc, safe_tz
from hrms.jobs.models import JobRun

logger = logging.getLogger("hrms.jobs")

# A job returns a summary line, or counts to sum over tenants onto job_runs.findings.
TenantJob = Callable[..., Awaitable[str | dict[str, int]]]


async def _accrual(session, tenant_id: UUID) -> str:
    from hrms.modules.leave.router import accrue_period

    timezone = (
        await session.execute(
            text("SELECT timezone FROM tenants WHERE id=:tid"), {"tid": tenant_id}
        )
    ).scalar_one()
    period = now_utc().astimezone(safe_tz(timezone)).strftime("%Y-%m")
    checkpoint = (
        await session.execute(
            text(
                "SELECT period FROM tenant_job_checkpoints WHERE tenant_id=:tid AND job='accrual'"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    start = checkpoint or settings.jobs_accrual_start_period or period
    credited = 0
    for due in _periods(start, period):
        result = await accrue_period(
            session, tenant_id, due, recorded_by=SYSTEM_ACTOR, current_period=period
        )
        credited += result.balances_credited
    await session.execute(
        text("""
        INSERT INTO tenant_job_checkpoints (tenant_id,job,period,completed_at)
        VALUES (:tid,'accrual',:period,now()) ON CONFLICT (tenant_id,job)
        DO UPDATE SET period=EXCLUDED.period, completed_at=EXCLUDED.completed_at
    """),
        {"tid": tenant_id, "period": period},
    )
    return f"{start}..{period}: {credited} credited"


async def _scheduled_actions(session, tenant_id: UUID) -> str:
    from hrms.modules.people.router import apply_due_actions

    await apply_due_actions(session, tenant_id)
    # Expiry is enforced on reads; reclaim persisted report rows even if their user
    # never returns. The FK cascades deletion and the tenant predicate preserves RLS.
    await session.execute(
        text("DELETE FROM daily_report_snapshots WHERE tenant_id=:tid AND expires_at<=now()"),
        {"tid": tenant_id},
    )
    return "applied; expired reports removed"


async def _leave_holds(session, tenant_id: UUID) -> str:
    """Lapse unused leave held for people who left and did not return in time."""
    from hrms.modules.leave.separation import resolve_holds

    counts = await resolve_holds(session, tenant_id, business_today())
    return f"{counts['lapsed']} lapsed, {counts['restored']} restored"


async def _missed_punches(session, tenant_id: UUID) -> str:
    """Flag recent days still checked in 24 hours later as MISSED_PUNCH, even if the
    employee never punches again (a new check-in flags the previous day straight away)."""
    from hrms.modules.policy.engine import resolve_policy
    from hrms.modules.time.service import MAX_OPEN_SESSION, recompute_day

    rows = await session.execute(
        text("""
        SELECT ad.employment_id, ad.work_date FROM attendance_days ad
        WHERE ad.tenant_id = :tid AND ad.status <> 'MISSED_PUNCH' AND NOT ad.is_locked
          AND ad.work_date >= :since AND ad.first_punch_in < :cutoff
          AND EXISTS (
              SELECT 1 FROM punches p
              WHERE p.tenant_id = ad.tenant_id AND p.employment_id = ad.employment_id
                AND p.work_date = ad.work_date
                AND p.punch_type IN ('IN', 'BREAK_START', 'BREAK_END')
                AND (ad.last_punch_out IS NULL OR p.punched_at > ad.last_punch_out))
    """),
        {
            "tid": tenant_id,
            "cutoff": now_utc() - MAX_OPEN_SESSION,
            "since": (now_utc() - timedelta(days=14)).date(),
        },
    )
    flagged = 0
    for employment_id, work_date in rows.all():
        policy = await resolve_policy(employment_id, work_date, session, tenant_id)
        day = await recompute_day(session, tenant_id, employment_id, work_date, policy)
        flagged += day.status == "MISSED_PUNCH"
    return f"{flagged} missed punch{'' if flagged == 1 else 'es'} flagged"


async def _integrations(session, tenant_id: UUID) -> str:
    """
    Connected-app housekeeping: release held events whose time has come (the feed also does
    this when an app reads), drop delivered events older than the feed keeps, and trim the sync
    log to each app's retention setting and the rate-limit counters to the last hour.
    """
    from hrms.modules.integrations.events import purge_old_events, release_due
    from hrms.modules.integrations.profiles import tenant_settings

    released = await release_due(session, tenant_id)
    purged = await purge_old_events(session, tenant_id)
    trimmed = 0
    apps = (
        await session.execute(
            text("SELECT id FROM connected_apps WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
    ).scalars().all()
    for app_id in apps:
        days = (await tenant_settings(session, tenant_id, app_id))["retention_days"]
        result = await session.execute(
            text("""
                DELETE FROM integration_requests
                WHERE tenant_id = :tid AND app_id = :app
                  AND created_at < now() - make_interval(days => :days)
            """),
            {"tid": tenant_id, "app": app_id, "days": days},
        )
        trimmed += result.rowcount or 0
    await session.execute(
        text("""DELETE FROM integration_rate_windows
                WHERE tenant_id = :tid AND window_start < now() - interval '1 hour'"""),
        {"tid": tenant_id},
    )
    return f"{released} released, {purged} events purged, {trimmed} log rows trimmed"


async def _integrity(session, tenant_id: UUID) -> dict[str, int]:
    """
    References the database can't protect with a foreign key (hrms.db.integrity). The counts
    are summed over tenants onto the run's job_runs.findings; /metrics exports them.
    """
    from hrms.db.integrity import run_checks

    return await run_checks(session)


JOBS: dict[str, TenantJob] = {
    "scheduled-actions": _scheduled_actions,
    "accrual": _accrual,
    "leave-holds": _leave_holds,
    "missed-punches": _missed_punches,
    "integrations": _integrations,
    "integrity": _integrity,
}


async def _active_tenants() -> list[UUID]:
    async with database.AsyncSessionLocal() as session:
        rows = await session.execute(
            text(
                "SELECT id FROM tenants WHERE status = 'ACTIVE' AND archived_at IS NULL ORDER BY id"
            )
        )
        return [UUID(str(r)) for r in rows.scalars()]


async def _run_job(name: str) -> bool:
    """Run one job for every active tenant and record the run. True when every tenant succeeded."""
    job = JOBS[name]
    run = JobRun(job=name, status="RUNNING", started_at=now_utc())
    async with database.AsyncSessionLocal() as session, session.begin():
        session.add(run)
    failures: list[str] = []
    findings: dict[str, int] = {}
    ok = 0
    for tenant_id in await _active_tenants():
        try:
            async with database.AsyncSessionLocal() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
                )
                outcome = await job(session, tenant_id)
            ok += 1
            if isinstance(outcome, dict):
                for check, count in outcome.items():
                    findings[check] = findings.get(check, 0) + count
            logger.info("job %s tenant %s: %s", name, tenant_id, outcome)
        except Exception as exc:  # one tenant must not stop the rest
            failures.append(f"{tenant_id}: {type(exc).__name__}")
            logger.exception("job %s failed for tenant %s", name, tenant_id)
    async with database.AsyncSessionLocal() as session, session.begin():
        stored = await session.get(JobRun, run.id)
        assert stored is not None
        stored.status = "FAILED" if failures else "SUCCEEDED"
        stored.finished_at = now_utc()
        stored.tenants_ok = ok
        stored.tenants_failed = len(failures)
        stored.detail = "; ".join(failures)[:2000] or None
        stored.findings = findings or None
    logger.info("job %s finished: %d ok, %d failed", name, ok, len(failures))
    return not failures


async def run_all() -> bool:
    results = [await run_job(name) for name in JOBS]
    return all(results)


def _periods(start: str, end: str) -> list[str]:
    """Resume the last period too: new hires can become eligible within that month."""
    if not all(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", p) for p in (start, end)):
        raise ValueError("Accrual checkpoints must be YYYY-MM")
    if start > end:
        raise ValueError("Accrual checkpoint is ahead of the tenant's current month")
    periods = []
    year, month = map(int, start.split("-"))
    while f"{year:04d}-{month:02d}" <= end:
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return periods


async def run_job(name: str) -> bool:
    # Keep one checked-out connection in AUTOCOMMIT for the session lock. No idle
    # transaction spans tenant processing, and the same connection unlocks it.
    async with database.AsyncSessionLocal() as lease:
        conn = await lease.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        key = f"hrms-scheduler:{name}"
        acquired = (
            await conn.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key}
            )
        ).scalar()
        if not acquired:
            logger.info("job %s already running; leaving it to the lock owner", name)
            return True
        try:
            return await _run_job(name)
        finally:
            await conn.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": key}
            )
