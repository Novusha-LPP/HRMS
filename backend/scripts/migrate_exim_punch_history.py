"""Import the EXIM punch history (April - October 2026) and let HRMS compute each day.

Builds on migrate_legacy_attendance.py (October only). Same rules: dry-run by default (one
transaction, rolled back), exact EXIM employee links, deterministic ids so a re-run changes
nothing, unrelated tenants and native records untouched.

What differs from the October import, because the history is messier:
  * exact duplicate punches (same person, instant and direction; mostly repeated legacy
    auto check-outs) are imported once and counted, not rejected;
  * the legacy `auto` check-out has no HRMS equivalent, so it is stored as a MANUAL (system)
    punch with an explicit reason rather than passed off as a person's own punch;
  * records that cannot be linked are reported by reason and skipped, not fatal;
  * policy assignments only start on 2026-10-01, so earlier days would use the tenant default
    rules. Each linked employee gets an additional assignment of the SAME policy for
    2026-04-01 .. 2026-09-30; existing assignments are never edited;
  * RABS punches stay deferred (their employee links await confirmation);
  * the old system's corrections often changed only a day's STATUS (present) without adding
    times, so there is nothing to recompute from. Where HRMS's own result for a day differs
    from the old status, the day carries that status as `status_override` (migration 0066);
    a finished old day (present / half day) with no punches at all is created that way too.
    Leave days are left to the leave import, and weekly offs, holidays and plain absences
    that HRMS derives from its calendars are not stored.

Run from backend:
  .venv/bin/python scripts/migrate_exim_punch_history.py --tenant suraj-group \
      --punches "exim.attendancepunches copy.json"
Add --apply to commit.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exim_scope
from fastapi import HTTPException
from migrate_legacy_attendance import add_once, instant, source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import select

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.policy.models import EmployeePolicyAssignment
from hrms.modules.time.models import AttendanceDay, Punch
from hrms.modules.time.service import event_minutes, events_for_day, lock_day, recompute_day

ROOT = Path(__file__).resolve().parents[2]
IST = ZoneInfo("Asia/Kolkata")
HISTORY_START = date(2026, 4, 1)
OCTOBER_START = date(2026, 10, 1)
SOURCES = {"web": "WEB", "mobile": "MOBILE", "auto": "MANUAL"}
AUTO_REASON = "Automatic check-out by the legacy attendance system"
OVERRIDE_NOTE = "Status carried over from the legacy attendance record (EXIM)"
HISTORY_END = date(2026, 10, 19)  # the export date
LEGACY_STATUS = {
    "present": "PRESENT",
    "half_day": "HALF_DAY",
    "incomplete": "MISSED_PUNCH",
    "absent": "ABSENT",
    "weekly_off": "WEEKEND",
    "holiday": "HOLIDAY",
}
WORKED = {"PRESENT", "LATE", "EARLY_DEPARTURE"}


def group(status):
    """Late and early-departure days are still worked days."""
    return "WORKED" if status in WORKED else status


ALIAS = {"suraj forwarders": "suraj forwarders private limited"}


async def prepare(session, tenant_ref, data_dir, punches_file, company="suraj", decisions=None):
    """Read-only: link and classify every source punch, grouped per employee."""
    tenant = (
        (
            await session.execute(
                text("SELECT id,slug FROM tenants WHERE slug = :ref OR id::text = :ref"),
                {"ref": tenant_ref},
            )
        )
        .mappings()
        .one()
    )
    tid = tenant["id"]
    stats = {
        "tenant": tenant["slug"],
        "source_punches": 0,
        "created": Counter(),
        "existing": Counter(),
        "skipped": Counter(),
        "duplicates_removed": Counter(),
        "other_company_punches": 0,
        "unresolved_samples": [],
        "recomputed_days": 0,
        "attendance_statuses": Counter(),
        "legacy_conflict_days": 0,
        "history_policy_assignments": 0,
        "agreeing_days": 0,
        "override_new_days": 0,
        "override_changed": Counter(),
        "derived_by_hrms": Counter(),
        "override_skipped_locked": 0,
        "override_on_conflicting_punches": 0,
        "leave_days_for_leave_import": 0,
    }

    def skip(reason, sid):
        stats["skipped"][reason] += 1
        if len(stats["unresolved_samples"]) < 20:
            stats["unresolved_samples"].append({"punch_id": sid, "reason": reason})

    users = {
        unwrap(r["_id"]): r for r in json.loads((data_dir / "exim.users copy.json").read_text())
    }
    punches = json.loads((data_dir / punches_file).read_text())
    rows = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_user_id, ua.employment_id, e.legal_entity_id
        FROM user_accounts ua JOIN employments e
          ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        WHERE ua.tenant_id = :tid AND ua.erp_system = 'EXIM' AND e.archived_at IS NULL
    """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    links = {r["erp_user_id"]: r for r in rows}
    links.update(await exim_scope.decided_links(session, tid, decisions))
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
    entities = {r["name"].casefold(): r["id"] for r in entity_rows}

    entity_for, other_company = exim_scope.build(company, entities, ALIAS)

    seen = set()
    per_employee = {}
    for r in punches:
        sid, uid = unwrap(r["_id"]), unwrap(r["employee_id"])
        stats["source_punches"] += 1
        user = users.get(uid)
        if user is None:
            skip("source user missing", sid)
        elif other_company(user):
            stats["other_company_punches"] += 1
        elif uid not in links:
            skip("no HRMS employee link", sid)
        elif entity_for(user) != links[uid]["legal_entity_id"]:
            skip("company differs from the linked employee", sid)
        elif r["punch_type"] not in {"IN", "OUT"}:
            skip("unsupported punch type", sid)
        elif not r["is_valid"]:
            skip("marked invalid in the source", sid)
        elif r["punch_method"] not in SOURCES:
            skip("unsupported punch method", sid)
        else:
            stamp = instant(r["punch_time"])
            day = stamp.astimezone(IST).date()
            if day != date.fromisoformat(r["punch_date_str"]):
                skip("business date differs from the instant", sid)
                continue
            eid = links[uid]["employment_id"]
            key = (eid, stamp, r["punch_type"])
            if key in seen:
                stats["duplicates_removed"][r["punch_method"]] += 1
                continue
            seen.add(key)
            per_employee.setdefault((eid, uid), []).append(
                {
                    "sid": sid,
                    "type": r["punch_type"],
                    "stamp": stamp,
                    "day": day,
                    "method": r["punch_method"],
                    "created": instant(r["createdAt"]),
                }
            )
    legacy_days = {}
    for rec in json.loads((data_dir / "exim.attendancerecords.json").read_text()):
        uid = unwrap(rec["employee_id"])
        user = users.get(uid)
        if (
            user is None
            or other_company(user)
            or uid not in links
            or entity_for(user) != links[uid]["legal_entity_id"]
        ):
            continue
        day = date.fromisoformat(rec["attendance_date_str"])
        if not HISTORY_START <= day <= HISTORY_END:
            continue
        if rec["status"] == "leave":
            stats["leave_days_for_leave_import"] += 1
            continue
        key = (links[uid]["employment_id"], uid)
        legacy_days.setdefault(key, {})[day] = (rec["status"], unwrap(rec["_id"]))
    for key, days in legacy_days.items():
        if any(st in {"present", "half_day"} for st, _ in days.values()):
            per_employee.setdefault(key, [])
    stats["source_fingerprint"] = hashlib.sha256((data_dir / punches_file).read_bytes()).hexdigest()
    return tid, per_employee, legacy_days, stats


