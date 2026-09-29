"""Account security, login throttling, indexed login lookup, failed scheduled actions.

- user_accounts.must_change_password / password_changed_at / token_epoch — forced
  first-login password change (imported / admin-reset accounts) and revocation
  of every token issued before a password change. Tokens carry the account's
  epoch and are refused once it moves on; a counter (unlike a timestamp) is
  exact and immune to clock skew between API hosts.
- auth_throttle — DB-backed attempt counters for login and public registration.
- login_lookup() rewritten. 0018 turned the old single indexed predicate into an
  OR-chain with a per-row regex, which forced a sequential scan of every
  account in every tenant on each (unauthenticated) login (~0.5 s at 100k
  accounts) and returned an arbitrary row when an identifier was ambiguous.
  It now has one indexable branch per identifier kind, prefers ACTIVE accounts,
  and returns up to five candidates so the caller can settle ambiguity by
  password instead of guessing. EXECUTE is revoked from PUBLIC.
- personnel_actions.failure_reason — a scheduled action that can no longer be
  applied is parked as FAILED with a reason instead of breaking every request.
- tenant foreign keys — eight tenant-scoped tables created in migration 0003 never
  got the tenant_id -> tenants(id) foreign key every other tenant table has.
- kyc_access_log — who opened someone else's KYC dossier or documents (append-only:
  the app role is granted INSERT and SELECT only).

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"

# Created by migration 0003 without the tenant foreign key.
TENANT_FK_GAPS = (
    "attendance_correction_requests",
    "correction_approval_actions",
    "employee_policy_assignments",
    "leave_applications",
    "leave_approval_actions",
    "leave_balances",
    "leave_types",
    "policy_templates",
)


def _login_lookup_sql(name: str, params: str, tenant_filter: str) -> str:
    """
    One branch per identifier kind, each answerable from an index; ACTIVE accounts first;
    up to five candidates so the caller can settle ambiguity by password (or company code)
    rather than by a coin toss. `tenant_filter` narrows every branch to one company.
    """
    branches = [
        "lower(ua.email) = lower(btrim(p_identifier))",
        "lower(ua.employee_code) = lower(btrim(p_identifier))",
        "ua.mobile = btrim(p_identifier)",
        r"""length(regexp_replace(btrim(p_identifier), '\D', '', 'g')) >= 10
                  AND right(regexp_replace(ua.mobile, '\D', '', 'g'), 10)
                      = right(regexp_replace(btrim(p_identifier), '\D', '', 'g'), 10)""",
    ]
    union = "\n                UNION ALL\n".join(
        f"""                SELECT ua.tenant_id, ua.id, ua.password_hash, ua.status, ua.employment_id,
                       ua.created_at
                FROM user_accounts ua
                WHERE length(btrim(p_identifier)) > 0 {tenant_filter}
                  AND {branch}"""
        for branch in branches
    )
    return f"""
    CREATE OR REPLACE FUNCTION {name}({params})
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
        SELECT c.tenant_id, c.id, c.password_hash, c.status, c.employment_id
        FROM (
            SELECT DISTINCT ON (m.tenant_id, m.id) m.*
            FROM (
{union}
            ) m
            ORDER BY m.tenant_id, m.id
        ) c
        ORDER BY (c.status = 'ACTIVE') DESC, c.created_at, c.id
        LIMIT 5
    $$;
"""


LOGIN_LOOKUP_V19 = _login_lookup_sql("login_lookup", "p_identifier text", "")
# The same lookup inside one company, for when the identifier exists in several.
LOGIN_LOOKUP_IN_V19 = _login_lookup_sql(
    "login_lookup_in",
    "p_identifier text, p_tenant_slug text",
    "AND ua.tenant_id = (SELECT t.id FROM tenants t WHERE lower(t.slug) = lower(btrim(p_tenant_slug)))",
)

# What 0018 installed — restored by downgrade().
LOGIN_LOOKUP_V18 = r"""
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
        SELECT tenant_id, id, password_hash, status, employment_id
        FROM user_accounts
        WHERE (
            lower(email) = lower(trim(p_identifier))
            OR lower(employee_code) = lower(trim(p_identifier))
            OR mobile = trim(p_identifier)
            OR (
                length(regexp_replace(trim(p_identifier), '\D', '', 'g')) >= 10
                AND (
                    mobile = right(regexp_replace(trim(p_identifier), '\D', '', 'g'), 10)
                    OR regexp_replace(mobile, '\D', '', 'g')
                       = regexp_replace(trim(p_identifier), '\D', '', 'g')
                )
            )
        )
        LIMIT 1;
    $$;
