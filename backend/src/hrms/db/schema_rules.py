"""
Check the live schema against docs/database-conventions.md and list every violation.

Each violation is one stable line, "<rule> <what> <where>", with no OIDs or counts, so a sorted
list can be kept in tests/schema_baseline.txt and diffed in review. The test
(tests/test_schema_conventions.py) fails when a violation appears that the baseline doesn't
list, and also when the baseline lists one that is gone — fixed debt must be deleted from it.

    python -m hrms.db.schema_rules                 # print current violations
    python -m hrms.db.schema_rules --write FILE    # rewrite the baseline (review the diff!)

It reads the database HRMS_DATABASE_URL points at. Use a private, migrated database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from hrms.db import conventions as cv

STANDARD_POLICY = "(tenant_id = current_tenant_id())"
APP_ROLE = "hrms_app"
# Columns that look like they hold one of a closed set of values.
DOMAIN_LIKE = re.compile(
    r"(^|_)(status|state|type|kind|source|outcome|action|unit|mode|gender|category|stage|"
    r"decision|priority|frequency|basis|method)$"
)


async def _rows(conn: AsyncConnection, sql: str, **params):
    return (await conn.execute(text(sql), params)).mappings().all()


async def collect(conn: AsyncConnection) -> list[str]:
    """Every violation in the database `conn` is connected to, sorted."""
    out: set[str] = set()

    tables = {
        r["name"]: r
        for r in await _rows(
            conn,
            """
            SELECT c.relname AS name, c.oid, c.relrowsecurity AS rls,
                   c.relforcerowsecurity AS forced, obj_description(c.oid) AS comment
            FROM pg_class c
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
              AND NOT c.relispartition
            """,
        )
    }
    columns: dict[str, dict[str, str]] = defaultdict(dict)
    for r in await _rows(
        conn,
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema = 'public'
        """,
    ):
        columns[r["table_name"]][r["column_name"]] = r["data_type"]
    tenant_tables = {t for t in tables if "tenant_id" in columns[t] and t not in cv.GLOBAL_TABLES}

    constraints = await _rows(
        conn,
        """
        SELECT k.conname AS name, k.contype::text AS type, rel.relname AS tbl,
               ref.relname AS ref, k.confdeltype::text AS on_delete, k.convalidated AS valid,
               pg_get_constraintdef(k.oid) AS def,
               ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, i)
                     JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n
                     ORDER BY u.i) AS cols,
               ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(n, i)
                     JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.n
                     ORDER BY u.i) AS ref_cols
        FROM pg_constraint k
        JOIN pg_class rel ON rel.oid = k.conrelid
        LEFT JOIN pg_class ref ON ref.oid = k.confrelid
        WHERE k.connamespace = 'public'::regnamespace AND NOT rel.relispartition
        """,
    )
    by_table = defaultdict(list)
    for k in constraints:
        by_table[k["tbl"]].append(k)
    fks = [k for k in constraints if k["type"] == "f"]

    indexes = await _rows(
        conn,
        """
        SELECT ic.relname AS name, c.relname AS tbl, i.indisunique AS is_unique,
               i.indisprimary AS is_primary, i.indisvalid AS valid, am.amname AS method,
               i.indpred IS NOT NULL AS partial, i.indexprs IS NOT NULL AS has_expr,
               pg_get_expr(i.indpred, i.indrelid) AS predicate, i.indnkeyatts AS nkeys,
               ARRAY(SELECT COALESCE(a.attname, '<expr>')
                     FROM unnest(i.indkey::int2[]) WITH ORDINALITY u(n, pos)
                     LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = u.n
                     ORDER BY u.pos) AS cols
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_am am ON am.oid = ic.relam
        WHERE c.relnamespace = 'public'::regnamespace AND NOT c.relispartition
        """,
    )
    idx_by_table = defaultdict(list)
    for i in indexes:
        idx_by_table[i["tbl"]].append(i)

    # L1 · primary keys
    for t in tables:
        pk = next((k for k in by_table[t] if k["type"] == "p"), None)
        if pk is None:
            out.add(f"L1 no-primary-key {t}")
        elif t in tenant_tables and pk["cols"][0] != "tenant_id":
            out.add(f"L1 pk-not-tenant-first {t}")

    # L2 · tenancy: every non-global table is tenant-scoped, references tenants, and has RLS
    policies = defaultdict(list)
    for p in await _rows(
        conn,
        """
        SELECT c.relname AS tbl, p.polname AS name, p.polcmd::text AS cmd,
               p.polpermissive AS permissive,
               pg_get_expr(p.polqual, p.polrelid) AS qual,
               pg_get_expr(p.polwithcheck, p.polrelid) AS with_check
        FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
        WHERE c.relnamespace = 'public'::regnamespace
        """,
    ):
        policies[p["tbl"]].append(p)
    for t in tables:
        if t not in cv.GLOBAL_TABLES and t not in tenant_tables:
            out.add(f"L2 not-tenant-scoped {t}")
    for t in tenant_tables:
        if not any(
            k["type"] == "f" and k["ref"] == "tenants" and k["cols"] == ["tenant_id"]
            for k in by_table[t]
        ):
            out.add(f"L2 no-tenant-fk {t}")
        if not tables[t]["rls"]:
            out.add(f"L2 rls-disabled {t}")
        if not tables[t]["forced"]:
            out.add(f"L2 rls-not-forced {t}")
        pol = policies[t]
        standard = (
            len(pol) == 1
            and pol[0]["cmd"] == "*"
            and pol[0]["permissive"]
            and pol[0]["qual"] == STANDARD_POLICY
            and pol[0]["with_check"] in (None, STANDARD_POLICY)
        )
        if not standard:
            out.add(f"L2 non-standard-policy {t}")

    # L3 · references keep tenants apart; only TENANT_CASCADE tables cascade from tenants
    for k in fks:
        if k["tbl"] in tenant_tables and k["ref"] in tenant_tables:
            cols, ref_cols = k["cols"], k["ref_cols"]
            if "tenant_id" not in cols or ref_cols[cols.index("tenant_id")] != "tenant_id":
                out.add(f"L3 cross-tenant-reference {k['tbl']} {k['name']}")
        if k["ref"] == "tenants" and k["on_delete"] == "c" and k["tbl"] not in cv.TENANT_CASCADE:
            out.add(f"L3 unlisted-tenant-cascade {k['tbl']}")
    for t in cv.TENANT_CASCADE:
        if not any(k["ref"] == "tenants" and k["on_delete"] == "c" for k in by_table[t]):
            out.add(f"L0 stale TENANT_CASCADE {t}")

    # L4 · every *_id / *_by uuid column is a real reference, or a declared soft one
    fk_columns = {(k["tbl"], c) for k in fks for c in k["cols"]}
    for t, cols in columns.items():
        if t not in tables:
            continue
        for c, dtype in cols.items():
            if dtype != "uuid" or c in ("id", "tenant_id") or not re.search(r"_(id|by)$", c):
                continue
            key = f"{t}.{c}"
            if (t, c) not in fk_columns and key not in cv.SOFT_REFERENCES:
                out.add(f"L4 unreferenced {key}")
    for key in cv.SOFT_REFERENCES:
        t, c = key.split(".")
        if c not in columns.get(t, {}):
            out.add(f"L0 stale SOFT_REFERENCES {key}")
        elif (t, c) in fk_columns:
            out.add(f"L0 stale SOFT_REFERENCES {key} (now has a foreign key)")

    # L5 · every foreign key has an index led by its columns
    def indexed(table: str, fk_cols: list[str]) -> bool:
        n = len(fk_cols)
        return any(
            i["nkeys"] >= n and set(i["cols"][:n]) == set(fk_cols) for i in idx_by_table[table]
        )

    for k in fks:
        key = f"{k['tbl']}.{k['name']}"
        if not indexed(k["tbl"], k["cols"]) and key not in cv.UNINDEXED_FK_OK:
            out.add(f"L5 unindexed-fk {k['tbl']} {k['name']}")
    fk_keys = {f"{k['tbl']}.{k['name']}": k for k in fks}
    for key in cv.UNINDEXED_FK_OK:
        k = fk_keys.get(key)
        if k is None or indexed(k["tbl"], k["cols"]):
            out.add(f"L0 stale UNINDEXED_FK_OK {key}")

    # L6 · exact numbers only
    for t, cols in columns.items():
        for c, dtype in cols.items():
            if t in tables and dtype in ("real", "double precision"):
                out.add(f"L6 float {t}.{c}")

    # L7 · closed sets of values: the CHECK allows exactly the enum's values
    for t, cols in columns.items():
        for c, dtype in cols.items():
            key = f"{t}.{c}"
            if (
                t in tables
                and dtype in ("character varying", "text")
                and DOMAIN_LIKE.search(c)
                and key not in cv.DOMAINS
                and key not in cv.DOMAIN_EXEMPT
            ):
                out.add(f"L7 no-domain {key}")
    for key, enum_path in cv.DOMAINS.items():
        t, c = key.split(".")
        if c not in columns.get(t, {}):
            out.add(f"L0 stale DOMAINS {key}")
            continue
        allowed = _check_values(by_table[t], c)
        if allowed is None:
            out.add(f"L7 no-check {key}")
            continue
        expected = set(cv.enum_values(enum_path))
        if allowed != expected:
            extra, missing = sorted(allowed - expected), sorted(expected - allowed)
            out.add(f"L7 check-differs-from-enum {key} db-only={extra} enum-only={missing}")
    for key in cv.DOMAIN_EXEMPT:
        t, c = key.split(".")
        if c not in columns.get(t, {}):
            out.add(f"L0 stale DOMAIN_EXEMPT {key}")

    # L8 · effective dating: range check, declared end semantics, matching no-overlap guard
    for t, cols in columns.items():
        if t not in tables or not {"effective_from", "effective_to"} <= cols.keys():
            continue
        checks = [k["def"] for k in by_table[t] if k["type"] == "c"]
        exclusions = [k["def"] for k in by_table[t] if k["type"] == "x"]
        exempt = t in cv.NO_OVERLAP_EXEMPT
        exclusive = t in cv.EFFECTIVE_END_EXCLUSIVE
        inclusive = t in cv.EFFECTIVE_END_INCLUSIVE
        range_checks = [d for d in checks if "effective_to" in d and "effective_from" in d]
        if not range_checks:
            out.add(f"L8 no-range-check {t}")
        elif inclusive and not any("effective_to >= effective_from" in d for d in range_checks):
            # A strict ">" would forbid a one-day row, which an inclusive end allows.
            out.add(f"L8 range-check-forbids-one-day {t}")
        if exempt:
            continue
        if not (exclusive or inclusive):
            out.add(f"L8 end-semantics-undeclared {t}")
        if not exclusions:
            out.add(f"L8 no-overlap-guard {t}")
        bounds = "'[)'" if exclusive else "'[]'"
        if exclusions and (exclusive or inclusive) and not all(bounds in d for d in exclusions):
            out.add(f"L8 overlap-guard-wrong-bounds {t}")
    for name in ("EFFECTIVE_END_EXCLUSIVE", "EFFECTIVE_END_INCLUSIVE", "NO_OVERLAP_EXEMPT"):
        for t in getattr(cv, name):
            if not {"effective_from", "effective_to"} <= columns.get(t, {}).keys():
                out.add(f"L0 stale {name} {t}")

    # L9 · no index is a leading-column duplicate of another
    for t, idx in idx_by_table.items():
        for a in idx:
            if a["is_unique"] or a["partial"] or a["has_expr"] or a["method"] != "btree":
                continue
            keys = a["cols"][: a["nkeys"]]
            for b in idx:
                if b is a or b["partial"] or b["has_expr"] or b["method"] != "btree":
                    continue
                b_keys = b["cols"][: b["nkeys"]]
                if b_keys[: len(keys)] == keys and (
                    len(b_keys) > len(keys) or b["is_unique"] or b["name"] < a["name"]
                ):
                    out.add(f"L9 redundant-index {t} {a['name']}")
                    break

    # L10 · privileges of the tenant runtime role
    if await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}):
        for t in cv.APPEND_ONLY | cv.PLATFORM_ONLY:
            if t not in tables:
                out.add(f"L0 stale APPEND_ONLY/PLATFORM_ONLY {t}")
        privs = await _rows(
            conn,
            """
            SELECT c.relname AS tbl,
                   has_any_column_privilege(:r, c.oid, 'SELECT') AS sel,
                   has_any_column_privilege(:r, c.oid, 'INSERT') AS ins,
                   has_any_column_privilege(:r, c.oid, 'UPDATE') AS upd,
                   has_table_privilege(:r, c.oid, 'DELETE') AS del
            FROM pg_class c
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
            """,
            r=APP_ROLE,
        )
        for p in privs:
            if p["tbl"] in cv.APPEND_ONLY:
                for flag, name in (("upd", "UPDATE"), ("del", "DELETE")):
                    if p[flag]:
                        out.add(f"L10 append-only-writable {p['tbl']} {name}")
            if p["tbl"] in cv.PLATFORM_ONLY:
                for flag, name in (
                    ("sel", "SELECT"),
                    ("ins", "INSERT"),
                    ("upd", "UPDATE"),
                    ("del", "DELETE"),
                ):
                    if p[flag]:
                        out.add(f"L10 platform-table-visible {p['tbl']} {name}")

    # L11 · SECURITY DEFINER functions pin their search_path
    for f in await _rows(
        conn,
        """
        SELECT p.proname AS name
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef
          AND NOT EXISTS (SELECT 1 FROM unnest(coalesce(p.proconfig, '{}')) s
                          WHERE s LIKE 'search_path=%')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.objid = p.oid AND d.deptype = 'e')
        """,
    ):
        out.add(f"L11 definer-without-search-path {f['name']}")

    # L12 · types and leftovers
    for t, cols in columns.items():
        for c, dtype in cols.items():
            if t not in tables:
                continue
            if dtype == "timestamp without time zone":
                out.add(f"L12 timestamp-without-time-zone {t}.{c}")
            if dtype == "json":
                out.add(f"L12 json-not-jsonb {t}.{c}")
    for k in constraints:
        if not k["valid"]:
            out.add(f"L12 not-valid-constraint {k['tbl']} {k['name']}")
    for i in indexes:
        if not i["valid"]:
            out.add(f"L12 invalid-index {i['tbl']} {i['name']}")

    # L13 · every table says what it is
    for t, row in tables.items():
        if t != "alembic_version" and not row["comment"]:
            out.add(f"L13 no-comment {t}")

    # L14 · unique keys on archivable tables say whether archived rows count
    for t, cols in columns.items():
        if t not in tables or "archived_at" not in cols:
            continue
        for i in idx_by_table[t]:
            if (
                i["is_unique"]
                and not i["is_primary"]
                and "archived_at" not in (i["predicate"] or "")
                and i["name"] not in cv.ARCHIVE_UNIQUE_INCLUDES_ARCHIVED
            ):
                out.add(f"L14 unique-counts-archived {t} {i['name']}")
    all_index_names = {i["name"] for i in indexes}
    for name in cv.ARCHIVE_UNIQUE_INCLUDES_ARCHIVED:
        if name not in all_index_names:
            out.add(f"L0 stale ARCHIVE_UNIQUE_INCLUDES_ARCHIVED {name}")

    return sorted(out)


