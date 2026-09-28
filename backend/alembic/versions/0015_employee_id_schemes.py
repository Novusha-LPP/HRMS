"""Configurable employee ID (employee_number) generation.

Employee numbers were always typed in by hand (EmploymentCreate.employee_number
was required, no generation logic anywhere). This adds an opt-in scheme —
prefix + zero-padded running number — settable tenant-wide or per legal
entity, so a group admin can set one global numbering series or let each
company run its own.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_id_schemes",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("legal_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("separator", sa.String(5), nullable=False, server_default="-"),
        sa.Column("number_digits", sa.Integer, nullable=False, server_default="4"),
        sa.Column("next_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_eis_legal_entity", "employee_id_schemes", ["legal_entity_id"])

    # At most one active scheme per company, and at most one active
    # tenant-wide scheme — enforced by the database, not application logic,
    # so a race between two admins can't leave two live schemes issuing
    # numbers for the same company.
    op.execute("""
        CREATE UNIQUE INDEX ix_eis_entity_unique ON employee_id_schemes (tenant_id, legal_entity_id)
        WHERE archived_at IS NULL AND legal_entity_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX ix_eis_global_unique ON employee_id_schemes (tenant_id)
        WHERE archived_at IS NULL AND legal_entity_id IS NULL
    """)

    op.execute("ALTER TABLE employee_id_schemes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_id_schemes FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON employee_id_schemes
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON employee_id_schemes TO hrms_app")


def downgrade() -> None:
    op.drop_table("employee_id_schemes")
