"""
Optimistic locking for edits (docs/database-hardening-plan.md, W6).

Every editable master record carries a `version`. A client that read version N sends it back
with its change; if someone else saved in between, the change is refused with 409
STALE_VERSION instead of silently overwriting theirs. The row is re-read under a lock first, so
two simultaneous saves can't both pass the check.

Sending `version` is optional for now, so older clients keep working (last write wins for
them); the DB-2 release makes it required.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.errors import CodedHTTPException


async def require_version(session: AsyncSession, row: Any, expected: int | None) -> None:
    """Lock and reload `row`, refuse a stale `expected` version, and bump the version."""
    await session.refresh(row, with_for_update=True)
    if expected is not None and expected != row.version:
        raise CodedHTTPException(
            409,
            "Someone else changed this record after you opened it. Reload it and try again.",
            code="STALE_VERSION",
        )
    row.version = (row.version or 0) + 1


def version_field() -> Any:
    """The optional `version` field of an update body."""
    return Field(
        default=None,
        description="The version you loaded; if the record changed since, the edit is refused "
        "with 409 STALE_VERSION",
    )
