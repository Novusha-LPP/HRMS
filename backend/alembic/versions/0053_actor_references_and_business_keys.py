"""Who-did-it columns reference real rows; the remaining references and business keys.

docs/database-hardening-plan.md, W2.3, W2.4 and W2.6.

- Actor columns: 39 hold a login (user_accounts; background jobs use the System account from
  0052) and 3 hold the acting employee (employments): attendance_days.ot_reviewed_by,
  comp_off_grants.granted_by and leave_encashments.processed_by, which the API reports as
  employment ids.
- Four references that had no key: external_identities.user_account_id,
  onboarding_items.integration_app_id, integration_events.employment_id and .origin_app_id.
- Business keys, case-insensitive and ignoring archived rows where the table archives: codes
  of leave types, jobs, grades and cost centres, company names, a calendar's holidays, and
  employee numbers per company. Live punches (not correction rows) are unique per employee,
  instant and type, so re-importing device or app punches can't double them.

Every key is added NOT VALID and then validated, so existing rows are checked without a long
lock; scripts/db_preflight.py counts what would fail beforehand.

Revision ID: 0053
Revises: 0052
"""

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

LOGIN_ACTORS = (
    ("api_keys", "created_by"),
    ("api_keys", "revoked_by"),
    ("assignments", "recorded_by"),
    ("attendance_correction_requests", "recorded_by"),
    ("attendance_days", "reviewed_by"),
    ("connected_apps", "created_by"),
    ("correction_approval_actions", "recorded_by"),
    ("employee_id_schemes", "recorded_by"),
    ("employee_kyc_documents", "uploaded_by"),
    ("employee_kyc_documents", "verified_by"),
    ("employee_kyc_records", "updated_by"),
    ("employee_kyc_records", "verified_by"),
    ("employee_policy_assignments", "recorded_by"),
    ("employments", "recorded_by"),
    ("holidays", "recorded_by"),
    ("integration_mappings", "created_by"),
    ("integration_profiles", "created_by"),
    ("integration_profiles", "published_by"),
    ("leave_applications", "recorded_by"),
    ("leave_approval_actions", "recorded_by"),
    ("leave_balance_buckets", "recorded_by"),
    ("leave_balance_transactions", "approved_by"),
    ("leave_balance_transactions", "recorded_by"),
    ("leave_balances", "recorded_by"),
    ("leave_bucket_policies", "recorded_by"),
    ("leave_policy_assignments", "recorded_by"),
    ("leave_policy_sets", "recorded_by"),
    ("leave_type_bucket_mapping", "recorded_by"),
    ("leave_types", "recorded_by"),
    ("legal_entities", "recorded_by"),
    ("locations", "recorded_by"),
    ("onboarding_items", "completed_by"),
    ("org_units", "recorded_by"),
    ("personnel_actions", "recorded_by"),
    ("persons", "recorded_by"),
    ("policy_templates", "recorded_by"),
    ("possible_duplicates", "resolved_by"),
    ("punches", "recorded_by"),
    ("report_definitions", "created_by"),
)
EMPLOYEE_ACTORS = (
    ("attendance_days", "ot_reviewed_by"),
    ("comp_off_grants", "granted_by"),
    ("leave_encashments", "processed_by"),
)
OTHER_REFERENCES = (
    ("external_identities", "user_account_id", "user_accounts"),
    ("onboarding_items", "integration_app_id", "connected_apps"),
    ("integration_events", "employment_id", "employments"),
    ("integration_events", "origin_app_id", "connected_apps"),
)
# (name, table, key, predicate) — small tables, built inside the transaction.
UNIQUE_KEYS = (
    ("uq_leave_types_code", "leave_types", "tenant_id, lower(code)", "archived_at IS NULL"),
    ("uq_legal_entities_name", "legal_entities", "tenant_id, lower(name)", "archived_at IS NULL"),
    ("uq_jobs_code", "jobs", "tenant_id, lower(code)", "archived_at IS NULL AND code IS NOT NULL"),
    ("uq_grades_code", "grades", "tenant_id, lower(code)", "archived_at IS NULL"),
    ("uq_cost_centres_code", "cost_centres", "tenant_id, lower(code)", "archived_at IS NULL"),
    (
        "uq_holidays_calendar_day",
        "holidays",
        "tenant_id, calendar_id, holiday_date, lower(name)",
        "archived_at IS NULL AND calendar_id IS NOT NULL",
    ),
    (
        "uq_employments_number_ci",
        "employments",
        "tenant_id, legal_entity_id, lower(employee_number)",
        None,
    ),
)


def _add_fk(table: str, column: str, target: str) -> None:
    name = f"fk_{table}_{column}"
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {column}) "
        f"REFERENCES {target}(tenant_id, id) DEFERRABLE INITIALLY DEFERRED NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    for table, column in LOGIN_ACTORS:
        _add_fk(table, column, "user_accounts")
    for table, column in EMPLOYEE_ACTORS:
        _add_fk(table, column, "employments")
    for table, column, target in OTHER_REFERENCES:
        _add_fk(table, column, target)
    for name, table, key, predicate in UNIQUE_KEYS:
        where = f" WHERE {predicate}" if predicate else ""
        op.execute(f"CREATE UNIQUE INDEX {name} ON {table} ({key}){where}")
    # punches can be large: build without blocking punch-ins.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY uq_punches_live ON punches "
            "(tenant_id, employment_id, punched_at, punch_type) WHERE NOT is_corrected"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_punches_live")
    for name, _, _, _ in UNIQUE_KEYS:
        op.execute(f"DROP INDEX {name}")
    for table, column, _ in OTHER_REFERENCES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT fk_{table}_{column}")
    for table, column in LOGIN_ACTORS + EMPLOYEE_ACTORS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT fk_{table}_{column}")
