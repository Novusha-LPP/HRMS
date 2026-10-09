"""
Request-body examples for the published docs, keyed by operationId.

Swagger UI pre-fills "Try it out" with these instead of one generated from the schema. The
generated ones fill in every optional field, which some endpoints refuse (a punch with
`punched_at`, for example). IDs are placeholders: replace them with real ones from a list call.
"""

from typing import Any

REQUEST_EXAMPLES: dict[str, dict[str, Any]] = {
    "login": {"identifier": "hr@example.com", "password": "your-password"},
    "change_password": {"current_password": "old-password", "new_password": "a-new-password"},
    "create_user": {
        "email": "integration@example.com",
        "password": "a-strong-password",
        "role": "HR_MANAGER",
        "scope_type": "LEGAL_ENTITY",
        "legal_entity_ids": ["le_..."],
        "must_change_password": False,
    },
    "create_person": {
        "legal_first_name": "Asha",
        "legal_last_name": "Verma",
        "date_of_birth": "1994-03-18",
        "gender": "FEMALE",
        "nationality": "IN",
    },
    "create_employment": {
        "person_id": "per_...",
        "legal_entity_id": "le_...",
        "hire_date": "2026-11-01",
    },
    "create_personnel_action": {
        "employment_id": "emp_...",
        "type": "TRANSFER",
        "effective_date": "2026-11-01",
        "changes": {"org_unit_id": "ou_...", "manager_employment_id": "emp_..."},
        "reason_code": "REORG",
        "idempotency_key": "transfer-emp-2026-11-01",
    },
    "create_punch": {"punch_type": "IN", "source": "WEB"},
    "create_correction": {
        "work_date": "2026-10-05",
        "correction_type": "MISSED_PUNCH",
        "requested_punch_out": "2026-10-05T18:30:00+05:30",
        "reason": "Forgot to check out",
    },
    "edit_day": {
        "punches": [
            {"punch_type": "IN", "punched_at": "2026-10-05T09:05:00+05:30"},
            {"punch_type": "OUT", "punched_at": "2026-10-05T18:10:00+05:30"},
        ],
        "reason": "Biometric device was offline",
    },
    "create_application": {
        "leave_type_id": "lt_...",
        "from_date": "2026-10-20",
        "to_date": "2026-10-21",
        "half_day_option": "NONE",
        "reason": "Family function",
    },
    "approve_application": {"action": "APPROVE", "comments": "Approved"},
    "reject_application": {"action": "REJECT", "comments": "Team is short-staffed that week"},
    "approve_correction": {"action": "APPROVE", "comments": "Verified with the gate register"},
    "reject_correction": {"action": "REJECT", "comments": "No record of attendance"},
    "adjust_balance": {
        "employment_id": "emp_...",
        "leave_type_id": "lt_...",
        "quantity": 2,
        "reason": "Opening balance from the previous system",
        "kind": "OPENING",
    },
    "decide": {"action": "APPROVE", "comments": "Looks good"},
    "assign_calendar": {"target": "LEGAL_ENTITY", "target_id": "le_...", "replace": True},
    "run_report": {
        "filters": [{"field": "work_date", "op": "between", "value": ["2026-10-01", "2026-10-31"]}],
        "limit": 1000,
    },
}
