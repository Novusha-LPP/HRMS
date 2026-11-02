"""
The registry the schema rules (schema_rules.py) check against.

Each rule in docs/database-conventions.md holds for every table unless an entry here says
otherwise, and every entry says why. An entry that no longer matches anything in the database
is itself reported, so this file can't silently go stale.

Migrations must not import this module or the enums it points to: a migration is a record of
what was true when it ran, so it copies values literally (see migration_kit.check_in).
"""

from __future__ import annotations

import enum
import importlib
import typing

# ── Table classes ────────────────────────────────────────────────────────────────────────────

# Tables without tenant_id: the platform itself, not any one tenant's data.
GLOBAL_TABLES = frozenset(
    {
        "alembic_version",
        "tenants",
        "platform_admins",
        "platform_audit_log",
        "platform_password_reset_tokens",
        "auth_throttle",
        "job_runs",
    }
)

# Platform-console data the tenant runtime role (hrms_app) must not touch at all (DB-D3).
PLATFORM_ONLY = frozenset(
    {"platform_admins", "platform_password_reset_tokens", "platform_audit_log"}
)

# History that is written once and never changed: hrms_app may INSERT and SELECT, nothing else.
# Deletes that cascade from a parent (candidate erasure) run as the table owner, not hrms_app.
APPEND_ONLY = frozenset(
    {
        "attendance_marks",
        "brand_assets",
        "entity_change_log",
        "kyc_access_log",
        "leave_balance_transactions",
        "approval_events",
        "leave_approval_actions",
        "correction_approval_actions",
        "recruitment_events",
        "platform_audit_log",
    }
)

# Tables removed together with their tenant (ON DELETE CASCADE from tenants). Everything else
# blocks a tenant delete; scripts/purge_tenant.py is the only offboarding path.
TENANT_CASCADE = frozenset(
    {
        "api_keys",
        "connected_apps",
        "external_identities",
        "import_batches",
        "integration_app_events",
        "integration_cursors",
        "integration_events",
        "integration_mappings",
        "integration_profiles",
        "integration_rate_windows",
        "integration_requests",
        "possible_duplicates",
    }
)

# ── References ───────────────────────────────────────────────────────────────────────────────

# uuid columns named *_id / *_by that deliberately have no foreign key.
SOFT_REFERENCES = {
    # Polymorphic: the row type is in a sibling column, so no single table can be referenced.
    "entity_change_log.entity_id": "polymorphic; entity_type names the table",
    "approval_instances.request_id": "polymorphic; request_type names the table",
    "leave_balance_transactions.reference_id": "polymorphic; reference_type names the table",
    "integration_events.subject_id": "polymorphic; event_type names the subject",
    "integration_mappings.target_id": "polymorphic; kind names the table",
    "platform_audit_log.target_id": "polymorphic; target_type names the table",
    "approval_delegations.step_id": "points at a step inside approval_instances.steps (JSONB)",
    # Logs pruned by retention; they must outlive the key or app they mention.
    "integration_requests.app_id": "sync log; kept after an app is removed",
    "integration_requests.api_key_id": "sync log; kept after a key is removed",
    "integration_requests.employment_id": "sync log; may record a rejected, unknown employee",
    "integration_rate_windows.api_key_id": "per-minute counters, trimmed hourly",
}

_ACTOR = (
    "who-did-it column: accounts and employees are deactivated, never deleted, and the column "
    "is only shown with its own row"
)

