"""Put the EXIM drivers in an attendance group and bring in their old day-by-day attendance.

Run after migrate_tenants.py --drivers-entity (which creates the drivers as employees). Then:

  * the group (default "Drivers") is found by name, or created;
  * each driver is in it from their join date until they left (the database allows one group
    per person at a time; a driver already in another group then is reported and left alone);
  * every row of exim.attendances.json becomes a mark on that day, as if marked on the
    marking sheet (time/marking.py): present / absent, with who marked it in the old system and
    when. "leave" in the old system had no leave application behind it, so it becomes absent
    with a note saying so. Present on a weekly off or holiday is off-day work.

Never overwrites HRMS: a day already marked in HRMS, a day with the driver's own punches, a
day on approved leave, a locked day, a day outside their employment, or absent on a day off is
skipped and counted. Deterministic ids: running it again adds nothing. Dry-run by default (one
transaction per driver, rolled back).

  python scripts/import_exim_drivers_group.py --tenant suraj-group --fallback-marker hr@x.com
  ... --apply
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from migrate_legacy_attendance import source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import select

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.core.datetime_utils import now_utc
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.policy.models import EmployeePolicyAssignment, PolicyTemplate
from hrms.modules.time.models import (
    AttendanceDay,
    AttendanceGroup,
    AttendanceGroupMember,
    AttendanceMark,
    AttendanceStatus,
    MarkSource,
    MarkStatus,
)
from hrms.modules.time.service import is_off_day, lock_day, recompute_day

ROOT = Path(__file__).resolve().parents[2]
OLD_STATUS = {
    "present": MarkStatus.PRESENT,
    "absent": MarkStatus.ABSENT,
    "leave": MarkStatus.ABSENT,
}
LEAVE_NOTE = "On leave in the old system (no leave application was recorded)"


async def prepare(session, args):
    tid, slug = (
        await session.execute(
            text("SELECT id, slug FROM tenants WHERE slug = :r OR CAST(id AS text) = :r"),
            {"r": args.tenant},
        )
    ).one()
    users = {
        unwrap(u["_id"]): u for u in json.loads((args.data_dir / "exim.users.json").read_text())
    }
    drivers = {k for k, u in users.items() if (u.get("role") or "").strip().lower() == "driver"}
    accounts = {
        r["erp_user_id"]: r
        for r in (
            await session.execute(
                text("""
                    SELECT ua.erp_user_id, ua.id AS account_id, ua.employment_id,
                           e.hire_date, e.separation_date
                    FROM user_accounts ua
                    LEFT JOIN employments e
                      ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                    WHERE ua.tenant_id = :tid AND ua.erp_system = 'EXIM'
                """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    }
    fallback = None
    if args.fallback_marker:
        fallback = (
            await session.execute(
                text("""
                    SELECT id FROM user_accounts WHERE tenant_id = :tid
                      AND (lower(email) = lower(:m) OR lower(employee_code) = lower(:m))
                """),
                {"tid": tid, "m": args.fallback_marker},
            )
        ).scalar()
        if fallback is None:
            raise SystemExit(f"--fallback-marker {args.fallback_marker!r}: no such login")
    return tid, slug, users, drivers, accounts, fallback


async def ensure_group(session, tid, name) -> UUID:
    found = (
        await session.execute(
            text("""
                SELECT id FROM attendance_groups WHERE tenant_id = :tid
                  AND lower(name) = lower(:n) AND archived_at IS NULL
            """),
            {"tid": tid, "n": name},
        )
    ).scalar()
    if found:
        return found
    gid = source_uuid(tid, "attendance-group", name.lower())
    session.add(AttendanceGroup(tenant_id=tid, id=gid, name=name, description="Imported from EXIM"))
    await session.flush()
    return gid


async def ensure_policy(session, tid, name: str, work_week: str) -> UUID:
    """The drivers' policy: found by name, or a copy of the company's default with their week."""
    found = (
        await session.execute(
            select(PolicyTemplate)
            .where(PolicyTemplate.tenant_id == tid)
            .where(PolicyTemplate.name == name)
            .where(PolicyTemplate.archived_at == None)  # noqa: E711
        )
    ).scalar_one_or_none()
    if found:
        return found.id
    default = (
        await session.execute(
            select(PolicyTemplate)
            .where(PolicyTemplate.tenant_id == tid)
            .where(PolicyTemplate.is_default == True)  # noqa: E712
            .where(PolicyTemplate.archived_at == None)  # noqa: E711
        )
    ).scalar_one_or_none()
    if default is None:
        raise SystemExit("The tenant has no default policy to copy the drivers' policy from")
    keep = default.model_dump(
        exclude={
            "tenant_id",
            "id",
            "name",
            "description",
            "is_default",
            "recorded_at",
            "recorded_by",
            "version",
            "archived_at",
            "work_days",
        }
    )
    pid = source_uuid(tid, "policy-template", name.lower())
    session.add(
        PolicyTemplate(
            tenant_id=tid,
            id=pid,
            name=name,
            description=f"Copied from {default.name} for drivers: works {work_week}",
            is_default=False,
            work_days=work_week,
            recorded_at=now_utc(),
            **keep,
        )
    )
    await session.flush()
    return pid


async def assign_policy(session, tid, pid, driver, stats) -> None:
    eid = driver["employment_id"]
    own = (
        (
            await session.execute(
                select(EmployeePolicyAssignment)
                .where(EmployeePolicyAssignment.tenant_id == tid)
                .where(EmployeePolicyAssignment.employment_id == eid)
                .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
            )
        )
        .scalars()
        .all()
    )
    if any(a.policy_template_id == pid for a in own):
        stats["policy_existing"] += 1
        return
    if own:
        stats["policy_kept_their_own"] += 1  # HR gave them one already: leave it
        return
    session.add(
        EmployeePolicyAssignment(
            tenant_id=tid,
            id=source_uuid(tid, "driver-policy", str(eid)),
            employment_id=eid,
            policy_template_id=pid,
            effective_from=driver["hire_date"],
            recorded_at=now_utc(),
        )
    )
    await session.flush()
    stats["policy_assigned"] += 1


async def place(session, tid, gid, driver, stats) -> bool:
    """Make sure the driver is in the group for their employment; False if they can't be."""
    eid, start, end = driver["employment_id"], driver["hire_date"], driver["separation_date"]
    rows = (
        await session.execute(
            text("""
                SELECT group_id FROM attendance_group_members
                WHERE tenant_id = :tid AND employment_id = :e
                  AND effective_from < COALESCE(CAST(:end AS date), '9999-12-31')
                  AND (effective_to IS NULL OR effective_to > :start)
            """),
            {"tid": tid, "e": eid, "start": start, "end": end},
        )
    ).all()
    if any(g != gid for (g,) in rows):
        stats["skipped_drivers"]["in another group"] += 1
        return False
    if rows:
        stats["members_existing"] += 1
        return True
    session.add(
        AttendanceGroupMember(
            tenant_id=tid,
            id=source_uuid(tid, "attendance-group-member", f"{gid}:{eid}"),
            group_id=gid,
            employment_id=eid,
            effective_from=start,
            effective_to=end,
        )
    )
    await session.flush()
    stats["members_added"] += 1
    return True


