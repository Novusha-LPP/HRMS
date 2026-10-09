"""Import RABS leave policy definitions only; employee links await confirmation.

Dry-run by default. --apply commits atomically. Original deduction settings,
eligibility and source status are retained. Never creates employee assignments,
employees, balance allocations or leave transactions.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

from legacy_leave_names import rabs_policy_name
from migrate_legacy_leave import RABS, ROOT, add_once, oid, policy_fields, stamp, uid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveBucketPolicy,
    LeavePolicySet,
    LeaveType,
    LeaveTypeBucketMapping,
)

TARGET_SLUG = "rabs-industries-india-private-limited"


def type_code(policy):
    # Two PL policies carry different entitlements. Each source ID receives
    # a distinct type AND bucket, including inactive predecessor definitions.
    suffix = hashlib.sha256(oid(policy["_id"]).encode()).hexdigest()
    return ("EX" + policy["leave_code"] + suffix)[:10].upper()


def validate_definition(policy):
    if policy["status"] not in {"active", "inactive"}:
        raise ValueError("Unknown RABS source status")
    if policy["leave_type"] not in {"privilege", "casual", "lwp"}:
        raise ValueError("Unknown RABS leave kind")
    rules = policy["rules"]
    if (
        policy["annual_quota"] < 0
        or rules["min_days_per_application"] > rules["max_days_per_application"]
    ):
        raise ValueError("Invalid RABS entitlement/application limits")
    levels = policy["approval_workflow"]["levels"]
    if len(levels) > 3:
        raise ValueError("Too many source approval levels")


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
        raise ValueError("This import is restricted to the approved RABS tenant")
    tid = tenant["id"]
    await lock_resource(session, tid, "EXIM-rabs-leave-definitions")
    path = data_dir / "exim.leavepolicies.json"
    source = json.loads(path.read_text())
    selected = [p for p in source if oid(p["company_id"]) == RABS]
    if not selected or len({oid(p["_id"]) for p in selected}) != len(selected):
        raise ValueError("Require unique RABS policy definitions")
    for p in selected:
        validate_definition(p)
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    batch_id = uid(tid, "rabs-definitions-batch", "2026-10")
    batch = await session.get(ImportBatch, (tid, batch_id))
    if batch and batch.details["source_fingerprint"] != fingerprint:
        raise ValueError("Source export changed after the applied RABS import")
    stats = dict(
        tenant=tenant["slug"],
        created=Counter(),
        existing=Counter(),
        source_policy_count=len(selected),
        active_source_policies=sum(p["status"] == "active" for p in selected),
        inactive_source_policies=sum(p["status"] == "inactive" for p in selected),
        source_fingerprint=fingerprint,
        source_policy_records=selected,
        mappings=[],
        employee_assignments_created=0,
        balances_imported=0,
        assignment_basis=(
            "User requested definitions remain unassigned pending confirmed employee links"
        ),
        deduction_basis=(
            "Preserve RABS source settings, including deduct_from_salary=false on Unpaid Leave"
        ),
        balance_basis="Staff LeaveBalance export unavailable; annual quotas are not balances",
        rule_activation=(
            "Eligibility, sandwich and approver mapping require verification "
            "before employee activation"
        ),
    )
    codes = [type_code(p) for p in selected]
    if len(set(codes)) != len(codes):
        raise ValueError("Imported type code collision")
    for p in sorted(selected, key=lambda r: oid(r["_id"])):
        sid = oid(p["_id"])
        type_id, bucket_id = uid(tid, "rabs-type", sid), uid(tid, "rabs-bucket", sid)
        set_id = uid(tid, "rabs-definition", sid)
        active = p["status"] == "active"
        archived = None if active else stamp(p["updatedAt"])
        recorded = stamp(p["createdAt"])
        rules, carry = p["rules"], p["carry_forward"]
        name = rabs_policy_name(p)
        code = type_code(p)
        await add_once(
            session,
            LeaveBalanceBucket(
                tenant_id=tid,
                id=bucket_id,
                name=name,
                code=code,
                is_unlimited=p["leave_type"] == "lwp",
                is_active=active,
                archived_at=archived,
                recorded_at=recorded,
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
                days_per_year=p["annual_quota"],
                carry_forward=carry["allowed"],
                max_carry_forward_days=carry.get("max_days") if carry["allowed"] else None,
                requires_approval=not p["approval_workflow"]["auto_approve_if_balance"],
                approval_levels=max(1, len(p["approval_workflow"]["levels"])),
                min_days_per_application=rules["min_days_per_application"],
                max_days_per_application=rules["max_days_per_application"],
                advance_notice_days=rules["advance_notice_days"],
                requires_document=rules["requires_document"],
                is_paid=not p["deduction_rules"]["deduct_from_salary"],
                is_active=active,
                archived_at=archived,
                legacy_managed=True,
                encashable=carry["encashment_allowed"],
                accrual_enabled=False,
                recorded_at=recorded,
            ),
            stats,
        )
        await add_once(
            session,
            LeaveTypeBucketMapping(
                tenant_id=tid,
                id=uid(tid, "rabs-mapping", sid),
                leave_type_id=type_id,
                bucket_id=bucket_id,
                recorded_at=recorded,
            ),
            stats,
        )
        await add_once(
            session,
            LeavePolicySet(
                tenant_id=tid,
                id=set_id,
                name=name,
                description=(
                    "RABS source definition; unassigned until employee links "
                    "and rule activation are confirmed."
                ),
                is_default=False,
                archived_at=archived,
                recorded_at=recorded,
            ),
            stats,
        )
        await add_once(
            session,
            LeaveBucketPolicy(
                tenant_id=tid,
                id=uid(tid, "rabs-definition-bucket", sid),
                policy_set_id=set_id,
                bucket_id=bucket_id,
                recorded_at=recorded,
                **policy_fields(p),
            ),
            stats,
        )
        stats["mappings"].append(
            dict(
                source_policy_id=sid,
                source_name=p["policy_name"],
                source_code=p["leave_code"],
                status=p["status"],
                type_id=str(type_id),
                type_code=code,
                bucket_id=str(bucket_id),
                policy_set_id=str(set_id),
            )
        )
    return tid, batch_id, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default=TARGET_SLUG)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/rabs-leave-import.json"))
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
                                source_system="EXIM_RABS_LEAVE",
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
                        if k not in {"source_policy_records", "source_fingerprint", "mappings"}
                    },
                    indent=2,
                )
            )
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
