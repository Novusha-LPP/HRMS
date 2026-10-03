"""The catalog backfill must work with deferred PostgreSQL foreign keys."""

import importlib.util
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


def check_migration_on_temporary_tables(connection):
    # Temp tables shadow the real table only on this connection and disappear on rollback.
    connection.execute(text("CREATE TEMP TABLE migration_tenants (id uuid PRIMARY KEY)"))
    connection.execute(
        text("""
        CREATE TEMP TABLE org_units (
            tenant_id uuid NOT NULL,
            id uuid NOT NULL,
            name varchar(255) NOT NULL,
            code varchar(50),
            type varchar(50) NOT NULL,
            parent_id uuid,
            legal_entity_id uuid,
            status varchar(50) NOT NULL DEFAULT 'ACTIVE',
            effective_from date NOT NULL DEFAULT CURRENT_DATE,
            recorded_at timestamptz DEFAULT now(),
            version integer NOT NULL DEFAULT 0,
            archived_at timestamptz,
            PRIMARY KEY (tenant_id, id),
            FOREIGN KEY (tenant_id) REFERENCES migration_tenants (id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (tenant_id, parent_id) REFERENCES org_units (tenant_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    )
    assert connection.scalar(
        text("""
        SELECT pg_my_temp_schema() = relnamespace
        FROM pg_class WHERE oid = 'org_units'::regclass
    """)
    )
    tenant, department, team, company = [uuid4() for _ in range(4)]
    connection.execute(text("INSERT INTO migration_tenants VALUES (:id)"), {"id": tenant})
    connection.execute(
        text("""
        INSERT INTO org_units (tenant_id, id, name, type, legal_entity_id)
        VALUES (:tenant, :id, 'Sales', 'DEPARTMENT', :company)
    """),
        {"tenant": tenant, "id": department, "company": company},
    )
    connection.execute(
        text("""
        INSERT INTO org_units (tenant_id, id, name, type, parent_id, legal_entity_id)
        VALUES (:tenant, :id, 'Inside Sales', 'TEAM', :parent, :company)
    """),
        {"tenant": tenant, "id": team, "parent": department, "company": company},
    )
    # Seeding is checked before migration begins; migration's own writes remain deferred.
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    path = Path(__file__).parents[1] / "alembic/versions/0035_shared_departments.py"
    spec = importlib.util.spec_from_file_location("shared_departments_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = Operations(MigrationContext.configure(connection))
    with patch.object(migration, "op", operations):
        migration.upgrade()
    rows = connection.execute(text("SELECT * FROM org_units")).mappings().all()
    assert len(rows) == 3
    template = next(r for r in rows if r["type"] == "DEPARTMENT_TEMPLATE")
    original = next(r for r in rows if r["id"] == department)
    assert original["department_template_id"] == template["id"]
    assert original["legal_entity_id"] == company
    assert next(r for r in rows if r["id"] == team)["parent_id"] == department
    # Force every deferred check before rollback so errors can't be hidden by cleanup.
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.database
async def test_backfill_with_deferred_foreign_keys(api):
    _, engine = api
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(check_migration_on_temporary_tables)
        finally:
            await transaction.rollback()