# Foreign keys that deliberately have no supporting index, as "table.constraint_name".
UNINDEXED_FK_OK: dict[str, str] = {
    "legal_entities.fk_legal_entities_recorded_by": _ACTOR,
    "locations.fk_locations_recorded_by": _ACTOR,
    "org_units.fk_org_units_recorded_by": _ACTOR,
    "persons.fk_persons_recorded_by": _ACTOR,
    "employments.fk_employments_recorded_by": _ACTOR,
    "assignments.fk_assignments_recorded_by": _ACTOR,
    "personnel_actions.fk_personnel_actions_recorded_by": _ACTOR,
    "punches.fk_punches_recorded_by": _ACTOR,
    "attendance_days.fk_attendance_days_ot_reviewed_by": _ACTOR,
    "attendance_days.fk_attendance_days_reviewed_by": _ACTOR,
    "onboarding_items.fk_onboarding_items_completed_by": _ACTOR,
    "report_definitions.fk_report_definitions_created_by": _ACTOR,
    "policy_templates.fk_policy_templates_recorded_by": _ACTOR,
    "employee_policy_assignments.fk_employee_policy_assignments_recorded_by": _ACTOR,
    "leave_types.fk_leave_types_recorded_by": _ACTOR,
    "leave_balances.fk_leave_balances_recorded_by": _ACTOR,
    "leave_applications.fk_leave_applications_recorded_by": _ACTOR,
    "leave_approval_actions.fk_leave_approval_actions_recorded_by": _ACTOR,
    "attendance_correction_requests.fk_attendance_correction_requests_recorded_by": _ACTOR,
    "correction_approval_actions.fk_correction_approval_actions_recorded_by": _ACTOR,
    "employee_kyc_records.fk_employee_kyc_records_updated_by": _ACTOR,
    "employee_kyc_records.fk_employee_kyc_records_verified_by": _ACTOR,
    "employee_kyc_documents.fk_employee_kyc_documents_uploaded_by": _ACTOR,
    "employee_kyc_documents.fk_employee_kyc_documents_verified_by": _ACTOR,
    "holidays.fk_holidays_recorded_by": _ACTOR,
    "comp_off_grants.fk_comp_off_grants_granted_by": _ACTOR,
    "leave_encashments.fk_leave_encashments_processed_by": _ACTOR,
    "employee_id_schemes.fk_employee_id_schemes_recorded_by": _ACTOR,
    "api_keys.fk_api_keys_created_by": _ACTOR,
    "api_keys.fk_api_keys_revoked_by": _ACTOR,
    "leave_balance_buckets.fk_leave_balance_buckets_recorded_by": _ACTOR,
    "leave_type_bucket_mapping.fk_leave_type_bucket_mapping_recorded_by": _ACTOR,
    "leave_policy_sets.fk_leave_policy_sets_recorded_by": _ACTOR,
    "leave_bucket_policies.fk_leave_bucket_policies_recorded_by": _ACTOR,
    "leave_policy_assignments.fk_leave_policy_assignments_recorded_by": _ACTOR,
    "leave_balance_transactions.fk_leave_balance_transactions_approved_by": _ACTOR,
    "leave_balance_transactions.fk_leave_balance_transactions_recorded_by": _ACTOR,
    "entity_change_log.fk_entity_change_log_changed_by": _ACTOR,
    "approval_flows.fk_approval_flows_updated_by": _ACTOR,
    "approval_delegations.fk_approval_delegations_created_by": _ACTOR,
    "approval_delegations.fk_approval_delegations_revoked_by": _ACTOR,
    "employee_approval_flows.employee_approval_flows_tenant_id_updated_by_fkey": _ACTOR,
    "job_openings.fk_job_openings_approved_by": _ACTOR,
    "job_openings.fk_job_openings_requested_by": _ACTOR,
    "candidates.fk_candidates_created_by": _ACTOR,
    "job_applications.fk_job_applications_created_by": _ACTOR,
    "statutory_rules.fk_statutory_rules_recorded_by": _ACTOR,
    "statutory_rules.fk_statutory_rules_verified_by": _ACTOR,
    "pay_components.fk_pay_components_recorded_by": _ACTOR,
    "salary_structures.fk_salary_structures_recorded_by": _ACTOR,
    "employee_compensations.fk_employee_compensations_recorded_by": _ACTOR,
    "connected_apps.fk_connected_apps_created_by": _ACTOR,
    "integration_mappings.fk_integration_mappings_created_by": _ACTOR,
    "integration_profiles.fk_integration_profiles_created_by": _ACTOR,
    "integration_profiles.fk_integration_profiles_published_by": _ACTOR,
    "possible_duplicates.fk_possible_duplicates_resolved_by": _ACTOR,
}

