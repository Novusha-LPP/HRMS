"""Platform enterprise features: audit log, admin roles, password reset.

Three additions, all still outside the tenant/RLS boundary (same reasoning
as platform_admins in migration 0006 — these describe the platform's own
operations, not any tenant's data):

- platform_audit_log — every mutating platform action (who, what, when).
  Nothing here is a tenant-facing feature; it exists so a platform operator
  can answer "who suspended this tenant and when" after the fact.
- platform_admins.role — ADMIN (full read/write) vs VIEWER (read-only
  support tier). Previously every platform admin had identical power.
- platform_password_reset_tokens — self-service password reset for platform
  admins. Tokens are stored hashed (sha256, not bcrypt — these are random
  high-entropy single-use tokens, not user-chosen passwords, so a fast hash
  is the right tool: exact-match verification, not a slow KDF).

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def upgrade() -> None:
    op.add_column("platform_admins", sa.Column("role", sa.String(50), nullable=False, server_default="ADMIN"))

    op.create_table(
        "platform_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_admin_id", UUID(as_uuid=True), sa.ForeignKey("platform_admins.id"), nullable=True),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column("target_label", sa.String(255), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_platform_audit_log_created_at", "platform_audit_log", ["created_at"])

    op.create_table(
        "platform_password_reset_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", UUID(as_uuid=True), sa.ForeignKey("platform_admins.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    for table in ("platform_audit_log", "platform_password_reset_tokens"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON platform_admins TO {APP_ROLE}")  # role column now writable

    # Redefine platform_list_tenants(): now also returns archived_at, and no
    # longer filters archived rows out itself — the console needs to be able
    # to show/hide archived (offboarded) tenants, so filtering moves to
    # whatever query wraps this function rather than being baked in here.
    # Postgres requires DROP before CREATE when the OUT-parameter (return
    # column) list changes — CREATE OR REPLACE alone only covers a body
    # change with an identical signature.
    op.execute("DROP FUNCTION IF EXISTS platform_list_tenants()")
    op.execute("""
        CREATE FUNCTION platform_list_tenants()
        RETURNS TABLE(
            id uuid, slug text, display_name text, status text, plan text,
            legal_entity_count bigint, created_at timestamptz, archived_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT t.id, t.slug, t.display_name, t.status, t.plan,
                   COUNT(le.id) AS legal_entity_count, t.created_at, t.archived_at
            FROM tenants t
            LEFT JOIN legal_entities le
                ON le.tenant_id = t.id AND le.archived_at IS NULL
            GROUP BY t.id
            ORDER BY t.display_name
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform_list_tenants()")
    op.execute("""
        CREATE FUNCTION platform_list_tenants()
        RETURNS TABLE(
            id uuid, slug text, display_name text, status text, plan text,
            legal_entity_count bigint, created_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT t.id, t.slug, t.display_name, t.status, t.plan,
                   COUNT(le.id) AS legal_entity_count, t.created_at
            FROM tenants t
            LEFT JOIN legal_entities le
                ON le.tenant_id = t.id AND le.archived_at IS NULL
            WHERE t.archived_at IS NULL
            GROUP BY t.id
            ORDER BY t.display_name
        $$;
    """)
    op.drop_table("platform_password_reset_tokens")
    op.drop_index("ix_platform_audit_log_created_at", table_name="platform_audit_log")
    op.drop_table("platform_audit_log")
    op.drop_column("platform_admins", "role")
