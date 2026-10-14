"""One row-level-security policy everywhere, and history the app can't rewrite.

docs/database-hardening-plan.md, W5.1 and W5.2.

- The three holiday-calendar tables cast current_setting('app.tenant_id') straight to uuid, so
  any query without a tenant set failed with "invalid input syntax for type uuid" instead of
  returning no rows. api_keys and import_batches spelled the same rule with NULLIF. All five
  now use the standard policy, tenant_id = current_tenant_id(), and import_batches forces RLS
  like every other tenant table.
- Approval events, leave and correction approval actions, recruitment events and the platform
  audit log are history: the app role may add and read rows, not change or delete them.
  Deletes that cascade from a parent (erasing a candidate) run as the table owner and still work.

Revision ID: 0055
Revises: 0054
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"
POLICY_TABLES = {
    "holiday_calendars": "(tenant_id = (current_setting('app.tenant_id', true))::uuid)",
    "holiday_calendar_assignments": "(tenant_id = (current_setting('app.tenant_id', true))::uuid)",
    "holiday_calendar_days": "(tenant_id = (current_setting('app.tenant_id', true))::uuid)",
    "api_keys": "(tenant_id = (NULLIF(current_setting('app.tenant_id', true), ''))::uuid)",
    "import_batches": "(tenant_id = (NULLIF(current_setting('app.tenant_id', true), ''))::uuid)",
}
HISTORY = (
    "approval_events",
    "leave_approval_actions",
    "correction_approval_actions",
    "recruitment_events",
    "platform_audit_log",
)


def upgrade() -> None:
    for table in POLICY_TABLES:
        for sql in kit.replace_tenant_policy(table):
            op.execute(sql)
    for table in HISTORY:
        op.execute(kit.make_append_only(table))


def downgrade() -> None:
    for table in HISTORY:
        op.execute(f"GRANT UPDATE, DELETE ON {table} TO {APP_ROLE}")
    for table, expression in POLICY_TABLES.items():
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING {expression} WITH CHECK {expression}"
        )
    op.execute("ALTER TABLE import_batches NO FORCE ROW LEVEL SECURITY")
