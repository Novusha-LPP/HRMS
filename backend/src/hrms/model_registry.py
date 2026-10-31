"""
Complete model metadata for the application and Alembic.

The migrations are hand-written and are the source of truth for the schema; the
models exist for the ORM. Where the two legitimately differ in ways the model
classes can't express (composite tenant-aware foreign keys, constraints added by
migration), this module declares them so that `alembic check` — run in CI — can
tell a real omission (a model field with no migration) from noise, and so that
autogenerate never proposes to undo something a migration deliberately did.
"""

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import SQLModel

from hrms.jobs import models as jobs  # noqa: F401
from hrms.modules.approvals import models as approvals  # noqa: F401
from hrms.modules.branding import models as branding  # noqa: F401
from hrms.modules.corrections import models as corrections  # noqa: F401
from hrms.modules.dashboard import models as dashboard  # noqa: F401
from hrms.modules.kernel import models as kernel  # noqa: F401
from hrms.modules.kyc import models as kyc  # noqa: F401
from hrms.modules.leave import models as leave  # noqa: F401
from hrms.modules.onboarding import models as onboarding  # noqa: F401
from hrms.modules.org import models as org  # noqa: F401
from hrms.modules.payroll import models as payroll  # noqa: F401
from hrms.modules.people import models as people  # noqa: F401
from hrms.modules.policy import models as policy  # noqa: F401
from hrms.modules.preferences import models as preferences  # noqa: F401
from hrms.modules.recruitment import models as recruitment  # noqa: F401
from hrms.modules.reminders import models as reminders  # noqa: F401
from hrms.modules.reports import models as reports  # noqa: F401
from hrms.modules.time import models as time  # noqa: F401

metadata = SQLModel.metadata

