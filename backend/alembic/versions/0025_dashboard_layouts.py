"""Per-user dashboard layouts

Each HR/admin user can choose which dashboard widgets they see, in what order and at what
size (dashboard/widgets.py holds the catalog). One row per (user, dashboard); no row means
the default layout.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_layouts",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dashboard", sa.String(length=30), nullable=False),
        sa.Column("widgets", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_dashboard_layouts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_account_id"],
            ["user_accounts.tenant_id", "user_accounts.id"],
            name="fk_dashboard_layouts_user_account_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_account_id", "dashboard", name="uq_dashboard_layout_user"
        ),
    )
    op.execute("ALTER TABLE dashboard_layouts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dashboard_layouts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON dashboard_layouts
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    op.drop_table("dashboard_layouts")