# ── Allowed values ───────────────────────────────────────────────────────────────────────────

_CORRECTIONS = "hrms.modules.corrections.models:"
_INTEGRATIONS = "hrms.modules.integrations.schemas:"
_MASTER = "hrms.modules.org.schemas:MasterStatus"
_PAYROLL = "hrms.modules.payroll.models:"
_RECRUITMENT = "hrms.modules.recruitment.schemas:"
_REMINDERS = "hrms.modules.reminders.models:"
_REQUEST_TYPE = "hrms.modules.approvals.schemas:RequestType"

# "table.column" -> "module:Name", where Name is a StrEnum or a Literal type; or a tuple
# ("module:Name", *extra) for values the code stores but the API must not accept, each extra
# explained where it is written. The database CHECK must allow exactly these values.
DOMAINS: dict[str, str | tuple[str, ...]] = {
    # DIRECT_EDIT: HR's direct day edits (time/register.py), never a request type
    "attendance_correction_requests.correction_type": (
        _CORRECTIONS + "CorrectionType",
        "DIRECT_EDIT",
    ),
    # PENDING / CANCEL_PENDING: approval chains deeper than 3 levels (approvals/service.py,
    # pending_status) store the plain form instead of PENDING_L4, PENDING_L5, ...
    "attendance_correction_requests.status": (_CORRECTIONS + "CorrectionStatus", "PENDING"),
    "attendance_days.ot_status": "hrms.modules.time.models:OvertimeStatus",
    "attendance_group_access.access_level": "hrms.modules.time.models:GroupAccess",
    "attendance_marks.source": "hrms.modules.time.models:MarkSource",
    "attendance_marks.status": "hrms.modules.time.models:MarkStatus",
    "attendance_days.status": "hrms.modules.time.models:AttendanceStatus",
    "brand_assets.kind": "hrms.modules.branding.models:AssetKind",
    "employee_kyc_documents.document_type": "hrms.modules.kyc.models:DocumentType",
    "employee_kyc_documents.status": "hrms.modules.kyc.models:DocumentStatus",
    "employee_kyc_records.status": "hrms.modules.kyc.models:KycStatus",
    "employments.employment_state": "hrms.modules.people.models:EmploymentState",
    "rejoin_records.mode": "hrms.modules.people.models:RejoinMode",
    "rejoin_policies.default_mode": "hrms.modules.people.models:RejoinMode",
    "company_transfers.leave_mode": "hrms.modules.people.models:TransferLeaveMode",
    "leave_separation_rules.on_separation": "hrms.modules.leave.models:SeparationAction",
    "leave_separation_settlements.action": "hrms.modules.leave.models:SeparationAction",
    "leave_separation_settlements.resolution": "hrms.modules.leave.models:SettlementResolution",
    "job_openings.status": "hrms.modules.recruitment.models:OpeningStatus",
    "leave_applications.status": (
        "hrms.modules.leave.models:LeaveApplicationStatus",
        "PENDING",
        "CANCEL_PENDING",
    ),
    "leave_approval_actions.action_type": "hrms.modules.leave.models:LeaveApprovalActionType",
    "leave_balance_transactions.transaction_type": "hrms.modules.leave.models:LeaveTransactionType",
    "onboarding_cases.status": "hrms.modules.onboarding.models:CaseStatus",
    "onboarding_items.assignee_type": "hrms.modules.onboarding.models:AssigneeType",
    "onboarding_items.item_type": "hrms.modules.onboarding.models:OnboardingItemType",
    "onboarding_items.status": "hrms.modules.onboarding.models:ItemStatus",
    "onboarding_template_items.assignee_type": "hrms.modules.onboarding.models:AssigneeType",
    "onboarding_template_items.item_type": "hrms.modules.onboarding.models:OnboardingItemType",
    "pay_components.kind": "hrms.modules.payroll.models:ComponentKind",
    "pay_components.statutory_code": "hrms.modules.payroll.models:StatutoryCode",
    "personnel_actions.status": "hrms.modules.people.models:PersonnelActionStatus",
    "personnel_actions.type": "hrms.modules.people.models:PersonnelActionType",
    # VOID: a correction row cancelling an earlier punch (time/register.py)
    "punches.punch_type": ("hrms.modules.time.models:PunchType", "VOID"),
    "punches.source": "hrms.modules.time.models:PunchSource",
    "recruitment_stages.category": "hrms.modules.recruitment.models:StageCategory",
    "salary_structure_lines.calc_type": "hrms.modules.payroll.models:CalcType",
    "approval_flows.request_type": _REQUEST_TYPE,
    "approval_instances.request_type": _REQUEST_TYPE,
    "employee_approval_flows.request_type": _REQUEST_TYPE,
    "approval_instances.status": "hrms.modules.approvals.models:ApprovalStatus",
    "correction_approval_actions.action": "hrms.modules.approvals.schemas:DecisionAction",
    "assignment_managers.manager_type": "hrms.modules.people.models:ManagerType",
    "role_assignments.scope_type": "hrms.core.authz:GrantScope",
    "user_accounts.status": "hrms.modules.kernel.models:AccountStatus",
    "tenants.status": "hrms.modules.platform.schemas:TenantStatus",
    "platform_admins.status": "hrms.modules.platform.schemas:AdminStatus",
    "cost_centres.status": _MASTER,
    "grades.status": _MASTER,
    "jobs.status": _MASTER,
    "legal_entities.status": _MASTER,
    "locations.status": _MASTER,
    "org_units.status": _MASTER,
    "positions.status": _MASTER,
    "onboarding_templates.status": "hrms.modules.onboarding.models:TemplateStatus",
    "report_definitions.owner_type": "hrms.modules.reports.models:ReportOwner",
    "leave_bucket_policies.accrual_type": "hrms.modules.leave.schemas:AccrualType",
    "leave_balance_transactions.reference_type": "hrms.modules.leave.models:LeaveReferenceType",
    "connected_apps.kind": _INTEGRATIONS + "AppKind",
    "connected_apps.status": _INTEGRATIONS + "AppStatus",
    "integration_mappings.kind": _INTEGRATIONS + "MappingKind",
    "integration_profiles.status": _INTEGRATIONS + "ProfileStatus",
    "possible_duplicates.status": _INTEGRATIONS + "DuplicateStatus",
    "pay_components.status": _PAYROLL + "ComponentStatus",
    "payslip_templates.layout": _PAYROLL + "PayslipLayout",
    "payslip_templates.signature_mode": _PAYROLL + "SignatureMode",
    "reminder_rules.trigger": _REMINDERS + "ReminderTrigger",
    "reminder_rules.frequency": _REMINDERS + "ReminderFrequency",
    "reminder_outbox.audience": _REMINDERS + "Audience",
    "reminder_outbox.status": _REMINDERS + "OutboxStatus",
    "salary_structures.status": _PAYROLL + "StructureStatus",
    "statutory_rules.status": _PAYROLL + "RuleStatus",
    "statutory_rules.unit": _PAYROLL + "RuleUnit",
    "job_openings.approval_mode": _RECRUITMENT + "ApprovalMode",
    "job_openings.employment_type": _RECRUITMENT + "EmploymentType",
    "job_openings.priority": _RECRUITMENT + "Priority",
    "job_openings.work_mode": _RECRUITMENT + "WorkMode",
    "candidates.source": _RECRUITMENT + "CandidateSource",
}

