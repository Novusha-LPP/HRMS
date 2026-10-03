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
        try:
            await run_all()
        except Exception:  # the database being down must not kill the scheduler
            logger.exception("scheduled run failed; retrying at the next slot")
        wait = _seconds_until(settings.jobs_daily_at)
        logger.info(
            "next run in %.0f s (%s %s)", wait, settings.jobs_daily_at, settings.default_timezone
        )
        await asyncio.sleep(wait)


def main(argv: list[str]) -> int:
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    if len(argv) >= 1 and argv[0] == "schedule":
        asyncio.run(_schedule())
        return 0
    if len(argv) == 2 and argv[0] == "run" and (argv[1] == "all" or argv[1] in JOBS):
        ok = asyncio.run(run_all() if argv[1] == "all" else run_job(argv[1]))
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
