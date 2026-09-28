"""Complete model metadata for the application and Alembic."""

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
    "onboarding_cases": {"employment_id": "employments", "template_id": "onboarding_templates"},
    "onboarding_items": {"case_id": "onboarding_cases"},
    "onboarding_template_items": {"template_id": "onboarding_templates"},
}
for table in metadata.tables.values():
    for column in table.c:
        if isinstance(column.type, DateTime):
            column.type.timezone = True
for table_name, references in RELATIONS.items():
    table = metadata.tables[table_name]
    for column, target in references.items():
        table.append_constraint(
            ForeignKeyConstraint(
                ["tenant_id", column],
                [f"{target}.tenant_id", f"{target}.id"],
                name=f"fk_{table_name}_{column}",
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
