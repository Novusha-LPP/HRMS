"""Rehearse the leavers / rejoining rollout on a throwaway database (docs/REJOIN_RUNBOOK.md).

Builds a database at migration 0066 with synthetic people and leave, upgrades it to head, checks
that nothing existing changed and every employment got its first stint, then proves the way back:
the downgrade refuses while lifecycle entries exist in the leave ledger, and once they are gone it
returns to 0066 with the original data intact and upgrades again without duplicating anything.

    HRMS_DATABASE_URL=postgresql+asyncpg://.../hrms_rehearsal python scripts/rehearse_lifecycle_rollout.py

Refuses any database whose name does not end in _rehearsal or _test, or that already has tables.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[1]
PEOPLE = 300


def alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def check(condition: bool, message: str) -> None:
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        raise SystemExit(1)


async def main() -> None:
    url = make_url(os.environ["HRMS_DATABASE_URL"])
    if not (url.database or "").endswith(("_rehearsal", "_test")):
        raise SystemExit("Refusing: the database name must end in _rehearsal or _test")
    engine = create_async_engine(url)
    async with engine.connect() as c:
        if await c.scalar(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        ):
            raise SystemExit("Refusing: the database is not empty")

    print("1. Migrate a new database to 0066 and seed it")
    check(alembic("upgrade", "0066").returncode == 0, "upgraded to 0066")
    tenants = [uuid4(), uuid4()]
    async with engine.begin() as c:
        for i, t in enumerate(tenants):
            await c.execute(
                text(
                    "INSERT INTO tenants (id, slug, display_name, status, plan) "
                    "VALUES (:t, :s, :s, 'ACTIVE', 'STARTER')"
                ),
                {"t": t, "s": f"rehearse-{i}"},
            )
            le, lt, bucket = uuid4(), uuid4(), uuid4()
            await c.execute(
                text("INSERT INTO legal_entities (tenant_id, id, name) VALUES (:t, :e, 'Co')"),
                {"t": t, "e": le},
            )
            await c.execute(
                text("""
                INSERT INTO persons (tenant_id, id, legal_first_name, legal_last_name)
                SELECT :t, gen_random_uuid(), 'P', 'N' || g FROM generate_series(1, :n) g"""),
                {"t": t, "n": PEOPLE},
            )
            await c.execute(
                text("""
                INSERT INTO employments (tenant_id, id, person_id, legal_entity_id, employee_number,
                    hire_date, separation_date, employment_state)
                SELECT :t, gen_random_uuid(), p.id, :e, 'E' || row_number() OVER (),
                    date '2019-01-01' + (row_number() OVER ())::int,
                    CASE WHEN row_number() OVER () % 6 = 0 THEN date '2026-01-01' END,
                    CASE WHEN row_number() OVER () % 6 = 0 THEN 'SEPARATED'
                         WHEN row_number() OVER () % 6 = 1 THEN 'PROBATION' ELSE 'ACTIVE' END
                FROM persons p WHERE p.tenant_id = :t"""),
                {"t": t, "e": le},
            )
            await c.execute(
                text(
                    "INSERT INTO leave_types (tenant_id, id, name, code, days_per_year) "
                    "VALUES (:t, :l, 'Annual', 'AL', 12)"
                ),
                {"t": t, "l": lt},
            )
            await c.execute(
                text(
                    "INSERT INTO leave_balance_buckets (tenant_id, id, name, code, is_unlimited) "
                    "VALUES (:t, :b, 'Annual', 'AL', false)"
                ),
                {"t": t, "b": bucket},
            )
            await c.execute(
                text("""
                INSERT INTO leave_monthly_ledger (tenant_id, id, employment_id, bucket_id, calendar_year,
                    calendar_month, fy_year, opening, closing)
                SELECT :t, gen_random_uuid(), e.id, :b, 2026, 10, 2026, 10, 10
                FROM employments e WHERE e.tenant_id = :t"""),
                {"t": t, "b": bucket},
            )

    async def fingerprint():
        async with engine.connect() as c:
            return (
                await c.scalar(text("SELECT count(*) FROM employments")),
                await c.scalar(
                    text("SELECT count(*) FROM employments WHERE employment_state = 'SEPARATED'")
                ),
                await c.scalar(text("SELECT sum(closing) FROM leave_monthly_ledger")),
                await c.scalar(text("SELECT count(*) FROM persons")),
            )

    before = await fingerprint()
    print(f"   {before[0]} employments, {before[1]} separated, {float(before[2]):g} days of leave")

    print("2. Upgrade to head")
    began = time.perf_counter()
    result = alembic("upgrade", "head")
    check(result.returncode == 0, f"upgraded in {time.perf_counter() - began:.1f}s")
    check(await fingerprint() == before, "existing people and leave are unchanged")
    async with engine.connect() as c:
        employments = await c.scalar(text("SELECT count(*) FROM employments"))
        check(
            await c.scalar(text("SELECT count(*) FROM employment_spells")) == employments,
            "every employment has exactly one stint",
        )
        check(
            await c.scalar(
                text("""
            SELECT count(*) FROM employment_spells s JOIN employments e
              ON e.tenant_id = s.tenant_id AND e.id = s.employment_id
            WHERE s.spell_no = 1 AND s.joined_on = e.hire_date
              AND s.left_on IS NOT DISTINCT FROM e.separation_date
              AND e.continuity_start_date = e.hire_date AND e.current_spell_no = 1""")
            )
            == employments,
            "each stint matches its employment's dates and service start",
        )
        check(
            await c.scalar(
                text("""
            SELECT count(*) FROM pg_class WHERE relname IN ('employment_spells', 'rejoin_records',
              'leave_separation_rules', 'leave_separation_settlements', 'rejoin_policies',
              'prior_service', 'company_transfers') AND relrowsecurity AND relforcerowsecurity""")
            )
            == 7,
            "row-level security is on and forced for all seven new tables",
        )

    print("3. The way back")
    async with engine.begin() as c:
        t = tenants[0]
        await c.execute(
            text("""
            INSERT INTO leave_balance_transactions (tenant_id, id, employment_id, bucket_id,
                transaction_type, quantity, previous_balance, new_balance, effective_date,
                reference_type, recorded_by)
            SELECT e.tenant_id, gen_random_uuid(), e.id, b.id, 'LAPSE', 1, 10, 9, current_date,
                   'SEPARATION', '00000000-0000-0000-0000-000000000000'
            FROM employments e JOIN leave_balance_buckets b ON b.tenant_id = e.tenant_id
            WHERE e.tenant_id = :t LIMIT 1"""),
            {"t": t},
        )
    refused = alembic("downgrade", "0066")
    check(
        refused.returncode != 0 and "cannot be rolled back" in (refused.stderr + refused.stdout),
        "the downgrade refuses while lifecycle entries sit in the leave ledger",
    )
    async with engine.begin() as c:
        await c.execute(
            text("DELETE FROM leave_balance_transactions WHERE reference_type = 'SEPARATION'")
        )
    check(alembic("downgrade", "0066").returncode == 0, "the downgrade works once they are gone")
    check(await fingerprint() == before, "after the downgrade the original data is intact")
    async with engine.connect() as c:
        check(
            await c.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_name = 'employments' AND column_name = 'continuity_start_date'"
                )
            )
            == 0,
            "the new columns are gone",
        )
    check(alembic("upgrade", "head").returncode == 0, "upgrading again works")
    async with engine.connect() as c:
        check(
            await c.scalar(text("SELECT count(*) FROM employment_spells")) == before[0],
            "and does not duplicate any stint",
        )
    print("Rehearsal passed.")
    await engine.dispose()


asyncio.run(main())