"""


def upgrade() -> None:
    # ── 1. account security ─────────────────────────────────────────────────
    op.add_column(
        "user_accounts",
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "user_accounts", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user_accounts",
        sa.Column("token_epoch", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # ── 2. attempt counters ─────────────────────────────────────────────────
    op.create_table(
        "auth_throttle",
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("scope", "key_hash", name="pk_auth_throttle"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON auth_throttle TO {APP_ROLE}")

    # ── 3. cross-tenant indexes for login_lookup (deliberately NOT unique:
    #      employee codes and mobile numbers are only unique within a tenant,
    #      and family members can share a phone) ─────────────────────────────
    op.execute(
        "CREATE INDEX ix_user_accounts_login_code ON user_accounts (lower(employee_code)) "
        "WHERE employee_code IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_user_accounts_login_mobile ON user_accounts (mobile) "
        "WHERE mobile IS NOT NULL"
    )
    op.execute(
        r"CREATE INDEX ix_user_accounts_login_mobile10 ON user_accounts "
        r"((right(regexp_replace(mobile, '\D', '', 'g'), 10))) WHERE mobile IS NOT NULL"
    )

    # ── 4. parked scheduled actions ─────────────────────────────────────────
    op.add_column(
        "personnel_actions", sa.Column("failure_reason", sa.String(length=500), nullable=True)
    )
    op.create_index(
        "ix_personnel_actions_due",
        "personnel_actions",
        ["tenant_id", "effective_date"],
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )

    # ── 5. KYC access log ───────────────────────────────────────────────────
    op.create_table(
        "kyc_access_log",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("unmasked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_kyc_access_log"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employment_id"],
            ["employments.tenant_id", "employments.id"],
            name="fk_kyc_access_log_employment_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_account_id"],
            ["user_accounts.tenant_id", "user_accounts.id"],
            name="fk_kyc_access_log_actor_user_account_id",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_kyc_access_log_employment",
        "kyc_access_log",
        ["tenant_id", "employment_id", "occurred_at"],
    )
    op.execute("ALTER TABLE kyc_access_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kyc_access_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON kyc_access_log
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)
    # Append-only for the running app: no UPDATE, no DELETE. (Migration 0005 set
    # default privileges, so a new table starts out fully writable by the app
    # role — that has to be taken away explicitly, not just left ungranted.)
    op.execute(f"REVOKE ALL ON kyc_access_log FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON kyc_access_log TO {APP_ROLE}")

    # ── 6. tenant foreign keys (validated: a stray tenant_id fails the migration
    #      loudly, and the transaction rolls back, rather than being ignored) ──
    for table in TENANT_FK_GAPS:
        op.create_foreign_key(f"{table}_tenant_id_fkey", table, "tenants", ["tenant_id"], ["id"])

    # ── 7. login_lookup ─────────────────────────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS login_lookup(text)")
    op.execute(LOGIN_LOOKUP_V19)
    op.execute("REVOKE ALL ON FUNCTION login_lookup(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup(text) TO {APP_ROLE}")
    op.execute(LOGIN_LOOKUP_IN_V19)
    op.execute("REVOKE ALL ON FUNCTION login_lookup_in(text, text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup_in(text, text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS login_lookup_in(text, text)")
    for table in reversed(TENANT_FK_GAPS):
        op.drop_constraint(f"{table}_tenant_id_fkey", table, type_="foreignkey")

    op.drop_table("kyc_access_log")

    op.execute("DROP FUNCTION IF EXISTS login_lookup(text)")
    op.execute(LOGIN_LOOKUP_V18)
    op.execute(f"GRANT EXECUTE ON FUNCTION login_lookup(text) TO {APP_ROLE}")

    op.drop_index("ix_personnel_actions_due", table_name="personnel_actions")
    # Older code has no FAILED status; CANCELLED is the closest existing meaning.
    op.execute("UPDATE personnel_actions SET status = 'CANCELLED' WHERE status = 'FAILED'")
    op.drop_column("personnel_actions", "failure_reason")

    op.execute("DROP INDEX IF EXISTS ix_user_accounts_login_mobile10")
    op.execute("DROP INDEX IF EXISTS ix_user_accounts_login_mobile")
    op.execute("DROP INDEX IF EXISTS ix_user_accounts_login_code")

    op.drop_table("auth_throttle")

    op.drop_column("user_accounts", "token_epoch")
    op.drop_column("user_accounts", "password_changed_at")
    op.drop_column("user_accounts", "must_change_password")
