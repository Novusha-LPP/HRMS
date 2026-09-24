"""Platform admins — a role above every tenant, not inside one.

Every existing SUPER_ADMIN is a role_assignment scoped to ONE tenant: its
JWT carries that tenant_id, and RLS enforces the boundary from there — that
role can never reach a second tenant no matter what permission string it
holds (see core/authz.py, core/tenancy.py). That's the whole point of the
isolation model, so it's the wrong table to extend for "manage the whole
platform, register any company, link it under an existing group or stand it
up on its own."

platform_admins is therefore a separate, tenant-free table: no tenant_id
column, no RLS policy (same reasoning as `tenants` itself — this table IS
part of the root of the isolation boundary, not a tenant living inside it).
Its login issues a differently-typed JWT (see core/security.py) that the
ordinary tenant-scoped dependencies (CurrentUser, TenantDep, ScopeDep) don't
even recognise, so a platform token can't accidentally be used as a tenant
token or vice versa.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    # No RLS: this table has no tenant_id — it's above the tenant boundary,
    # not inside it. Grant hrms_app ordinary access, same as every other table.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform_admins TO {APP_ROLE}")

    # tenants itself has no RLS either, so a plain SELECT already lists every
    # tenant regardless of app.tenant_id — but legal_entities DOES have RLS,
    # so counting each tenant's companies from an unbound platform session
    # would silently return zero for everyone (current_tenant_id() is NULL,
    # and NULL never equals anything). A SECURITY DEFINER function, same
    # pattern as login_lookup() in migration 0005, is the one legitimate way
    # to cross that boundary read-only for a platform-level view.
    op.execute("""
        CREATE OR REPLACE FUNCTION platform_list_tenants()
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
    op.execute(f"GRANT EXECUTE ON FUNCTION platform_list_tenants() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform_list_tenants()")
    op.drop_table("platform_admins")
