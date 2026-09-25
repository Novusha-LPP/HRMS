"""
Opaque typed IDs for the public API.

Internal storage: UUIDv7 (time-ordered, random suffix).
Public representation: "<prefix>_<base32-encoded-uuid>" e.g. emp_01J8Z3K7Q9...

Rules from the architecture:
- Never expose raw database UUIDs in the API.
- Never reuse an ID after deletion.
- Typed prefixes make IDs self-describing and prevent cross-resource confusion.
"""

import base64
import uuid
from uuid import UUID

try:
    from uuid7 import uuid7  # type: ignore[import-untyped]
except ImportError:
    # Fallback to uuid4 if uuid7 is not installed yet
    def uuid7() -> UUID:  # type: ignore[misc]
        return uuid.uuid4()


_PREFIX_MAP: dict[str, str] = {
    "tenant": "ten",
    "legal_entity": "le",
    "location": "loc",
    "org_unit": "ou",
    "job": "job",
    "grade": "grd",
    "position": "pos",
    "cost_centre": "cc",
    "person": "per",
    "employment": "emp",
    "assignment": "asgn",
    "personnel_action": "pa",
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
    # Corrections
    "attendance_correction": "cor",
    "correction_approval": "cappr",
    # KYC
    "kyc_record": "kyc",
    "kyc_document": "kdoc",
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
    parts = typed_id.split("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid typed ID: {typed_id!r}")
    return _decode(parts[1])


def to_typed_id(resource: str, uid: UUID) -> str:
    prefix = _PREFIX_MAP.get(resource, resource[:3])
    return f"{prefix}_{_encode(uid)}"
