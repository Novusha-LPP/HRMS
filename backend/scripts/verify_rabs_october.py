"""Read-only verification of confirmed RABS October punches and preserved rows."""

import asyncio
import json
from datetime import date
from pathlib import Path
from uuid import UUID

from migrate_legacy_attendance import instant, source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.config import settings


async def main():
    folder = Path(__file__).resolve().parents[1] / "storage/migration-backups"
    before = json.loads((folder / "rabs-october-before.json").read_text())
    applied = json.loads((folder / "rabs-october-applied.json").read_text())
    rerun = json.loads((folder / "rabs-october-rerun.json").read_text())
    engine = create_async_engine(settings.database_url)
    result = {
        "month": "2026-10",
        "tenant": applied["tenant"],
        "existing_rows_unchanged": {},
        "new_rows": {},
    }
    try:
        async with engine.connect() as conn:
            tid = (
                await conn.execute(
                    text("select id from tenants where slug=:s"), {"s": applied["tenant"]}
                )
            ).scalar_one()
            for table, old in before.items():
                rows = [
                    dict(r)
                    for r in (
                        await conn.execute(
                            text("select * from " + table + " order by tenant_id,id")
                        )
                    ).mappings()
                ]
                current = {
                    (r["tenant_id"], r["id"]): r for r in json.loads(json.dumps(rows, default=str))
                }
                oldkeys = set()
                for row in old:
                    key = (row["tenant_id"], row["id"])
                    oldkeys.add(key)
                    assert current[key] == row, (table, key)
                added = [r for k, r in current.items() if k not in oldkeys]
                assert all(r["tenant_id"] == str(tid) for r in added)
                if table not in ["punches", "attendance_days"]:
                    assert not added, table
                result["existing_rows_unchanged"][table] = len(old)
                result["new_rows"][table] = len(added)
            root = Path(__file__).resolve().parents[2]
            source = json.loads((root / "exim.attendancepunches.json").read_text())
            links = {s: UUID(e) for s, e in applied["confirmed_links"].items()}
            checked = 0
            for row in source:
                sid, day = unwrap(row["employee_id"]), date.fromisoformat(row["punch_date_str"])
                if sid not in links or not date(2026, 10, 1) <= day < date(2026, 11, 1):
                    continue
                stored = (
                    (
                        await conn.execute(
                            text("select * from punches where tenant_id=:t and id=:p"),
                            {
                                "t": tid,
                                "p": source_uuid(tid, "attendancepunches", unwrap(row["_id"])),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                assert stored["employment_id"] == links[sid]
                assert stored["punch_type"] == row["punch_type"]
                assert stored["punched_at"] == instant(row["punch_time"])
                assert stored["work_date"] == day
                assert stored["recorded_at"] == instant(row["createdAt"])
                assert stored["source"] == "MOBILE"
                checked += 1
            result.update(
                source_punches=applied["source_october_punches"],
                source_employees=len(links) + len(applied["deferred_source_employee_ids"]),
                punches_verified=checked,
                employee_days=applied["employee_days"],
                employee_code="RI_039",
                deferred_punches=applied["deferred_punches"],
                unresolved_employees=len(applied["deferred_source_employee_ids"]),
                rerun_created_records=sum(rerun["created"].values()),
                rerun_recomputed_days=rerun["recomputed_days"],
            )
            days = (
                (
                    await conn.execute(
                        text(
                            "select work_date,status,review_flags from attendance_days "
                            "where tenant_id=:tid order by work_date"
                        ),
                        {"tid": tid},
                    )
                )
                .mappings()
                .all()
            )
            result["attendance_days"] = [dict(row) for row in days]
        output = root / "docs/legacy-mongo-analysis/rabs-october-attendance-status.json"
        output.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(json.dumps(result, indent=2, default=str))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