# References include tenant_id, so a UUID belonging to another tenant cannot be linked.
RELATIONS = {
    "approval_flows": {
        "org_unit_id": "org_units",
        "employment_id": "employments",
        "owner_employment_id": "employments",
        "legal_entity_id": "legal_entities",
        "updated_by": "user_accounts",
    },
    "employee_approval_flows": {"employment_id": "employments", "updated_by": "user_accounts"},
    "approval_instances": {"flow_id": "approval_flows", "employment_id": "employments"},
    "approval_delegations": {
        "flow_id": "approval_flows",
        "instance_id": "approval_instances",
        "original_user_id": "user_accounts",
        "delegate_user_id": "user_accounts",
        "created_by": "user_accounts",
        "revoked_by": "user_accounts",
    },
    "approval_events": {
        "flow_id": "approval_flows",
        "instance_id": "approval_instances",
        "actor_user_id": "user_accounts",
    },
    "role_assignments": {"user_account_id": "user_accounts", "role_id": "roles"},
    "user_accounts": {"employment_id": "employments"},
    "locations": {"legal_entity_id": "legal_entities"},
    "org_units": {
        "legal_entity_id": "legal_entities",
        "parent_id": "org_units",
        "location_id": "locations",
        "cost_centre_id": "cost_centres",
    },
    "positions": {"org_unit_id": "org_units", "job_id": "jobs", "grade_id": "grades"},
    "employments": {"person_id": "persons", "legal_entity_id": "legal_entities"},
    "reminder_rules": {
        "legal_entity_id": "legal_entities",
        "org_unit_id": "org_units",
        "created_by": "user_accounts",
        "updated_by": "user_accounts",
    },
    "reminder_outbox": {"rule_id": "reminder_rules"},
    "assignments": {
        "employment_id": "employments",
        "org_unit_id": "org_units",
        "location_id": "locations",
        "job_id": "jobs",
        "grade_id": "grades",
        "position_id": "positions",
        "cost_centre_id": "cost_centres",
    },
    "assignment_managers": {"assignment_id": "assignments", "manager_employment_id": "employments"},
    "personnel_actions": {"employment_id": "employments"},
    "employment_spells": {"employment_id": "employments", "created_by": "user_accounts"},
    "leave_separation_rules": {
        "legal_entity_id": "legal_entities",
        "leave_type_id": "leave_types",
        "created_by": "user_accounts",
    },
    "leave_separation_settlements": {
        "employment_id": "employments",
        "spell_id": "employment_spells",
        "leave_type_id": "leave_types",
        "bucket_id": "leave_balance_buckets",
        "balance_transaction_id": "leave_balance_transactions",
        "created_by": "user_accounts",
    },
    "rejoin_policies": {"legal_entity_id": "legal_entities", "created_by": "user_accounts"},
    "company_transfers": {
        "person_id": "persons",
        "from_employment_id": "employments",
        "to_employment_id": "employments",
        "created_by": "user_accounts",
    },
    "prior_service": {
        "person_id": "persons",
        "document_id": "employee_kyc_documents",
        "created_by": "user_accounts",
    },
    "rejoin_records": {
        "employment_id": "employments",
        "personnel_action_id": "personnel_actions",
        "previous_spell_id": "employment_spells",
        "new_spell_id": "employment_spells",
        "approved_by": "user_accounts",
        "created_by": "user_accounts",
    },
    "employee_id_schemes": {"legal_entity_id": "legal_entities"},
    "employee_policy_assignments": {
        "employment_id": "employments",
        "policy_template_id": "policy_templates",
        "org_unit_id": "org_units",
        "legal_entity_id": "legal_entities",
    },
    "punches": {"employment_id": "employments", "original_punch_id": "punches"},
    "attendance_days": {"employment_id": "employments"},
    "holidays": {"legal_entity_id": "legal_entities", "calendar_id": "holiday_calendars"},
    "holiday_calendar_assignments": {
        "employment_id": "employments",
        "calendar_id": "holiday_calendars",
        "legal_entity_id": "legal_entities",
        "org_unit_id": "org_units",
    },
    "holiday_calendar_days": {"calendar_id": "holiday_calendars", "holiday_id": "holidays"},
    "leave_balances": {"employment_id": "employments", "leave_type_id": "leave_types"},
    "leave_applications": {
        "employment_id": "employments",
        "leave_type_id": "leave_types",
        "document_id": "employee_kyc_documents",
    },
    "leave_approval_actions": {
        "application_id": "leave_applications",
        "approver_employment_id": "employments",
        "approver_user_account_id": "user_accounts",
    },
    "comp_off_grants": {"employment_id": "employments"},
    "leave_encashments": {"employment_id": "employments", "leave_type_id": "leave_types"},
    "attendance_correction_requests": {"employment_id": "employments"},
    "correction_approval_actions": {
        "correction_id": "attendance_correction_requests",
        "approver_employment_id": "employments",
        "approver_user_account_id": "user_accounts",
    },
    "employee_kyc_records": {"employment_id": "employments", "person_id": "persons"},
    "employee_kyc_documents": {"employment_id": "employments"},
    "kyc_access_log": {"employment_id": "employments", "actor_user_account_id": "user_accounts"},
    "onboarding_cases": {"employment_id": "employments", "template_id": "onboarding_templates"},
    "onboarding_items": {
        "case_id": "onboarding_cases",
        "template_item_id": "onboarding_template_items",
    },
    "onboarding_template_items": {"template_id": "onboarding_templates"},
    "leave_type_bucket_mapping": {
        "leave_type_id": "leave_types",
        "bucket_id": "leave_balance_buckets",
    },
    "leave_bucket_policies": {
        "policy_set_id": "leave_policy_sets",
        "bucket_id": "leave_balance_buckets",
    },
    "leave_policy_assignments": {
        "employment_id": "employments",
        "org_unit_id": "org_units",
        "legal_entity_id": "legal_entities",
        "leave_policy_set_id": "leave_policy_sets",
    },
    "leave_monthly_ledger": {
        "employment_id": "employments",
        "bucket_id": "leave_balance_buckets",
    },
    "leave_balance_transactions": {
        "employment_id": "employments",
        "bucket_id": "leave_balance_buckets",
        "leave_type_id": "leave_types",
    },
    "entity_change_log": {"changed_by": "user_accounts"},
    "dashboard_layouts": {"user_account_id": "user_accounts"},
    "user_preferences": {"user_account_id": "user_accounts"},
    "job_openings": {
        "legal_entity_id": "legal_entities",
        "org_unit_id": "org_units",
        "job_id": "jobs",
        "location_id": "locations",
        "hiring_manager_employment_id": "employments",
        "requested_by": "user_accounts",
        "requester_employment_id": "employments",
        "approved_by": "user_accounts",
    },
    "candidates": {"created_by": "user_accounts"},
    "job_applications": {
        "stage_id": "recruitment_stages",
        "owner_user_id": "user_accounts",
        "hired_employment_id": "employments",
        "created_by": "user_accounts",
    },
    "recruitment_events": {"actor_user_id": "user_accounts"},
    "statutory_rules": {"verified_by": "user_accounts", "recorded_by": "user_accounts"},
    "pay_components": {"recorded_by": "user_accounts"},
    "salary_structures": {
        "legal_entity_id": "legal_entities",
        "supersedes_id": "salary_structures",
        "recorded_by": "user_accounts",
    },
    "salary_structure_lines": {
        "component_id": "pay_components",
        "base_component_id": "pay_components",
    },
    "employee_compensations": {
        "employment_id": "employments",
        "structure_id": "salary_structures",
        "recorded_by": "user_accounts",
    },
}
# The same tenant-aware references, removed together with their parent row.
CASCADE_RELATIONS = {
    "job_applications": {"opening_id": "job_openings", "candidate_id": "candidates"},
    "recruitment_events": {"opening_id": "job_openings", "application_id": "job_applications"},
    "salary_structure_lines": {"structure_id": "salary_structures"},
}
# Bookkeeping timestamps are `NOT NULL` in the Python models (they always carry a
# default_factory) but nullable-with-a-server-default in the database. The
# database is the truth here, so say so.
# (Tables whose migrations declare them NOT NULL are listed in _STRICT_TABLES.)
_STRICT_TABLES = {
    "approval_flows",
    "approval_instances",
    "employee_approval_flows",
    "approval_delegations",
    "approval_events",
    "api_keys",
    "job_runs",
    "import_batches",
    "auth_throttle",
    "kyc_access_log",
    "leave_balance_transactions",
    "entity_change_log",
    "dashboard_layouts",
    "user_preferences",
    "recruitment_stages",
    "job_openings",
    "candidates",
    "job_applications",
    "recruitment_events",
    "statutory_rules",
    "pay_components",
    "salary_structures",
    "employee_compensations",
    "employment_spells",
    "rejoin_records",
    "leave_separation_rules",
    "leave_separation_settlements",
    "rejoin_policies",
    "prior_service",
    "company_transfers",
    "attendance_groups",
    "attendance_group_members",
    "attendance_group_access",
    "brand_assets",
    "brand_profiles",
    "document_signatories",
    "payslip_templates",
    "reminder_rules",
    "reminder_outbox",
}
_NULLABLE_TIMESTAMPS = {
    "created_at",
    "recorded_at",
    "granted_at",
    "started_at",
    "updated_at",
    "uploaded_at",
}


