"""Platform audit log — one helper, called from every mutating platform action."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.platform_authz import PlatformAdminContext
from hrms.modules.kernel.models import PlatformAuditLog


async def record_audit(
    session: AsyncSession, actor: PlatformAdminContext, action: str,
    target_type: str, target_id: UUID | None, target_label: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(PlatformAuditLog(
        id=uuid4(), actor_admin_id=actor.admin_id, actor_name=actor.name,
        action=action, target_type=target_type, target_id=target_id,
        target_label=target_label, metadata_json=metadata,
    ))
    await session.flush()
