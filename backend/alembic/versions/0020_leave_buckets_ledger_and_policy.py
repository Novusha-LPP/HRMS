"""Leave balance buckets, ledger, bucket policies, and transaction journal.

- legal_entities.financial_year_start_month — company-scoped financial year start month (1-12)
- leave_balance_buckets — balance pool decoupled from leave types
- leave_type_bucket_mapping — maps leave types to balance buckets
- leave_policy_sets — grouped leave policies
- leave_bucket_policies — entitlement rules per (policy set, bucket)
- leave_policy_assignments — 3-tier cascade assignment (employment / org_unit / legal_entity)
- leave_monthly_ledger — materialized monthly ledger with held, taken, accrual, and closing
- leave_balance_transactions — append-only transaction audit log (app role: SELECT, INSERT only)

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def upgrade() -> None:
    # ── 1. LegalEntity financial_year_start_month ─────────────────────────────
    op.add_column(
        "legal_entities",
        sa.Column("financial_year_start_month", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_legal_entities_fy_start_month",
        "legal_entities",
        "financial_year_start_month >= 1 AND financial_year_start_month <= 12",
    )

    # ── 2. leave_balance_buckets ──────────────────────────────────────────────
    op.create_table(
        "leave_balance_buckets",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("is_unlimited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_balance_buckets"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_balance_buckets_tenant_id"
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_leave_balance_bucket_code"),
    )
    _enable_rls("leave_balance_buckets")

    # ── 3. leave_type_bucket_mapping ──────────────────────────────────────────
    op.create_table(
        "leave_type_bucket_mapping",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_type_bucket_mapping"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_type_bucket_mapping_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_type_bucket_mapping_leave_type_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["leave_balance_buckets.tenant_id", "leave_balance_buckets.id"],
            name="fk_leave_type_bucket_mapping_bucket_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint("tenant_id", "leave_type_id", name="uq_leave_type_bucket_mapping"),
    )
    _enable_rls("leave_type_bucket_mapping")

    # ── 4. leave_policy_sets ──────────────────────────────────────────────────
    op.create_table(
        "leave_policy_sets",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_policy_sets"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_policy_sets_tenant_id"
        ),
    )
    _enable_rls("leave_policy_sets")

    # ── 5. leave_bucket_policies ──────────────────────────────────────────────
    op.create_table(
        "leave_bucket_policies",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("policy_set_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_id", UUID(as_uuid=True), nullable=False),
        sa.Column("accrual_type", sa.String(length=20), nullable=False),
        sa.Column("days_per_year", sa.Float(), nullable=False),
        sa.Column(
            "carry_forward_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("max_carry_forward_days", sa.Float(), nullable=True),
        sa.Column("lapse_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "encashment_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("max_encashment_days", sa.Float(), nullable=True),
        sa.Column(
            "probation_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("min_service_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "pro_rate_first_year", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_bucket_policies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_bucket_policies_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_set_id"],
            ["leave_policy_sets.tenant_id", "leave_policy_sets.id"],
            name="fk_leave_bucket_policies_policy_set_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["leave_balance_buckets.tenant_id", "leave_balance_buckets.id"],
            name="fk_leave_bucket_policies_bucket_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "tenant_id", "policy_set_id", "bucket_id", name="uq_leave_bucket_policy"
        ),
    )
    _enable_rls("leave_bucket_policies")

    # ── 6. leave_policy_assignments ───────────────────────────────────────────
    op.create_table(
        "leave_policy_assignments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("org_unit_id", UUID(as_uuid=True), nullable=True),
        sa.Column("legal_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("leave_policy_set_id", UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_policy_assignments"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_policy_assignments_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"],
            ["employments.tenant_id", "employments.id"],
            name="fk_leave_policy_assignments_employment_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "org_unit_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_leave_policy_assignments_org_unit_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "legal_entity_id"],
            ["legal_entities.tenant_id", "legal_entities.id"],
            name="fk_leave_policy_assignments_legal_entity_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_policy_set_id"],
            ["leave_policy_sets.tenant_id", "leave_policy_sets.id"],
            name="fk_leave_policy_assignments_leave_policy_set_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "num_nonnulls(employment_id, org_unit_id, legal_entity_id) = 1",
            name="ck_lpa_exactly_one_target",
        ),
    )
    op.create_index("ix_lpa_employment", "leave_policy_assignments", ["tenant_id", "employment_id"])
    op.create_index("ix_lpa_org_unit", "leave_policy_assignments", ["tenant_id", "org_unit_id"])
    op.create_index(
        "ix_lpa_legal_entity", "leave_policy_assignments", ["tenant_id", "legal_entity_id"]
    )
    _enable_rls("leave_policy_assignments")

    # ── 7. leave_monthly_ledger ───────────────────────────────────────────────
    op.create_table(
        "leave_monthly_ledger",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_id", UUID(as_uuid=True), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("calendar_month", sa.Integer(), nullable=False),
        sa.Column("fy_year", sa.Integer(), nullable=False),
        sa.Column("opening", sa.Float(), nullable=False, server_default="0"),
        sa.Column("accrued", sa.Float(), nullable=False, server_default="0"),
        sa.Column("granted", sa.Float(), nullable=False, server_default="0"),
        sa.Column("held", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("taken", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lapsed", sa.Float(), nullable=False, server_default="0"),
        sa.Column("encashed", sa.Float(), nullable=False, server_default="0"),
        sa.Column("closing", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_monthly_ledger"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_monthly_ledger_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"],
            ["employments.tenant_id", "employments.id"],
            name="fk_leave_monthly_ledger_employment_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["leave_balance_buckets.tenant_id", "leave_balance_buckets.id"],
            name="fk_leave_monthly_ledger_bucket_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employment_id",
            "bucket_id",
            "calendar_year",
            "calendar_month",
            name="uq_leave_monthly_ledger_period",
        ),
        sa.CheckConstraint(
            "calendar_month >= 1 AND calendar_month <= 12",
            name="ck_lml_calendar_month",
        ),
    )
    op.create_index(
        "ix_lml_emp_bucket", "leave_monthly_ledger", ["tenant_id", "employment_id", "bucket_id"]
    )
    op.create_index("ix_lml_fy_year", "leave_monthly_ledger", ["tenant_id", "fy_year"])
    _enable_rls("leave_monthly_ledger")

    # ── 8. leave_balance_transactions ─────────────────────────────────────────
    op.create_table(
        "leave_balance_transactions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", UUID(as_uuid=True), nullable=True),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("previous_balance", sa.Float(), nullable=False),
        sa.Column("new_balance", sa.Float(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reference_type", sa.String(length=30), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_leave_balance_transactions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_leave_balance_transactions_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"],
            ["employments.tenant_id", "employments.id"],
            name="fk_leave_balance_transactions_employment_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["leave_balance_buckets.tenant_id", "leave_balance_buckets.id"],
            name="fk_leave_balance_transactions_bucket_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_balance_transactions_leave_type_id",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_lbt_lookup",
        "leave_balance_transactions",
        ["tenant_id", "employment_id", "bucket_id", "recorded_at"],
    )
    op.create_index(
        "ix_lbt_reference",
        "leave_balance_transactions",
        ["tenant_id", "reference_type", "reference_id"],
    )
    _enable_rls("leave_balance_transactions")

    # Append-only for the running app: no UPDATE, no DELETE (matching migration 0019 kyc_access_log)
    op.execute(f"REVOKE ALL ON leave_balance_transactions FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON leave_balance_transactions TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("leave_balance_transactions")
    op.drop_table("leave_monthly_ledger")
    op.drop_table("leave_policy_assignments")
    op.drop_table("leave_bucket_policies")
    op.drop_table("leave_policy_sets")
    op.drop_table("leave_type_bucket_mapping")
    op.drop_table("leave_balance_buckets")
    op.drop_constraint("ck_legal_entities_fy_start_month", "legal_entities", type_="check")
    op.drop_column("legal_entities", "financial_year_start_month")
