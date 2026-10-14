"""daily_report_rows references tenants directly, like every other tenant table.

docs/database-hardening-plan.md (rule L2). The rows already belonged to a tenant through their
snapshot; the direct key makes the rule uniform and lets a tenant purge check every table the
same way.

Revision ID: 0058
Revises: 0057
"""

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE daily_report_rows ADD CONSTRAINT fk_daily_report_rows_tenant "
        "FOREIGN KEY (tenant_id) REFERENCES tenants(id) NOT VALID"
    )
    op.execute("ALTER TABLE daily_report_rows VALIDATE CONSTRAINT fk_daily_report_rows_tenant")


def downgrade() -> None:
    op.execute("ALTER TABLE daily_report_rows DROP CONSTRAINT fk_daily_report_rows_tenant")