def _is_datetime(column) -> bool:
    # SQLModel types datetimes with a TypeDecorator (UTCDateTime), which is not a
    # DateTime subclass — look through it to the type it wraps.
    return isinstance(getattr(column.type, "impl", column.type), DateTime)


for table in metadata.tables.values():
    for column in table.c:
        if isinstance(column.type, DateTime):
            column.type.timezone = True
        if (
            _is_datetime(column)
            and column.name in _NULLABLE_TIMESTAMPS
            and table.name not in _STRICT_TABLES
        ):
            column.nullable = True
    # Every tenant-scoped table references tenants(id) (the migrations add it to each).
    if (
        "tenant_id" in table.c
        and table.name != "tenants"
        and not any(fk.column.table.name == "tenants" for fk in table.c.tenant_id.foreign_keys)
    ):
        table.append_constraint(ForeignKeyConstraint(["tenant_id"], ["tenants.id"]))
for table_name, references in RELATIONS.items():
    table = metadata.tables[table_name]
    for fk_column, target in references.items():
        table.append_constraint(
            ForeignKeyConstraint(
                ["tenant_id", fk_column],
                [f"{target}.tenant_id", f"{target}.id"],
                name=f"fk_{table_name}_{fk_column}",
                deferrable=True,
                initially="DEFERRED",
            )
        )
for table_name, references in CASCADE_RELATIONS.items():
    table = metadata.tables[table_name]
    for fk_column, target in references.items():
        table.append_constraint(
            ForeignKeyConstraint(
                ["tenant_id", fk_column],
                [f"{target}.tenant_id", f"{target}.id"],
                name=f"fk_{table_name}_{fk_column}",
                ondelete="CASCADE",
                deferrable=True,
                initially="DEFERRED",
            )
        )
metadata.tables["leave_balances"].append_constraint(
    UniqueConstraint(
        "tenant_id", "employment_id", "leave_type_id", "year", name="uq_leave_balance_period"
    )
)
metadata.tables["employments"].append_constraint(
    UniqueConstraint(
        "tenant_id", "legal_entity_id", "employee_number", name="uq_company_employee_number"
    )
)

# Uniqueness the migrations create that the model classes don't spell out.
for unique_table, unique_columns, unique_name in (
    ("attendance_days", ("tenant_id", "employment_id", "work_date"), "uq_attendance_day"),
    ("employee_kyc_records", ("tenant_id", "employment_id"), "uq_tenant_kyc_employment"),
    ("platform_admins", ("email",), "platform_admins_email_key"),
    ("tenants", ("slug",), "tenants_slug_key"),
    ("leave_balance_buckets", ("tenant_id", "code"), "uq_leave_balance_bucket_code"),
    (
        "dashboard_layouts",
        ("tenant_id", "user_account_id", "dashboard"),
        "uq_dashboard_layout_user",
    ),
    ("user_preferences", ("tenant_id", "user_account_id"), "uq_user_preferences_user"),
    (
        "holiday_calendar_days",
        ("tenant_id", "calendar_id", "holiday_id"),
        "uq_holiday_calendar_day",
    ),
    ("leave_type_bucket_mapping", ("tenant_id", "leave_type_id"), "uq_leave_type_bucket_mapping"),
    (
        "leave_bucket_policies",
        ("tenant_id", "policy_set_id", "bucket_id"),
        "uq_leave_bucket_policy",
    ),
    (
        "leave_monthly_ledger",
        ("tenant_id", "employment_id", "bucket_id", "calendar_year", "calendar_month"),
        "uq_leave_monthly_ledger_period",
    ),
):
    metadata.tables[unique_table].append_constraint(
        UniqueConstraint(*unique_columns, name=unique_name)
    )

metadata.tables["approval_flows"].append_constraint(
    UniqueConstraint("tenant_id", "id", "request_type", name="uq_approval_flow_kind")
)
metadata.tables["employee_approval_flows"].append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "flow_id", "request_type"],
        ["approval_flows.tenant_id", "approval_flows.id", "approval_flows.request_type"],
    )
)
