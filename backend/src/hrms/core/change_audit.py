"""
Generic field-level change audit for tenant reference data — the tenant-scoped
counterpart to core/audit.py (which only covers the platform console).

Every writer goes through record_change(), which:
  * keeps entity_type a small, known vocabulary instead of free text that
    drifts as new call sites get added (extend ENTITY_TYPES, not a raw string);
  * diffs `before`/`after` itself, so a call site never has to hand-build the
    {"field": {"old", "new"}} shape, or accidentally record fields that didn't
    change;
  * coerces UUID/date/datetime/Enum values to something JSONB can actually
    store, so callers can pass model attributes straight through.

Append-only at the database level too (migration 0021): the hrms_app role has
SELECT and INSERT on entity_change_log, nothing else — mirrors kyc_access_log.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.kernel.models import EntityChangeLog

# Extend this when wiring a new entity's PATCH endpoint into the audit trail —
# record_change() refuses anything not listed here.
ENTITY_TYPES = frozenset({"legal_entity", "location", "org_unit", "job"})

ACTIONS = frozenset({"CREATE", "UPDATE", "ARCHIVE"})


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return str(value)


async def record_change(
    session: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
    changed_by: UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """
    Diff `before` and `after` (plain {field: value} dicts) and append one row
    if anything actually differs; a no-op diff writes nothing.

    `before=None` means the entity didn't exist yet (a CREATE) — every field
    in `after` is recorded as old=None. `after=None` means it's being
    archived — pass the fields as they stood immediately before archiving,
    they're recorded as new=None. For an UPDATE, pass only the fields the
    caller actually tried to change (e.g. a Pydantic model's
    `model_dump(exclude_unset=True)` keys) in both dicts — untouched fields
    can't have changed, so there's no need to diff the whole row.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unknown entity_type for change audit: {entity_type!r}")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action for change audit: {action!r}")

    before = before or {}
    after = after or {}
    diff: dict[str, Any] = {}
    for key in before.keys() | after.keys():
        old_raw, new_raw = before.get(key), after.get(key)
        if old_raw != new_raw:
            diff[key] = {"old": _jsonable(old_raw), "new": _jsonable(new_raw)}
    if not diff:
        return

    session.add(
        EntityChangeLog(
            tenant_id=tenant_id,
            id=uuid4(),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            changes=diff,
            changed_by=changed_by,
        )
    )
    await session.flush()
