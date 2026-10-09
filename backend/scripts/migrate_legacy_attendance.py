"""Import October 2026 EXIM punches and complete calendars/week-off definitions.

Dry-run by default (same transaction, rolled back). Requires an existing tenant
and exact EXIM ERP employee links; unrelated tenants and native records are kept.
Run from backend: .venv/bin/python scripts/migrate_legacy_attendance.py --tenant suraj-group
Add --apply to commit. --correct-gandhi-date records the explicitly approved correction.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from legacy_attendance_rules import (
    SUNDAY_FALLBACK_NAME,
    attendance_policy_name,
    resolve_source_weekoff,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import select

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.policy.models import EmployeePolicyAssignment, PolicyTemplate
from hrms.modules.time.models import (
    AttendanceDay,
    Holiday,
    HolidayCalendar,
    HolidayCalendarAssignment,
    Punch,
)
from hrms.modules.time.service import event_minutes, events_for_day, lock_day, recompute_day

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = UUID("5377dc4a-8427-41bd-a168-c13b9c642b64")
START, END = date(2026, 10, 1), date(2026, 11, 1)


def unwrap(value):
    while isinstance(value, dict):
        key = next((k for k in ("$oid", "$date", "$numberLong") if k in value), None)
        if key is None:
            raise ValueError(f"Unsupported Extended JSON value: {value}")
        value = value[key]
    return value


def instant(value):
    value = unwrap(value)
    if isinstance(value, int) or (isinstance(value, str) and value.lstrip("-").isdigit()):
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(value))
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Source timestamp must have a timezone")
    return result.astimezone(UTC)


def source_uuid(tenant, collection, key):
    return uuid5(NAMESPACE, f"{tenant}:EXIM:{collection}:{key}")


def weekoff_fields(record):
    """Translate only the supported full-day rules; reject lossy conversions."""
    if record["policy_type"] != "fixed" or not record["applicability"]["teams"]["all"]:
        raise ValueError("Only fixed, all-team week-off definitions can be imported")
    days = list("1111111")
    saturday = set()
    for item in record["day_rules"]:
        day = item["day_index"]
        if not 0 <= day <= 6:
            raise ValueError("Invalid source weekday")
        for rule in item["rules"]:
            week = rule["week_number"]
            if rule["off_type"] != "full_day":
                raise ValueError("Unsupported source off_type")
            if week == 0:
                days[(day + 6) % 7] = "0"
            elif day == 6:
                saturday.add(week)
            else:
                raise ValueError("Unsupported monthly weekday rule")
    patterns = {
        frozenset(): "ALL",
        frozenset({2}): "SECOND_OFF",
        frozenset({2, 4}): "SECOND_FOURTH_OFF",
        frozenset({1, 3}): "FIRST_THIRD_OFF",
    }
    if frozenset(saturday) not in patterns:
        raise ValueError("Unsupported Saturday pattern")
    return {"work_days": "".join(days), "saturday_pattern": patterns[frozenset(saturday)]}


def holiday_date(entry, year, correct):
    result = instant(entry["holiday_date"]).date()
    corrected = False
    if result.year != year:
        if correct and result == date(206, 10, 2) and year == 2026:
            result, corrected = date(2026, 10, 2), True
        else:
            raise ValueError(f"Holiday year mismatch: {entry['holiday_name']}: {result}")
    return result, corrected


async def add_once(session, model, row, stats):
    existing = await session.get(model, (row.tenant_id, row.id))
    if existing:
        # A rerun must not silently hide source drift or changes to imported rows.
        ignored = {"recorded_at", "recorded_by", "version"}
        for key, value in row.model_dump().items():
            if key not in ignored and getattr(existing, key) != value:
                raise ValueError(f"Existing imported {model.__name__} differs at {key}: {row.id}")
        stats["existing"][model.__tablename__] += 1
    else:
        session.add(row)
        await session.flush()
        stats["created"][model.__tablename__] += 1


async def migrate(session, tenant_ref, data_dir, correct_gandhi=False):
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
    await lock_resource(session, tid, "EXIM-attendance-2026-10-import")
    stats = {
        "tenant": tenant["slug"],
        "month": "2026-10",
        "created": Counter(),
        "existing": Counter(),
        "deferred_rabs_punches": [],
        "deferred_rabs_users": [],
        "unresolved": [],
        "corrections": [],
        "recomputed_days": 0,
        "attendance_statuses": Counter(),
        "days_needing_correction": [],
        "shift_basis": "Existing tenant default; shift export unavailable",
    }
    data = {
        name: json.loads((data_dir / f"exim.{name}.json").read_text())
        for name in ["users", "attendancepunches", "weekoffpolicies", "holidaypolicies"]
    }
    users = {unwrap(r["_id"]): r for r in data["users"]}
    if len(users) != len(data["users"]):
        raise ValueError("Duplicate user source IDs")
    accounts = (
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
    links = {r["erp_user_id"]: r for r in accounts}
    defaults = (
        (
            await session.execute(
                select(PolicyTemplate).where(
                    PolicyTemplate.tenant_id == tid,
                    PolicyTemplate.is_default == True,  # noqa: E712
                    PolicyTemplate.archived_at == None,  # noqa: E711
                )
            )
        )
        .scalars()
        .all()
    )
    if len(defaults) != 1:
        raise ValueError(
            "Require exactly one current tenant default policy to inherit shift settings"
        )
    baseline = defaults[0]
    # Keep company aliases aligned with the already-applied person import.
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
    alias = {"suraj forwarders": "suraj forwarders private limited"}

    def entity_for(user):
        name = (user.get("company") or "").strip().casefold()
        return entities.get(alias.get(name, name))

    def is_rabs(user):
        return (
            user.get("company") or ""
        ).strip().casefold() == "rabs industries india private limited"

    policy_ids = {}
    for r in data["weekoffpolicies"]:
        sid = unwrap(r["_id"])
        payload = baseline.model_dump(
            exclude={
                "tenant_id",
                "id",
                "recorded_at",
                "recorded_by",
                "version",
                "archived_at",
                "name",
                "description",
                "is_default",
            }
        )
        payload.update(weekoff_fields(r))
        pid = source_uuid(tid, "weekoffpolicies", sid)
        policy_ids[sid] = pid
        await add_once(
            session,
            PolicyTemplate,
            PolicyTemplate(
                tenant_id=tid,
                id=pid,
                name=attendance_policy_name(r),
                description=r.get("description"),
                is_default=False,
                recorded_at=instant(r["createdAt"]),
                **payload,
            ),
            stats,
        )
    calendar_ids = {}
    for r in data["holidaypolicies"]:
        sid = unwrap(r["_id"])
        if not r["applicability"]["teams"]["all"]:
            raise ValueError("Unsupported team-restricted holiday calendar")
        cid = source_uuid(tid, "holidaypolicies", sid)
        calendar_ids[sid] = cid
        await add_once(
            session,
            HolidayCalendar,
            HolidayCalendar(
                tenant_id=tid,
                id=cid,
                name=r["policy_name"],
                year=r["year"],
                recorded_at=instant(r["createdAt"]),
            ),
            stats,
        )
        for index, entry in enumerate(r["holidays"]):
            day, corrected = holiday_date(entry, r["year"], correct_gandhi)
            if corrected:
                stats["corrections"].append(
                    {
                        "policy_id": sid,
                        "holiday": entry["holiday_name"],
                        "from": "0206-10-02",
                        "to": day.isoformat(),
                    }
                )
            await add_once(
                session,
                Holiday,
                Holiday(
                    tenant_id=tid,
                    id=source_uuid(tid, "holiday-entry", f"{sid}:{index}"),
                    calendar_id=cid,
                    holiday_date=day,
                    name=entry["holiday_name"],
                    is_library=True,
                    is_optional=entry["is_optional"],
                    holiday_type=entry["holiday_type"],
                    recorded_at=instant(r["createdAt"]),
                ),
                stats,
            )

    resolved_weekoffs = {
        sid: resolve_source_weekoff(users[sid], data["weekoffpolicies"]) for sid in links
    }
    # Policy migration covers every linked employee, including those without October punches.
    fallback_users = {
        sid for sid, policy in resolved_weekoffs.items() if policy is None
    }
    if fallback_users:
        fallback_id = source_uuid(tid, "weekoffpolicies", "legacy-sunday-fallback")
        payload = baseline.model_dump(
            exclude={
                "tenant_id",
                "id",
                "recorded_at",
                "recorded_by",
                "version",
                "archived_at",
                "name",
                "description",
                "is_default",
                "work_days",
                "saturday_pattern",
            }
        )
        await add_once(
            session,
            PolicyTemplate,
            PolicyTemplate(
                tenant_id=tid,
                id=fallback_id,
                name=SUNDAY_FALLBACK_NAME,
                description="Old Sunday fallback for employees without a company week-off policy",
                is_default=False,
                work_days="1111110",
                saturday_pattern="ALL",
                **payload,
            ),
            stats,
        )
        policy_ids["legacy-sunday-fallback"] = fallback_id
    stats["legacy_sunday_fallback_assignments"] = len(fallback_users)
    # Explicit source assignment beats calendar company metadata (HO spans companies).
    for sid, user in users.items():
        wid, hid = unwrap(user.get("weekoff_policy_id")), unwrap(user.get("holiday_policy_id"))
        if sid in resolved_weekoffs and resolved_weekoffs[sid] is not None:
            wid = unwrap(resolved_weekoffs[sid]["_id"])
        if sid in fallback_users:
            wid = "legacy-sunday-fallback"
        if not (wid or hid):
            continue
        if sid not in links:
            stats["deferred_rabs_users" if is_rabs(user) else "unresolved"].append(sid)
            continue
        eid = links[sid]["employment_id"]
        if entity_for(user) != links[sid]["legal_entity_id"]:
            stats["unresolved"].append({"user_id": sid, "reason": "company mismatch"})
            continue
        if wid:
            pid = policy_ids[wid]
            aid = source_uuid(tid, "weekoff-assignment", sid)
            overlap = (
                (
                    await session.execute(
                        select(EmployeePolicyAssignment).where(
                            EmployeePolicyAssignment.tenant_id == tid,
                            EmployeePolicyAssignment.employment_id == eid,
                            EmployeePolicyAssignment.archived_at == None,  # noqa: E711
                            EmployeePolicyAssignment.id != aid,
                            (EmployeePolicyAssignment.effective_to == None)  # noqa: E711
                            | (EmployeePolicyAssignment.effective_to >= START),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if overlap:
                raise ValueError(f"Existing employee policy assignment overlaps import: {sid}")
            await add_once(
                session,
                EmployeePolicyAssignment,
                EmployeePolicyAssignment(
                    tenant_id=tid,
                    id=aid,
                    employment_id=eid,
                    policy_template_id=pid,
                    effective_from=START,
                ),
                stats,
            )
        if hid:
            await add_once(
                session,
                HolidayCalendarAssignment,
                HolidayCalendarAssignment(
                    tenant_id=tid,
                    id=source_uuid(tid, "holiday-assignment", sid),
                    employment_id=eid,
                    calendar_id=calendar_ids[hid],
                    effective_from=START,
                    effective_to=date(2026, 12, 31),
                ),
                stats,
            )

    selected = [
        r
        for r in data["attendancepunches"]
        if START <= date.fromisoformat(r["punch_date_str"]) < END
    ]
    stats["source_october_punches"] = len(selected)
    days = set()
    seen = set()
    for r in selected:
        sid, uid = unwrap(r["_id"]), unwrap(r["employee_id"])
        user = users.get(uid)
        if user is None:
            stats["unresolved"].append({"punch_id": sid, "reason": "missing source user"})
            continue
        if is_rabs(user):
            stats["deferred_rabs_punches"].append(sid)
            continue
        if uid not in links or entity_for(user) != links[uid]["legal_entity_id"]:
            stats["unresolved"].append({"punch_id": sid, "reason": "missing employee/company link"})
            continue
        # company IDs are historical references; reject a mismatch with the user export.
        if unwrap(r["company_id"]) != unwrap(user.get("company_id")):
            stats["unresolved"].append(
                {"punch_id": sid, "reason": "source company differs from user"}
            )
            continue
        stamp, day = instant(r["punch_time"]), date.fromisoformat(r["punch_date_str"])
        if stamp.astimezone(ZoneInfo("Asia/Kolkata")).date() != day:
            raise ValueError(f"Source business date mismatch: {sid}")
        if r["punch_type"] not in {"IN", "OUT"} or not r["is_valid"] or r["is_regularized"]:
            raise ValueError(f"Unsupported punch state: {sid}")
        source = {"web": "WEB", "mobile": "MOBILE"}.get(r["punch_method"])
        if source is None:
            raise ValueError(f"Unsupported October punch method: {sid}")
        eid = links[uid]["employment_id"]
        event_key = (eid, stamp, r["punch_type"])
        if event_key in seen:
            raise ValueError(f"Duplicate October source event: {sid}")
        seen.add(event_key)
        await add_once(
            session,
            Punch,
            Punch(
                tenant_id=tid,
                id=source_uuid(tid, "attendancepunches", sid),
                employment_id=eid,
                punch_type=r["punch_type"],
                punched_at=stamp,
                work_date=day,
                source=source,
                recorded_at=instant(r["createdAt"]),
            ),
            stats,
        )
        days.add((eid, day))
    if stats["unresolved"]:
        raise ValueError(f"Unresolved non-RABS source records: {stats['unresolved']}")
    for eid, day in sorted(days):
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
            before = ad.model_dump(mode="json") if ad else None
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
            stats["days_needing_correction"].append(
                {
                    "employment_id": str(eid),
                    "work_date": day.isoformat(),
                    "reason": str(exc.detail),
                    "prior_attendance": before,
                }
            )
        else:
            ad = await recompute_day(session, tid, eid, day, policy)
        stats["attendance_statuses"][ad.status] += 1
        stats["recomputed_days"] += 1
    stats["imported_employee_days"] = len(days)
    stats["imported_employees"] = len({eid for eid, _ in days})
    stats["source_fingerprints"] = {
        name: hashlib.sha256((data_dir / f"exim.{name}.json").read_bytes()).hexdigest()
        for name in data
    }
    # Preserve full policy source documents and mappings, without user credentials.
    stats["policy_source_records"] = {
        name: data[name] for name in ["weekoffpolicies", "holidaypolicies"]
    }
    return tid, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--correct-gandhi-date", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-attendance-migration.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, stats = await migrate(
                    session, args.tenant, args.data_dir, args.correct_gandhi_date
                )
                stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
                if args.apply:
                    await session.execute(
                        text("""
                        INSERT INTO import_batches
                          (tenant_id,id,source_system,imported_at,total_records,
                            created_records,updated_records,is_dry_run,details)
                        VALUES (:tid,:id,'EXIM_ATTENDANCE',now(),:total,:created,0,
                                false,CAST(:details AS jsonb))
                    """),
                        {
                            "tid": tid,
                            "id": source_uuid(tid, "batch", datetime.now(UTC).isoformat()),
                            "total": stats["source_october_punches"],
                            "created": sum(stats["created"].values()),
                            "details": json.dumps(stats, default=str),
                        },
                    )
                else:
                    await session.rollback()
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in stats.items()
                        if k
                        not in {
                            "policy_source_records",
                            "deferred_rabs_punches",
                            "deferred_rabs_users",
                            "source_fingerprints",
                            "days_needing_correction",
                        }
                    },
                    indent=2,
                    default=str,
                )
            )
            print(
                f"Deferred RABS: {len(stats['deferred_rabs_punches'])} punches; "
                f"{len(stats['deferred_rabs_users'])} policy assignments"
            )
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
