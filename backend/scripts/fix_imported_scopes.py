"""
Repair access on accounts created by the first version of scripts/migrate_tenants.py.

That version gave EVERY imported account a company-wide (LEGAL_ENTITY) scope, so an
ordinary employee could list and report on the whole company, and a manager could read
every employee's records rather than their own reports'. It also did not set the
"must change password" flag the Sharanga initial-password scheme depends on.

This changes ONLY those defects, and ONLY on accounts the import created
(user_accounts.erp_system IS NOT NULL):

  1. EMPLOYEE role assigned with any scope wider than SELF          -> SELF
  2. MANAGER role assigned LEGAL_ENTITY scope for exactly the company their own employment
     belongs to (the pattern the import produced; a manager somebody deliberately widened
     to other companies is left alone)                               -> DIRECT_REPORTS
  3. Sharanga accounts that never changed their password and aren't yet flagged
                                                                     -> must_change_password

Nothing else is touched: no passwords, no statuses, no HR/accountant/admin assignments.
SUPER_ADMIN accounts the import created are listed for you to review, not changed.

Dry-run by default — it prints exactly what it would do:
    uv run python scripts/fix_imported_scopes.py
    uv run python scripts/fix_imported_scopes.py --apply
    uv run python scripts/fix_imported_scopes.py --apply --tenant <slug-or-uuid>

Runs as the database owner (settings.database_url), all in one transaction.
"""

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.authz import decode_scope_ids
from hrms.core.config import settings


async def find_changes(session, tenant_filter: str | None) -> dict:
    where, params = "", {}
    if tenant_filter:
        try:
            UUID(tenant_filter)
            where, params = "AND t.id = CAST(:tf AS uuid)", {"tf": tenant_filter}
        except ValueError:
            where, params = "AND t.slug = :tf", {"tf": tenant_filter}

    rows = (
        (
            await session.execute(
                text(f"""
                SELECT t.display_name AS tenant, ua.tenant_id, ua.id AS account_id,
                       COALESCE(ua.employee_code, ua.email) AS who, ua.erp_system,
                       ua.employment_id, ra.id AS assignment_id, ra.scope_type, ra.scope_value,
                       r.name AS role_name, e.legal_entity_id AS own_entity
                FROM user_accounts ua
                JOIN tenants t ON t.id = ua.tenant_id
                JOIN role_assignments ra
                  ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
                JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                WHERE ua.erp_system IS NOT NULL {where}
                ORDER BY t.display_name, who
            """),
                params,
            )
        )
        .mappings()
        .all()
    )

    changes = {"to_self": [], "to_direct_reports": [], "review_admins": [], "left_alone": []}
    for r in rows:
        if r["role_name"] == "EMPLOYEE" and r["scope_type"] != "SELF":
            if r["employment_id"]:
                changes["to_self"].append(r)
            else:
                changes["left_alone"].append((r, "EMPLOYEE account with no employment record"))
        elif r["role_name"] == "MANAGER" and r["scope_type"] == "LEGAL_ENTITY":
            if r["employment_id"] and decode_scope_ids(r["scope_value"]) == {r["own_entity"]}:
                changes["to_direct_reports"].append(r)
            else:
                changes["left_alone"].append(
                    (r, "MANAGER scope isn't just their own company — looks deliberate")
                )
        elif r["role_name"] == "SUPER_ADMIN":
            changes["review_admins"].append(r)

    changes["force_password_change"] = (
        (
            await session.execute(
                text(f"""
                SELECT t.display_name AS tenant, ua.tenant_id, ua.id AS account_id,
                       COALESCE(ua.employee_code, ua.email) AS who
                FROM user_accounts ua JOIN tenants t ON t.id = ua.tenant_id
                WHERE ua.erp_system = 'SHARANGA' AND ua.password_changed_at IS NULL
                  AND ua.must_change_password = false {where}
                ORDER BY t.display_name, who
            """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return changes


def report(changes: dict) -> None:
    def block(title, rows, key="who"):
        print(f"\n{title}: {len(rows)}")
        for r in rows[:8]:
            print(f"   - {r['tenant']}: {r[key]}")
        if len(rows) > 8:
            print(f"   ... and {len(rows) - 8} more")

    block("EMPLOYEE accounts to narrow to SELF", changes["to_self"])
    block("MANAGER accounts to narrow to DIRECT_REPORTS", changes["to_direct_reports"])
    block("Sharanga accounts to flag 'must change password'", changes["force_password_change"])
    print(
        f"\nSUPER_ADMIN accounts from the import (NOT changed — please review): "
        f"{len(changes['review_admins'])}"
    )
    for r in changes["review_admins"]:
        print(f"   - {r['tenant']}: {r['who']}")
    if changes["left_alone"]:
        print(f"\nLeft alone on purpose: {len(changes['left_alone'])}")
        for r, why in changes["left_alone"][:8]:
            print(f"   - {r['tenant']}: {r['who']} — {why}")


async def apply(session, changes: dict) -> None:
    for r in changes["to_self"]:
        await session.execute(
            text("""
                UPDATE role_assignments SET scope_type = 'SELF', scope_value = NULL
                WHERE tenant_id = :t AND id = :i
            """),
            {"t": r["tenant_id"], "i": r["assignment_id"]},
        )
    for r in changes["to_direct_reports"]:
        await session.execute(
            text("""
                UPDATE role_assignments SET scope_type = 'DIRECT_REPORTS', scope_value = NULL
                WHERE tenant_id = :t AND id = :i
            """),
            {"t": r["tenant_id"], "i": r["assignment_id"]},
        )
    for r in changes["force_password_change"]:
        await session.execute(
            text("""
                UPDATE user_accounts SET must_change_password = true
                WHERE tenant_id = :t AND id = :i
            """),
            {"t": r["tenant_id"], "i": r["account_id"]},
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--apply", action="store_true", help="Make the changes (default: report only)"
    )
    parser.add_argument("--tenant", help="Limit to one tenant (UUID or slug)")
    args = parser.parse_args()

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session, session.begin():
        changes = await find_changes(session, args.tenant)
        report(changes)
        total = (
            len(changes["to_self"])
            + len(changes["to_direct_reports"])
            + len(changes["force_password_change"])
        )
        if not args.apply:
            print(f"\nDRY RUN — {total} change(s) would be made. Re-run with --apply.")
        else:
            await apply(session, changes)
            print(f"\nApplied {total} change(s).")
            print(json.dumps({k: len(v) for k, v in changes.items()}))
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
