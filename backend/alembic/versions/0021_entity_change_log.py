"""Entity change log — tenant-level "what was this before" audit trail

Adds entity_change_log: append-only field-level change history for tenant
reference data (legal entities, org units, locations, jobs to start).
Written exclusively through core.change_audit.record_change(); hrms_app is
granted SELECT and INSERT only — the same treatment kyc_access_log and
leave_balance_transactions already got (0019, 0020), so an audit trail can't
be edited or deleted even by a bug in the application, only by a real
database administrator.

Also adds legal_entities.financial_year_start_month's write path: the
column itself already exists (migration 0020 added it), but no endpoint
could set it yet — org/router.py's PATCH /v1/org/legal-entities/{id} (added
alongside this migration) is what actually uses it.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def upgrade() -> None:
    op.create_table(
        "entity_change_log",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("changes", JSONB, nullable=False),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_entity_change_log"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "changed_by"],
            ["user_accounts.tenant_id", "user_accounts.id"],
            name="fk_entity_change_log_changed_by",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_entity_change_log_entity",
        "entity_change_log",
        ["tenant_id", "entity_type", "entity_id", "changed_at"],
    )
    op.execute("ALTER TABLE entity_change_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE entity_change_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON entity_change_log
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)
    # Append-only for the running app: no UPDATE, no DELETE. (Migration 0005 set
    # default privileges, so a new table starts out fully writable by the app
    # role — that has to be taken away explicitly, not just left ungranted.)
    op.execute(f"REVOKE ALL ON entity_change_log FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON entity_change_log TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("entity_change_log")
