"""Approval eligibility shared by leave and attendance corrections."""

from fastapi import HTTPException
from sqlalchemy import text

from hrms.core.authz import authorize_employment


async def require_reviewer(
    session,
    tenant_id,
    principal,
    scope,
    employment_id,
    level,
    previous_accounts,
    previous_employments,
    admin_permission,
):
    if principal.employment_id == employment_id:
        raise HTTPException(403, "You cannot review your own request")
    if principal.user_account_id in previous_accounts or (
        principal.employment_id and principal.employment_id in previous_employments
    ):
        raise HTTPException(409, "A different reviewer is required at each approval level")
    manager = employment_id
    seen = {employment_id}
    for _ in range(level):
        manager = (
            await session.execute(
                text("""
            SELECT am.manager_employment_id FROM assignments a
            JOIN assignment_managers am ON am.tenant_id = a.tenant_id AND am.assignment_id = a.id
            WHERE a.tenant_id = :tid AND a.employment_id = :eid AND am.manager_type = 'LINE'
              AND a.effective_from <= CURRENT_DATE
              AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
              AND am.effective_from <= CURRENT_DATE
              AND (am.effective_to IS NULL OR am.effective_to > CURRENT_DATE)
            ORDER BY am.effective_from DESC LIMIT 1
        """),
                {"tid": tenant_id, "eid": manager},
            )
        ).scalar()
        if manager is None:
            break
        if manager in seen:
            raise HTTPException(409, "Reporting hierarchy contains a cycle")
        seen.add(manager)
    if manager:
        if principal.employment_id != manager:
            raise HTTPException(403, "This level must be reviewed by the designated line manager")
    else:
        # HR/admin handles levels for which the reporting chain has no manager.
        await authorize_employment(
            session, tenant_id, scope.for_permission(admin_permission), employment_id
        )
