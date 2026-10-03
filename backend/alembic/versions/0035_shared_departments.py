"""Shared department catalog with separate company departments and teams.

Existing company department IDs, team parents and employee assignments stay intact.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("org_units", sa.Column("department_template_id", UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_org_units_department_template",
        "org_units",
        "org_units",
        ["tenant_id", "department_template_id"],
        ["tenant_id", "id"],
    )
    # Build indexes before data writes enqueue deferred foreign-key trigger events.
    op.create_index(
        "uq_company_department_template",
        "org_units",
        ["tenant_id", "legal_entity_id", "department_template_id"],
        unique=True,
        postgresql_where=sa.text(
            "archived_at IS NULL AND department_template_id IS NOT NULL "
            "AND legal_entity_id IS NOT NULL"
        ),
    )
    op.execute("""
        CREATE UNIQUE INDEX uq_shared_department_name
        ON org_units (tenant_id, lower(btrim(name)))
        WHERE type = 'DEPARTMENT_TEMPLATE' AND archived_at IS NULL
    """)
    op.execute("""
        INSERT INTO org_units
            (tenant_id, id, name, code, type, status, effective_from, recorded_at, version)
        SELECT tenant_id, gen_random_uuid(), name, code, 'DEPARTMENT_TEMPLATE',
               'ACTIVE', CURRENT_DATE, now(), 0
        FROM (
            SELECT DISTINCT ON (tenant_id, lower(btrim(name)))
                   tenant_id, btrim(name) AS name, code
            FROM org_units
            WHERE type = 'DEPARTMENT' AND archived_at IS NULL
              AND legal_entity_id IS NOT NULL AND btrim(name) != ''
            ORDER BY tenant_id, lower(btrim(name)), recorded_at, id
        ) existing
        WHERE NOT EXISTS (
            SELECT 1 FROM org_units template
            WHERE template.tenant_id = existing.tenant_id
              AND template.type = 'DEPARTMENT_TEMPLATE' AND template.archived_at IS NULL
              AND lower(btrim(template.name)) = lower(existing.name)
        )
    """)
    # Keep duplicate legacy rows: link one canonical department per company/name.
    op.execute("""
        WITH canonical AS (
            SELECT id, tenant_id,
                   row_number() OVER (
                       PARTITION BY tenant_id, legal_entity_id, lower(btrim(name))
                       ORDER BY recorded_at, id
                   ) AS rank
            FROM org_units WHERE type = 'DEPARTMENT' AND archived_at IS NULL
              AND legal_entity_id IS NOT NULL
        )
        UPDATE org_units department SET department_template_id = template.id
        FROM org_units template, canonical
        WHERE department.id = canonical.id AND department.tenant_id = canonical.tenant_id
          AND canonical.rank = 1 AND template.tenant_id = department.tenant_id
          AND template.type = 'DEPARTMENT_TEMPLATE' AND template.archived_at IS NULL
          AND lower(btrim(template.name)) = lower(btrim(department.name))
    """)


def downgrade() -> None:
    op.drop_index("uq_shared_department_name", "org_units")
    op.drop_index("uq_company_department_template", "org_units")
    op.drop_constraint("fk_org_units_department_template", "org_units", type_="foreignkey")
    op.drop_column("org_units", "department_template_id")
    # Catalog rows can be removed; company department IDs and placements are retained.
    op.execute("DELETE FROM org_units WHERE type = 'DEPARTMENT_TEMPLATE'")
