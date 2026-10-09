"""Import Suraj leave policies/applicability atomically; dry-run by default.

Annual quotas never create balances. RABS and driver quotas remain deferred.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid5

from legacy_leave_names import assigned_policy_name, definition_name, suraj_type_name
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import col, select

from hrms import model_registry  # noqa: F401
from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveBucketPolicy,
    LeavePolicyAssignment,
    LeavePolicySet,
    LeaveType,
    LeaveTypeBucketMapping,
)
from hrms.modules.leave.policy_resolver import resolve_leave_policy_set

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = UUID("29e7f12b-2b6c-493b-a733-c8f90ec321aa")
START = date(2026, 10, 1)
RABS = "69cd1e3b50e6c73acc73a926"
INITIAL = "69cd1351ff5301f416796cec"
TARGET_SLUG = "suraj-group"
ALIASES = {"suraj forwarders": "suraj forwarders private limited"}


def oid(value):
    return value["$oid"] if isinstance(value, dict) else value


def stamp(value):
    return datetime.fromisoformat(value["$date"].replace("Z", "+00:00"))


def uid(tid, kind, key):
    return uuid5(NAMESPACE, f"{tid}:EXIM_LEAVE:{kind}:{key}")


async def add_once(session, row, stats):
    found = await session.get(type(row), (row.tenant_id, row.id))
    if found:
        for key, value in row.model_dump().items():
            if (
                key not in {"recorded_at", "recorded_by", "version"}
                and getattr(found, key) != value
            ):
                raise ValueError(f"Imported {type(row).__name__} changed at {key}: {row.id}")
        stats["existing"][row.__tablename__] += 1
    else:
        session.add(row)
        await session.flush()
        stats["created"][row.__tablename__] += 1


def validate_definition(p):
    """Reject unsupported restrictions rather than discard source rules."""
    kind = p["leave_type"]
    if kind not in {"privilege", "lwp"} or p["status"] != "active":
        raise ValueError("Unsupported Suraj leave kind/status")
    e, r, d = p["eligibility"], p["rules"], p["deduction_rules"]
    if e.get("employment_types") or e.get("min_service_months") or e.get("gender"):
        raise ValueError("Restricted eligibility requires a separate migration")
    if (
        r.get("sandwich_rule_enabled")
        or r.get("min_gap_between_applications")
        or r.get("clubbing_allowed_with")
        or r.get("backdated_allowed")
        or r.get("requires_document")
        or not r.get("can_apply_on_probation")
    ):
        raise ValueError("Unsupported Suraj application rules")
    if any(
        d[k] != (kind == "lwp")
        for k in ["deduct_from_salary", "affects_attendance_percentage", "counted_as_absence"]
    ):
        raise ValueError("Ambiguous deduction rules")
    if p["approval_workflow"].get("levels") or p["approval_workflow"].get(
        "auto_approve_if_balance"
    ):
        raise ValueError("Nonstandard approval workflow")
    if p.get("accrual") and p["accrual"] != {
        "accrual_type": "yearly",
        "accrual_rate": 1,
        "accrual_start_date": "calendar_year",
    }:
        raise ValueError("Unsupported accrual definition")
    if r["min_days_per_application"] > r["max_days_per_application"]:
        raise ValueError("Invalid application duration")


def policy_fields(p):
    carry = p["carry_forward"]
    return dict(
        accrual_type="NONE" if p["leave_type"] == "lwp" else "ANNUAL_UPFRONT",
        days_per_year=p["annual_quota"],
        carry_forward_enabled=carry["allowed"],
        max_carry_forward_days=carry.get("max_days") if carry["allowed"] else None,
        lapse_enabled=False,
        encashment_enabled=carry["encashment_allowed"],
        probation_eligible=p["rules"]["can_apply_on_probation"],
        min_service_months=p["eligibility"]["min_service_months"],
        pro_rate_first_year=False,
        source_policy=p,
    )


async def migrate(session, tenant_ref, data_dir):
    tenant = (
        (
            await session.execute(
                text("SELECT id,slug FROM tenants WHERE slug=:ref OR id::text=:ref"),
                {"ref": tenant_ref},
            )
        )
        .mappings()
        .one()
    )
    if tenant["slug"] != TARGET_SLUG:
        raise ValueError("Only the approved Suraj Group tenant is supported")
    tid = tenant["id"]
    await lock_resource(session, tid, "EXIM-leave-import")
    data = {
        n: json.loads((data_dir / f"exim.{n}.json").read_text())
        for n in ["users", "leavepolicies", "leavequotas"]
    }
    users = {oid(u["_id"]): u for u in data["users"]}
    policies = {oid(p["_id"]): p for p in data["leavepolicies"]}
    if len(users) != len(data["users"]) or len(policies) != len(data["leavepolicies"]):
        raise ValueError("Duplicate source IDs")
    selected = {s: p for s, p in policies.items() if oid(p["company_id"]) not in {RABS, INITIAL}}
    for p in selected.values():
        validate_definition(p)
    stats = dict(
        tenant=tenant["slug"],
        effective_from=str(START),
        created=Counter(),
        existing=Counter(),
        employees=[],
        ignored_cross_company_references=[],
        deferred_policy_ids=sorted(set(policies) - set(selected)),
        deferred_driver_quota_records=len(data["leavequotas"]),
        source_policy_count=len(selected),
        source_policy_records=list(selected.values()),
        balances_imported=0,
        source_fingerprints={
            n: hashlib.sha256((data_dir / f"exim.{n}.json").read_bytes()).hexdigest() for n in data
        },
        balance_basis="Staff LeaveBalance export unavailable; annual quotas are not balances",
        approval_basis="Three HRMS approval levels; current configured flows take precedence",
        lwp_basis="Legacy applyLeave bypasses balance checking for lwp; unlimited target bucket",
    )
    batch_id = uid(tid, "batch", "2026-10")
    prior_batch = await session.get(ImportBatch, (tid, batch_id))
    prior_employees = {}
    if prior_batch:
        if prior_batch.details["source_fingerprints"] != stats["source_fingerprints"]:
            raise ValueError("Source exports changed after import")
        prior_employees = {e["source_user_id"]: e for e in prior_batch.details["employees"]}
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
    company_names = {}
    for u in users.values():
        cid = oid(u.get("company_id"))
        if cid and u.get("company"):
            company_names.setdefault(cid, Counter())[u["company"].strip().casefold()] += 1
    links = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_user_id,ua.employment_id,e.legal_entity_id
        FROM user_accounts ua JOIN employments e
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
    if len({r["erp_user_id"] for r in links}) != len(links) or not links:
        raise ValueError("Require unique existing EXIM employment mappings")
    now = datetime.now(UTC)
    buckets = {}
    for kind, code, name, days in [
        ("privilege", "EXIMPL", suraj_type_name("privilege"), 25),
        ("lwp", "EXIMLWP", suraj_type_name("lwp"), 0),
    ]:
        bucket_id, type_id = uid(tid, "bucket", kind), uid(tid, "type", kind)
        buckets[kind] = bucket_id
        await add_once(
            session,
            LeaveBalanceBucket(
                tenant_id=tid,
                id=bucket_id,
                name=name,
                code=code,
                is_unlimited=kind == "lwp",
                recorded_at=now,
            ),
            stats,
        )
        await add_once(
            session,
            LeaveType(
                tenant_id=tid,
                id=type_id,
                name=name,
                code=code,
                days_per_year=days,
                carry_forward=kind == "privilege",
                max_carry_forward_days=15 if kind == "privilege" else None,
                requires_approval=True,
                approval_levels=3,
                min_days_per_application=1,
                max_days_per_application=15 if kind == "privilege" else 30,
                advance_notice_days=7 if kind == "privilege" else 1,
                is_paid=kind == "privilege",
                legacy_managed=True,
                color="#10B981" if kind == "privilege" else "#EF4444",
                recorded_at=now,
            ),
            stats,
        )
        await add_once(
            session,
            LeaveTypeBucketMapping(
                tenant_id=tid,
                id=uid(tid, "mapping", kind),
                leave_type_id=type_id,
                bucket_id=bucket_id,
                recorded_at=now,
            ),
            stats,
        )
    # Keep every source definition independently addressable in the library.
    for sid, p in sorted(selected.items()):
        cid = oid(p["company_id"])
        if cid not in company_names:
            raise ValueError(f"Unmapped source company {cid}")
        label = company_names[cid].most_common(1)[0][0].title()
        pset_id = uid(tid, "definition", sid)
        await add_once(
            session,
            LeavePolicySet(
                tenant_id=tid,
                id=pset_id,
                name=definition_name(p, label),
                description=f"EXIM source policy {sid}; complete source rules retained.",
                recorded_at=stamp(p["createdAt"]),
            ),
            stats,
        )
        await add_once(
            session,
            LeaveBucketPolicy(
                tenant_id=tid,
                id=uid(tid, "definition-bucket", sid),
                policy_set_id=pset_id,
                bucket_id=buckets[p["leave_type"]],
                recorded_at=stamp(p["createdAt"]),
                **policy_fields(p),
            ),
            stats,
        )
    for link in links:
        sid = link["erp_user_id"]
        if sid not in users:
            raise ValueError(f"Missing source user: {sid}")
        user = users[sid]
        cid = oid(user.get("company_id"))
        name = (user.get("company") or "").strip().casefold()
        target_entity = entities.get(ALIASES.get(name, name))
        if target_entity != link["legal_entity_id"] or cid in {RABS, INITIAL}:
            raise ValueError(f"Source/target company mismatch: {sid}")
        source_settings = user.get("leave_settings") or {}
        eligible = {}
        for pid in [oid(i) for i in source_settings.get("special_leave_policies", [])]:
            if pid not in policies:
                raise ValueError(f"Missing source policy: {pid}")
            p = policies[pid]
            if oid(p["company_id"]) != cid:
                stats["ignored_cross_company_references"].append(
                    dict(
                        source_user_id=sid,
                        source_policy_id=pid,
                    )
                )
                continue  # The old Suraj controller also filters by source company.
            if pid not in selected:
                raise ValueError(f"Inactive/unapproved policy: {pid}")
            kind = p["leave_type"]
            if kind in eligible and eligible[kind] != pid:
                raise ValueError(f"Ambiguous source policies for {sid}: {kind}")
            eligible[kind] = pid
        if source_settings.get("leave_applicable") is False:
            eligible = {}
        elif "lwp" not in eligible:
            candidates = [
                s
                for s, p in selected.items()
                if oid(p["company_id"]) == cid and p["leave_type"] == "lwp"
            ]
            if len(candidates) != 1:
                raise ValueError(f"Cannot resolve default LWP for {sid}")
            eligible["lwp"] = candidates[0]
        employee_id = link["employment_id"]
        assignment_id = uid(tid, "assignment", sid)
        conflict = (
            (
                await session.execute(
                    select(LeavePolicyAssignment).where(
                        col(LeavePolicyAssignment.tenant_id) == tid,
                        col(LeavePolicyAssignment.employment_id) == employee_id,
                        col(LeavePolicyAssignment.archived_at).is_(None),
                        col(LeavePolicyAssignment.effective_from) >= START,
                        col(LeavePolicyAssignment.id) != assignment_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if conflict:
            raise ValueError(f"Existing current/future direct assignment: {sid}")
        if prior_batch:
            if sid not in prior_employees:
                raise ValueError("Employee mappings changed after import")
            native_id = prior_employees[sid]["native_policy_set_id"]
            native = (
                await session.get(LeavePolicySet, (tid, UUID(native_id))) if native_id else None
            )
        else:
            native = await resolve_leave_policy_set(session, tid, employee_id, START)
        inherited = (
            (
                await session.execute(
                    select(LeaveBucketPolicy).where(
                        col(LeaveBucketPolicy.tenant_id) == tid,
                        col(LeaveBucketPolicy.policy_set_id) == native.id,
                    )
                )
            )
            .scalars()
            .all()
            if native
            else []
        )
        if any(bp.source_policy for bp in inherited):
            raise ValueError("Unexpected imported baseline without an import batch")
        key = (
            ":".join(sorted(eligible.values()))
            + ":native:"
            + (str(native.id) if native else "none")
            + ":entity:"
            + str(target_entity)
        )
        set_id = uid(tid, "employee-set", key)
        source_company = company_names[cid].most_common(1)[0][0]
        await add_once(
            session,
            LeavePolicySet(
                tenant_id=tid,
                id=set_id,
                name=assigned_policy_name(
                    source_company,
                    [selected[pid] for pid in eligible.values()],
                    native.name if native else None,
                    next(r["name"] for r in entity_rows if r["id"] == target_entity),
                ),
                description="Assigned legacy rules; existing native bucket entitlements preserved.",
                recorded_at=now,
            ),
            stats,
        )
        for kind, pid in sorted(eligible.items()):
            await add_once(
                session,
                LeaveBucketPolicy(
                    tenant_id=tid,
                    id=uid(tid, "employee-bucket", f"{set_id}:{kind}"),
                    policy_set_id=set_id,
                    bucket_id=buckets[kind],
                    recorded_at=now,
                    **policy_fields(selected[pid]),
                ),
                stats,
            )
        for bp in inherited:
            fields = bp.model_dump(
                exclude={"tenant_id", "id", "policy_set_id", "recorded_at", "recorded_by"}
            )
            await add_once(
                session,
                LeaveBucketPolicy(
                    tenant_id=tid,
                    id=uid(tid, "native-bucket", f"{set_id}:{bp.bucket_id}"),
                    policy_set_id=set_id,
                    recorded_at=now,
                    **fields,
                ),
                stats,
            )
        await add_once(
            session,
            LeavePolicyAssignment(
                tenant_id=tid,
                id=assignment_id,
                employment_id=employee_id,
                leave_policy_set_id=set_id,
                effective_from=START,
                recorded_at=now,
            ),
            stats,
        )
        stats["employees"].append(
            dict(
                source_user_id=sid,
                employment_id=str(employee_id),
                source_policy_ids=sorted(eligible.values()),
                native_policy_set_id=str(native.id) if native else None,
                leave_policy_set_id=str(set_id),
            )
        )
    if prior_batch and set(prior_employees) != {e["source_user_id"] for e in stats["employees"]}:
        raise ValueError("Employee mappings changed after import")
    stats["assigned_employees"] = len(stats["employees"])
    stats["employees_with_privilege_leave"] = sum(
        any(selected[p]["leave_type"] == "privilege" for p in e["source_policy_ids"])
        for e in stats["employees"]
    )
    return tid, batch_id, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="suraj-group")
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-leave-migration.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, batch_id, stats = await migrate(session, args.tenant, args.data_dir)
                stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
                if args.apply:
                    if not await session.get(ImportBatch, (tid, batch_id)):
                        session.add(
                            ImportBatch(
                                tenant_id=tid,
                                id=batch_id,
                                source_system="EXIM_LEAVE",
                                total_records=stats["source_policy_count"],
                                created_records=sum(stats["created"].values()),
                                details=stats,
                            )
                        )
                else:
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
                            "employees",
                            "source_policy_records",
                            "source_fingerprints",
                            "ignored_cross_company_references",
                        }
                    },
                    indent=2,
                    default=str,
                )
            )
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
