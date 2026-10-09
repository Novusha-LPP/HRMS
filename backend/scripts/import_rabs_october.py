"""Import October RABS punches using an explicitly confirmed employee CSV.

Dry-run by default. No employee or policy assignments are created. --allow-partial
imports confirmed owners only and reports the remaining source employees.
"""

import argparse
import asyncio
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from migrate_legacy_attendance import END, ROOT, START, add_once, instant, source_uuid, unwrap
from migrate_rabs_leave import RABS, TARGET_SLUG
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.core.ids import to_uuid
from hrms.core.locking import lock_resource
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import AttendanceDay, Punch
from hrms.modules.time.service import event_minutes, events_for_day, lock_day, recompute_day


def confirmed_links(path):
    links, seen = {}, set()
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"legacy_user_id", "confirmed_hrms_employment_id"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Mapping requires legacy_user_id and confirmed_hrms_employment_id")
        for row in reader:
            sid = row["legacy_user_id"].strip()
            if not sid or sid in seen:
                raise ValueError("Blank or duplicate source employee ID in mapping")
            seen.add(sid)
            target = row["confirmed_hrms_employment_id"].strip()
            if target:
                links[sid] = to_uuid(target) if "_" in target else UUID(target)
    if len(set(links.values())) != len(links):
        raise ValueError("Multiple source employees map to one target; confirm aliases separately")
    return links


