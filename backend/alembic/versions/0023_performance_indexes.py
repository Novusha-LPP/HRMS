"""Performance: tenant-wide date indexes, leave-list index, inlinable RLS helper

Measured on the 2,000-employee benchmark tenant (docs/performance-baseline-2026-09-30.md):

- attendance_days had no index serving "every employee, one date / date range". The only
  candidate, (tenant_id, employment_id, work_date), skips its middle column, so the HR
  dashboard, daily analysis and reports sequentially scanned the whole table (335k rows
  removed by filter to find 2k). -> ix_attendance_tenant_date.
- /v1/time/overtime/pending scanned 337k rows to find the handful still PENDING.
  -> partial ix_attendance_ot_pending (24 ms -> 0.5 ms).
- The leave-applications list is now paged newest-first by (applied_at, id).
  -> ix_la_tenant_applied, matching that order exactly.
- current_tenant_id(), which every RLS policy calls, was SECURITY DEFINER. Postgres never
  inlines such a function, so its body ran as a separate nested statement for every
  policy check (1.15M times in a 2.5-minute load test). current_setting() needs no
  privileges, so the definer rights bought nothing. Plain STABLE SQL is inlined into each
  policy and remains usable as an index condition.

Indexes are built CONCURRENTLY (outside the migration transaction) so a production
deployment never blocks attendance writes while they build. IF NOT EXISTS makes a retry
after an interrupted build safe. If an interrupted build left an INVALID index, drop it
before re-running.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_attendance_tenant_date", "attendance_days (tenant_id, work_date)"),
    (
        "ix_attendance_ot_pending",
        "attendance_days (tenant_id, work_date) WHERE ot_status = 'PENDING'",
    ),
    (
        "ix_la_tenant_applied",
        "leave_applications (tenant_id, applied_at DESC, id DESC) WHERE archived_at IS NULL",
    ),
]


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE SECURITY INVOKER AS
        $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
    """)
    with op.get_context().autocommit_block():
        for name, definition in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute("""
        CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER AS
        $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
    """)
