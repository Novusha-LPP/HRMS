"""Probe the migration owner's RLS behavior before changing any persistent schema.

RDS administrators are not ordinary PostgreSQL superusers. HRMS currently relies on
owner-executed login lookup functions being able to read FORCE RLS tables. Failing
this probe requires a reviewed RDS role/policy setup, not weaker runtime credentials.
"""

import asyncio
import sys

from hrms.core.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            # A temporary table plus a rolled-back transaction: no persistent changes.
            await conn.execute(text("CREATE TEMP TABLE hrms_owner_rls_probe (id integer)"))
            await conn.execute(text("INSERT INTO hrms_owner_rls_probe VALUES (1)"))
            await conn.execute(text("ALTER TABLE hrms_owner_rls_probe ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE hrms_owner_rls_probe FORCE ROW LEVEL SECURITY"))
            await conn.execute(
                text("CREATE POLICY deny_rows ON hrms_owner_rls_probe USING (false)")
            )
            visible = await conn.scalar(text("SELECT count(*) FROM hrms_owner_rls_probe"))
            await conn.rollback()
            if visible != 1:
                raise RuntimeError(
                    "Migration owner cannot bypass forced RLS. HRMS login lookup functions "
                    "need a reviewed RDS owner/role policy configuration before deployment. "
                    "See docs/AWS_TESTING_CICD.md. Never give hrms_app BYPASSRLS."
                )
        print("RDS TLS connection and migration-owner RLS probe passed")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - avoid printing connection URLs from driver errors
        print(
            f"Database preflight failed ({type(exc).__name__}); "
            "inspect RDS access and TLS settings locally",
            file=sys.stderr,
        )
        sys.exit(1)
