"""One grant per role and scope; background jobs can report findings; query statistics.

docs/database-hardening-plan.md, W2.6, W7.3 and W9.4.

- role_assignments: a login holding the same role with the same scope twice gains nothing from
  the second row, it only makes revoking unreliable. Existing duplicates are merged (the grant
  that lasts longest is kept; the trigger from 0062 records each removal), and a unique key
  keeps it that way. Different scopes for the same role remain allowed.
- job_runs.findings: counts a job reports (the nightly integrity job's checks), summed over
  tenants, so /metrics can export them without reading tenant data.
- pg_stat_statements, for finding slow statements. Created only where the server preloads it
  (deploy/compose.yml does); elsewhere this step is skipped.

Revision ID: 0064
Revises: 0063
"""

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

GRANT_KEY = "tenant_id, user_account_id, role_id, scope_type, md5(COALESCE(scope_value, ''))"


def upgrade() -> None:
    op.execute("ALTER TABLE role_assignments NO FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DELETE FROM role_assignments ra
        USING (
            SELECT tenant_id, id, row_number() OVER (
                PARTITION BY {GRANT_KEY}
                ORDER BY expires_at DESC NULLS FIRST, granted_at, id
            ) AS rank
            FROM role_assignments
        ) ranked
        WHERE ra.tenant_id = ranked.tenant_id
          AND ra.id = ranked.id AND ranked.rank > 1
    """)
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("ALTER TABLE role_assignments FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE UNIQUE INDEX uq_role_assignments_grant ON role_assignments ({GRANT_KEY})")

    op.execute("ALTER TABLE job_runs ADD COLUMN findings jsonb")
    op.execute(
        "ALTER TABLE job_runs ADD CONSTRAINT ck_job_runs_findings "
        "CHECK (findings IS NULL OR jsonb_typeof(findings) = 'object')"
    )

    op.execute("""
        DO $$
        BEGIN
          IF current_setting('shared_preload_libraries') LIKE '%pg_stat_statements%' THEN
            CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
          END IF;
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'pg_stat_statements needs a privileged role; skipped';
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE job_runs DROP CONSTRAINT ck_job_runs_findings")
    op.execute("ALTER TABLE job_runs DROP COLUMN findings")
    op.execute("DROP INDEX uq_role_assignments_grant")
    # pg_stat_statements is left installed: other tools may use it, and it holds no data.
