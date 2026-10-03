"""
Per-user preferences: GET/PATCH /v1/me/preferences.

Every signed-in tenant user reads and changes only their own; there is no way to address
anyone else's. Stored server-side so a choice follows the person to any device.
"""

from uuid import uuid4

from fastapi import APIRouter
from sqlalchemy import text

from hrms.core.authn import CurrentUser
from hrms.core.database import SessionDep
from hrms.core.tenancy import TenantDep
from hrms.modules.preferences.schemas import Preferences, PreferencesUpdate

router = APIRouter(prefix="/v1/me", tags=["Preferences"])


async def _read(session, tenant_id, principal) -> Preferences:
    row = (
        (
            await session.execute(
                text("""
                    SELECT color_theme, dashboard_style FROM user_preferences
                    WHERE tenant_id = CAST(:tid AS uuid) AND user_account_id = CAST(:uid AS uuid)
                """),
                {"tid": str(tenant_id), "uid": str(principal.user_account_id)},
            )
        )
        .mappings()
        .first()
    )
    return Preferences(**row) if row else Preferences()


@router.get("/preferences", response_model=Preferences, summary="Your theme and dashboard choice")
async def get_preferences(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> Preferences:
    return await _read(session, tenant_id, principal)


@router.patch("/preferences", response_model=Preferences, summary="Change your preferences")
async def update_preferences(
    body: PreferencesUpdate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> Preferences:
    merged = (await _read(session, tenant_id, principal)).model_copy(
        update=body.model_dump(exclude_none=True)
    )
    await session.execute(
        text("""
            INSERT INTO user_preferences (tenant_id, id, user_account_id, color_theme,
                                          dashboard_style, updated_at)
            VALUES (CAST(:tid AS uuid), CAST(:id AS uuid), CAST(:uid AS uuid), :theme,
                    :style, now())
            ON CONFLICT (tenant_id, user_account_id)
            DO UPDATE SET color_theme = EXCLUDED.color_theme,
                          dashboard_style = EXCLUDED.dashboard_style, updated_at = now()
        """),
        {
            "tid": str(tenant_id),
            "id": str(uuid4()),
            "uid": str(principal.user_account_id),
            "theme": merged.color_theme,
            "style": merged.dashboard_style,
        },
    )
    return merged
