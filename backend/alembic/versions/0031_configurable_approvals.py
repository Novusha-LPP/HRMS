"""Configurable department/team approval routes and audited delegation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def uid(name, nullable=False):
    return sa.Column(name, UUID(as_uuid=True), nullable=nullable)


def stamp(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def create(name, columns, relations, extras=()):
    op.create_table(
        name,
        uid("tenant_id"),
        uid("id"),
        *columns,
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        *(
            sa.ForeignKeyConstraint(
                ["tenant_id", key],
                [f"{target}.tenant_id", f"{target}.id"],
                name=f"fk_{name}_{key}",
                deferrable=True,
                initially="DEFERRED",
            )
            for key, target in relations.items()
        ),
        *extras,
    )
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY tenant_isolation ON {name}
        USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id())""")


def upgrade():
    create(
        "approval_flows",
        [
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("request_type", sa.String(30), nullable=False),
            uid("org_unit_id", True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("steps", JSONB, nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            uid("updated_by"),
            stamp("updated_at"),
        ],
        dict(org_unit_id="org_units", updated_by="user_accounts"),
    )
    op.create_index(
        "uq_approval_flow_org",
        "approval_flows",
        ["tenant_id", "request_type", "org_unit_id"],
        unique=True,
        postgresql_where=sa.text("org_unit_id IS NOT NULL"),
    )
    op.create_index(
        "uq_approval_flow_default",
        "approval_flows",
        ["tenant_id", "request_type"],
        unique=True,
        postgresql_where=sa.text("org_unit_id IS NULL"),
    )
    create(
        "approval_instances",
        [
            uid("flow_id"),
            sa.Column("request_type", sa.String(30), nullable=False),
            uid("request_id"),
            uid("employment_id"),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("flow_version", sa.Integer(), nullable=False),
            sa.Column("steps", JSONB, nullable=False),
            sa.Column("current_level", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            stamp("created_at"),
            stamp("updated_at"),
        ],
        dict(flow_id="approval_flows", employment_id="employments"),
        [
            sa.UniqueConstraint(
                "tenant_id",
                "request_type",
                "request_id",
                "generation",
                name="uq_approval_instance_generation",
            )
        ],
    )
    op.create_index(
        "ix_approval_instances_pending", "approval_instances", ["tenant_id", "status", "created_at"]
    )
    create(
        "approval_delegations",
        [
            uid("flow_id"),
            uid("instance_id", True),
            uid("step_id"),
            uid("original_user_id"),
            uid("delegate_user_id"),
            stamp("valid_from"),
            stamp("valid_until"),
            sa.Column("reason", sa.String(1000), nullable=False),
            uid("created_by"),
            stamp("created_at"),
            stamp("revoked_at", True),
            uid("revoked_by", True),
        ],
        dict(
            flow_id="approval_flows",
            instance_id="approval_instances",
            original_user_id="user_accounts",
            delegate_user_id="user_accounts",
            created_by="user_accounts",
            revoked_by="user_accounts",
        ),
    )
    op.create_index(
        "ix_approval_delegations_live",
        "approval_delegations",
        ["tenant_id", "flow_id", "step_id", "valid_until"],
    )
    create(
        "approval_events",
        [
            uid("flow_id"),
            uid("instance_id", True),
            uid("actor_user_id", True),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("details", JSONB, nullable=False),
            stamp("created_at"),
        ],
        dict(
            flow_id="approval_flows",
            instance_id="approval_instances",
            actor_user_id="user_accounts",
        ),
    )
    op.create_index(
        "ix_approval_events_instance", "approval_events", ["tenant_id", "instance_id", "created_at"]
    )


def downgrade():
    for name in ["approval_events", "approval_delegations", "approval_instances", "approval_flows"]:
        op.drop_table(name)
