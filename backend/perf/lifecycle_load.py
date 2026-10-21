"""Load check for the leavers / rejoining work: N people who left with held leave.

Creates its own throwaway tenant (slug perf-lifecycle-*), bulk-inserts N separated employees
with a held leave balance, then times what scales with N:

  * the daily job that lapses held leave          (resolve_holds, one row per balance)
  * the three lifecycle reports                    (JSON and CSV, with SQL statement counts)
  * the monthly accrual with earlier service       (the correlated prior_service lookup)

Run it only against a private, throwaway database (see README.md). It refuses a database that
holds a tenant whose slug does not start with perf-.

    python perf/lifecycle_load.py --employees 5000
"""

import argparse
import asyncio
import os
import time
from datetime import date, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core import database
from hrms.main import app
from hrms.modules.leave.separation import resolve_holds

TODAY = date.today()


async def main(n: int) -> None:
    async with database.AsyncSessionLocal() as probe:
        stray = await probe.scalar(
            text("SELECT count(*) FROM tenants WHERE slug NOT LIKE 'perf-%'")
        )
    if stray:
        raise SystemExit("This database holds a tenant that is not a perf- one. Refusing to run.")

    tag = uuid4().hex[:6]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://perf") as client:
        reg = await client.post(
            "/v1/auth/register-company",
            json={
                "company_name": f"perf-lifecycle-{tag}",
                "admin_email": f"perf-{tag}@example.com",
                "admin_password": "PerfPassw0rd!",
            },
        )
        reg.raise_for_status()
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-HRMS-Session": "bearer"}
        me = reg.json()["user"]
        tenant_id, entity = me["tenant_id"], me["legal_entities"][0]["id"]
        lt = (
            await client.post(
                "/v1/leave/types",
                headers=headers,
                json={"name": "Annual", "code": "AL", "days_per_year": 12},
            )
        ).json()
        await client.post("/v1/leave/accrual/run", headers=headers)

        from hrms.core.ids import to_uuid

        t, le, lt_id = to_uuid(tenant_id), to_uuid(entity), to_uuid(lt["id"])
        owner = create_async_engine(os.environ["HRMS_DATABASE_URL"])
        started = time.perf_counter()
        async with owner.begin() as c:
            bucket = (
                await c.execute(
                    text(
                        "SELECT bucket_id FROM leave_type_bucket_mapping WHERE tenant_id=:t AND leave_type_id=:l"
                    ),
                    {"t": t, "l": lt_id},
                )
            ).scalar()
            await c.execute(
                text("""
                INSERT INTO persons (tenant_id, id, legal_first_name, legal_last_name)
                SELECT :t, gen_random_uuid(), 'Perf', 'Person ' || g FROM generate_series(1, :n) g"""),
                {"t": t, "n": n},
            )
            await c.execute(
                text("""
                INSERT INTO employments (tenant_id, id, person_id, legal_entity_id, employee_number,
                    hire_date, separation_date, employment_state, continuity_start_date,
                    current_spell_no)
                SELECT :t, gen_random_uuid(), p.id, :le, 'LC-' || row_number() OVER (), '2020-01-01',
                    :gone, 'SEPARATED', '2020-01-01', 1
                FROM persons p WHERE p.tenant_id = :t AND p.legal_last_name LIKE 'Person %'"""),
                {"t": t, "le": le, "gone": TODAY - timedelta(days=40)},
            )
            await c.execute(
                text("""
                INSERT INTO employment_spells (tenant_id, id, employment_id, spell_no, joined_on, left_on)
                SELECT :t, gen_random_uuid(), e.id, 1, '2020-01-01', :gone FROM employments e
                WHERE e.tenant_id = :t AND e.employee_number LIKE 'LC-%'"""),
                {"t": t, "gone": TODAY - timedelta(days=40)},
            )
            await c.execute(
                text("""
                INSERT INTO leave_monthly_ledger (tenant_id, id, employment_id, bucket_id,
                    calendar_year, calendar_month, fy_year, opening, closing)
                SELECT :t, gen_random_uuid(), e.id, :b, :y, :m, :y, 10, 10 FROM employments e
                WHERE e.tenant_id = :t AND e.employee_number LIKE 'LC-%'"""),
                {"t": t, "b": bucket, "y": TODAY.year, "m": TODAY.month},
            )
            await c.execute(
                text("""
                INSERT INTO leave_separation_settlements (tenant_id, id, employment_id, spell_id,
                    leave_type_id, bucket_id, days, action, settled_on, hold_expires_on)
                SELECT :t, gen_random_uuid(), s.employment_id, s.id, :l, :b, 10, 'HOLD', :gone, :due
                FROM employment_spells s WHERE s.tenant_id = :t"""),
                {
                    "t": t,
                    "l": lt_id,
                    "b": bucket,
                    "gone": TODAY - timedelta(days=40),
                    "due": TODAY - timedelta(days=5),
                },
            )
        print(f"seeded {n} leavers with held leave in {time.perf_counter() - started:.1f}s")
        # A bulk insert leaves the planner without statistics until autovacuum runs; production
        # never reads a table in that state, so measure the way it would be read.
        async with owner.connect() as c:
            raw = await c.execution_options(isolation_level="AUTOCOMMIT")
            for table in (
                "persons",
                "employments",
                "employment_spells",
                "leave_monthly_ledger",
                "leave_separation_settlements",
            ):
                await raw.execute(text(f"ANALYZE {table}"))
        await owner.dispose()

        for path in (
            "/v1/people/reports/rejoins",
            "/v1/leave/reports/separation-settlements",
            "/v1/people/reports/company-transfers",
        ):
            for fmt in ("json", "csv"):
                began = time.perf_counter()
                r = await client.get(f"{path}?format={fmt}&from_date=2020-01-01", headers=headers)
                took = time.perf_counter() - began
                rows = len(r.json()["rows"]) if fmt == "json" else r.text.count("\n") - 1
                print(
                    f"GET {path}?format={fmt}: {r.status_code}, {rows} rows, {took * 1000:.0f} ms,"
                    f" {r.headers.get('X-DB-Queries', '?')} statements"
                )

        began = time.perf_counter()
        async with database.AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)}
            )
            counts = await resolve_holds(session, t, TODAY)
        took = time.perf_counter() - began
        print(
            f"resolve_holds: {counts} in {took:.1f}s = {took / max(n, 1) * 1000:.1f} ms per balance"
            f" ({took / max(n, 1) * 10000:.0f}s for 10,000)"
        )

        began = time.perf_counter()
        r = await client.post(f"/v1/leave/accrual/run?period={TODAY:%Y-%m}", headers=headers)
        print(
            f"accrual run (leavers are skipped): {r.status_code} in {time.perf_counter() - began:.2f}s"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--employees", type=int, default=2000)
    asyncio.run(main(parser.parse_args().employees))