def _check_values(table_constraints, column: str) -> set[str] | None:
    """The values a CHECK on `column` allows, or None if no CHECK lists them."""
    pattern = re.compile(
        rf"\(\(?{re.escape(column)}\)?(?:::text)? = ANY \(\(?ARRAY\[(?P<values>[^\]]*)\]"
    )
    # PostgreSQL writes a one-value list as a plain comparison: ((col)::text = 'X'::text).
    single = re.compile(rf"\(\(?{re.escape(column)}\)?(?:::text)? = '(?P<value>(?:[^']|'')*)'")
    for k in table_constraints:
        if k["type"] != "c":
            continue
        m = pattern.search(k["def"])
        if m:
            return set(re.findall(r"'((?:[^']|'')*)'", m.group("values")))
        m = single.search(k["def"])
        if m and " OR " not in k["def"]:
            return {m.group("value")}
    return None


def read_baseline(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]


BASELINE_HEADER = """\
# Known violations of docs/database-conventions.md, frozen when the rules were introduced.
# This list may only shrink. tests/test_schema_conventions.py fails on a violation that is not
# listed here, and on a line here that no longer occurs (delete it when you fix it).
# Regenerate after a deliberate change with: python -m hrms.db.schema_rules --write <this file>
"""


async def _main(write: str | None) -> None:
    engine = create_async_engine(os.environ["HRMS_DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            found = await collect(conn)
    finally:
        await engine.dispose()
    if write:
        with open(write, "w", encoding="utf-8") as fh:
            fh.write(BASELINE_HEADER + "\n".join(found) + "\n")
        print(f"{len(found)} violations written to {write}")
    else:
        print("\n".join(found))
        print(f"-- {len(found)} violations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--write", metavar="FILE", help="write the baseline file")
    asyncio.run(_main(parser.parse_args().write))
