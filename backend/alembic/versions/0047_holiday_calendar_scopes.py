"""Holiday calendars share one holiday list and are assigned to a company, entity or department.

- holiday_calendar_days links a calendar to holidays, so a date common to several calendars
  (Diwali, Republic Day) is one holiday row instead of one copy per calendar.
- holiday_calendar_assignments can target the whole company (no target), a legal entity, a
  department (org unit, including its sub-units) or one employee.
- holiday_calendar_for() resolves the calendar an employee follows on a date: the employee's
  own assignment, else the nearest department up the tree, else their legal entity, else the
  company-wide one.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def _fk(table, column, target):
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        deferrable=True,
        initially="DEFERRED",
    )


def upgrade():
    op.create_table(
        "holiday_calendar_days",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("holiday_id", sa.Uuid(), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        _fk("holiday_calendar_days", "calendar_id", "holiday_calendars"),
        _fk("holiday_calendar_days", "holiday_id", "holidays"),
        sa.UniqueConstraint(
            "tenant_id", "calendar_id", "holiday_id", name="uq_holiday_calendar_day"
        ),
    )
    op.create_index("ix_holiday_calendar_days_holiday", "holiday_calendar_days", ["holiday_id"])

    op.alter_column("holiday_calendar_assignments", "employment_id", nullable=True)
    op.add_column("holiday_calendar_assignments", sa.Column("legal_entity_id", sa.Uuid()))
    op.add_column("holiday_calendar_assignments", sa.Column("org_unit_id", sa.Uuid()))
    for column, target in (("legal_entity_id", "legal_entities"), ("org_unit_id", "org_units")):
        op.create_foreign_key(
            f"fk_holiday_calendar_assignments_{column}",
            "holiday_calendar_assignments",
            target,
            ["tenant_id", column],
            ["tenant_id", "id"],
            deferrable=True,
            initially="DEFERRED",
        )
    op.create_check_constraint(
        "ck_hca_one_target",
        "holiday_calendar_assignments",
        "num_nonnulls(employment_id, legal_entity_id, org_unit_id) <= 1",
    )
    op.create_index(
        "ix_holiday_calendar_assignments_calendar", "holiday_calendar_assignments", ["calendar_id"]
    )

    op.execute("ALTER TABLE holiday_calendar_days ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE holiday_calendar_days FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON holiday_calendar_days "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON holiday_calendar_days TO hrms_app")

    # Most specific assignment wins; among equals the latest start. Runs as the caller, so
    # row-level security keeps it inside the caller's tenant.
    op.execute("""
        CREATE OR REPLACE FUNCTION holiday_calendar_for(p_tenant uuid, p_employment uuid, p_day date)
        RETURNS uuid LANGUAGE sql STABLE AS $$
          WITH RECURSIVE placement AS (
            SELECT e.legal_entity_id,
                   (SELECT a.org_unit_id FROM assignments a
                     WHERE a.tenant_id = p_tenant AND a.employment_id = p_employment
                       AND a.effective_from <= p_day
                       AND (a.effective_to IS NULL OR a.effective_to > p_day)
                     ORDER BY a.effective_from DESC LIMIT 1) AS org_unit_id
            FROM employments e WHERE e.tenant_id = p_tenant AND e.id = p_employment
          ), units(id, depth) AS (
            SELECT org_unit_id, 0 FROM placement WHERE org_unit_id IS NOT NULL
            UNION ALL
            SELECT ou.parent_id, u.depth + 1 FROM units u
              JOIN org_units ou ON ou.tenant_id = p_tenant AND ou.id = u.id
             WHERE ou.parent_id IS NOT NULL AND u.depth < 20
          )
          SELECT hca.calendar_id
            FROM holiday_calendar_assignments hca
            JOIN holiday_calendars hc
              ON hc.tenant_id = hca.tenant_id AND hc.id = hca.calendar_id AND hc.archived_at IS NULL
            LEFT JOIN units u ON u.id = hca.org_unit_id
           WHERE hca.tenant_id = p_tenant AND hca.archived_at IS NULL
             AND hca.effective_from <= p_day
             AND (hca.effective_to IS NULL OR hca.effective_to >= p_day)
             AND (hca.employment_id = p_employment
                  OR u.id IS NOT NULL
                  OR hca.legal_entity_id = (SELECT legal_entity_id FROM placement)
                  OR num_nonnulls(hca.employment_id, hca.legal_entity_id, hca.org_unit_id) = 0)
           ORDER BY CASE WHEN hca.employment_id IS NOT NULL THEN 0
                         WHEN hca.org_unit_id IS NOT NULL THEN 1 + u.depth
                         WHEN hca.legal_entity_id IS NOT NULL THEN 100
                         ELSE 200 END,
                    hca.effective_from DESC
           LIMIT 1
        $$
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS holiday_calendar_for(uuid, uuid, date)")
    op.drop_index("ix_holiday_calendar_assignments_calendar", "holiday_calendar_assignments")
    op.drop_constraint("ck_hca_one_target", "holiday_calendar_assignments")
    for column in ("org_unit_id", "legal_entity_id"):
        op.drop_constraint(
            f"fk_holiday_calendar_assignments_{column}", "holiday_calendar_assignments"
        )
        op.drop_column("holiday_calendar_assignments", column)
    op.execute("DELETE FROM holiday_calendar_assignments WHERE employment_id IS NULL")
    op.alter_column("holiday_calendar_assignments", "employment_id", nullable=False)
    op.drop_table("holiday_calendar_days")