# Columns the "looks like a status" rule matches that are not a closed set of values.
_LOG = "an append-only log's vocabulary, written only by code; a new entry kind needs no migration"
_LABEL = "a free label the API accepts as text (max length enforced)"
DOMAIN_EXEMPT = {
    "candidates.resume_mime_type": "MIME type; the upload allowlist checks it",
    "employee_kyc_documents.mime_type": "MIME type; the upload allowlist checks it",
    "integration_events.event_type": "open vocabulary of feed events, versioned with the API",
    "entity_change_log.entity_type": "core.change_audit.ENTITY_TYPES validates it on write",
    "entity_change_log.action": "core.change_audit.ACTIONS validates it on write",
    "platform_audit_log.action": _LOG,
    "platform_audit_log.target_type": _LOG,
    "approval_events.action": _LOG,
    "recruitment_events.action": _LOG,
    "kyc_access_log.action": _LOG,
    "integration_requests.outcome": _LOG,
    "job_runs.status": _LOG,
    "statutory_rules.source": "where a statutory value comes from, as written provenance text",
    "employee_kyc_records.marital_status": _LABEL,
    "persons.gender": _LABEL + "; which values are canonical is an open decision",
    "locations.type": _LABEL,
    "org_units.type": _LABEL,
    "assignments.worker_type": _LABEL + " (worker classification; roadmap A1 editable lists)",
    "employments.service_stage": _LABEL + " (service classification; roadmap A1 editable lists)",
    "holidays.holiday_type": _LABEL + " (holiday libraries import their own type labels)",
}

