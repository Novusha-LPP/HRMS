"""
    python -m hrms.jobs run [accrual|scheduled-actions|all]   one run, exit 1 if anything failed
    python -m hrms.jobs schedule                              run now, then every day at
                                                              HRMS_JOBS_DAILY_AT (tenant time)

`schedule` is what the deploy's `jobs` container runs; `run` is for cron, a CI smoke test or
running a job by hand.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from hrms import model_registry  # noqa: F401
from hrms.core.config import settings
from hrms.core.datetime_utils import safe_tz
from hrms.core.logging import setup_logging
from hrms.jobs.runner import JOBS, logger, run_all, run_job


def _seconds_until(hh_mm: str) -> float:
    tz = safe_tz(settings.default_timezone)
    now = datetime.now(tz)
    hour, minute = (int(x) for x in hh_mm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _schedule() -> None:
    while True:
        ok = False
        try:
            ok = await run_all()
        except Exception:
            logger.exception("scheduled run failed")
        wait = _seconds_until(settings.jobs_daily_at) if ok else settings.jobs_retry_seconds
        logger.info(
            "next run in %.0f s (%s %s)", wait, settings.jobs_daily_at, settings.default_timezone
        )
        await asyncio.sleep(wait)


REMINDER_TICK_SECONDS = 15 * 60


async def _schedule_reminders() -> None:
    """Birthday and anniversary mail goes out at a time of day chosen per rule, so this job
    cannot wait for the daily run: it checks every few minutes."""
    while True:
        try:
            await run_job("reminders")
        except Exception:
            logger.exception("reminders run failed")
        await asyncio.sleep(REMINDER_TICK_SECONDS)


async def _schedulers() -> None:
    if settings.mail_backend == "ses":
        from hrms.core.mail import schedule_delivery

        await asyncio.gather(_schedule(), schedule_delivery(), _schedule_reminders())
    else:
        await _schedule()


def main(argv: list[str]) -> int:
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    if len(argv) >= 1 and argv[0] == "schedule":
        asyncio.run(_schedulers())
        return 0
    if len(argv) == 2 and argv[0] == "run" and (argv[1] == "all" or argv[1] in JOBS):
        ok = asyncio.run(run_all() if argv[1] == "all" else run_job(argv[1]))
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
