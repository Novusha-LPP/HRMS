"""Reusable workflows explicitly selected for each employee and request type."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "approval_flows",
        sa.Column("reusable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column, target in [
        ("owner_employment_id", "employments"),
        ("legal_entity_id", "legal_entities"),
    ]:
        op.add_column("approval_flows", sa.Column(column, UUID(as_uuid=True)))
        op.create_foreign_key(
            f"fk_approval_flow_{column}",
            "approval_flows",
            target,
            ["tenant_id", column],
            ["tenant_id", "id"],
        )
    for name, columns, condition in [
        (
            "uq_approval_flow_default",
            ["tenant_id", "request_type"],
            "org_unit_id IS NULL AND employment_id IS NULL",
        ),
        (
            "uq_approval_flow_org",
            ["tenant_id", "request_type", "org_unit_id"],
            "org_unit_id IS NOT NULL",
        ),
        (
            "uq_approval_flow_employee",
            ["tenant_id", "request_type", "employment_id"],
            "employment_id IS NOT NULL",
        ),
    ]:
        op.drop_index(name, table_name="approval_flows")
        op.create_index(
            name,
            "approval_flows",
            columns,
            unique=True,
            postgresql_where=sa.text(f"NOT reusable AND {condition}"),
        )
    op.create_unique_constraint(
        "uq_approval_flow_kind", "approval_flows", ["tenant_id", "id", "request_type"]
    )
    op.create_table(
        "employee_approval_flows",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("flow_id", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "employment_id", "request_type"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"], ["employments.tenant_id", "employments.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "flow_id", "request_type"],
            ["approval_flows.tenant_id", "approval_flows.id", "approval_flows.request_type"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by"], ["user_accounts.tenant_id", "user_accounts.id"]
        ),
    )
    op.execute("ALTER TABLE employee_approval_flows ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_approval_flows FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY tenant_isolation ON employee_approval_flows
        USING (tenant_id=current_tenant_id()) WITH CHECK (tenant_id=current_tenant_id())""")
    # Freeze existing routing into employee selections, preserving configured behavior.
    # Future placement changes no longer choose a different workflow.
    op.execute("""
        WITH RECURSIVE chain AS (
            SELECT a.tenant_id,a.employment_id,ou.id,ou.parent_id,0 AS depth,ARRAY[ou.id] AS path
            FROM assignments a JOIN org_units ou ON ou.tenant_id=a.tenant_id AND ou.id=a.org_unit_id
            WHERE a.effective_from<=CURRENT_DATE
              AND (a.effective_to IS NULL OR a.effective_to>CURRENT_DATE)
              AND ou.archived_at IS NULL AND ou.status='ACTIVE'
            UNION ALL
            SELECT c.tenant_id,c.employment_id,ou.id,ou.parent_id,c.depth+1,c.path||ou.id
            FROM chain c JOIN org_units ou ON ou.tenant_id=c.tenant_id AND ou.id=c.parent_id
            WHERE NOT ou.id=ANY(c.path) AND ou.archived_at IS NULL AND ou.status='ACTIVE'
        ), routes AS (
            SELECT e.tenant_id,e.id AS employment_id,f.id AS flow_id,f.request_type,f.updated_by,
              row_number() OVER (PARTITION BY e.tenant_id,e.id,f.request_type ORDER BY
                CASE WHEN f.employment_id=e.id THEN -1
                     ELSE COALESCE(c.depth,2147483647) END,f.id) AS rank
            FROM employments e JOIN approval_flows f
              ON f.tenant_id=e.tenant_id AND f.enabled AND NOT f.reusable
            LEFT JOIN chain c
              ON c.tenant_id=e.tenant_id AND c.employment_id=e.id AND c.id=f.org_unit_id
            WHERE e.archived_at IS NULL AND (f.employment_id=e.id OR (f.employment_id IS NULL
              AND (f.org_unit_id IS NULL OR c.id IS NOT NULL)))
        )
        INSERT INTO employee_approval_flows
          (tenant_id,employment_id,request_type,flow_id,version,updated_by,updated_at)
        SELECT tenant_id,employment_id,request_type,flow_id,1,updated_by,now()
        FROM routes WHERE rank=1
    """)


def downgrade():
    raise RuntimeError(
        "Employee workflow selections must be preserved; "
        "this migration cannot be reversed automatically"
    )