async def import_driver(session, tid, gid, pid, driver, rows, accounts, fallback, stats):
    if not await place(session, tid, gid, driver, stats):
        return
    if pid is not None:
        await assign_policy(session, tid, pid, driver, stats)
    eid = driver["employment_id"]
    for row in sorted(rows, key=lambda r: unwrap(r["date"])):
        day = date.fromisoformat(str(unwrap(row["date"]))[:10])
        mid = source_uuid(tid, "driver-attendance", unwrap(row["_id"]))
        target = OLD_STATUS.get(row.get("status"))
        if await session.get(AttendanceMark, (tid, mid)) is not None:
            stats["existing"] += 1
            continue
        if target is None:
            stats["skipped"][f"unknown status {row.get('status')!r}"] += 1
            continue
        if day < driver["hire_date"] or (
            driver["separation_date"] and day >= driver["separation_date"]
        ):
            stats["skipped"]["outside their employment"] += 1
            continue
        marker = accounts.get(unwrap(row.get("marked_by")) or "")
        marked_by = marker["account_id"] if marker else fallback
        if marked_by is None:
            stats["skipped"]["old marker has no HRMS login (pass --fallback-marker)"] += 1
            continue
        ad = await lock_day(session, tid, eid, day)
        if ad is not None and ad.is_locked:
            stats["skipped"]["locked day"] += 1
            continue
        busy = (
            (
                await session.execute(
                    text("""
                    SELECT
                      EXISTS (SELECT 1 FROM attendance_marks WHERE tenant_id = :tid
                              AND employment_id = :e AND work_date = :d) AS marked,
                      EXISTS (SELECT 1 FROM punches p WHERE p.tenant_id = :tid
                              AND p.employment_id = :e AND p.work_date = :d
                              AND p.punch_type <> 'VOID'
                              AND NOT EXISTS (SELECT 1 FROM punches v
                                              WHERE v.tenant_id = p.tenant_id
                                              AND v.punch_type = 'VOID'
                                              AND v.original_punch_id = p.id)) AS punched,
                      EXISTS (SELECT 1 FROM leave_applications WHERE tenant_id = :tid
                              AND employment_id = :e AND status = 'APPROVED'
                              AND from_date <= :d AND to_date >= :d) AS on_leave
                """),
                    {"tid": tid, "e": eid, "d": day},
                )
            )
            .mappings()
            .one()
        )
        if busy["marked"]:
            stats["skipped"]["already marked in HRMS"] += 1
            continue
        if busy["punched"]:
            stats["skipped"]["the driver punched that day"] += 1
            continue
        if busy["on_leave"]:
            stats["skipped"]["approved leave in HRMS"] += 1
            continue
        policy = await resolve_policy(eid, day, session, tid)
        off_day = await is_off_day(session, tid, eid, day, policy)
        if off_day and target == MarkStatus.ABSENT:
            stats["skipped"]["absent on a day off"] += 1
            continue
        ad = ad or AttendanceDay(
            tenant_id=tid,
            id=source_uuid(tid, "attendance-day", f"{eid}:{day}"),
            employment_id=eid,
            work_date=day,
        )
        present = target == MarkStatus.PRESENT
        ad.status_override = AttendanceStatus.OFF_DAY_WORKED if present and off_day else target
        ad.override_note = "Marked present" if present else "Marked absent"
        await recompute_day(session, tid, eid, day, policy, ad)
        old_remark = (row.get("remark") or "").strip()
        note = LEAVE_NOTE if row.get("status") == "leave" else "Imported from the old EXIM system"
        session.add(
            AttendanceMark(
                tenant_id=tid,
                id=mid,
                employment_id=eid,
                work_date=day,
                status=target,
                remark=(f"{old_remark} — {note}" if old_remark else note)[:500],
                source=MarkSource.MANUAL,
                marked_by=marked_by,
                marked_at=datetime.fromisoformat(
                    str(unwrap(row["createdAt"])).replace("Z", "+00:00")
                ),
            )
        )
        await session.flush()
        stats["created"][row["status"]] += 1


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--group", default="Drivers")
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument(
        "--fallback-marker",
        help="Login (email or code) recorded as the marker when the old one has no HRMS login",
    )
    parser.add_argument(
        "--policy-name",
        default="Drivers (7-day week)",
        help="Policy given to drivers who have none of their own ('' = keep the company's)",
    )
    parser.add_argument(
        "--work-week", default="1111111", help="Working days Mon..Sun for that policy"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-drivers-group.json"))
    args = parser.parse_args()
    stats = {
        "drivers_in_export": 0,
        "drivers_found": 0,
        "drivers_missing": [],
        "members_added": 0,
        "members_existing": 0,
        "policy_assigned": 0,
        "policy_existing": 0,
        "policy_kept_their_own": 0,
        "skipped_drivers": Counter(),
        "created": Counter(),
        "existing": 0,
        "skipped": Counter(),
    }
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, slug, users, drivers, accounts, fallback = await prepare(session, args)
                gid = await ensure_group(session, tid, args.group)
                pid = None
                if args.policy_name:
                    pid = await ensure_policy(session, tid, args.policy_name, args.work_week)
                if not args.apply:
                    await session.rollback()
            by_driver: dict[str, list[dict]] = {}
            for row in json.loads((args.data_dir / "exim.attendances.json").read_text()):
                by_driver.setdefault(unwrap(row["driver_id"]), []).append(row)
            stats["drivers_in_export"] = len(drivers)
            for uid in sorted(drivers):
                driver = accounts.get(uid)
                if driver is None or driver["employment_id"] is None:
                    stats["drivers_missing"].append(users[uid].get("username"))
                    continue
                stats["drivers_found"] += 1
                async with session.begin():
                    if not args.apply:  # the dry run rolled these back
                        await ensure_group(session, tid, args.group)
                        if args.policy_name:
                            await ensure_policy(session, tid, args.policy_name, args.work_week)
                    await import_driver(
                        session,
                        tid,
                        gid,
                        pid,
                        driver,
                        by_driver.get(uid, []),
                        accounts,
                        fallback,
                        stats,
                    )
                    if not args.apply:
                        await session.rollback()
        stats["tenant"] = slug
        stats["group"] = args.group
        stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
        args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
        args.report.chmod(0o600)
        print(json.dumps(stats, indent=2, default=str))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
