"""Preserve separately assigned holiday calendars during legacy imports."""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "holiday_calendars",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "holiday_calendar_assignments",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employment_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"],
            ["employments.tenant_id", "employments.id"],
            name="fk_holiday_calendar_assignments_employment_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["holiday_calendars.tenant_id", "holiday_calendars.id"],
            name="fk_holiday_calendar_assignments_calendar_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="ck_hca_dates"
        ),
    )
    op.create_index(
        "ix_holiday_calendar_assignments_employment_id",
        "holiday_calendar_assignments",
        ["employment_id"],
    )
    op.add_column("holidays", sa.Column("calendar_id", sa.Uuid()))
    op.add_column("holidays", sa.Column("holiday_type", sa.String(50)))
    op.create_foreign_key(
        "fk_holidays_calendar_id",
        "holidays",
        "holiday_calendars",
        ["tenant_id", "calendar_id"],
        ["tenant_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    for table in ("holiday_calendars", "holiday_calendar_assignments"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hrms_app")


def downgrade():
    op.drop_constraint("fk_holidays_calendar_id", "holidays", type_="foreignkey")
    op.drop_column("holidays", "holiday_type")
    op.drop_column("holidays", "calendar_id")
    op.drop_table("holiday_calendar_assignments")
    op.drop_table("holiday_calendars")
