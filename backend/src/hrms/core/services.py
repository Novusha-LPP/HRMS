"""Optional services the platform switches on per company (tenants.enabled_services)."""

from __future__ import annotations

from typing import Literal, get_args
from uuid import UUID

from fastapi import Depends
from sqlalchemy import text

from hrms.core.database import SessionDep
from hrms.core.errors import CodedHTTPException
from hrms.core.tenancy import TenantDep

Service = Literal["SCHEDULED_MAIL"]
SERVICES: tuple[str, ...] = get_args(Service)
SCHEDULED_MAIL: Service = "SCHEDULED_MAIL"


async def enabled_services(session, tenant_id: UUID) -> list[str]:
    row = await session.execute(
        text("SELECT enabled_services FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )
    return sorted(row.scalar() or [])


async def is_enabled(session, tenant_id: UUID, service: str) -> bool:
    return service in await enabled_services(session, tenant_id)


def require_service(service: Service):
    """Refuse a request unless the platform has switched this service on for the company."""

    async def _dep(tenant_id: TenantDep, session: SessionDep) -> None:
        if not await is_enabled(session, tenant_id, service):
            raise CodedHTTPException(
                403,
                "This service is not enabled for your company. Ask your platform administrator.",
                code="SERVICE_NOT_ENABLED",
            )

    return Depends(_dep)
