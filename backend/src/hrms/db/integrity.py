"""
Nightly checks for references the database can't hold with a foreign key
(docs/database-hardening-plan.md, W7.3).

Some columns point at a different table depending on a sibling column (entity_type,
request_type, reference_type, kind) or into a JSON document, so no FOREIGN KEY can protect
them. Each check below counts, for one tenant, the rows whose target is missing. The
`integrity` job (hrms.jobs.runner) runs them for every tenant, stores the totals on its
job_runs row, and /metrics exports them as hrms_integrity_violations{check}; an alert fires
above zero.

History that points at something deliberately removed is not a finding: a change-log entry
whose entity was later deleted or archived (its own DELETE / ARCHIVE entry says so) is
history, not damage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    what: str
    sql: str  # counts violations for the tenant in app.tenant_id


def _typed(
    column_table: str,
    type_column: str,
    id_column: str,
    targets: dict[str, str],
    unless: str | None = None,
) -> str:
    """
    Rows whose `id_column` names no row of the table its `type_column` selects, except those
    matching `unless`.
    """
    arms = " OR ".join(
        f"(x.{type_column} = '{kind}' AND NOT EXISTS "
        f"(SELECT 1 FROM {table} t WHERE t.tenant_id = x.tenant_id AND t.id = x.{id_column}))"
        for kind, table in targets.items()
    )
    excused = f" AND NOT ({unless})" if unless else ""
    return (
        f"SELECT count(*) FROM {column_table} x "
        f"WHERE x.{id_column} IS NOT NULL{excused} AND ({arms})"
    )


# entity_change_log.entity_type -> the table it names (core/change_audit.ENTITY_TYPES).
CHANGE_LOG_TARGETS = {
    "legal_entity": "legal_entities",
    "location": "locations",
    "org_unit": "org_units",
    "job": "jobs",
    "grade": "grades",
    "position": "positions",
    "cost_centre": "cost_centres",
    "user_account": "user_accounts",
    "statutory_rule": "statutory_rules",
    "pay_component": "pay_components",
    "salary_structure": "salary_structures",
    "employee_compensation": "employee_compensations",
    "connected_app": "connected_apps",
    "api_key": "api_keys",
    "integration_profile": "integration_profiles",
    "integration_mapping": "integration_mappings",
    "integration_override": "employments",
    "person": "persons",
    "employment": "employments",
    "role_assignment": "role_assignments",
    "leave_type": "leave_types",
    "leave_bucket": "leave_balance_buckets",
    "leave_policy_set": "leave_policy_sets",
    "leave_bucket_policy": "leave_bucket_policies",
    "leave_policy_assignment": "leave_policy_assignments",
    "policy_template": "policy_templates",
    "employee_policy_assignment": "employee_policy_assignments",
    "holiday": "holidays",
    "holiday_calendar": "holiday_calendars",
    "holiday_calendar_assignment": "holiday_calendar_assignments",
    "approval_flow": "approval_flows",
}
# approval_instances.request_type -> the request's table (approvals/router.py).
REQUEST_TARGETS = {
    "LEAVE": "leave_applications",
    "LEAVE_CANCELLATION": "leave_applications",
    "CORRECTION": "attendance_correction_requests",
    "OVERTIME": "attendance_days",
    "FIELD_OVERRIDE": "personnel_actions",
    "JOB_REQUISITION": "job_openings",
}
# leave_balance_transactions.reference_type -> the table it names. ACCRUAL_RUN, YEAR_END and
# MANUAL reference a run or nothing, not a row.
LEAVE_REFERENCE_TARGETS = {
    "LEAVE_APPLICATION": "leave_applications",
    "ENCASHMENT": "leave_encashments",
    "COMP_OFF": "comp_off_grants",
}
# integration_mappings.kind -> the table its target_id names (ROLE maps to a name, not an id).
MAPPING_TARGETS = {
    "LEGAL_ENTITY": "legal_entities",
    "DEPARTMENT": "org_units",
    "LOCATION": "locations",
    "DESIGNATION": "jobs",
}

_REMOVED = (
    "EXISTS (SELECT 1 FROM entity_change_log g WHERE g.tenant_id = x.tenant_id "
    "AND g.entity_type = x.entity_type AND g.entity_id = x.entity_id "
    "AND g.action IN ('DELETE', 'ARCHIVE'))"
)

CHECKS: tuple[Check, ...] = (
    Check(
        "change_log_target_missing",
        "change-history entries whose record is gone without a DELETE or ARCHIVE entry",
        _typed(
            "entity_change_log", "entity_type", "entity_id", CHANGE_LOG_TARGETS, unless=_REMOVED
        ),
    ),
    Check(
        "change_log_unknown_entity_type",
        "change-history entries naming an entity type this check doesn't know",
        "SELECT count(*) FROM entity_change_log WHERE entity_type NOT IN ("
        + ", ".join(f"'{t}'" for t in CHANGE_LOG_TARGETS)
        + ")",
    ),
    Check(
        "approval_request_missing",
        "approvals whose request (leave, correction, overtime, …) is gone",
        _typed("approval_instances", "request_type", "request_id", REQUEST_TARGETS),
    ),
    Check(
        "leave_reference_missing",
        "leave balance movements whose application, encashment or comp-off grant is gone",
        _typed(
            "leave_balance_transactions", "reference_type", "reference_id", LEAVE_REFERENCE_TARGETS
        ),
    ),
    Check(
        "integration_mapping_target_missing",
        "connected-app mappings pointing at a company, department, location or job that is gone",
        _typed("integration_mappings", "kind", "target_id", MAPPING_TARGETS),
    ),
    Check(
        "delegation_step_missing",
        "delegations for an approval step that no longer exists",
        """
        SELECT count(*) FROM approval_delegations d
        WHERE NOT EXISTS (
            SELECT 1 FROM approval_instances i, jsonb_array_elements(i.steps) s
            WHERE i.tenant_id = d.tenant_id AND i.id = d.instance_id
              AND s ->> 'id' = d.step_id::text)
          AND NOT EXISTS (
            SELECT 1 FROM approval_flows f, jsonb_array_elements(f.steps) s
            WHERE f.tenant_id = d.tenant_id AND f.id = d.flow_id
              AND s ->> 'id' = d.step_id::text)
        """,
    ),
)


async def run_checks(session) -> dict[str, int]:
    """Every check for the tenant the session is scoped to: {check name: violations}."""
    from sqlalchemy import text

    return {check.name: int(await session.scalar(text(check.sql)) or 0) for check in CHECKS}
