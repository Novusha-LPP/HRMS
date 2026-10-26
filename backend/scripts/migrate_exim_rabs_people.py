"""Create the RABS people who exist in EXIM but not yet in HRMS, without creating a duplicate.

Who is created is decided by a reviewer (backups/rabs-review.csv -> a decisions JSON with a
"create" list). This script adds three guards on top, so a mistake cannot duplicate anyone:
  1. at run time every person is checked again against everyone already in the tenant
     (exim_matching): someone already linked is skipped; someone who now matches an existing
     employee by email, mobile, code or name is REFUSED and reported, never created;
  2. nobody whose legacy role would give more than ordinary access is created (reported for a
     human to handle);
  3. afterwards the tenant is scanned for two employees with the same name, and the run fails
     (rolling everything back) if the import created one.

The accounts are created exactly as the Suraj import creates them (same code): the old bcrypt
password carries over, the role is a plain employee. Dry-run by default (rolled back); the
whole run is one transaction. Re-running creates nobody new.

Run from backend:
  .venv/bin/python scripts/migrate_exim_rabs_people.py --tenant <rabs slug> \
      --decisions rabs_decisions.json
Add --apply to commit.
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import exim_matching
from migrate_legacy_attendance import source_uuid, unwrap
from migrate_tenants import (
    Context,
    build_suraj_record,
    ensure_jobs,
    get_roles,
    import_record,
    new_stats,
    setup_org_structure,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings

ROOT = Path(__file__).resolve().parents[2]


async def duplicate_names(session, tid):
    rows = (
        await session.execute(
            text("""
        SELECT p.legal_first_name, coalesce(p.legal_last_name, '') FROM persons p
        JOIN employments e ON e.tenant_id = p.tenant_id AND e.person_id = p.id
        WHERE p.tenant_id = :tid
    """),
            {"tid": tid},
        )
    ).all()
    seen = Counter(exim_matching.squash(first, last) for first, last in rows)
    return sum(1 for key, n in seen.items() if key and n > 1)


async def migrate(session, args):
    tenant = (
        (
            await session.execute(
                text("SELECT id,slug FROM tenants WHERE slug = :ref OR id::text = :ref"),
                {"ref": args.tenant},
            )
        )
        .mappings()
        .one()
    )
    tid = tenant["id"]
    entity_rows = (
        (
            await session.execute(
                text(
                    "SELECT id,name FROM legal_entities "
                    "WHERE tenant_id=:tid AND archived_at IS NULL"
                ),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    if len(entity_rows) != 1:
        raise ValueError("The RABS tenant must have exactly one legal entity")
    entity_id, entity_name = entity_rows[0]["id"], entity_rows[0]["name"]

    decisions = json.loads(args.decisions.read_text())
    wanted = set(decisions.get("create", []))
    users = {
        unwrap(u["_id"]): u
        for u in json.loads((args.data_dir / "exim.users.json").read_text())
    }
    stats = new_stats(
        requested=len(wanted),
        already_created=0,
        refused_duplicate=[],
        refused_elevated_role=[],
        not_in_export=0,
        created_codes=[],
    )
    index = exim_matching.Index(await exim_matching.load_people(session, tid))
    before_duplicates = await duplicate_names(session, tid)

    records, departments = [], set()
    for exim_id in sorted(wanted):
        user = users.get(exim_id)
        if user is None:
            stats["not_in_export"] += 1
            continue
        kind, found, why = index.classify(user, exim_id)
        if kind == "linked":
            stats["already_created"] += 1
            continue
        if kind == "matched":
            stats["refused_duplicate"].append({"source_id": exim_id, "reason": why})
            continue
        rec = build_suraj_record(user, entity_id)
        if rec is None:
            stats["errors"].append({"source_id": exim_id, "error": "missing _id/username"})
            continue
        if rec.access.role_name != "EMPLOYEE":
            stats["refused_elevated_role"].append(
                {"source_id": exim_id, "role": rec.access.role_name}
            )
            continue
        records.append(rec)
        if rec.access.department:
            departments.add(rec.access.department)

    loc_id, _, dept_map = await setup_org_structure(
        session,
        tid,
        entity_id,
        entity_name,
        "RABS",
        is_factory=True,
        extra_departments=sorted(departments),
    )
    jobs = {r.access.job for r in records if r.access.job}
    ctx = Context(
        session=session,
        tenant_id=tid,
        overwrite=False,
        jobs=await ensure_jobs(session, tid, sorted(jobs)),
        roles=await get_roles(session, tid),
        stats=stats,
        entity_dirs={entity_id: (loc_id, dept_map)},
        repair=False,
    )
    for rec in records:
        await import_record(ctx, rec)
        stats["created_codes"].append(rec.employee_code)

    after_duplicates = await duplicate_names(session, tid)
    stats["duplicate_name_groups_before"] = before_duplicates
    stats["duplicate_name_groups_after"] = after_duplicates
    if after_duplicates > before_duplicates:
        raise RuntimeError("The import would create two employees with the same name; stopped")
    if stats["errors"]:
        raise RuntimeError(f"{len(stats['errors'])} record(s) failed; nothing was committed")
    return tid, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-rabs-people.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, stats = await migrate(session, args)
                stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
                if args.apply and stats["created_users"]:
                    await session.execute(
                        text("""
                        INSERT INTO import_batches
                          (tenant_id,id,source_system,imported_at,total_records,
                            created_records,updated_records,is_dry_run,details)
                        VALUES (:tid,:id,'EXIM_RABS_PEOPLE',now(),:total,:created,0,
                                false,CAST(:details AS jsonb))
                    """),
                        {
                            "tid": tid,
                            "id": source_uuid(
                                tid, "rabs-people-batch", datetime.now(UTC).isoformat()
                            ),
                            "total": stats["requested"],
                            "created": stats["created_users"],
                            "details": json.dumps(stats, default=str),
                        },
                    )
                elif not args.apply:
                    await session.rollback()
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(json.dumps(stats, indent=2, default=str))
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
