"""
Opaque typed IDs for the public API.

Internal storage: a UUID. new_id() below generates UUIDv7 (time-ordered); most
code currently calls uuid4() directly, which is equally valid — just not time-ordered.
Public representation: "<prefix>_<base32-encoded-uuid>" e.g. emp_01J8Z3K7Q9...

Rules from the architecture:
- Never expose raw database UUIDs in the API.
- Never reuse an ID after deletion.
- Typed prefixes make IDs self-describing and prevent cross-resource confusion.
"""

import base64
import uuid
from uuid import UUID

from fastapi import HTTPException

try:
    # The PyPI package "uuid7" installs a module named `uuid_extensions` — `import uuid7` never
    # worked, so the fallback below silently ran everywhere until this was corrected.
    from uuid_extensions import uuid7
except ImportError:
    # A stale virtualenv may lack the package. Fall back to a random UUID rather than failing to
    # import — IDs stay unique, just not time-ordered.
    def uuid7() -> UUID:
        return uuid.uuid4()


_PREFIX_MAP: dict[str, str] = {
    "approval_flow": "afl",
    "approval_instance": "ain",
    "approval_step": "ast",
    "approval_delegation": "adg",
    "approval_event": "aev",
    "tenant": "ten",
    "legal_entity": "le",
    "holiday_calendar": "hcal",
    "holiday_calendar_day": "hday",
    "holiday_calendar_assignment": "hasg",
    "location": "loc",
    "org_unit": "ou",
    "job": "job",
    "grade": "grd",
    "position": "pos",
    "cost_centre": "cc",
    "person": "per",
    "employment": "emp",
    "employee_id_scheme": "eis",
    "assignment": "asgn",
    "personnel_action": "pa",
    "rejoin_policy": "rjp",
    "user": "usr",
    "role": "rol",
    # Policy
    "policy_template": "pol",
    "employee_policy": "epol",
    # Leave
    "leave_type": "lt",
    "leave_balance": "lb",
    "leave_application": "la",
    "leave_approval": "lappr",
    "leave_bucket": "lmb",
    "leave_mapping": "lmap",
    "leave_policy_set": "lps",
    "leave_bucket_policy": "lbp",
    "leave_policy_assignment": "lpa",
    "leave_ledger": "ll",
    "leave_transaction": "ltx",
    "leave_separation_rule": "lsr",
    "leave_separation_settlement": "lss",
    # Corrections
    "attendance_correction": "cor",
    "correction_approval": "cappr",
    # KYC
    "kyc_record": "kyc",
    "kyc_document": "kdoc",
    # Recruitment
    "job_opening": "jopn",
    "recruitment_stage": "rstg",
    "candidate": "cand",
    "job_application": "japp",
    "recruitment_event": "revt",
    # Payroll
    "statutory_rule": "srul",
    "pay_component": "pcmp",
    "salary_structure": "sstr",
    "salary_structure_line": "ssln",
    "employee_compensation": "ecmp",
    # Integrations
    "connected_app": "app",
    "api_key": "key",
    "integration_profile": "iprf",
    "integration_mapping": "imap",
    "integration_request": "ireq",
    "possible_duplicate": "dup",
    # Change audit
    "entity_change": "chg",
}


def _encode(uid: UUID) -> str:
    return base64.b32encode(uid.bytes).decode("ascii").rstrip("=").lower()


def _decode(encoded: str) -> UUID:
    padded = encoded.upper() + "=" * ((8 - len(encoded) % 8) % 8)
    return UUID(bytes=base64.b32decode(padded))


def new_id(resource: str) -> str:
    prefix = _PREFIX_MAP.get(resource, resource[:3])
    return f"{prefix}_{_encode(uuid7())}"


def to_uuid(typed_id: str) -> UUID:
    try:
        parts = typed_id.split("_", 1)
        if len(parts) != 2:
            raise ValueError("Missing type prefix")
        return _decode(parts[1])
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid resource identifier") from exc


def to_typed_id(resource: str, uid: UUID) -> str:
    prefix = _PREFIX_MAP.get(resource, resource[:3])
    return f"{prefix}_{_encode(uid)}"
