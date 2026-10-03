"""Align approval constraints and persist tenant job recovery checkpoints."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    for table, names in {
        "approval_flows": ["fk_approval_flow_employee", "fk_approval_flow_owner_employment_id",
                           "fk_approval_flow_legal_entity_id"],
        "employee_approval_flows": ["employee_approval_flows_tenant_id_employment_id_fkey",
                                    "employee_approval_flows_tenant_id_updated_by_fkey"],
    }.items():
        for name in names:
            op.execute(f'ALTER TABLE {table} ALTER CONSTRAINT "{name}" DEFERRABLE INITIALLY DEFERRED')
    op.create_foreign_key("fk_employee_approval_flows_tenant", "employee_approval_flows",
                          "tenants", ["tenant_id"], ["id"])
    op.add_column("tenants", sa.Column("timezone", sa.String(100), nullable=False,
                                      server_default="Asia/Kolkata"))
    op.create_table(
        "tenant_job_checkpoints",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("job", sa.String(60), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "job"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.execute("ALTER TABLE tenant_job_checkpoints ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_job_checkpoints FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY tenant_isolation ON tenant_job_checkpoints
        USING (tenant_id=current_tenant_id()) WITH CHECK (tenant_id=current_tenant_id())""")


def downgrade():
    # A checkpoint is operational accounting history: never erase it for a code rollback.
    raise RuntimeError("Keep job recovery checkpoints; roll back code with the expanded schema")
