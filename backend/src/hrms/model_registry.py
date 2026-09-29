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

from hrms.modules.corrections import models as corrections  # noqa: F401
from hrms.modules.kernel import models as kernel  # noqa: F401
from hrms.modules.kyc import models as kyc  # noqa: F401
from hrms.modules.leave import models as leave  # noqa: F401
from hrms.modules.onboarding import models as onboarding  # noqa: F401
from hrms.modules.org import models as org  # noqa: F401
from hrms.modules.people import models as people  # noqa: F401
from hrms.modules.policy import models as policy  # noqa: F401
from hrms.modules.reports import models as reports  # noqa: F401
from hrms.modules.time import models as time  # noqa: F401

metadata = SQLModel.metadata

# References include tenant_id, so a UUID belonging to another tenant cannot be linked.
RELATIONS = {
    "role_assignments": {"user_account_id": "user_accounts", "role_id": "roles"},
    "user_accounts": {"employment_id": "employments"},
    "locations": {"legal_entity_id": "legal_entities"},
    "org_units": {"legal_entity_id": "legal_entities", "parent_id": "org_units"},
    "positions": {"org_unit_id": "org_units", "job_id": "jobs", "grade_id": "grades"},
    "employments": {"person_id": "persons", "legal_entity_id": "legal_entities"},
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
    "employee_id_schemes": {"legal_entity_id": "legal_entities"},
    "employee_policy_assignments": {
        "employment_id": "employments",
        "policy_template_id": "policy_templates",
        "org_unit_id": "org_units",
        "legal_entity_id": "legal_entities",
    },
    "punches": {"employment_id": "employments", "original_punch_id": "punches"},
    "attendance_days": {"employment_id": "employments"},
    "holidays": {"legal_entity_id": "legal_entities"},
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
    "onboarding_items": {"case_id": "onboarding_cases"},
    "onboarding_template_items": {"template_id": "onboarding_templates"},
}
# Bookkeeping timestamps are `NOT NULL` in the Python models (they always carry a
# default_factory) but nullable-with-a-server-default in the database. The
# database is the truth here, so say so.
# (Tables whose migrations declare them NOT NULL are listed in _STRICT_TABLES.)
_STRICT_TABLES = {"api_keys", "import_batches", "auth_throttle", "kyc_access_log"}
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
):
    metadata.tables[unique_table].append_constraint(
        UniqueConstraint(*unique_columns, name=unique_name)
    )
