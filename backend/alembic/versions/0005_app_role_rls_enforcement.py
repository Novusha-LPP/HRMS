"""Make row-level security an active enforcement layer, not decoration.

The Postgres role the app has been connecting as (hrms) is a superuser with
BYPASSRLS, so every RLS policy created in 0001-0003 has been silently
ignored — tenant isolation has only ever been the application's own
`WHERE tenant_id = ...` filters. This migration creates a NOSUPERUSER,
NOBYPASSRLS role (hrms_app) for the running application to connect as
instead (see HRMS_APP_DATABASE_URL / core/database.py), so a query that
forgets its tenant filter is still blocked by Postgres itself.

Login is the one legitimate cross-tenant lookup (you don't know your tenant
until you've been identified by email), so it goes through a narrow
SECURITY DEFINER function that returns only the columns login needs, rather
than granting hrms_app any broader bypass.

Revision ID: 0005
Revises: 0004
"""

import os

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"
# The published development default. A production deployment sets HRMS_APP_ROLE_PASSWORD before
# running migrations (and core/config.py refuses to start in production while the app is still
# configured with this value). Only takes effect when the role is first created.
APP_ROLE_PASSWORD = os.environ.get("HRMS_APP_ROLE_PASSWORD", "hrms_app_dev_password")


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE_PASSWORD.replace("'", "''")}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
    """)

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )
    # tenants has no RLS policy (root of the isolation boundary, see
    # kernel/models.py) — that's fine, it holds no per-tenant secrets.

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
            LIMIT 1
        $$;
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS login_lookup(text)")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
