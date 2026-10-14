"""Every table says what it holds (COMMENT ON TABLE).

docs/database-hardening-plan.md, W10.1. Rule L13 requires a comment on every new table;
migration_kit.tenant_table() takes one.

Revision ID: 0057
Revises: 0056
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

COMMENTS = {
    # Platform
    "tenants": "A customer organisation. Every tenant-scoped row belongs to exactly one.",
    "platform_admins": "Operators of the platform console. Not tenant users.",
    "platform_audit_log": "Append-only record of what platform admins did.",
    "platform_password_reset_tokens": "One-time password-reset links for platform admins.",
    "auth_throttle": "Failed-attempt counters and lockouts for sign-in and similar endpoints.",
    "job_runs": "One row per background job run, across all tenants, for monitoring.",
    "tenant_job_checkpoints": "The last period a background job completed for a tenant.",
    # Access
    "user_accounts": (
        "A login. At most one per employee. Each tenant has one SYSTEM account "
        "(id 0) that background jobs act as; it cannot sign in."
    ),
    "roles": "Roles a tenant can grant (built-in ones are is_system).",
    "role_assignments": "A role granted to a login, with the scope it applies to.",
    "user_preferences": "Per-login display preferences (theme, dashboard style).",
    "dashboard_layouts": "Per-login widget layout of a dashboard.",
    # Organisation
    "legal_entities": "A company of the tenant: the employer of record.",
    "locations": "A place people work (office, plant, site), optionally tied to a company.",
    "org_units": "Departments and teams, as a tree within a company.",
    "jobs": "Job titles (designations).",
    "grades": "Pay grades or bands, ordered by sequence.",
    "cost_centres": "Cost centres that assignments and units are charged to.",
    "positions": "Budgeted seats in an org unit, for a job and grade.",
    "employee_id_schemes": "How new employee numbers are generated, per company or tenant-wide.",
    # People
    "persons": "A human being. One person can have several employments over time.",
    "employments": "A person's employment with one company: the employee record.",
    "assignments": (
        "Where an employment sits over time (unit, location, job, grade, position). "
        "No overlaps; effective_to is exclusive."
    ),
    "assignment_managers": (
        "Who manages an assignment over time, by manager type. "
        "No overlaps per type; effective_to is exclusive."
    ),
    "personnel_actions": "Hires, transfers, promotions, separations and similar changes.",
    "employee_kyc_records": "An employee's identity, statutory and bank details (encrypted).",
    "employee_kyc_documents": "Uploaded KYC documents and their verification status.",
    "kyc_access_log": "Append-only record of who viewed or unmasked KYC data.",
    # Onboarding
    "onboarding_templates": "Reusable onboarding checklists.",
    "onboarding_template_items": "The tasks of an onboarding template.",
    "onboarding_cases": "An onboarding checklist started for one new employee.",
    "onboarding_items": "One task of an onboarding case and its progress.",
    # Time and attendance
    "policy_templates": "Attendance rules: working hours, grace, half day, overtime.",
    "employee_policy_assignments": (
        "Which attendance policy applies to an employee, unit or company from a date. "
        "The latest start wins; effective_to is inclusive."
    ),
    "punches": (
        "Clock-in and clock-out events. Never edited: corrections add rows "
        "(is_corrected), and VOID rows cancel earlier ones."
    ),
    "attendance_days": "The calculated attendance of one employee on one work date.",
    "attendance_correction_requests": "A request to correct a day's attendance, and its status.",
    "correction_approval_actions": "Append-only decisions on attendance correction requests.",
    "holidays": "A holiday, either in the tenant's library or on a calendar.",
    "holiday_calendars": "A named list of holidays for a year.",
    "holiday_calendar_days": "The holidays a calendar contains.",
    "holiday_calendar_assignments": (
        "Which calendar an employee, unit, company or the whole tenant follows. "
        "One per target at a time; effective_to is inclusive."
    ),
    "comp_off_grants": "Compensatory leave earned for working on an off day.",
    # Leave
    "leave_types": "Kinds of leave and their application rules.",
    "leave_balance_buckets": "Balances that one or more leave types draw from.",
    "leave_type_bucket_mapping": "Which bucket each leave type draws from.",
    "leave_policy_sets": "A named set of leave entitlements.",
    "leave_bucket_policies": "The entitlement rules of a bucket within a policy set.",
    "leave_policy_assignments": (
        "Which leave policy set applies to an employee, unit or company from a date. "
        "The latest start wins; effective_to is inclusive."
    ),
    "leave_balances": "Yearly balance per employee and leave type.",
    "leave_monthly_ledger": "Monthly movement of each bucket per employee, opening to closing.",
    "leave_balance_transactions": "Append-only ledger of every change to a leave balance.",
    "leave_applications": "A request for leave and its status.",
    "leave_approval_actions": "Append-only decisions on leave applications.",
    "leave_encashments": "Leave days paid out instead of taken.",
    # Approvals
    "approval_flows": "Configured approval routes for a request type.",
    "employee_approval_flows": "The approval flow chosen for one employee and request type.",
    "approval_instances": "A running approval of one request, with a snapshot of its steps.",
    "approval_delegations": "Temporary hand-over of an approver's authority.",
    "approval_events": "Append-only history of approval decisions and delegations.",
    # Recruitment
    "recruitment_stages": "Pipeline stages a tenant uses for candidates.",
    "job_openings": "A requisition to hire, its approval and status.",
    "candidates": "People who applied or were sourced.",
    "job_applications": "A candidate in the pipeline of one opening.",
    "recruitment_events": "Append-only history of what happened to openings and applications.",
    # Payroll
    "statutory_rules": "Statutory values (PF, ESIC and similar) by rule and date, verified.",
    "pay_components": "Earnings, deductions and contributions a salary is built from.",
    "salary_structures": "Versioned salary templates; a published version is never edited.",
    "salary_structure_lines": "How one component of a salary structure is calculated.",
    "employee_compensations": "An employee's salary over time. No overlaps.",
    # Reports
    "report_definitions": "Saved report layouts and filters.",
    "daily_report_snapshots": "Cached daily report results per login, kept until expiry.",
    "daily_report_rows": "The rows of a cached daily report.",
    "entity_change_log": "Append-only field-level history of changes to master data.",
    "import_batches": "Records of bulk imports from other systems.",
    # Integrations
    "connected_apps": "Outside systems a tenant connects (ERP, CRM, BI).",
    "api_keys": "Credentials a connected app uses; stored as hashes.",
    "external_identities": "An employee's id in a connected app.",
    "integration_mappings": "A connected app's values mapped to HRMS companies, units and roles.",
    "integration_profiles": "Versioned settings of a connected app; published versions are frozen.",
    "integration_requests": "Log of every sync request from a connected app (retention-pruned).",
    "integration_events": "Outbox of employee changes for connected apps to read.",
    "integration_app_events": "Each app's position in the events feed.",
    "integration_cursors": "How far each app has read the events feed.",
    "integration_rate_windows": "Per-key request counters for rate limiting.",
    "possible_duplicates": "Records from an app that look like an existing employee.",
}


def upgrade() -> None:
    for table, text in COMMENTS.items():
        op.execute(kit.table_comment(table, text))


def downgrade() -> None:
    for table in COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
