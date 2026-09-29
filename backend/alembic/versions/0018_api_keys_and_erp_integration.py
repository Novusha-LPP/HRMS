"""API keys, ERP integration metadata, and multi-identifier login lookup.

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def upgrade() -> None:
    # ── 1. user_accounts ERP tracking columns ────────────────────────────────
    op.add_column("user_accounts", sa.Column("erp_system", sa.String(length=20), nullable=True))
    op.add_column("user_accounts", sa.Column("erp_user_id", sa.String(length=100), nullable=True))

    op.create_index(
        "uq_user_accounts_erp",
        "user_accounts",
        ["tenant_id", "erp_system", "erp_user_id"],
        unique=True,
        postgresql_where=sa.text("erp_system IS NOT NULL AND erp_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_user_accounts_employee_code",
        "user_accounts",
        ["tenant_id", sa.text("lower(employee_code)")],
        postgresql_where=sa.text("employee_code IS NOT NULL"),
    )
    op.create_index(
        "ix_user_accounts_mobile",
        "user_accounts",
        ["tenant_id", "mobile"],
        postgresql_where=sa.text("mobile IS NOT NULL"),
    )

    # ── 2. api_keys table ───────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", JSONB, server_default="[]", nullable=False),
        sa.Column("allowed_ips", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="600", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=45), nullable=True),
        sa.Column("total_requests", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_api_keys"),
    )
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)

    # ── 3. import_batches table ──────────────────────────────────────────────
    op.create_table(
        "import_batches",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "imported_by", sa.String(length=100), server_default="system_migration", nullable=False
        ),
        sa.Column("total_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_dry_run", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("details", JSONB, nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_import_batches"),
    )

    # ── 4. RLS & Privileges ──────────────────────────────────────────────────
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY api_keys_tenant_isolation ON api_keys
            FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    op.execute("ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY import_batches_tenant_isolation ON import_batches
            FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON import_batches TO {APP_ROLE}")

    # ── 5. Stored Procedure: login_lookup (supports email / employee_code / mobile) ─
    op.execute("DROP FUNCTION IF EXISTS login_lookup(text)")
    op.execute(r"""
        CREATE OR REPLACE FUNCTION login_lookup(p_identifier text)
        RETURNS TABLE(
            tenant_id uuid,
            id uuid,
            password_hash text,
            status text,
            employment_id uuid
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT 
                tenant_id, 
                id, 
                password_hash, 
                status, 
                employment_id
            FROM user_accounts
            WHERE (
                lower(email) = lower(trim(p_identifier))
                OR lower(employee_code) = lower(trim(p_identifier))
                OR mobile = trim(p_identifier)
                OR (
                    length(regexp_replace(trim(p_identifier), '\D', '', 'g')) >= 10
                    AND (
                        mobile = right(regexp_replace(trim(p_identifier), '\D', '', 'g'), 10)
                        OR regexp_replace(mobile, '\D', '', 'g') = regexp_replace(trim(p_identifier), '\D', '', 'g')
                    )
                )
            )
            LIMIT 1;
        $$;
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS login_lookup(text)")
    op.execute("""
        CREATE OR REPLACE FUNCTION login_lookup(p_email text)
        RETURNS TABLE(
            tenant_id uuid,
            id uuid,
            password_hash text,
            status text,
            employment_id uuid
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT tenant_id, id, password_hash, status, employment_id
            FROM user_accounts
            WHERE lower(email) = lower(p_email)
            LIMIT 1;
        $$;
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup(text) TO {APP_ROLE}")

    op.drop_table("import_batches")
    op.drop_table("api_keys")

    op.drop_index("ix_user_accounts_mobile", table_name="user_accounts")
    op.drop_index("ix_user_accounts_employee_code", table_name="user_accounts")
    op.drop_index("uq_user_accounts_erp", table_name="user_accounts")

    op.drop_column("user_accounts", "erp_user_id")
    op.drop_column("user_accounts", "erp_system")
