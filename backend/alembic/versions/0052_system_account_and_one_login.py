"""System account per tenant, one login per employee, one email index.

docs/database-hardening-plan.md, W2.1, W2.2 and W2.7.

- Every tenant gets a "System" account (id 00000000-0000-0000-0000-000000000000, status
  SYSTEM, no email, password or employment), so background jobs that write SYSTEM_ACTOR into
  recorded_by and similar columns point at a real row and those columns can carry foreign keys
  (0053). A trigger on tenants creates it, so every way of creating a tenant gets one. It can't
  sign in: login looks accounts up by email, employee number, code or mobile, and it has none.
- An employee has at most one login: UNIQUE (tenant_id, employment_id). If the data already
  holds duplicates the migration stops and says so; which login to keep is an HR decision
  (scripts/db_preflight.py counts them beforehand).
- ix_user_accounts_email_unique (email) duplicated uq_account_email_lower (lower(email)), which
  already makes emails unique across all tenants, case-insensitively.

Revision ID: 0052
Revises: 0051
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

SYSTEM = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    # Owner writes across tenants: lift forced RLS for the owner while doing them (as in 0028).
    op.execute("ALTER TABLE user_accounts NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        DECLARE duplicates bigint;
        BEGIN
          SELECT COALESCE(sum(n - 1), 0) INTO duplicates FROM (
            SELECT count(*) AS n FROM user_accounts WHERE employment_id IS NOT NULL
            GROUP BY tenant_id, employment_id HAVING count(*) > 1) d;
          IF duplicates > 0 THEN
            RAISE EXCEPTION '% employee login(s) duplicate another login of the same employee. '
              'Decide which to keep (scripts/db_preflight.py --ids), then migrate again.',
              duplicates;
          END IF;
        END $$
    """)
    op.execute(f"""
        INSERT INTO user_accounts (tenant_id, id, status, must_change_password)
        SELECT id, '{SYSTEM}', 'SYSTEM', false FROM tenants
        ON CONFLICT (tenant_id, id) DO NOTHING
    """)
    # The insert queued deferred foreign-key checks; run them now, before altering the table.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("ALTER TABLE user_accounts FORCE ROW LEVEL SECURITY")

    # Runs as the owner (SECURITY DEFINER) and points RLS at the new tenant for its one insert,
    # restoring the caller's tenant afterwards.
    op.execute(f"""
        CREATE FUNCTION create_system_account() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE previous text := current_setting('app.tenant_id', true);
        BEGIN
          PERFORM set_config('app.tenant_id', NEW.id::text, true);
          INSERT INTO user_accounts (tenant_id, id, status, must_change_password)
          VALUES (NEW.id, '{SYSTEM}', 'SYSTEM', false)
          ON CONFLICT (tenant_id, id) DO NOTHING;
          PERFORM set_config('app.tenant_id', COALESCE(previous, ''), true);
          RETURN NEW;
        END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION create_system_account() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER tenants_system_account AFTER INSERT ON tenants "
        "FOR EACH ROW EXECUTE FUNCTION create_system_account()"
    )

    op.execute(
        "CREATE UNIQUE INDEX uq_user_accounts_employment ON user_accounts "
        "(tenant_id, employment_id) WHERE employment_id IS NOT NULL"
    )
    op.execute("DROP INDEX ix_user_accounts_email_unique")


def downgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ix_user_accounts_email_unique ON user_accounts (email) "
        "WHERE email IS NOT NULL"
    )
    op.execute("DROP INDEX uq_user_accounts_employment")
    op.execute("DROP TRIGGER tenants_system_account ON tenants")
    op.execute("DROP FUNCTION create_system_account()")
    op.execute("ALTER TABLE user_accounts NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM user_accounts WHERE id = '{SYSTEM}' AND status = 'SYSTEM'")
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("ALTER TABLE user_accounts FORCE ROW LEVEL SECURITY")