async def import_employee(session, tid, eid, uid, items, legacy_days, stats):
    await lock_resource(session, tid, "EXIM-punch-history-import")
    days = set()
    for it in items:
        await add_once(
            session,
            Punch,
            Punch(
                tenant_id=tid,
                id=source_uuid(tid, "attendancepunches", it["sid"]),
                employment_id=eid,
                punch_type=it["type"],
                punched_at=it["stamp"],
                work_date=it["day"],
                source=SOURCES[it["method"]],
                correction_reason=AUTO_REASON if it["method"] == "auto" else None,
                recorded_at=it["created"],
            ),
            stats,
        )
        days.add(it["day"])

    # Earlier days need the employee's own week-off rules, not the tenant default.
    current = (
        (
            await session.execute(
                select(EmployeePolicyAssignment).where(
                    EmployeePolicyAssignment.tenant_id == tid,
                    EmployeePolicyAssignment.employment_id == eid,
                    EmployeePolicyAssignment.archived_at == None,  # noqa: E711
                )
            )
        )
        .scalars()
        .all()
    )
    if not any(a.effective_from < OCTOBER_START for a in current):
        october = next((a for a in current if a.effective_from == OCTOBER_START), None)
        if october is None:
            stats["skipped"]["no October policy assignment to extend backwards"] += 1
        else:
            before = stats["created"]["employee_policy_assignments"]
            await add_once(
                session,
                EmployeePolicyAssignment,
                EmployeePolicyAssignment(
                    tenant_id=tid,
                    id=source_uuid(tid, "weekoff-assignment-history", uid),
                    employment_id=eid,
                    policy_template_id=october.policy_template_id,
                    effective_from=HISTORY_START,
                    effective_to=date(2026, 9, 30),
                ),
                stats,
            )
            stats["history_policy_assignments"] += (
                stats["created"]["employee_policy_assignments"] - before
            )

    for day in sorted(days):
        policy = await resolve_policy(eid, day, session, tid)
        events = await events_for_day(session, tid, eid, day, policy)
        try:
            event_minutes(events)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            ad = await lock_day(session, tid, eid, day)
            if ad and (ad.reviewed_at or ad.ot_status not in {"NONE", "INFO"} or ad.comp_off_days):
                raise ValueError(
                    f"Reviewed/rewarded day needs manual conflict resolution: {eid}/{day}"
                ) from exc
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
            ad.status = "MISSED_PUNCH"
            ad.review_flags = "LEGACY_CONFLICT"
            ad.reviewed_at = ad.reviewed_by = None
            ad.gross_minutes = ad.break_minutes = ad.effective_minutes = 0
            ad.late_by_minutes = ad.early_departure_minutes = 0
            ad.ot_minutes, ad.ot_status, ad.comp_off_days = 0, "NONE", 0.0
            session.add(ad)
            await session.flush()
            stats["legacy_conflict_days"] += 1
        else:
            ad = await recompute_day(session, tid, eid, day, policy)
        stats["attendance_statuses"][ad.status] += 1
        stats["recomputed_days"] += 1
    # The old status wins where HRMS's own result differs (or there are no punches at all).
    for day, (old, _rec) in sorted(legacy_days.items()):
        target = LEGACY_STATUS[old]
        ad = await lock_day(session, tid, eid, day)
        if ad is None:
            if old not in {"present", "half_day"}:
                stats["derived_by_hrms"][old] += 1
                continue
            ad = AttendanceDay(
                tenant_id=tid,
                id=source_uuid(tid, "attendance-day", f"{eid}:{day}"),
                employment_id=eid,
                work_date=day,
                status=target,
            )
            stats["override_new_days"] += 1
        elif group(ad.status) == group(target):
            stats["agreeing_days"] += 1
            continue
        elif ad.is_locked:
            stats["override_skipped_locked"] += 1
            continue
        else:
            stats["override_changed"][f"{ad.status} -> {target}"] += 1
        ad.status_override, ad.override_note = target, OVERRIDE_NOTE
        session.add(ad)
        await session.flush()
        policy = await resolve_policy(eid, day, session, tid)
        try:
            await recompute_day(session, tid, eid, day, policy, ad)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            # Conflicting punches cannot be recalculated; the old status stands as it is.
            ad.status = target
            ad.ot_minutes, ad.ot_status, ad.comp_off_days = 0, "NONE", 0.0
            session.add(ad)
            await session.flush()
            stats["override_on_conflicting_punches"] += 1
    return len(days)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--punches", default="exim.attendancepunches copy.json")
    parser.add_argument("--company", choices=["suraj", "rabs"], default="suraj")
    parser.add_argument(
        "--decisions", type=Path, help="JSON with {'same': {exim id: employee code}}"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-punch-history.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, per_employee, legacy_days, stats = await prepare(
                    session, args.tenant, args.data_dir, args.punches, args.company, args.decisions
                )
            stats["employees"] = len(per_employee)
            stats["employee_days"] = 0
            # One transaction per employee: bounded locks, resumable, and a failure rolls back
            # only that person. A dry run rolls every one of them back.
            for (eid, uid), items in sorted(per_employee.items(), key=lambda kv: str(kv[0][0])):
                async with session.begin():
                    stats["employee_days"] += await import_employee(
                        session, tid, eid, uid, items, legacy_days.get((eid, uid), {}), stats
                    )
                    if not args.apply:
                        await session.rollback()
            stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
            if args.apply:
                async with session.begin():
                    await session.execute(
                        text("""
                        INSERT INTO import_batches
                          (tenant_id,id,source_system,imported_at,total_records,
                            created_records,updated_records,is_dry_run,details)
                        VALUES (:tid,:id,'EXIM_PUNCH_HISTORY',now(),:total,:created,0,
                                false,CAST(:details AS jsonb))
                    """),
                        {
                            "tid": tid,
                            "id": source_uuid(
                                tid, "punch-history-batch", datetime.now(UTC).isoformat()
                            ),
                            "total": stats["source_punches"],
                            "created": sum(stats["created"].values()),
                            "details": json.dumps(stats, default=str),
                        },
                    )
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(json.dumps(stats, indent=2, default=str))
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
