"""Save the punches the history import cannot recreate, and put them back after a reload.

`wipe_activity.sql` deletes every punch. Imported punches keep the old system's millisecond
precision; punches made in HRMS (and the ERP/CRM integration) carry microseconds, so those are
the ones the export file cannot replace. `export` writes them to a private JSON file, `restore`
inserts them again after run_history.sh and recomputes just their days. Dry-run by default.

  python scripts/preserve_live_punches.py export --file /seed/live.json [--skip-integration]
  python scripts/preserve_live_punches.py restore --file /seed/live.json [--apply]
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import AttendanceDay, Punch
from hrms.modules.time.service import events_for_day, lock_day, recompute_day

LIVE = """
    SELECT * FROM punches
    WHERE punched_at <> date_trunc('milliseconds', punched_at)
       OR (source = 'INTEGRATION' AND NOT :skip_integration)
    ORDER BY tenant_id, employment_id, punched_at
"""
UUID_FIELDS = {"tenant_id", "id", "employment_id", "original_punch_id", "recorded_by"}


def encode(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        elif isinstance(value, UUID):
            out[key] = str(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def decode(item):
    row = dict(item)
    for key in UUID_FIELDS:
        if row.get(key):
            row[key] = UUID(row[key])
    row["punched_at"] = datetime.fromisoformat(row["punched_at"])
    row["recorded_at"] = datetime.fromisoformat(row["recorded_at"])
    if row.get("work_date"):
        row["work_date"] = date.fromisoformat(row["work_date"])
    return row


async def export(engine, args):
    async with engine.connect() as conn:
        rows = (
            (await conn.execute(text(LIVE), {"skip_integration": args.skip_integration}))
            .mappings()
            .all()
        )
    items = [encode(dict(r)) for r in rows]
    args.file.write_text(json.dumps(items, indent=1) + "\n")
    args.file.chmod(0o600)
    print(f"Saved {len(items)} punches to {args.file}")
    print(dict(Counter((i["source"], i["source_system"]) for i in items)))


async def flag_conflict(session, tid, eid, day, policy):
    ad = await lock_day(session, tid, eid, day) or AttendanceDay(
        tenant_id=tid, id=uuid4(), employment_id=eid, work_date=day
    )
    events = await events_for_day(session, tid, eid, day, policy)
    ins = [p.punched_at for p in events if p.punch_type == "IN"]
    outs = [p.punched_at for p in events if p.punch_type == "OUT"]
    ad.first_punch_in = min(ins) if ins else None
    ad.last_punch_out = max(outs) if outs else None
    ad.status = "MISSED_PUNCH"
    ad.review_flags = "LEGACY_CONFLICT"
    ad.reviewed_at = ad.reviewed_by = None
    ad.gross_minutes = ad.break_minutes = ad.effective_minutes = 0
    ad.late_by_minutes = ad.early_departure_minutes = 0
    ad.ot_minutes, ad.ot_status, ad.comp_off_days = 0, "NONE", 0.0
    session.add(ad)
    await session.flush()


async def restore(engine, args):
    items = [decode(i) for i in json.loads(args.file.read_text())]
    stats = {"file": len(items), "inserted": 0, "already_there": 0, "no_employee": 0}
    stats["days_recomputed"] = 0
    stats["days_conflicting"] = 0
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        days = set()
        for row in items:
            found = await session.execute(
                text("SELECT 1 FROM employments WHERE tenant_id=:t AND id=:e"),
                {"t": row["tenant_id"], "e": row["employment_id"]},
            )
            if found.first() is None:
                stats["no_employee"] += 1
                continue
            if await session.get(Punch, (row["tenant_id"], row["id"])) is not None:
                stats["already_there"] += 1
            else:
                session.add(Punch(**row))
                stats["inserted"] += 1
            days.add((row["tenant_id"], row["employment_id"], row["work_date"]))
        await session.flush()
        for tid, eid, day in sorted(days, key=str):
            policy = await resolve_policy(eid, day, session, tid)
            try:
                async with session.begin_nested():
                    await recompute_day(session, tid, eid, day, policy)
                stats["days_recomputed"] += 1
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                # Same rule as the history import: keep every punch, flag the day for HR.
                await flag_conflict(session, tid, eid, day, policy)
                stats["days_conflicting"] += 1
        stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
        if not args.apply:
            await session.rollback()
    print(json.dumps(stats, indent=2))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["export", "restore"])
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--skip-integration", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        await (export if args.mode == "export" else restore)(engine, args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
