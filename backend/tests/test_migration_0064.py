"""Grant cleanup must identify rows by their complete tenant-scoped primary key."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.database


async def test_duplicate_cleanup_preserves_same_id_in_another_tenant(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0064_grant_merge_and_job_findings.py"
    spec = importlib.util.spec_from_file_location("migration_0064", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    cleanup = next(sql for sql in statements if "DELETE FROM role_assignments" in sql)

    engine = create_async_engine(os.environ["HRMS_TEST_DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            # A temporary table shadows the real table: exercise the actual migration SQL
            # without changing any migrated application rows.
            await conn.execute(text("""
                CREATE TEMP TABLE role_assignments (
                    tenant_id uuid, id uuid, user_account_id uuid, role_id uuid,
                    scope_type text, scope_value text, expires_at timestamptz,
                    granted_at timestamptz, PRIMARY KEY (tenant_id, id)
                ) ON COMMIT DROP
            """))
            first, second, shared, winner, user, role = (uuid4() for _ in range(6))
            insert = text("""
                INSERT INTO role_assignments VALUES
                (:tenant, :id, :user, :role, 'ALL', NULL, :expiry, now())
            """)
            from datetime import UTC, datetime

            for tenant, identifier, expiry in (
                (first, winner, None),
                (first, shared, datetime(2030, 1, 1, tzinfo=UTC)),
                (second, shared, None),
            ):
                await conn.execute(insert, {
                    "tenant": tenant, "id": identifier, "user": user,
                    "role": role, "expiry": expiry,
                })
            await conn.execute(text(cleanup))
            remaining = set((await conn.execute(
                text("SELECT tenant_id, id FROM role_assignments")
            )).all())
            assert remaining == {(first, winner), (second, shared)}
            await conn.execute(text(cleanup))
            assert await conn.scalar(text("SELECT count(*) FROM role_assignments")) == 2
    finally:
        await engine.dispose()
