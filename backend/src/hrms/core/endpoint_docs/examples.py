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
    "create_grade": {"code": "M2", "name": "Manager", "sequence": 20},
    "create_cost_centre": {"code": "CC-OPS", "name": "Operations"},
    "create_position": {
        "title": "Shift Supervisor",
        "org_unit_id": "ou_...",
        "job_id": "job_...",
        "grade_id": "grd_...",
        "max_headcount": 3,
    },
    "issue_sign_in_slips": {"employment_ids": ["emp_...", "emp_..."], "numeric": True},
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
    "mark_day": {
        "marks": [
            {"employment_id": "emp_driver_1", "status": "PRESENT"},
            {
                "employment_id": "emp_guard_1",
                "status": "PRESENT",
                "punch_in": "20:00",
                "punch_out": "08:00",
            },
            {"employment_id": "emp_driver_2", "status": "ABSENT", "remark": "Not at the depot"},
        ],
        "remark": "Daily roll call",
    },
    "create_group": {"name": "Guards", "description": "Gate and site security"},
    "add_members": {
        "employment_ids": ["emp_guard_1", "emp_guard_2"],
        "effective_from": "2026-11-01",
    },
    "grant_access": {"access_level": "MARK"},
    "record_leave": {
        "employment_id": "emp_...",
        "leave_type_id": "lt_...",
        "from_date": "2026-10-20",
        "to_date": "2026-10-22",
        "reason": "Family function",
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
    "create_statutory_rule": {
        "rule_code": "ESIC_WAGE_CEILING",
        "value": "21000",
        "effective_from": "2027-04-01",
        "source": "ESIC notification dated ... (paste the reference)",
    },
    "create_pay_component": {
        "code": "CONV",
        "name": "Conveyance allowance",
        "kind": "EARNING",
        "taxable": True,
        "in_pf_wages": False,
        "in_esic_wages": True,
        "payslip_order": 30,
    },
    "update_pay_component": {"name": "Conveyance", "payslip_order": 35},
    "create_salary_structure": {
        "name": "Staff",
        "lines": [
            {"component_id": "pcmp_...", "calc_type": "PERCENT", "percent": "50", "base": "CTC"},
            {"component_id": "pcmp_...", "calc_type": "BALANCE"},
            {"component_id": "pcmp_...", "calc_type": "STATUTORY"},
        ],
    },
    "replace_salary_structure": {
        "name": "Staff",
        "lines": [
            {"component_id": "pcmp_...", "calc_type": "PERCENT", "percent": "40", "base": "CTC"},
            {"component_id": "pcmp_...", "calc_type": "BALANCE"},
            {"component_id": "pcmp_...", "calc_type": "STATUTORY"},
        ],
    },
    "preview_salary_breakup": {
        "annual_ctc": "600000",
        "lines": [
            {"component_id": "pcmp_...", "calc_type": "PERCENT", "percent": "50", "base": "CTC"},
            {"component_id": "pcmp_...", "calc_type": "BALANCE"},
        ],
    },
    "set_employee_compensation": {
        "structure_id": "sstr_...",
        "annual_ctc": "600000",
        "effective_from": "2026-11-01",
        "reason": "Annual revision",
    },
    "put_group_brand_profile": {
        "logo_asset_id": "bast_...",
        "primary_color": "#0F766E",
        "accent_color": None,
        "footer_text": "Registered office: Plot 12, MIDC, Andheri East, Mumbai 400093",
        "contact_email": "payroll@example.com",
        "contact_phone": None,
        "website": "www.example.com",
        "version": 0,
    },
    "create_signatory": {
        "name": "Asha Verma",
        "designation": "Head of HR",
        "legal_entity_id": None,
        "signature_asset_id": "bast_...",
    },
    "put_group_payslip_template": {
        "layout": "MODERN",
        "title": "Payslip",
        "employee_fields": ["employee_number", "designation", "department", "pan", "uan"],
        "show_attendance": True,
        "show_leave_balances": False,
        "show_employer_contributions": False,
        "show_ytd": False,
        "hide_zero_lines": True,
        "signature_mode": "COMPUTER_GENERATED",
        "note_text": "For questions about your pay, write to payroll@example.com.",
    },
    "preview_payslip_template": {"legal_entity_id": None, "template": {"layout": "CLASSIC"}},
}
