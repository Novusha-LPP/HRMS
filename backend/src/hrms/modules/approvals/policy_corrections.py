"""Present policy-based correction reviews in the shared approval inbox.

These requests keep their existing policy and reporting-manager authorization.
They have no configurable flow snapshot and cannot use flow delegation.
"""

from fastapi import HTTPException
from sqlalchemy import exists, text
from sqlmodel import col, select

from hrms.core.authz import authorize_employment, visible_employment_ids
from hrms.core.ids import to_typed_id, to_uuid
from hrms.modules.approvals.models import ApprovalInstance
from hrms.modules.corrections import router as corrections
from hrms.modules.corrections.models import AttendanceCorrectionRequest
from hrms.modules.corrections.schemas import CorrectionApprovalRequest

PENDING = ("PENDING_L1", "PENDING_L2", "PENDING_L3", "PENDING")


def without_flow():
    return ~exists(
        select(ApprovalInstance.id).where(
            ApprovalInstance.tenant_id == AttendanceCorrectionRequest.tenant_id,
            ApprovalInstance.request_type == "CORRECTION",
            ApprovalInstance.request_id == AttendanceCorrectionRequest.id,
        )
    )


async def get(session, tenant_id, scope, principal, request_id):
    cor = (
        (
            await session.execute(
                select(AttendanceCorrectionRequest).where(
                    AttendanceCorrectionRequest.tenant_id == tenant_id,
                    AttendanceCorrectionRequest.id == to_uuid(request_id),
                    col(AttendanceCorrectionRequest.archived_at).is_(None),
                    without_flow(),
                )
            )
        )
        .scalars()
        .first()
    )
    if cor is None:
        raise HTTPException(404, "Policy correction request not found")
    if principal.employment_id != cor.employment_id:
        await authorize_employment(
            session, tenant_id, scope.for_permission("corrections.approve"), cor.employment_id
        )
    return cor


async def public(session, tenant_id, scope, principal, cor):
    can_act = False
    if cor.status in PENDING and scope.has("corrections.approve"):
        try:
            review_scope = scope.for_permission("corrections.approve")
            await authorize_employment(session, tenant_id, review_scope, cor.employment_id)
            await corrections._check_reviewer(session, tenant_id, principal, review_scope, cor)
            can_act = True
        except HTTPException as exc:
            if exc.status_code not in (403, 409):
                raise
    person = (
        (
            await session.execute(
                text("""
                SELECT e.employee_number,
                       p.legal_first_name || ' ' || p.legal_last_name AS employee_name
                FROM employments e JOIN persons p
                  ON p.tenant_id=e.tenant_id AND p.id=e.person_id
                WHERE e.tenant_id=:tid AND e.id=:eid
            """),
                dict(tid=tenant_id, eid=cor.employment_id),
            )
        )
        .mappings()
        .one()
    )
    history = await corrections._get_history(session, tenant_id, cor.id)
    return dict(
        approval_mode="POLICY",
        id=to_typed_id("attendance_correction", cor.id),
        request_id=to_typed_id("attendance_correction", cor.id),
        request_type="CORRECTION",
        employment_id=to_typed_id("employment", cor.employment_id),
        employee_name=person["employee_name"],
        employee_number=person["employee_number"],
        flow_id=None,
        flow_name="Attendance policy",
        flow_version=0,
        steps=[
            dict(name=f"Approval level {level}", approver_ids=[])
            for level in range(1, cor.total_levels + 1)
        ],
        current_level=cor.current_level,
        status="PENDING" if cor.status in PENDING else cor.status,
        can_act=can_act,
        delegable_levels=[],
        can_manage_flow=False,
        request=dict(
            work_date=cor.work_date,
            correction_type=cor.correction_type,
            requested_punch_in=cor.requested_punch_in,
            requested_punch_out=cor.requested_punch_out,
            reason=cor.reason,
        ),
        history=[
            dict(
                action=h.action,
                actor_id=None,
                actor_name=f"Level {h.level} reviewer",
                details=dict(step_name=f"Approval level {h.level}", comments=h.comments),
                created_at=h.actioned_at,
            )
            for h in history
        ],
        created_at=cor.submitted_at,
    )


async def inbox(session, tenant_id, scope, principal):
    query = select(AttendanceCorrectionRequest).where(
        AttendanceCorrectionRequest.tenant_id == tenant_id,
        col(AttendanceCorrectionRequest.archived_at).is_(None),
        col(AttendanceCorrectionRequest.status).in_(PENDING),
        without_flow(),
    )
    if scope.has("corrections.approve"):
        review_scope = scope.for_permission("corrections.approve")
        if not review_scope.is_all:
            allowed = set(await visible_employment_ids(session, tenant_id, review_scope))
            if principal.employment_id:
                allowed.add(principal.employment_id)
            query = query.where(col(AttendanceCorrectionRequest.employment_id).in_(allowed))
    elif principal.employment_id:
        query = query.where(AttendanceCorrectionRequest.employment_id == principal.employment_id)
    else:
        return []
    rows = (
        await session.execute(query.order_by(col(AttendanceCorrectionRequest.submitted_at)))
    ).scalars()
    return [await public(session, tenant_id, scope, principal, cor) for cor in rows]


async def decide(session, tenant_id, scope, principal, request_id, body):
    # The domain handler locks the record and rechecks all decision authority.
    await get(session, tenant_id, scope, principal, request_id)
    handler = (
        corrections.approve_correction
        if body.action == "APPROVE"
        else corrections.reject_correction
    )
    await handler(
        request_id,
        CorrectionApprovalRequest(action=body.action, comments=body.comments),
        principal,
        scope,
        tenant_id,
        session,
    )
    cor = await get(session, tenant_id, scope, principal, request_id)
    return await public(session, tenant_id, scope, principal, cor)
