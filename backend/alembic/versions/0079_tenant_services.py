"""Platform-managed services a company can use.

Expand only: tenants.enabled_services lists the optional services the platform has switched on
for the company (today only SCHEDULED_MAIL, the birthday / anniversary / joiner / exit / late
arrival mail). A company starts with none; a platform admin enables what it needs. Existing
companies are left with none, so nothing sends mail until it is switched on.

Revision ID: 0079
Revises: 0078
"""

from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN enabled_services text[] NOT NULL DEFAULT '{}'")
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT ck_tenants_enabled_services "
        "CHECK (enabled_services <@ ARRAY['SCHEDULED_MAIL']::text[])"
    )
    op.execute(
        "COMMENT ON COLUMN tenants.enabled_services IS "
        "'Optional services the platform has switched on for this company (SCHEDULED_MAIL).'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP CONSTRAINT ck_tenants_enabled_services")
    op.execute("ALTER TABLE tenants DROP COLUMN enabled_services")
