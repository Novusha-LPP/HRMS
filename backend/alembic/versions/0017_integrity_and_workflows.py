"""Integrity constraints and auditable attendance/leave workflows.

Fails rather than deleting existing duplicate or orphaned records. Reconcile any
reported constraint violation before retrying the migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

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


def upgrade():
    op.add_column("punches", sa.Column("work_date", sa.Date(), nullable=True))
    op.create_index("ix_punches_work_date", "punches", ["work_date"])
    op.add_column(
        "leave_applications",
        sa.Column("days_by_year", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("leave_applications", sa.Column("document_id", UUID(as_uuid=True), nullable=True))
    op.execute("""UPDATE leave_applications SET days_by_year = jsonb_build_object(EXTRACT(YEAR FROM from_date)::int::text, days_requested)
                  WHERE EXTRACT(YEAR FROM from_date) = EXTRACT(YEAR FROM to_date)""")
    op.create_unique_constraint(
        "uq_leave_balance_period",
        "leave_balances",
        ["tenant_id", "employment_id", "leave_type_id", "year"],
    )
    op.create_unique_constraint(
        "uq_company_employee_number",
        "employments",
        ["tenant_id", "legal_entity_id", "employee_number"],
    )
    op.create_index(
        "uq_account_email_lower",
        "user_accounts",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    for table, references in RELATIONS.items():
        for column, target in references.items():
            op.create_foreign_key(
                f"fk_{table}_{column}",
                table,
                target,
                ["tenant_id", column],
                ["tenant_id", "id"],
                deferrable=True,
                initially="DEFERRED",
            )


def downgrade():
    for table, references in reversed(list(RELATIONS.items())):
        for column in references:
            op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")
    op.drop_index("uq_account_email_lower", table_name="user_accounts")
    op.drop_constraint("uq_company_employee_number", "employments", type_="unique")
    op.drop_constraint("uq_leave_balance_period", "leave_balances", type_="unique")
    op.drop_column("leave_applications", "document_id")
    op.drop_column("leave_applications", "days_by_year")
    op.drop_index("ix_punches_work_date", table_name="punches")
    op.drop_column("punches", "work_date")
