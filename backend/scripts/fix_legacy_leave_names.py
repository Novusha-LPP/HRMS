"""Correct only imported leave names; dry-run unless --apply is specified.

Save all leave rows before applying and verify every other field is unchanged.
Employee assignments, balances, source policies, IDs and codes are preserved.
"""

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import UUID

from legacy_leave_names import (
    assigned_policy_name,
    definition_name,
    rabs_policy_name,
    suraj_type_name,
)
from migrate_legacy_leave import ROOT, oid, uid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.leave.models import LeavePolicySet


async def snapshot(session):
    tables = (
        (
            await session.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND (tablename LIKE 'leave_%' OR tablename='comp_off_grants') "
                    "ORDER BY tablename"
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        table: [
            dict(r)
            for r in (
                await session.execute(text(f'SELECT * FROM "{table}" ORDER BY tenant_id,id'))
            ).mappings()
        ]
        for table in tables
    }


async def name_plan(session):
    plan = {}

    def add(tid, table, row_id, name):
        key = (table, tid, row_id)
        if key in plan and plan[key] != name:
            raise ValueError("Inconsistent labels for a shared policy set")
        plan[key] = name

    companies = defaultdict(Counter)
    for user in json.loads((ROOT / "exim.users.json").read_text()):
        if user.get("company_id") and user.get("company"):
            companies[oid(user["company_id"])][user["company"].strip().casefold()] += 1

    tenants = (
        (
            await session.execute(
                text(
                    "SELECT id,slug FROM tenants WHERE slug IN "
                    "('suraj-group','rabs-industries-india-private-limited') ORDER BY slug"
                )
            )
        )
        .mappings()
        .all()
    )
    if len(tenants) != 2:
        raise ValueError("Both approved migration tenants are required")
    for tenant in tenants:
        tid = tenant["id"]
        suraj = tenant["slug"] == "suraj-group"
        await lock_resource(
            session, tid, "EXIM-leave-import" if suraj else "EXIM-rabs-leave-definitions"
        )
        bid = uid(tid, "batch" if suraj else "rabs-definitions-batch", "2026-10")
        batch = await session.get(ImportBatch, (tid, bid))
        if not batch:
            raise ValueError(f"Missing applied import for {tenant['slug']}")
        policies = {oid(p["_id"]): p for p in batch.details["source_policy_records"]}
        if suraj:
            for kind in ("privilege", "lwp"):
                for table, id_kind in (
                    ("leave_types", "type"),
                    ("leave_balance_buckets", "bucket"),
                ):
                    add(tid, table, uid(tid, id_kind, kind), suraj_type_name(kind))
            for sid, policy in policies.items():
                company = companies[oid(policy["company_id"])].most_common(1)[0][0]
                add(
                    tid,
                    "leave_policy_sets",
                    uid(tid, "definition", sid),
                    definition_name(policy, company),
                )
            for employee in batch.details["employees"]:
                pset_id = UUID(employee["leave_policy_set_id"])
                selected = [policies[sid] for sid in employee["source_policy_ids"]]
                if not selected:
                    raise ValueError("Cannot identify company for an empty imported policy set")
                company_id = oid(selected[0]["company_id"])
                if any(oid(p["company_id"]) != company_id for p in selected):
                    raise ValueError("Policies span multiple companies")
                company = companies[company_id].most_common(1)[0][0]
                native_id = employee["native_policy_set_id"]
                native = (
                    (await session.get(LeavePolicySet, (tid, UUID(native_id))))
                    if native_id
                    else None
                )
                employment_company = (
                    await session.execute(
                        text(
                            "SELECT le.name FROM employments e JOIN legal_entities le "
                            "ON le.tenant_id=e.tenant_id AND le.id=e.legal_entity_id "
                            "WHERE e.tenant_id=:tid AND e.id=CAST(:eid AS uuid)"
                        ),
                        {"tid": tid, "eid": employee["employment_id"]},
                    )
                ).scalar_one()
                add(
                    tid,
                    "leave_policy_sets",
                    pset_id,
                    assigned_policy_name(
                        company, selected, native.name if native else None, employment_company
                    ),
                )
        else:
            for sid, policy in policies.items():
                for table, id_kind in (
                    ("leave_types", "rabs-type"),
                    ("leave_balance_buckets", "rabs-bucket"),
                    ("leave_policy_sets", "rabs-definition"),
                ):
                    add(tid, table, uid(tid, id_kind, sid), rabs_policy_name(policy))
    return plan


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    folder = ROOT / "backend/storage/migration-backups"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    try:
        async with AsyncSession(engine) as session, session.begin():
            plan = await name_plan(session)
            before = await snapshot(session)
            changes = []
            expected = {table: [dict(r) for r in rows] for table, rows in before.items()}
            for (table, tid, row_id), name in plan.items():
                found = [r for r in expected[table] if r["tenant_id"] == tid and r["id"] == row_id]
                if len(found) != 1:
                    raise ValueError(f"Missing imported row: {table}/{row_id}")
                row = found[0]
                if row["name"] != name:
                    changes.append(
                        dict(
                            table=table,
                            tenant_id=str(tid),
                            id=str(row_id),
                            before=row["name"],
                            after=name,
                        )
                    )
                    row["name"] = name
            if args.apply and changes:
                backup = folder / f"before-leave-names-{stamp}.json"
                with backup.open("x") as file:
                    backup.chmod(0o600)
                    json.dump(before, file, indent=2, default=str)
            for change in changes:
                await session.execute(
                    text(
                        f'UPDATE "{change["table"]}" SET name=:name WHERE tenant_id=:tid AND id=:id'
                    ),
                    {
                        "name": change["after"],
                        "tid": UUID(change["tenant_id"]),
                        "id": UUID(change["id"]),
                    },
                )
            if await snapshot(session) != expected:
                raise ValueError("Leave data changed beyond the planned name correction")
            report = dict(
                mode="APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK",
                names_changed=len(changes),
                imported_rows_checked=len(plan),
                only_name_fields_changed=True,
                changes=changes,
            )
            if not args.apply:
                await session.rollback()
        output = folder / f"leave-names-{stamp}.json"
        output.write_text(json.dumps(report, indent=2) + "\n")
        output.chmod(0o600)
        print(json.dumps({k: v for k, v in report.items() if k != "changes"}))
        print(f"Report: {output}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
