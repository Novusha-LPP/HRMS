"""
Write docs/architecture/schema.md: the database as Mermaid entity-relationship diagrams, one per
area, plus every table's comment. Generated from the live catalog of a migrated database, so it
is never out of date by hand; tests/test_schema_diagram.py fails when the committed file differs.

    python scripts/schema_diagram.py            # rewrite docs/architecture/schema.md
    python scripts/schema_diagram.py --check    # exit 1 if it would change

It reads the database HRMS_DATABASE_URL points at. Use a private database migrated to head.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "schema.md"

# Which diagram a table belongs to. A table not listed here appears under "Other" until it is.
AREAS: dict[str, tuple[str, ...]] = {
    "Platform and access": (
        "tenants",
        "platform_admins",
        "platform_audit_log",
        "platform_password_reset_tokens",
        "user_accounts",
        "roles",
        "role_assignments",
        "user_preferences",
        "dashboard_layouts",
        "auth_throttle",
    ),
    "Organisation": (
        "legal_entities",
        "locations",
        "org_units",
        "jobs",
        "grades",
        "cost_centres",
        "positions",
        "employee_id_schemes",
    ),
    "People": (
        "persons",
        "employments",
        "assignments",
        "assignment_managers",
        "personnel_actions",
        "employee_kyc_records",
        "employee_kyc_documents",
        "kyc_access_log",
    ),
    "Onboarding": (
        "onboarding_templates",
        "onboarding_template_items",
        "onboarding_cases",
        "onboarding_items",
    ),
    "Time and attendance": (
        "policy_templates",
        "employee_policy_assignments",
        "punches",
        "attendance_days",
        "attendance_correction_requests",
        "correction_approval_actions",
        "holidays",
        "holiday_calendars",
        "holiday_calendar_days",
        "holiday_calendar_assignments",
        "comp_off_grants",
    ),
    "Leave": (
        "leave_types",
        "leave_balance_buckets",
        "leave_type_bucket_mapping",
        "leave_policy_sets",
        "leave_bucket_policies",
        "leave_policy_assignments",
        "leave_balances",
        "leave_monthly_ledger",
        "leave_balance_transactions",
        "leave_applications",
        "leave_approval_actions",
        "leave_encashments",
    ),
    "Approvals": (
        "approval_flows",
        "employee_approval_flows",
        "approval_instances",
        "approval_delegations",
        "approval_events",
    ),
    "Recruitment": (
        "recruitment_stages",
        "job_openings",
        "candidates",
        "job_applications",
        "recruitment_events",
    ),
    "Payroll": (
        "statutory_rules",
        "pay_components",
        "salary_structures",
        "salary_structure_lines",
        "employee_compensations",
    ),
    "Integrations": (
        "connected_apps",
        "api_keys",
        "external_identities",
        "integration_mappings",
        "integration_profiles",
        "integration_requests",
        "integration_events",
        "integration_app_events",
        "integration_cursors",
        "integration_rate_windows",
        "possible_duplicates",
        "import_batches",
    ),
    "Reports, history and jobs": (
        "report_definitions",
        "daily_report_snapshots",
        "daily_report_rows",
        "entity_change_log",
        "job_runs",
        "tenant_job_checkpoints",
    ),
}


async def _catalog(conn: AsyncConnection):
    tables = {
        r.name: r.comment or ""
        for r in await conn.execute(
            text("""
                SELECT c.relname AS name, obj_description(c.oid) AS comment
                FROM pg_class c
                WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
                  AND NOT c.relispartition AND c.relname <> 'alembic_version'
            """)
        )
    }
    columns: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in await conn.execute(
        text("""
            SELECT table_name, column_name, udt_name FROM information_schema.columns
            WHERE table_schema = 'public' ORDER BY table_name, ordinal_position
        """)
    ):
        columns[r.table_name].append((r.column_name, r.udt_name))
    keys = await conn.execute(
        text("""
            SELECT k.contype::text AS type, rel.relname AS tbl, ref.relname AS ref,
                   ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n
                         ORDER BY u.i) AS cols
            FROM pg_constraint k
            JOIN pg_class rel ON rel.oid = k.conrelid
            LEFT JOIN pg_class ref ON ref.oid = k.confrelid
            WHERE k.connamespace = 'public'::regnamespace AND k.contype IN ('p', 'f')
              AND NOT rel.relispartition
        """)
    )
    primary: dict[str, set[str]] = defaultdict(set)
    references: list[tuple[str, str, str]] = []  # (table, column, referenced table)
    for k in keys:
        if k.type == "p":
            primary[k.tbl].update(k.cols)
        elif k.ref != "tenants":
            column = next(c for c in reversed(k.cols) if c != "tenant_id")
            references.append((k.tbl, column, k.ref))
    return tables, columns, primary, sorted(set(references))


def render(tables, columns, primary, references) -> str:
    area_of = {t: area for area, members in AREAS.items() for t in members}
    areas = list(AREAS) + ["Other"]
    members: dict[str, list[str]] = {
        area: sorted(t for t in tables if area_of.get(t, "Other") == area) for area in areas
    }
    out = [
        "# Database schema",
        "",
        "Generated by `backend/scripts/schema_diagram.py` from a database migrated to head — "
        "don't edit by hand; `tests/test_schema_diagram.py` fails when this file is stale.",
        "",
        "Every tenant table also references `tenants(id)` through `tenant_id`, and every "
        "reference between tenant tables includes `tenant_id` (rule L3). Those lines are left "
        "out to keep the diagrams readable, as are the lines of the who-did-it columns "
        "(`*_by`, referencing `user_accounts` or `employments`), which are still marked FK. "
        "Each diagram shows its area's tables with their keys; a table from another area "
        "appears through its relationship lines only.",
        "",
    ]
    for area in areas:
        own = members[area]
        if not own:
            continue
        own_set = set(own)
        edges = [
            r
            for r in references
            if (r[0] in own_set or r[2] in own_set) and not r[1].endswith("_by")
        ]
        out += [f"## {area}", "", "```mermaid", "erDiagram"]
        for table in own:
            fk_cols = {c for t, c, _ in references if t == table}
            lines = []
            for column, udt in columns[table]:
                marks = []
                if column in primary[table]:
                    marks.append("PK")
                if column in fk_cols:
                    marks.append("FK")
                if marks:
                    lines.append(f"        {udt} {column} {','.join(marks)}")
            out += [f"    {table} {{", *lines, "    }"]
        for table, column, ref in edges:
            out.append(f"    {ref} ||--o{{ {table} : {column}")
        out += ["```", ""]
    out += ["## Tables", "", "| Table | Area | What it holds |", "|---|---|---|"]
    for table in sorted(tables):
        comment = tables[table].replace("|", "\\|").replace("\n", " ")
        out.append(f"| `{table}` | {area_of.get(table, 'Other')} | {comment} |")
    return "\n".join(out) + "\n"


async def generate(url: str) -> str:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return render(*(await _catalog(conn)))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    args = parser.parse_args()
    content = asyncio.run(generate(os.environ["HRMS_DATABASE_URL"]))
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    if args.check:
        sys.exit(0 if current == content else 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
