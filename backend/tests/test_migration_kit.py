"""Tables built with hrms.db.migration_kit pass every schema rule without exceptions."""

import os
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hrms.db import conventions, schema_rules
from hrms.db import migration_kit as kit

pytestmark = pytest.mark.database

TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
async def conn():
    """A connection whose work is always rolled back."""
    engine = create_async_engine(os.environ["HRMS_TEST_DATABASE_URL"], poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _build(conn, monkeypatch):
    monkeypatch.setattr(
        conventions, "EFFECTIVE_END_INCLUSIVE", conventions.EFFECTIVE_END_INCLUSIVE | {"kit_rates"}
    )
    monkeypatch.setattr(conventions, "APPEND_ONLY", conventions.APPEND_ONLY | {"kit_events"})
    statements = [
        *kit.tenant_table(
            "kit_rates",
            """
            employment_id uuid NOT NULL,
            owner_by uuid,
            days numeric(6,1) NOT NULL,
            effective_from date NOT NULL,
            effective_to date
            """,
            comment="Sample effective-dated table built by the migration kit.",
            references={"employment_id": "employments", "owner_by": "user_accounts"},
        ),
        *kit.add_check("kit_rates", "ck_kit_rates_days", kit.half_day("days")),
        *kit.effective_range_check("kit_rates"),
        kit.no_overlap("kit_rates", "ex_kit_rates_period", ["employment_id"], end_inclusive=True),
        *kit.tenant_table(
            "kit_events",
            "rate_id uuid NOT NULL, note text",
            comment="Sample append-only history built by the migration kit.",
            references={"rate_id": "kit_rates"},
            append_only=True,
        ),
    ]
    for sql in statements:
        await conn.execute(text(sql))


async def test_kit_tables_follow_every_rule(conn, monkeypatch):
    await _build(conn, monkeypatch)
    found = await schema_rules.collect(conn)
    mine = [v for v in found if "kit_rates" in v or "kit_events" in v]
    assert mine == []


async def test_kit_constraints_reject_bad_rows(conn, monkeypatch):
    await _build(conn, monkeypatch)
    tenant_row = await conn.scalar(text("SELECT id FROM tenants LIMIT 1"))
    if tenant_row is None:
        await conn.execute(
            text(
                "INSERT INTO tenants (id, slug, display_name, status, plan) "
                "VALUES (:id, 'kit-check', 'Kit check', 'ACTIVE', 'STARTER')"
            ),
            {"id": TENANT},
        )
        tenant_row = UUID(TENANT)
    # The references are deferred (checked at commit, which never comes), so only the CHECKs
    # under test can reject these rows.
    for days, start, end, constraint in (
        (Decimal("0.3"), date(2026, 1, 1), None, "ck_kit_rates_days"),
        (Decimal("1.0"), date(2026, 2, 1), date(2026, 1, 1), "ck_kit_rates_effective_range"),
    ):
        savepoint = await conn.begin_nested()
        with pytest.raises(IntegrityError, match=constraint):
            await conn.execute(
                text(
                    "INSERT INTO kit_rates (tenant_id, id, employment_id, days, effective_from, "
                    "effective_to) VALUES (:t, gen_random_uuid(), gen_random_uuid(), :d, :f, :e)"
                ),
                {"t": tenant_row, "d": days, "f": start, "e": end},
            )
        await savepoint.rollback()


def test_no_overlap_bounds_follow_end_semantics():
    assert "'[]'" in kit.no_overlap("t", "x", ["a"], end_inclusive=True)
    assert "'[)'" in kit.no_overlap("t", "x", ["a"], end_inclusive=False)


def test_names_postgres_would_truncate_are_refused():
    long_table = "t" * 60
    with pytest.raises(ValueError, match="63 bytes"):
        kit.tenant_fk(long_table, "owner_id", "user_accounts")
    with pytest.raises(ValueError, match="63 bytes"):
        kit.index(long_table, ["tenant_id", "owner_id"])
    with pytest.raises(ValueError, match="63 bytes"):
        kit.add_check("t", "ck_" + "x" * 61, "true")


def test_concurrent_index_never_skips_a_failed_build():
    sql = kit.index("punches", ["tenant_id", "work_date"], concurrently=True)
    assert sql.startswith("CREATE INDEX CONCURRENTLY ix_punches_work_date")
    assert "IF NOT EXISTS" not in sql


async def test_invalid_index_is_reported(conn):
    await conn.execute(text("CREATE TABLE kit_probe (tenant_id uuid NOT NULL, v int)"))
    await conn.execute(text("CREATE INDEX kit_probe_v ON kit_probe (v)"))
    await conn.execute(
        text("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'kit_probe_v'::regclass")
    )
    assert "L12 invalid-index kit_probe kit_probe_v" in await schema_rules.collect(conn)


async def test_partitions_are_checked_through_their_parent(conn):
    await conn.execute(
        text(
            "CREATE TABLE kit_parted (tenant_id uuid NOT NULL, id uuid NOT NULL, d date NOT NULL,"
            " PRIMARY KEY (tenant_id, id, d)) PARTITION BY RANGE (d)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE kit_parted_2026 PARTITION OF kit_parted "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')"
        )
    )
    found = await schema_rules.collect(conn)
    assert any(v.endswith(" kit_parted") for v in found)
    assert not any("kit_parted_2026" in v for v in found)


def test_check_in_quotes_values():
    assert kit.check_in("status", ["A", "O'B"]) == "status IN ('A', 'O''B')"


def test_one_value_checks_are_read_like_lists():
    single = [{"type": "c", "def": "CHECK (((manager_type)::text = 'LINE'::text))"}]
    listed = [
        {"type": "c", "def": "CHECK (((s)::text = ANY ((ARRAY['A'::character varying])::text[])))"}
    ]
    assert schema_rules._check_values(single, "manager_type") == {"LINE"}
    assert schema_rules._check_values(listed, "s") == {"A"}
    assert schema_rules._check_values(single, "other") is None


def test_record_changes_names_the_entity():
    sql = kit.record_changes("widgets", "widget")
    assert sql.startswith("CREATE TRIGGER record_widgets_change AFTER INSERT OR UPDATE OR DELETE")
    assert sql.endswith("record_row_change('widget')")
