"""Real authentication + authorization scoping support.

Adds password/JWT login (user_accounts.password_hash, .employment_id),
uniqueness for email lookup, and indexes that make per-request scope
resolution (role_assignments -> legal entities / org units / reports) fast.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("password_hash", sa.String(255)))
    op.add_column("user_accounts", sa.Column("employment_id", UUID(as_uuid=True)))

    # Login resolves the tenant from the email itself, so the address must be
    # globally unique (not just per-tenant) — see core/authn.py.
    op.create_index(
        "ix_user_accounts_email_unique",
        "user_accounts",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # Every authenticated request resolves scope via this lookup.
    op.create_index(
        "ix_role_assignments_user",
        "role_assignments",
        ["tenant_id", "user_account_id"],
    )

    # Scope filters join employments -> legal_entity_id on almost every list query.
    op.create_index(
        "ix_employments_legal_entity",
        "employments",
        ["tenant_id", "legal_entity_id"],
    )

    # Manager-chain resolution (direct/all reports) walks this on every request.
    op.create_index(
        "ix_assignment_managers_manager",
        "assignment_managers",
        ["tenant_id", "manager_employment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_managers_manager", table_name="assignment_managers")
    op.drop_index("ix_employments_legal_entity", table_name="employments")
    op.drop_index("ix_role_assignments_user", table_name="role_assignments")
    op.drop_index("ix_user_accounts_email_unique", table_name="user_accounts")
    op.drop_column("user_accounts", "employment_id")
    op.drop_column("user_accounts", "password_hash")
