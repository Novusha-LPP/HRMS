"""
Tenant identity, derived only from the verified JWT — never from a client-
supplied header. TenantDep keeps its original name/shape so every existing
route handler that declares `tenant_id: TenantDep` didn't need to change
when this switched from trusting X-Tenant-ID to trusting the access token.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from hrms.core.authn import CurrentUser


async def tenant_from_request(principal: CurrentUser) -> UUID:
    return principal.tenant_id


TenantDep = Annotated[UUID, Depends(tenant_from_request)]
