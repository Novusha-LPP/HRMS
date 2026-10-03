"""Per-user preferences: colour theme and dashboard style

Two independent choices each person makes for themselves (modules/preferences): the app's
colour theme and which HR dashboard they use. Stored per account so they follow the person
to any device. No row means the defaults (original theme, widget dashboard).

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("color_theme", sa.String(length=30), nullable=False, server_default="default"),
        sa.Column(
            "dashboard_style", sa.String(length=30), nullable=False, server_default="widgets"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_user_preferences"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_account_id"],
            ["user_accounts.tenant_id", "user_accounts.id"],
            name="fk_user_preferences_user_account_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint("tenant_id", "user_account_id", name="uq_user_preferences_user"),
        sa.CheckConstraint(
            "color_theme IN ('default', 'hrms-dashboard')", name="ck_user_preferences_theme"
        ),
        sa.CheckConstraint(
            "dashboard_style IN ('widgets', 'overview')", name="ck_user_preferences_dashboard"
        ),
    )
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON user_preferences
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    op.drop_table("user_preferences")
