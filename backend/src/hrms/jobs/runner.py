"""
The daily jobs. Each runs per tenant, in its own transaction with that tenant's RLS context,
so one tenant's failure is logged and counted without stopping the others; the run is FAILED
(and the process exits non-zero) if any tenant failed.

- accrual: credits this month's leave (POST /accrual/run's logic, for every employee, as
  SYSTEM_ACTOR). Idempotent per month, so running it every day is safe and catches up a
  missed day within the month.
- scheduled-actions: applies personnel actions whose effective date has arrived. Requests
  already apply them lazily; this makes sure they land even on a day nobody signs in.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import text

from hrms.core import database
from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.config import settings
from hrms.core.datetime_utils import now_utc, safe_tz
from hrms.jobs.models import JobRun

logger = logging.getLogger("hrms.jobs")

TenantJob = Callable[..., Awaitable[str]]


async def _accrual(session, tenant_id: UUID) -> str:
    from hrms.modules.leave.router import accrue_period

    timezone = (await session.execute(
        text("SELECT timezone FROM tenants WHERE id=:tid"), {"tid": tenant_id}
    )).scalar_one()
    period = now_utc().astimezone(safe_tz(timezone)).strftime("%Y-%m")
    checkpoint = (await session.execute(text(
        "SELECT period FROM tenant_job_checkpoints WHERE tenant_id=:tid AND job='accrual'"
    ), {"tid": tenant_id})).scalar()
    start = checkpoint or settings.jobs_accrual_start_period or period
    credited = 0
    for due in _periods(start, period):
        result = await accrue_period(session, tenant_id, due, recorded_by=SYSTEM_ACTOR,
                                    current_period=period)
        credited += result.balances_credited
    await session.execute(text("""
        INSERT INTO tenant_job_checkpoints (tenant_id,job,period,completed_at)
        VALUES (:tid,'accrual',:period,now()) ON CONFLICT (tenant_id,job)
        DO UPDATE SET period=EXCLUDED.period, completed_at=EXCLUDED.completed_at
    """), {"tid": tenant_id, "period": period})
    return f"{start}..{period}: {credited} credited"


async def _scheduled_actions(session, tenant_id: UUID) -> str:
    from hrms.modules.people.router import apply_due_actions

    await apply_due_actions(session, tenant_id)
    return "applied"


JOBS: dict[str, TenantJob] = {"scheduled-actions": _scheduled_actions, "accrual": _accrual}


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
    ok = 0
    for tenant_id in await _active_tenants():
        try:
            async with database.AsyncSessionLocal() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
                )
                outcome = await job(session, tenant_id)
            ok += 1
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
        acquired = (await conn.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key}
        )).scalar()
        if not acquired:
            logger.info("job %s already running; leaving it to the lock owner", name)
            return True
        try:
            return await _run_job(name)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                               {"key": key})
