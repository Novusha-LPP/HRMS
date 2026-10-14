"""
Count the rows that would break each constraint DB-1 adds, before it is added.

Read-only by construction: every statement runs in a READ ONLY transaction, so the script
cannot change data even by mistake. It prints counts, never names or values, so its output is
safe to share. Status-like columns can also be listed with --values (their distinct values and
counts; statuses are not personal data).

    python scripts/db_preflight.py            # one line per check: "<id>  <count>  <what>"
    python scripts/db_preflight.py --values   # distinct values of status-like columns
    python scripts/db_preflight.py --strict   # exit 1 if any check is above 0

Counts are taken tenant by tenant under row-level security, so any database login works.
docs/database-hardening-plan.md (W1) explains how the results decide the cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from hrms.db import conventions as cv

SYSTEM_ACCOUNT = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class Check:
    id: str
    what: str
    sql: str  # counts violating rows for the tenant in app.tenant_id


def _effective_range(table: str) -> Check:
    return Check(
        f"range:{table}",
        f"{table}: effective_to before effective_from",
        f"SELECT count(*) FROM {table} WHERE effective_to IS NOT NULL "
        "AND effective_to < effective_from",
    )


def _overlap(table: str, keys: list[str], where: str = "") -> Check:
    inclusive = table in cv.EFFECTIVE_END_INCLUSIVE
    bounds = "'[]'" if inclusive else "'[)'"
    period = (
        "daterange({a}.effective_from, COALESCE({a}.effective_to, '9999-12-31'), " + bounds + ")"
    )
    same = " AND ".join([f"a.{k} = b.{k}" for k in keys] or ["TRUE"])
    extra = f" AND {where.format(a='a')} AND {where.format(a='b')}" if where else ""
    return Check(
        f"overlap:{table}:{'+'.join(keys) or 'tenant-default'}",
        f"{table}: overlapping rows for the same {', '.join(keys) or 'tenant'}",
        f"SELECT count(*) FROM {table} a JOIN {table} b ON a.tenant_id = b.tenant_id "
        f"AND a.id < b.id AND {same} AND {period.format(a='a')} && {period.format(a='b')}"
        f"{extra}",
    )


def _duplicates(check_id: str, table: str, key: str, where: str = "TRUE") -> Check:
    return Check(
        f"duplicate:{check_id}",
        f"{table}: rows sharing {key}",
        f"SELECT COALESCE(sum(n - 1), 0) FROM (SELECT count(*) AS n FROM {table} "
        f"WHERE {where} GROUP BY {key} HAVING count(*) > 1) d",
    )


def _orphans(table: str, column: str, target: str) -> Check:
    system = f" AND x.{column} <> '{SYSTEM_ACCOUNT}'" if target == "user_accounts" else ""
    return Check(
        f"orphan:{table}.{column}",
        f"{table}.{column}: points at no {target} row",
        f"SELECT count(*) FROM {table} x WHERE x.{column} IS NOT NULL{system} "
        f"AND NOT EXISTS (SELECT 1 FROM {target} t WHERE t.tenant_id = x.tenant_id "
        f"AND t.id = x.{column})",
    )


STATIC_CHECKS: list[Check] = [
    # W2.2 one login per employee
    _duplicates(
        "login-per-employee", "user_accounts", "employment_id", "employment_id IS NOT NULL"
    ),
    # W2.4 the four references that get foreign keys
    _orphans("external_identities", "user_account_id", "user_accounts"),
    _orphans("onboarding_items", "integration_app_id", "connected_apps"),
    _orphans("integration_events", "employment_id", "employments"),
    _orphans("integration_events", "origin_app_id", "connected_apps"),
    # W2.6 business keys
    _duplicates("leave-type-code", "leave_types", "lower(code)", "archived_at IS NULL"),
    _duplicates("company-name", "legal_entities", "lower(name)", "archived_at IS NULL"),
    _duplicates("job-code", "jobs", "lower(code)", "archived_at IS NULL AND code IS NOT NULL"),
    _duplicates("grade-code", "grades", "lower(code)", "archived_at IS NULL"),
    _duplicates("cost-centre-code", "cost_centres", "lower(code)", "archived_at IS NULL"),
    _duplicates(
        "holiday",
        "holidays",
        "calendar_id, holiday_date, lower(name)",
        "archived_at IS NULL AND calendar_id IS NOT NULL",
    ),
    _duplicates("punch", "punches", "employment_id, punched_at, punch_type"),
    _duplicates(
        "punch-uncorrected",
        "punches",
        "employment_id, punched_at, punch_type",
        "NOT is_corrected",
    ),
    _duplicates("employee-number", "employments", "legal_entity_id, lower(employee_number)"),
    # W2.6: identical grants (same login, role and scope); migration 0064 merges these.
    _duplicates(
        "role-grant",
        "role_assignments",
        "user_account_id, role_id, scope_type, COALESCE(scope_value, '')",
    ),
    # W3.2 range and sanity rules
    Check(
        "range:leave_applications",
        "leave_applications: to_date before from_date, or days_requested below 0",
        "SELECT count(*) FROM leave_applications WHERE to_date < from_date OR days_requested < 0",
    ),
    Check(
        "range:approval_delegations",
        "approval_delegations: valid_until not after valid_from",
        "SELECT count(*) FROM approval_delegations WHERE valid_until <= valid_from",
    ),
    Check(
        "range:leave_balances",
        "leave_balances: allocated, used or pending below 0",
        "SELECT count(*) FROM leave_balances "
        "WHERE allocated_days < 0 OR used_days < 0 OR pending_days < 0",
    ),
    Check(
        "range:punch-coordinates",
        "punches: latitude or longitude out of range",
        "SELECT count(*) FROM punches WHERE latitude NOT BETWEEN -90 AND 90 "
        "OR longitude NOT BETWEEN -180 AND 180",
    ),
    Check(
        "range:fte",
        "assignments: fte not in (0, 1]",
        "SELECT count(*) FROM assignments WHERE fte <= 0 OR fte > 1",
    ),
    Check(
        "range:separation",
        "employments: separation_date before hire_date",
        "SELECT count(*) FROM employments WHERE separation_date < hire_date",
    ),
    # W3.3 no-overlap
    _overlap("assignment_managers", ["assignment_id", "manager_type"]),
    *[
        _duplicates(
            f"same-start:{t}:{scope}",
            t,
            f"{scope}, effective_from",
            f"{scope} IS NOT NULL AND archived_at IS NULL",
        )
        for t in ("employee_policy_assignments", "leave_policy_assignments")
        for scope in ("employment_id", "org_unit_id", "legal_entity_id")
    ],
    *[
        _overlap(
            "holiday_calendar_assignments",
            [scope],
            f"{{a}}.{scope} IS NOT NULL AND {{a}}.archived_at IS NULL",
        )
        for scope in ("employment_id", "org_unit_id", "legal_entity_id")
    ],
    _overlap(
        "holiday_calendar_assignments",
        [],
        "{a}.employment_id IS NULL AND {a}.org_unit_id IS NULL "
        "AND {a}.legal_entity_id IS NULL AND {a}.archived_at IS NULL",
    ),
    # W3.4 required work date
    Check(
        "required:punches.work_date",
        "punches: no work_date",
        "SELECT count(*) FROM punches WHERE work_date IS NULL",
    ),
]


async def _dynamic_checks(conn: AsyncConnection) -> list[Check]:
    """Checks derived from the catalog and the registry, so they follow the schema."""
    checks: list[Check] = []
    columns = (
        await conn.execute(
            text(
                """
                SELECT c.table_name, c.column_name, c.data_type
                FROM information_schema.columns c
                JOIN pg_class t ON t.relname = c.table_name
                     AND t.relnamespace = 'public'::regnamespace AND NOT t.relispartition
                WHERE c.table_schema = 'public'
                """
            )
        )
    ).all()
    by_table: dict[str, dict[str, str]] = {}
    for table, column, dtype in columns:
        by_table.setdefault(table, {})[column] = dtype
    tenant_tables = {t for t, cols in by_table.items() if "tenant_id" in cols} - cv.GLOBAL_TABLES
    # W2.3 actor columns: a login, except three that record the acting employee
    employee_actors = {
        ("attendance_days", "ot_reviewed_by"),
        ("comp_off_grants", "granted_by"),
        ("leave_encashments", "processed_by"),
    }
    for table in sorted(tenant_tables):
        for column, dtype in sorted(by_table[table].items()):
            if dtype == "uuid" and column.endswith("_by"):
                target = "employments" if (table, column) in employee_actors else "user_accounts"
                checks.append(_orphans(table, column, target))
    # W3.1 allowed values
    for key, enum_path in sorted(cv.DOMAINS.items()):
        table, column = key.split(".")
        if column not in by_table.get(table, {}):
            continue
        listed = ", ".join("'" + v.replace("'", "''") + "'" for v in cv.enum_values(enum_path))
        checks.append(
            Check(
                f"domain:{key}",
                f"{key}: a value outside {cv.domain_name(enum_path)}",
                f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL "
                f"AND {column}::text NOT IN ({listed})",
            )
        )
    # W3.2 effective ranges
    for table in sorted(tenant_tables):
        if {"effective_from", "effective_to"} <= by_table[table].keys():
            checks.append(_effective_range(table))
    # W4.1 half days: what people enter or configure (history keeps its exact values)
    entered = {
        ("leave_applications", "days_requested"),
        ("leave_encashments", "days"),
        ("comp_off_grants", "days_granted"),
        ("attendance_days", "comp_off_days"),
        ("leave_types", "days_per_year"),
        ("leave_types", "min_days_per_application"),
        ("leave_types", "max_days_per_application"),
        ("leave_types", "max_carry_forward_days"),
        ("leave_bucket_policies", "days_per_year"),
        ("leave_bucket_policies", "max_carry_forward_days"),
        ("leave_bucket_policies", "max_encashment_days"),
    }
    for table in sorted(tenant_tables):
        for column in sorted(by_table[table]):
            if (table, column) in entered:
                checks.append(
                    Check(
                        f"half-day:{table}.{column}",
                        f"{table}.{column}: not a whole or half day",
                        f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL "
                        f"AND abs({column} * 2 - round({column} * 2)) > 1e-9",
                    )
                )
    return checks


async def _global_email_clashes(conn: AsyncConnection, tenants: list[str]) -> int:
    """Emails used by more than one account across all tenants (login is global)."""
    seen: Counter[str] = Counter()
    for tid in tenants:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})
        rows = await conn.execute(
            text("SELECT lower(email) FROM user_accounts WHERE tenant_id = CAST(:tid AS uuid) "
                 "AND email IS NOT NULL"), {"tid": tid}
        )
        seen.update(r[0] for r in rows)
    return sum(n - 1 for n in seen.values() if n > 1)


async def _values(conn: AsyncConnection, tenants: list[str]) -> None:
    pattern = re.compile(
        r"(^|_)(status|state|type|kind|source|outcome|action|unit|mode|gender|category|stage|"
        r"decision|priority|frequency|basis|method)$"
    )
    columns = (
        await conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type IN ('character varying', 'text') "
                "ORDER BY 1, 2"
            )
        )
    ).all()
    for table, column in columns:
        key = f"{table}.{column}"
        if not pattern.search(column) or key in cv.DOMAIN_EXEMPT:
            continue
        counts: Counter[str] = Counter()
        tenant_scoped = table not in cv.GLOBAL_TABLES
        for tid in tenants if tenant_scoped else [None]:
            if tid:
                await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})
            rows = await conn.execute(
                text(f"SELECT {column}::text, count(*) FROM {table} GROUP BY 1")
            )
            counts.update({(v if v is not None else "<null>"): n for v, n in rows})
        listed = ", ".join(f"{v}={n}" for v, n in sorted(counts.items()))
        print(f"{key}: {listed or '(no rows)'}")


async def run(url: str, values: bool) -> dict[str, int]:
    engine = create_async_engine(url)
    results: dict[str, int] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            if (await conn.scalar(text("SHOW transaction_read_only"))) != "on":
                raise SystemExit("refusing to run: the transaction is not read-only")
            tenants = [
                str(t) for t in (await conn.execute(text("SELECT id FROM tenants"))).scalars()
            ]
            if values:
                await _values(conn, tenants)
                return {}
            checks = STATIC_CHECKS + await _dynamic_checks(conn)
            for check in checks:
                total = 0
                for tid in tenants:
                    await conn.execute(
                        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid}
                    )
                    total += int(await conn.scalar(text(check.sql)) or 0)
                results[check.id] = total
                print(f"{check.id:<70} {total:>8}  {check.what}")
            clashes = await _global_email_clashes(conn, tenants)
            results["duplicate:email-across-tenants"] = clashes
            print(f"{'duplicate:email-across-tenants':<70} {clashes:>8}  login emails used twice")
            await conn.rollback()
    finally:
        await engine.dispose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--values", action="store_true", help="list status-like column values")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any count is above 0")
    args = parser.parse_args()
    url = os.environ.get("HRMS_DATABASE_URL")
    if not url:
        raise SystemExit("Set HRMS_DATABASE_URL")
    results = asyncio.run(run(url, args.values))
    failing = {k: v for k, v in results.items() if v}
    if results:
        print(f"-- {len(results)} checks, {len(failing)} with violations")
    if args.strict and failing:
        sys.exit(1)


if __name__ == "__main__":
    main()
