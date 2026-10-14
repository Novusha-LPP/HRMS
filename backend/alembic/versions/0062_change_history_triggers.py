"""Field-level change history for people, leave and time setup, holidays, approvals, access.

docs/database-hardening-plan.md, W7.1. Org masters, payroll and integrations already record
their changes through core/change_audit.record_change(). These tables now record theirs with a
trigger, so every path is covered: the API, import scripts and plain SQL alike.

Each insert, update, archive or delete writes one entity_change_log row holding only the fields
that changed, as {"field": {"old": ..., "new": ...}} (the shape record_change uses). Bookkeeping
and secret columns are never recorded: version, timestamps, password hashes, MFA seeds, sign-in
counters. An update that changes nothing else writes nothing.

The actor is app.actor_id, which the request session sets next to app.tenant_id; anything else
(jobs, imports, the platform console) is recorded as the tenant's System account (0052).

Revision ID: 0062
Revises: 0061
"""

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

SYSTEM = "00000000-0000-0000-0000-000000000000"
# table -> entity_type written to entity_change_log
AUDITED = {
    "persons": "person",
    "employments": "employment",
    "user_accounts": "user_account",
    "role_assignments": "role_assignment",
    "leave_types": "leave_type",
    "leave_balance_buckets": "leave_bucket",
    "leave_policy_sets": "leave_policy_set",
    "leave_bucket_policies": "leave_bucket_policy",
    "leave_policy_assignments": "leave_policy_assignment",
    "policy_templates": "policy_template",
    "employee_policy_assignments": "employee_policy_assignment",
    "holidays": "holiday",
    "holiday_calendars": "holiday_calendar",
    "holiday_calendar_assignments": "holiday_calendar_assignment",
    "approval_flows": "approval_flow",
}
NEVER_RECORDED = (
    "tenant_id",
    "id",
    "version",
    "recorded_at",
    "recorded_by",
    "created_at",
    "updated_at",
    "last_login_at",
    "password_hash",
    "password_changed_at",
    "token_epoch",
    "mfa_secret",
    "mfa_pending_secret",
    "mfa_pending_at",
    "mfa_last_step",
)


def upgrade() -> None:
    skip = ", ".join(f"'{c}'" for c in NEVER_RECORDED)
    op.execute(f"""
        CREATE FUNCTION record_row_change() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          old_row jsonb := CASE WHEN TG_OP = 'INSERT' THEN '{{}}'::jsonb ELSE to_jsonb(OLD) END;
          new_row jsonb := CASE WHEN TG_OP = 'DELETE' THEN '{{}}'::jsonb ELSE to_jsonb(NEW) END;
          row_id jsonb := CASE WHEN TG_OP = 'DELETE' THEN old_row ELSE new_row END;
          diff jsonb := '{{}}'::jsonb;
          key text;
          act text;
        BEGIN
          FOR key IN SELECT jsonb_object_keys(old_row || new_row) LOOP
            CONTINUE WHEN key = ANY (ARRAY[{skip}]);
            IF (old_row -> key) IS DISTINCT FROM (new_row -> key) THEN
              diff := diff || jsonb_build_object(
                key, jsonb_build_object('old', old_row -> key, 'new', new_row -> key));
            END IF;
          END LOOP;
          IF diff = '{{}}'::jsonb THEN
            RETURN NULL;
          END IF;
          act := CASE
            WHEN TG_OP = 'INSERT' THEN 'CREATE'
            WHEN TG_OP = 'DELETE' THEN 'DELETE'
            WHEN old_row ->> 'archived_at' IS NULL AND new_row ->> 'archived_at' IS NOT NULL
              THEN 'ARCHIVE'
            ELSE 'UPDATE' END;
          INSERT INTO entity_change_log
            (tenant_id, id, entity_type, entity_id, action, changes, changed_by, changed_at)
          VALUES (
            (row_id ->> 'tenant_id')::uuid, gen_random_uuid(), TG_ARGV[0],
            (row_id ->> 'id')::uuid, act, diff,
            COALESCE(NULLIF(current_setting('app.actor_id', true), '')::uuid, '{SYSTEM}'),
            now());
          RETURN NULL;
        END $$
    """)
    for table, entity in AUDITED.items():
        op.execute(
            f"CREATE TRIGGER record_{table}_change AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION record_row_change('{entity}')"
        )


def downgrade() -> None:
    for table in AUDITED:
        op.execute(f"DROP TRIGGER record_{table}_change ON {table}")
    op.execute("DROP FUNCTION record_row_change()")
