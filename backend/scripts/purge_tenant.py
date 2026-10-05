"""
Permanently delete a tenant and every row that belongs to it — for test or abandoned
workspaces, never real customers.

    cd backend
    .venv/bin/python scripts/purge_tenant.py --slug regression-1234abcd            # dry run
    .venv/bin/python scripts/purge_tenant.py --slug regression-1234abcd --yes      # delete

Safety:
  - a dry run (the default) only reports what would be deleted;
  - a tenant that has any employment is refused unless --allow-employees is given;
  - everything happens in one transaction, so a failure leaves the tenant untouched;
  - stored documents (KYC scans, resumes) belonging to the tenant are removed after commit.

Tables are discovered from the schema (every table with a tenant_id column), so the script
keeps working as modules are added.
"""

import argparse
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core import document_store
from hrms.core.config import settings

DOCUMENT_COLUMNS = (("employee_kyc_documents", "storage_path"), ("candidates", "resume_ref"))


async def purge(slug: str, delete: bool, allow_employees: bool) -> None:
    engine = create_async_engine(settings.database_url)
    refs: list[str] = []
    try:
        async with engine.begin() as conn:
            tenant = (
                await conn.execute(
                    text("SELECT id, display_name FROM tenants WHERE slug = :s"), {"s": slug}
                )
            ).first()
            if tenant is None:
                sys.exit(f"No tenant with slug {slug!r}")
            tid = tenant.id
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            employees = (
                await conn.execute(
                    text("SELECT count(*) FROM employments WHERE tenant_id = :t"), {"t": tid}
                )
            ).scalar()
            if employees and not allow_employees:
                sys.exit(
                    f"{tenant.display_name} has {employees} employment(s). Refusing; pass "
                    "--allow-employees only if you are certain it holds no real people."
                )
            tables = [
                r[0]
                for r in await conn.execute(
                    text("""SELECT table_name FROM information_schema.columns
                            WHERE table_schema = 'public' AND column_name = 'tenant_id'
                              AND table_name <> 'tenants'
                              AND table_name IN (SELECT table_name FROM information_schema.tables
                                                 WHERE table_schema = 'public'
                                                   AND table_type = 'BASE TABLE')""")
                )
            ]
            counts = {}
            for table in tables:
                n = (
                    await conn.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'), {"t": tid}
                    )
                ).scalar()
                if n:
                    counts[table] = n
            for table, column in DOCUMENT_COLUMNS:
                if table in tables:
                    refs += [
                        r[0]
                        for r in await conn.execute(
                            text(f"SELECT {column} FROM {table} "
                                 f"WHERE tenant_id = :t AND {column} IS NOT NULL"),
                            {"t": tid},
                        )
                    ]
            print(f"{tenant.display_name} ({slug}): {sum(counts.values())} rows in "
                  f"{len(counts)} tables, {len(refs)} stored files")
            for table, n in sorted(counts.items()):
                print(f"  {table}: {n}")
            if not delete:
                print("Dry run — nothing deleted. Re-run with --yes to delete.")
                refs = []
                return
            # Foreign keys between tenant tables are deferred to commit; delete until empty.
            await conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            remaining = dict(counts)
            for _ in range(len(remaining) + 1):
                if not remaining:
                    break
                for table in list(remaining):
                    try:
                        async with conn.begin_nested():
                            await conn.execute(
                                text(f'DELETE FROM "{table}" WHERE tenant_id = :t'), {"t": tid}
                            )
                        del remaining[table]
                    except Exception:
                        continue  # a non-deferrable reference; retry after its children go
            if remaining:
                raise RuntimeError(f"Could not delete rows from: {', '.join(remaining)}")
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        print(f"Deleted {slug}.")
    except BaseException:
        refs = []  # the transaction rolled back, so the files must stay
        raise
    finally:
        await engine.dispose()
        for ref in refs:
            try:
                document_store.remove(ref)
            except Exception as exc:  # already gone is fine
                print(f"  (couldn't remove {ref}: {exc})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", required=True, action="append",
                        help="Tenant slug; repeat for several")
    parser.add_argument("--yes", action="store_true", help="Actually delete (default: dry run)")
    parser.add_argument("--allow-employees", action="store_true")
    args = parser.parse_args()
    for slug in args.slug:
        asyncio.run(purge(slug, args.yes, args.allow_employees))


if __name__ == "__main__":
    main()
