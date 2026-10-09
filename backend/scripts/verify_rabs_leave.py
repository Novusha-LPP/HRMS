"""Read-only verification of RABS definitions and preserved existing leave data."""

import asyncio
import hashlib
import json

from migrate_rabs_leave import RABS, ROOT, TARGET_SLUG, uid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveBucketPolicy,
    LeavePolicySet,
    LeaveType,
)


async def main():
    folder = ROOT / "backend/storage/migration-backups"
    before = json.loads((folder / "rabs-leave-before.json").read_text())
    applied = json.loads((folder / "rabs-leave-applied.json").read_text())
    source_path = ROOT / "exim.leavepolicies.json"
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == applied["source_fingerprint"]
    source = [p for p in json.loads(source_path.read_text()) if p["company_id"]["$oid"] == RABS]
    result = {"tenant": TARGET_SLUG, "existing_rows_unchanged": {}, "new_rows": {}}
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine) as session:
            tid = (
                await session.execute(
                    text("SELECT id FROM tenants WHERE slug=:slug"), {"slug": TARGET_SLUG}
                )
            ).scalar_one()
            for table, original in before.items():
                rows = [
                    dict(r)
                    for r in (
                        await session.execute(
                            text("SELECT * FROM " + table + " ORDER BY tenant_id,id")
                        )
                    ).mappings()
                ]
                rows = json.loads(json.dumps(rows, default=str))
                current = {(r["tenant_id"], r["id"]): r for r in rows}
                keys = set()
                for row in original:
                    key = (row["tenant_id"], row["id"])
                    keys.add(key)
                    assert current[key] == row, (table, row["id"])
                added = [r for r in rows if (r["tenant_id"], r["id"]) not in keys]
                assert all(r["tenant_id"] == str(tid) for r in added), "Another tenant changed"
                result["existing_rows_unchanged"][table] = len(original)
                result["new_rows"][table] = len(added)
            for table in [
                "leave_policy_assignments",
                "leave_monthly_ledger",
                "leave_balance_transactions",
                "leave_balances",
                "leave_applications",
            ]:
                assert result["new_rows"][table] == 0
            codes, active_pl_ids = set(), []
            for p in source:
                sid = p["_id"]["$oid"]
                lt = await session.get(LeaveType, (tid, uid(tid, "rabs-type", sid)))
                bucket = await session.get(LeaveBalanceBucket, (tid, uid(tid, "rabs-bucket", sid)))
                bp = await session.get(
                    LeaveBucketPolicy, (tid, uid(tid, "rabs-definition-bucket", sid))
                )
                pset = await session.get(LeavePolicySet, (tid, uid(tid, "rabs-definition", sid)))
                assert bp.source_policy == p
                assert lt.is_paid == (not p["deduction_rules"]["deduct_from_salary"])
                assert lt.days_per_year == bp.days_per_year == p["annual_quota"]
                assert bucket.is_unlimited == (p["leave_type"] == "lwp")
                assert lt.is_active == bucket.is_active == (p["status"] == "active")
                assert bool(lt.archived_at) == bool(pset.archived_at) == (p["status"] == "inactive")
                assert not pset.is_default and not lt.accrual_enabled
                codes.add(lt.code)
                if p["status"] == "active" and p["leave_code"] == "PL":
                    active_pl_ids.append((str(lt.id), str(bucket.id), p["annual_quota"]))
            assert len(codes) == len(source)
            assert len({row[0] for row in active_pl_ids}) == 2
            assert len({row[1] for row in active_pl_ids}) == 2
            result.update(
                exact_source_definitions_verified=len(source),
                active_source_policies=sum(p["status"] == "active" for p in source),
                archived_source_policies=sum(p["status"] == "inactive" for p in source),
                active_pl_entitlements=sorted(row[2] for row in active_pl_ids),
                deduction_flags_preserved=True,
                employee_assignments_created=0,
                suraj_unchanged=True,
                rerun_created_records=sum(
                    json.loads((folder / "rabs-leave-rerun.json").read_text())["created"].values()
                ),
            )
        output = ROOT / "docs/legacy-mongo-analysis/rabs-leave-verification.json"
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
