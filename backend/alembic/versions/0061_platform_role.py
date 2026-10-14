"""The platform console gets its own database login; tenant requests lose the platform tables.

docs/database-hardening-plan.md, W5.3 and decision DB-D3. Until now the role every tenant
request runs as (hrms_app) could read and write platform_admins (password hashes, MFA seeds),
their reset tokens and the platform audit log. Now only hrms_platform can.

hrms_platform is, like hrms_app, NOBYPASSRLS: when the console provisions a tenant it works
under row-level security exactly as the app does. It may not rewrite history either (the same
append-only revokes as hrms_app).

The development password below only applies when the role is first created; deployed
environments set HRMS_PLATFORM_ROLE_PASSWORD (python -m hrms.deploy migrate sets it on the
role, and core/config.py refuses the development password outside local development).

Revision ID: 0061
Revises: 0060
"""

import os

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"
PLATFORM_ROLE = "hrms_platform"
PLATFORM_ROLE_PASSWORD = os.environ.get(
    "HRMS_PLATFORM_ROLE_PASSWORD", "hrms_platform_dev_password"
)
PLATFORM_ONLY = ("platform_admins", "platform_password_reset_tokens", "platform_audit_log")
# History neither role may rewrite (0021, 0055 and the integration sync log's UPDATE revoke).
APPEND_ONLY = (
    "entity_change_log",
    "kyc_access_log",
    "leave_balance_transactions",
    "approval_events",
    "leave_approval_actions",
    "correction_approval_actions",
    "recruitment_events",
    "platform_audit_log",
)


def upgrade() -> None:
    password = PLATFORM_ROLE_PASSWORD.replace("'", "''")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                CREATE ROLE {PLATFORM_ROLE} LOGIN PASSWORD '{password}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {PLATFORM_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {PLATFORM_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {PLATFORM_ROLE}"
    )
    for table in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE UPDATE ON integration_requests FROM {PLATFORM_ROLE}")
    for table in PLATFORM_ONLY:
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    for table in PLATFORM_ONLY:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON platform_audit_log FROM {APP_ROLE}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {PLATFORM_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {PLATFORM_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PLATFORM_ROLE}")
    # The role is cluster-wide and may hold privileges in other databases on the same server
    # (development and CI clusters), so it stays, with no access to this one.
