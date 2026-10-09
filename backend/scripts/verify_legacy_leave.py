"""Read-only independent verification of the applied Suraj leave import."""

import asyncio
import json
from uuid import UUID

from migrate_legacy_leave import ROOT, START, uid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.modules.leave.models import LeaveBucketPolicy
from hrms.modules.leave.policy_resolver import resolve_leave_policy_set


async def main():
    folder = ROOT / "backend/storage/migration-backups"
    before = json.loads((folder / "exim-leave-before.json").read_text())
    report = json.loads((folder / "exim-leave-applied.json").read_text())
    engine = create_async_engine(settings.database_url)
    tid = UUID("c15c4c84-4041-4f4e-ab1c-544a206bf7d4")
    result = {"tenant": "suraj-group", "existing_rows_unchanged": {}, "new_rows": {}}
    try:
        async with AsyncSession(engine) as session:
            for table, old_rows in before.items():
                current = [
                    dict(r)
                    for r in (
                        await session.execute(
                            text("SELECT * FROM " + table + " ORDER BY tenant_id,id")
                        )
                    ).mappings()
                ]
                current = json.loads(json.dumps(current, default=str))
                by_id = {(r["tenant_id"], r["id"]): r for r in current}
                for old in old_rows:
                    row = by_id[(old["tenant_id"], old["id"])]
                    assert all(row[k] == v for k, v in old.items()), (table, old["id"])
                old_ids = {(r["tenant_id"], r["id"]) for r in old_rows}
                added = [r for r in current if (r["tenant_id"], r["id"]) not in old_ids]
                assert all(r["tenant_id"] == str(tid) for r in added), "Another tenant changed"
                result["existing_rows_unchanged"][table] = len(old_rows)
                result["new_rows"][table] = len(added)
            for table in [
                "leave_monthly_ledger",
                "leave_balance_transactions",
                "leave_balances",
                "leave_applications",
            ]:
                assert result["new_rows"][table] == 0, table
            for original in report["source_policy_records"]:
                sid = original["_id"]["$oid"]
                bp = await session.get(LeaveBucketPolicy, (tid, uid(tid, "definition-bucket", sid)))
                assert bp.source_policy == original
            for employee in report["employees"]:
                eid = UUID(employee["employment_id"])
                pset = await resolve_leave_policy_set(session, tid, eid, START)
                assert str(pset.id) == employee["leave_policy_set_id"]
                rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT source_policy FROM leave_bucket_policies "
                            "WHERE tenant_id=:tid AND policy_set_id=:pid "
                            "AND source_policy IS NOT NULL"
                            ),
                            {"tid": tid, "pid": pset.id},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert (
                    sorted(r["_id"]["$oid"] for r in rows if r is not None)
                    == employee["source_policy_ids"]
                )
            result.update(
                exact_source_definitions_verified=len(report["source_policy_records"]),
                employee_assignments_verified=len(report["employees"]),
                privilege_leave_employees=report["employees_with_privilege_leave"],
                lwp_employees=len(report["employees"]),
                cross_company_references_reported=len(report["ignored_cross_company_references"]),
                rabs_unchanged=True,
                rerun_created_records=sum(
                    json.loads((folder / "exim-leave-rerun.json").read_text())["created"].values()
                ),
            )
        destination = ROOT / "docs/legacy-mongo-analysis/leave-migration-verification.json"
        destination.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
