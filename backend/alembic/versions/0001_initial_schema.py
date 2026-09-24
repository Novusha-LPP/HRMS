"""Initial schema: tenants, org, people, RLS policies

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')

    # ── Tenants (public schema, no RLS — it is the isolation boundary) ────────
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100)),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="STARTER"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )

    # ── RLS helper function ────────────────────────────────────────────────────
    # Returns the tenant_id from the session-local setting.
    # Every RLS policy calls this function so the check is in one place.
    op.execute("""
        CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER AS
        $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$
    """)

    # ── User accounts ─────────────────────────────────────────────────────────
    op.create_table(
        "user_accounts",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("employee_code", sa.String(50)),
        sa.Column("mobile", sa.String(20)),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_user_accounts_email", "user_accounts", ["tenant_id", "email"])
    _enable_rls("user_accounts")

    # ── Roles & assignments ────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("roles")

    op.create_table(
        "role_assignments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False, server_default="ALL"),
        sa.Column("scope_value", sa.String(500)),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("role_assignments")

    # ── Legal entities ────────────────────────────────────────────────────────
    op.create_table(
        "legal_entities",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_name", sa.String(50)),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("legal_entities")

    # ── Locations ─────────────────────────────────────────────────────────────
    op.create_table(
        "locations",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("address_line1", sa.String(255)),
        sa.Column("address_line2", sa.String(255)),
        sa.Column("city", sa.String(100)),
        sa.Column("state_code", sa.String(10)),
        sa.Column("pincode", sa.String(20)),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("legal_entity_id", UUID(as_uuid=True)),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("locations")

    # ── Org units ─────────────────────────────────────────────────────────────
    op.create_table(
        "org_units",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50)),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True)),
        sa.Column("legal_entity_id", UUID(as_uuid=True)),
        sa.Column("location_id", UUID(as_uuid=True)),
        sa.Column("cost_centre_id", UUID(as_uuid=True)),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_org_units_code", "org_units", ["tenant_id", "code"])
    _enable_rls("org_units")

    # ── Jobs, Grades, Positions, Cost Centres ─────────────────────────────────
    for table, extra_cols in [
        ("jobs", [
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("code", sa.String(50)),
            sa.Column("function", sa.String(100)),
        ]),
        ("grades", [
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        ]),
        ("cost_centres", [
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
        ]),
    ]:
        op.create_table(
            table,
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            *extra_cols,
            sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
            sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("version", sa.Integer, nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime(timezone=True)),
            sa.PrimaryKeyConstraint("tenant_id", "id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        )
        _enable_rls(table)

    op.create_table(
        "positions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50)),
        sa.Column("org_unit_id", UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True)),
        sa.Column("grade_id", UUID(as_uuid=True)),
        sa.Column("max_headcount", sa.Integer),
        sa.Column("status", sa.String(50), nullable=False, server_default="OPEN"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("positions")

    # ── Persons ───────────────────────────────────────────────────────────────
    op.create_table(
        "persons",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("legal_first_name", sa.String(100), nullable=False),
        sa.Column("legal_last_name", sa.String(100), nullable=False),
        sa.Column("preferred_name", sa.String(100)),
        sa.Column("date_of_birth", sa.Date),
        sa.Column("gender", sa.String(20)),
        sa.Column("nationality", sa.String(2)),
        sa.Column("custom_fields", JSONB),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("persons")

    # ── Employments ───────────────────────────────────────────────────────────
    op.create_table(
        "employments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", UUID(as_uuid=True), nullable=False),
        sa.Column("legal_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_number", sa.String(50), nullable=False),
        sa.Column("hire_date", sa.Date, nullable=False),
        sa.Column("separation_date", sa.Date),
        sa.Column("employment_state", sa.String(50), nullable=False, server_default="PROBATION"),
        sa.Column("service_stage", sa.String(50)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_employments_person", "employments", ["tenant_id", "person_id"])
    op.create_index("ix_employments_number", "employments", ["tenant_id", "employee_number"])
    _enable_rls("employments")

    # ── Assignments (effective-dated) ─────────────────────────────────────────
    op.create_table(
        "assignments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("org_unit_id", UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("grade_id", UUID(as_uuid=True)),
        sa.Column("position_id", UUID(as_uuid=True)),
        sa.Column("cost_centre_id", UUID(as_uuid=True)),
        sa.Column("fte", sa.Numeric(4, 2), nullable=False, server_default="1.00"),
        sa.Column("worker_type", sa.String(50), nullable=False, server_default="PERMANENT"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_assignments_employment", "assignments", ["tenant_id", "employment_id"])
    # GIST exclusion constraint: no overlapping date ranges per employment
    op.execute("""
        ALTER TABLE assignments ADD CONSTRAINT uq_assignment_no_overlap
        EXCLUDE USING GIST (
            tenant_id WITH =,
            employment_id WITH =,
            daterange(effective_from, COALESCE(effective_to, '9999-12-31'::date), '[)') WITH &&
        )
    """)
    _enable_rls("assignments")

    # ── Assignment managers ───────────────────────────────────────────────────
    op.create_table(
        "assignment_managers",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manager_employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manager_type", sa.String(50), nullable=False, server_default="LINE"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("assignment_managers")

    # ── Personnel actions ─────────────────────────────────────────────────────
    op.create_table(
        "personnel_actions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("changes", JSONB),
        sa.Column("status", sa.String(50), nullable=False, server_default="DRAFT"),
        sa.Column("idempotency_key", sa.String(100)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_pa_employment", "personnel_actions", ["tenant_id", "employment_id"])
    op.create_index("ix_pa_idempotency", "personnel_actions", ["tenant_id", "idempotency_key"],
                    unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    _enable_rls("personnel_actions")


def _enable_rls(table: str) -> None:
    """Enable RLS and create an isolation policy for tenant-scoped tables."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    tables = [
        "personnel_actions", "assignment_managers", "assignments",
        "employments", "persons", "positions", "cost_centres", "grades",
        "jobs", "org_units", "locations", "legal_entities",
        "role_assignments", "roles", "user_accounts", "tenants",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_tenant_id() CASCADE")