# ── Effective dating ─────────────────────────────────────────────────────────────────────────

# How effective_to is read. Exclusive: the row stops applying ON that date (a change closes the
# old row with effective_to = new effective_from). Inclusive: the row still applies on that date
# (a change closes the old row the day before). A no-overlap constraint must use the matching
# range bounds, '[)' or '[]', or it lets two rows apply on the handover day.
EFFECTIVE_END_EXCLUSIVE = frozenset(
    {
        "assignments",
        "assignment_managers",
        "attendance_group_members",
        "employee_compensations",
        "statutory_rules",
    }
)
EFFECTIVE_END_INCLUSIVE = frozenset(
    {"employee_policy_assignments", "leave_policy_assignments", "holiday_calendar_assignments"}
)

# Effective-dated tables where rows don't form a history that could overlap.
NO_OVERLAP_EXEMPT = {
    "org_units": "the dates are one unit's validity window, not a history of rows",
    "positions": "the dates are one position's validity window, not a history of rows",
    "employee_policy_assignments": (
        "latest start wins (policy/engine.py), so an overlapping row is a temporary override; "
        "two rows for one target may not start on the same day (uq_*_same_start)"
    ),
    "leave_policy_assignments": (
        "latest start wins (leave/policy_resolver.py), so an overlapping row is a temporary "
        "override; two rows for one target may not start on the same day (uq_*_same_start)"
    ),
}

# ── Uniqueness and archiving ─────────────────────────────────────────────────────────────────

# Unique indexes on tables with archived_at that deliberately count archived rows too, as
# "index_name": reason. These keep today's behaviour (DB-1 changes none of them).
ARCHIVE_UNIQUE_INCLUDES_ARCHIVED = {
    "tenants_slug_key": "a slug names a tenant in sign-in links; an archived one's isn't reused",
    "uq_company_employee_number": "an employee number stays with its record, archived or not",
    "uq_employments_number_ci": "the same rule as uq_company_employee_number, ignoring case",
    "uq_leave_balance_period": "one balance row per employee, leave type and year",
    "uq_leave_balance_bucket_code": "history and imports refer to buckets by code",
}


def enum_values(domain: str | tuple[str, ...]) -> list[str]:
    """
    The values a DOMAINS entry allows: a "module:Name" StrEnum or Literal type, or a tuple of
    one plus extra stored values.
    """
    path, *extra = (domain,) if isinstance(domain, str) else domain
    module, name = path.split(":")
    target = getattr(importlib.import_module(module), name)
    if isinstance(target, type) and issubclass(target, enum.Enum):
        values = [str(member.value) for member in target]
    elif typing.get_origin(target) is typing.Literal:
        values = [str(v) for v in typing.get_args(target)]
    else:
        raise TypeError(f"{path} is neither an Enum nor a Literal")
    return values + [v for v in extra if v not in values]


def domain_name(domain: str | tuple[str, ...]) -> str:
    """A short label for messages: the enum or Literal name."""
    path = domain if isinstance(domain, str) else domain[0]
    return path.split(":")[1]