async def migrate(session, data_dir, mapping_file, allow_partial=False):
    tid = (
        await session.execute(
            text("SELECT id FROM tenants WHERE slug=:slug"), {"slug": TARGET_SLUG}
        )
    ).scalar_one()
    await lock_resource(session, tid, "EXIM-rabs-attendance-2026-10")
    users = {unwrap(r["_id"]): r for r in json.loads((data_dir / "exim.users.json").read_text())}
    selected = [
        r
        for r in json.loads((data_dir / "exim.attendancepunches.json").read_text())
        if START <= date.fromisoformat(r["punch_date_str"]) < END
        and unwrap(r["company_id"]) == RABS
    ]
    source_ids = {unwrap(r["employee_id"]) for r in selected}
    links = confirmed_links(mapping_file)
    if not set(links) <= source_ids:
        raise ValueError("Confirmed mapping contains an employee without October RABS punches")
    unresolved = sorted(source_ids - set(links))
    if not links:
        raise ValueError(f"No confirmed employee links; {len(selected)} punches remain unimported")
    if unresolved and not allow_partial:
        raise ValueError(
            f"Missing {len(unresolved)} confirmed employee links; "
            "use --allow-partial for confirmed owners"
        )
    stats = dict(
        tenant=TARGET_SLUG,
        month="2026-10",
        created=Counter(),
        existing=Counter(),
        confirmed_links={sid: str(eid) for sid, eid in links.items()},
        source_october_punches=len(selected),
        deferred_source_employee_ids=unresolved,
        deferred_punches=sum(unwrap(r["employee_id"]) in unresolved for r in selected),
        imported_punches=0,
        imported_employees=len(links),
        recomputed_days=0,
        statuses=Counter(),
        days_needing_correction=[],
        policy_basis=(
            "Existing HRMS RABS attendance policies; "
            "no shifts, week-offs or leave assignments changed"
        ),
        source_fingerprints={
            n: hashlib.sha256((data_dir / f"exim.{n}.json").read_bytes()).hexdigest()
            for n in ["users", "attendancepunches"]
        },
    )
    employments = {}
    for sid, eid in links.items():
        target = (
            (
                await session.execute(
                    text(
                        "SELECT e.id,e.hire_date,e.separation_date FROM employments e "
                        "JOIN legal_entities le ON le.tenant_id=e.tenant_id "
                        "AND le.id=e.legal_entity_id "
                        "WHERE e.tenant_id=:tid AND e.id=:eid AND e.archived_at IS NULL "
                        "AND lower(le.name)='rabs industries india private limited'"
                    ),
                    {"tid": tid, "eid": eid},
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            raise ValueError(f"Mapped employee is outside the RABS entity: {sid}")
        employments[eid] = target
    if len({unwrap(r["_id"]) for r in selected}) != len(selected):
        raise ValueError("Duplicate source punch IDs")
    days, seen = {}, set()
    for r in selected:
        sid, owner = unwrap(r["_id"]), unwrap(r["employee_id"])
        if owner not in links:
            continue
        user = users.get(owner)
        if user is None or unwrap(user.get("company_id")) != RABS:
            raise ValueError(f"Source employee/company mismatch: {owner}")
        eid, day, stamp = (
            links[owner],
            date.fromisoformat(r["punch_date_str"]),
            instant(r["punch_time"]),
        )
        target = employments[eid]
        if target["hire_date"] > day or (
            target["separation_date"] and target["separation_date"] <= day
        ):
            raise ValueError(f"Punch falls outside mapped employment dates: {owner}/{day}")
        if stamp.astimezone(ZoneInfo("Asia/Kolkata")).date() != day:
            raise ValueError(f"Source business date mismatch: {sid}")
        if r["punch_type"] not in {"IN", "OUT"} or not r["is_valid"] or r["is_regularized"]:
            raise ValueError(f"Unsupported source punch state: {sid}")
        source = {"mobile": "MOBILE", "web": "WEB"}.get(r["punch_method"])
        if source is None:
            raise ValueError(f"Unsupported source method: {sid}")
        key = (eid, stamp, r["punch_type"])
        if key in seen:
            raise ValueError(f"Duplicate source event: {sid}")
        seen.add(key)
        pid = source_uuid(tid, "attendancepunches", sid)
        new = await session.get(Punch, (tid, pid)) is None
        if (eid, day) not in days:
            ad = await lock_day(session, tid, eid, day)
            days[eid, day] = {"attendance": ad, "changed": False}
        ad = days[eid, day]["attendance"]
        if (
            new
            and ad
            and (ad.reviewed_at or ad.comp_off_days or ad.ot_status not in {"NONE", "INFO"})
        ):
            raise ValueError(f"Reviewed/rewarded attendance needs manual resolution: {eid}/{day}")
        await add_once(
            session,
            Punch,
            Punch(
                tenant_id=tid,
                id=pid,
                employment_id=eid,
                punch_type=r["punch_type"],
                punched_at=stamp,
                work_date=day,
                source=source,
                recorded_at=instant(r["createdAt"]),
            ),
            stats,
        )
        days[eid, day]["changed"] |= new
        stats["imported_punches"] += 1
    for (eid, day), state in sorted(days.items()):
        ad = state["attendance"]
        if state["changed"] or ad is None:
            policy = await resolve_policy(eid, day, session, tid)
            events = await events_for_day(session, tid, eid, day, policy)
            try:
                event_minutes(events)
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                ad = ad or AttendanceDay(
                    tenant_id=tid,
                    id=source_uuid(tid, "attendance-day", f"{eid}:{day}"),
                    employment_id=eid,
                    work_date=day,
                )
                ins = [p.punched_at for p in events if p.punch_type == "IN"]
                outs = [p.punched_at for p in events if p.punch_type == "OUT"]
                ad.first_punch_in = min(ins) if ins else None
                ad.last_punch_out = max(outs) if outs else None
                ad.status, ad.review_flags = "MISSED_PUNCH", "LEGACY_CONFLICT"
                ad.gross_minutes = ad.break_minutes = ad.effective_minutes = 0
                ad.late_by_minutes = ad.early_departure_minutes = 0
                ad.ot_minutes, ad.ot_status, ad.comp_off_days = 0, "NONE", 0
                session.add(ad)
                await session.flush()
                stats["days_needing_correction"].append(
                    dict(employment_id=str(eid), work_date=str(day), reason=str(exc.detail))
                )
            else:
                ad = await recompute_day(session, tid, eid, day, policy)
            stats["recomputed_days"] += 1
        stats["statuses"][ad.status] += 1
    stats["employee_days"] = len(days)
    return tid, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--employee-map", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/rabs-october-import.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, stats = await migrate(
                    session, args.data_dir, args.employee_map, args.allow_partial
                )
                stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
                if args.apply and stats["created"]:
                    session.add(
                        ImportBatch(
                            tenant_id=tid,
                            id=source_uuid(
                                tid, "rabs-attendance-batch", datetime.now(UTC).isoformat()
                            ),
                            source_system="EXIM_RABS_ATTENDANCE",
                            total_records=stats["imported_punches"],
                            created_records=sum(stats["created"].values()),
                            details=stats,
                        )
                    )
                elif not args.apply:
                    await session.rollback()
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in stats.items()
                        if k
                        not in {
                            "confirmed_links",
                            "source_fingerprints",
                            "days_needing_correction",
                            "deferred_source_employee_ids",
                        }
                    },
                    indent=2,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
