"""Audit Suraj policies against EXIM and repair names/missing week-off assignments.

Dry-run by default; --apply saves a private before-state and commits atomically.
Existing attendance results, leave balances and other tenants are preserved.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from fix_legacy_leave_names import snapshot as leave_snapshot
from legacy_attendance_rules import (
    SUNDAY_FALLBACK_NAME,
    attendance_policy_name,
    resolve_source_weekoff,
)
from migrate_legacy_attendance import START, source_uuid, unwrap, weekoff_fields
from migrate_legacy_leave import INITIAL, RABS, ROOT, oid, policy_fields, uid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.core.datetime_utils import is_working_day
from hrms.core.locking import lock_resource
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.leave.models import LeaveBucketPolicy, LeaveType
from hrms.modules.leave.policy_resolver import resolve_leave_policy_set
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.policy.models import EmployeePolicyAssignment, PolicyTemplate


async def snapshot(session):
    result = await leave_snapshot(session)
    for table in (
        "policy_templates",
        "employee_policy_assignments",
        "punches",
        "attendance_days",
        "holiday_calendars",
        "holiday_calendar_assignments",
        "holidays",
        "holiday_calendar_days",
    ):
        result[table] = [
            dict(r)
            for r in (
                await session.execute(text(f'SELECT * FROM "{table}" ORDER BY tenant_id,id'))
            ).mappings()
        ]
    return result


def source_off(day, policy):
    # Independent reference for the old resolver: JS weekday and ceil(day-of-month / 7).
    if policy is None:
        return day.weekday() == 6
    weekday, week = (day.weekday() + 1) % 7, (day.day + 6) // 7
    rules = next((r["rules"] for r in policy["day_rules"] if r["day_index"] == weekday), [])
    rule = next((r for r in rules if r["week_number"] == week), None)
    rule = rule or next((r for r in rules if r["week_number"] == 0), None)
    return bool(rule and rule["off_type"] != "none")


async def reconcile(session, apply=False):
    tid = (
        await session.execute(text("SELECT id FROM tenants WHERE slug='suraj-group'"))
    ).scalar_one()
    await lock_resource(session, tid, "EXIM-attendance-2026-10-import")
    await lock_resource(session, tid, "EXIM-leave-import")
    data = {
        n: json.loads((ROOT / f"exim.{n}.json").read_text())
        for n in ("users", "weekoffpolicies", "leavepolicies")
    }
    users = {oid(u["_id"]): u for u in data["users"]}
    batch = await session.get(ImportBatch, (tid, uid(tid, "batch", "2026-10")))
    if not batch:
        raise ValueError("Applied Suraj leave migration is required")
    for name, digest in batch.details["source_fingerprints"].items():
        if hashlib.sha256((ROOT / f"exim.{name}.json").read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source {name} changed after migration")
    attendance_audits = (
        (
            await session.execute(
                text(
                    "SELECT details FROM import_batches "
                    "WHERE tenant_id=:tid AND source_system='EXIM_ATTENDANCE'"
                ),
                {"tid": tid},
            )
        )
        .scalars()
        .all()
    )
    weekoff_digest = hashlib.sha256((ROOT / "exim.weekoffpolicies.json").read_bytes()).hexdigest()
    if not attendance_audits or any(
        a["source_fingerprints"]["weekoffpolicies"] != weekoff_digest for a in attendance_audits
    ):
        raise ValueError("Week-off source changed since the applied attendance import")
    links = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_user_id,ua.employment_id FROM user_accounts ua JOIN employments e
          ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
        WHERE ua.tenant_id=:tid AND ua.erp_system='EXIM' AND e.archived_at IS NULL
        ORDER BY ua.erp_user_id
    """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    if {r["erp_user_id"] for r in links} != {
        e["source_user_id"] for e in batch.details["employees"]
    }:
        raise ValueError("Employee links changed since the verified leave import")
    before = await snapshot(session)
    renames, additions, minimums, expected = [], [], [], {}
    for policy in data["weekoffpolicies"]:
        pid = source_uuid(tid, "weekoffpolicies", unwrap(policy["_id"]))
        row = await session.get(PolicyTemplate, (tid, pid))
        if not row:
            raise ValueError("Missing imported week-off definition")
        for key, value in weekoff_fields(policy).items():
            if getattr(row, key) != value:
                raise ValueError(f"Week-off rule drift: {policy['policy_name']}/{key}")
        name = attendance_policy_name(policy)
        if row.name != name:
            renames.append(dict(id=str(pid), before=row.name, after=name))
        expected[pid] = policy
    fallback_id = source_uuid(tid, "weekoffpolicies", "legacy-sunday-fallback")
    fallback = await session.get(PolicyTemplate, (tid, fallback_id))
    if not fallback or fallback.work_days != "1111110" or fallback.saturday_pattern != "ALL":
        raise ValueError("Missing/changed Sunday fallback")
    if fallback.name != SUNDAY_FALLBACK_NAME:
        renames.append(dict(id=str(fallback_id), before=fallback.name, after=SUNDAY_FALLBACK_NAME))
    expected[fallback_id] = None
    for link in links:
        source = resolve_source_weekoff(users[link["erp_user_id"]], data["weekoffpolicies"])
        pid = source_uuid(tid, "weekoffpolicies", unwrap(source["_id"])) if source else fallback_id
        aid = source_uuid(tid, "weekoff-assignment", link["erp_user_id"])
        found = await session.get(EmployeePolicyAssignment, (tid, aid))
        if found:
            if (
                found.policy_template_id != pid
                or found.employment_id != link["employment_id"]
                or found.effective_from != START
                or found.effective_to
                or found.archived_at
            ):
                raise ValueError("Existing imported week-off assignment differs from source")
        else:
            count = (
                await session.execute(
                    text("""
                SELECT count(*) FROM employee_policy_assignments WHERE tenant_id=:tid
                  AND employment_id=:eid AND archived_at IS NULL
                  AND (effective_to IS NULL OR effective_to>=:start)
            """),
                    {"tid": tid, "eid": link["employment_id"], "start": START},
                )
            ).scalar_one()
            if count:
                raise ValueError("An existing employee policy overlaps the proposed correction")
            count = (
                await session.execute(
                    text("""
                SELECT count(*) FROM attendance_days WHERE tenant_id=:tid
                  AND employment_id=:eid AND work_date>=:start
            """),
                    {"tid": tid, "eid": link["employment_id"], "start": START},
                )
            ).scalar_one()
            if count:
                raise ValueError("Assignment correction would require attendance recalculation")
            additions.append(
                EmployeePolicyAssignment(
                    tenant_id=tid,
                    id=aid,
                    employment_id=link["employment_id"],
                    policy_template_id=pid,
                    effective_from=START,
                )
            )
    for kind in ("privilege", "lwp"):
        lt = await session.get(LeaveType, (tid, uid(tid, "type", kind)))
        if not lt or not lt.legacy_managed:
            raise ValueError("Missing imported leave type")
        if lt.min_days_per_application != 1:
            if lt.min_days_per_application != 0.5:
                raise ValueError("Imported minimum duration was changed")
            minimums.append(lt)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    folder = ROOT / "backend/storage/migration-backups"
    if apply and (renames or additions or minimums):
        path = folder / f"before-suraj-policy-correction-{stamp}.json"
        with path.open("x") as file:
            path.chmod(0o600)
            json.dump(before, file, indent=2, default=str)
    for change in renames:
        await session.execute(
            text(
                "UPDATE policy_templates SET name=:name "
                "WHERE tenant_id=:tid AND id=CAST(:id AS uuid)"
            ),
            {"tid": tid, "id": change["id"], "name": change["after"]},
        )
    session.add_all(additions)
    for lt in minimums:
        lt.min_days_per_application = 1
    await session.flush()
    # Verify existing rows and allow only the explicitly planned field edits/new assignments.
    after = await snapshot(session)
    allowed_names = {r["id"] for r in renames}
    allowed_minimums = {str(lt.id) for lt in minimums}
    for table, rows in before.items():
        current = {(r["tenant_id"], r["id"]): r for r in after[table]}
        for old in rows:
            new = current[(old["tenant_id"], old["id"])]
            changed = {k for k in old if old[k] != new[k]}
            allowed = (
                {"name"}
                if table == "policy_templates" and str(old["id"]) in allowed_names
                else {"min_days_per_application"}
                if table == "leave_types" and str(old["id"]) in allowed_minimums
                else set()
            )
            if not changed <= allowed or (changed and old["tenant_id"] != tid):
                raise ValueError(f"Unexpected change to {table}/{old['id']}")
        added = set(current) - {(r["tenant_id"], r["id"]) for r in rows}
        allowed = (
            {(tid, r.id) for r in additions} if table == "employee_policy_assignments" else set()
        )
        if added != allowed:
            raise ValueError(f"Unexpected added rows in {table}")
    # Compare all dates in 2026, independently of the import's rule translator.
    calendar_checks = 0
    for pid, source in expected.items():
        row = await session.get(PolicyTemplate, (tid, pid))
        day = date(2026, 1, 1)
        while day.year == 2026:
            if source_off(day, source) != (
                not is_working_day(day, row.work_days, row.saturday_pattern)
            ):
                raise ValueError(f"Week-off behavior mismatch on {day}")
            calendar_checks += 1
            day += timedelta(days=1)
    counts = Counter()
    for link in links:
        source = resolve_source_weekoff(users[link["erp_user_id"]], data["weekoffpolicies"])
        for day in (START, date(2026, 10, 31)):
            policy = await resolve_policy(link["employment_id"], day, session, tid)
            for offset in range(31):
                check = START + timedelta(days=offset)
                if source_off(check, source) != (
                    not is_working_day(check, policy.work_days, policy.saturday_pattern)
                ):
                    raise ValueError("Employee week-off resolution differs from the source")
        counts[attendance_policy_name(source) if source else SUNDAY_FALLBACK_NAME] += 1
    selected = {
        oid(p["_id"]): p
        for p in data["leavepolicies"]
        if oid(p["company_id"]) not in {INITIAL, RABS}
    }
    for sid, source in selected.items():
        row = await session.get(LeaveBucketPolicy, (tid, uid(tid, "definition-bucket", sid)))
        if not row or any(getattr(row, k) != v for k, v in policy_fields(source).items()):
            raise ValueError("Imported leave definition differs from the source")
    privilege_count = 0
    for link in links:
        user = users[link["erp_user_id"]]
        eligible = {
            oid(sid)
            for sid in (user.get("leave_settings") or {}).get("special_leave_policies", [])
            if oid(sid) in selected
            and oid(selected[oid(sid)]["company_id"]) == oid(user["company_id"])
        }
        if (user.get("leave_settings") or {}).get("leave_applicable") is False:
            eligible = set()
        elif not any(selected[sid]["leave_type"] == "lwp" for sid in eligible):
            eligible.update(
                sid
                for sid, p in selected.items()
                if p["leave_type"] == "lwp" and oid(p["company_id"]) == oid(user["company_id"])
            )
        pset = await resolve_leave_policy_set(session, tid, link["employment_id"], START)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT source_policy FROM leave_bucket_policies "
                        "WHERE tenant_id=:tid AND policy_set_id=:pid"
                    ),
                    {"tid": tid, "pid": pset.id},
                )
            )
            .scalars()
            .all()
        )
        rows = [p for p in rows if p]
        if {oid(p["_id"]) for p in rows} != eligible or any(
            p != selected[oid(p["_id"])] for p in rows
        ):
            raise ValueError("Employee leave policy resolution differs from the source")
        privilege_count += any(p["leave_type"] == "privilege" for p in rows)
    result = dict(
        mode="APPLIED" if apply else "DRY_RUN_ROLLED_BACK",
        tenant="suraj-group",
        attendance_names_corrected=len(renames),
        missing_weekoff_assignments_added=len(additions),
        leave_minimum_labels_corrected=len(minimums),
        weekoff_assignments_verified=len(links),
        attendance_assignment_counts=dict(counts),
        calendar_rule_checks=calendar_checks,
        exact_leave_definitions_verified=len(selected),
        leave_assignments_verified=len(links),
        employees_with_privilege_leave=privilege_count,
        existing_attendance_and_leave_balances_unchanged=True,
        other_tenants_unchanged=True,
        limitations=[
            "Legacy shift, grace and overtime configuration export unavailable",
            "Staff leave balance export unavailable",
            "Legacy named approver routes have not been migrated",
            "Old leave calculator applies sandwich counting even when the exported flag is false; "
            "HRMS follows the exported false flag",
        ],
        attendance_name_changes=renames,
    )
    correction_id = source_uuid(tid, "batch", "suraj-policy-reconciliation-2026-10")
    if apply and (renames or additions or minimums):
        if await session.get(ImportBatch, (tid, correction_id)):
            raise ValueError("An applied correction has drifted; review before changing it")
        session.add(
            ImportBatch(
                tenant_id=tid,
                id=correction_id,
                source_system="EXIM_SURAJ_POLICY_CORRECTION",
                total_records=len(links),
                created_records=len(additions),
                updated_records=len(renames) + len(minimums),
                details={
                    **result,
                    "source_weekoff_fingerprint": weekoff_digest,
                    "employee_assignment_ids": [str(r.id) for r in additions],
                    "backup": str(path),
                },
            )
        )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            result = await reconcile(session, args.apply)
            if not args.apply:
                await session.rollback()
        name = "suraj-policy-verification.json" if args.apply else "suraj-policy-dry-run.json"
        path = ROOT / "docs/legacy-mongo-analysis" / name
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
