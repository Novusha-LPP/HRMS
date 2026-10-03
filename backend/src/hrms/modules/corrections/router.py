"""
Attendance corrections router.

GET  /v1/corrections              ?employment_id=&status= (defaults to
                                     everything the caller's scope covers)
POST /v1/corrections              — submit a correction request, defaults to self
POST /v1/corrections/{id}/approve (corrections.approve)
POST /v1/corrections/{id}/reject  (corrections.approve)
POST /v1/corrections/{id}/cancel

Same fix as leave: employment_id defaulted to and checked against the
caller's own scope instead of being trusted verbatim, and the approver is
always the caller (from the token), never a client-supplied query param.
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from hrms.core.approvals import require_reviewer
from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    authorize_write,
    read_scope,
    resolve_acting_employment_id,
    visible_employment_ids,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.approvals import service as approval_flow
from hrms.modules.corrections.models import (
    AttendanceCorrectionRequest,
    CorrectionApprovalAction,
    CorrectionStatus,
)
from hrms.modules.corrections.schemas import (
    CorrectionApprovalActionResponse,
    CorrectionApprovalRequest,
    CorrectionCreateRequest,
    CorrectionResponse,
)
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import Punch
from hrms.modules.time.service import (
    events_for_day,
    lock_day,
    recompute_day,
    work_bounds,
    work_date_for,
)

router = APIRouter(prefix="/v1/corrections", tags=["Attendance Corrections"])


@router.get("", response_model=list[CorrectionResponse])
async def list_corrections(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[CorrectionResponse]:
    scope = read_scope(scope, "corrections.read", "corrections.approve")
    q = (
        select(AttendanceCorrectionRequest)
        .where(AttendanceCorrectionRequest.tenant_id == tenant_id)
        .where(AttendanceCorrectionRequest.archived_at == None)  # noqa: E711
    )
    if employment_id:
        emp_uuid = to_uuid(employment_id)
        await authorize_employment(session, tenant_id, scope, emp_uuid)
        q = q.where(AttendanceCorrectionRequest.employment_id == emp_uuid)
    elif not scope.is_all:
        allowed_ids = await visible_employment_ids(session, tenant_id, scope)
        q = q.where(AttendanceCorrectionRequest.employment_id.in_(allowed_ids))
    if status:
        q = q.where(AttendanceCorrectionRequest.status == status)
    rows = await session.execute(q.order_by(AttendanceCorrectionRequest.work_date.desc()))
    results = []
    for cor in rows.scalars():
        history = await _get_history(session, tenant_id, cor.id)
        results.append(_cor_resp(cor, history))
    return results


@router.post("", response_model=CorrectionResponse, status_code=201)
async def create_correction(
    body: CorrectionCreateRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> CorrectionResponse:
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    await authorize_write(
        session, tenant_id, scope, principal, emp_uuid, "corrections.write", "corrections.request"
    )
    policy = await resolve_policy(emp_uuid, body.work_date, session, tenant_id)
    uid = uuid4()
    route = await approval_flow.start(session, tenant_id, "CORRECTION", uid, emp_uuid)
    requires_approval = route is not None or policy.correction_requires_approval
    total_levels = len(route.steps) if route else policy.correction_approval_levels
    status = CorrectionStatus.PENDING_L1 if requires_approval else CorrectionStatus.APPROVED
    cor = AttendanceCorrectionRequest(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        work_date=body.work_date,
        correction_type=body.correction_type,
        requested_punch_in=body.requested_punch_in,
        requested_punch_out=body.requested_punch_out,
        reason=body.reason,
        status=status,
        current_level=1 if requires_approval else 0,
        total_levels=max(total_levels, 1),
        submitted_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(cor)

    if status == CorrectionStatus.APPROVED:
        await _apply_correction(session, tenant_id, cor, policy)

    await session.flush()
    return _cor_resp(cor, [])


@router.post("/{correction_id}/approve", response_model=CorrectionResponse)
async def approve_correction(
    correction_id: str,
    body: CorrectionApprovalRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> CorrectionResponse:
    cor = await _get_cor(session, tenant_id, correction_id)
    if await approval_flow.current_instance(session, tenant_id, "CORRECTION", cor.id) is None:
        scope = scope.for_permission("corrections.approve")
        await authorize_employment(session, tenant_id, scope, cor.employment_id)
    _assert_pending(cor)
    await _check_reviewer(session, tenant_id, principal, scope, cor)

    action = CorrectionApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        correction_id=cor.id,
        action="APPROVE",
        level=cor.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)

    await approval_flow.record_decision(
        session, tenant_id, "CORRECTION", cor.id, principal, "APPROVE", body.comments
    )
    if cor.current_level >= cor.total_levels:
        cor.status = CorrectionStatus.APPROVED
        policy = await resolve_policy(cor.employment_id, cor.work_date, session, tenant_id)
        await _apply_correction(session, tenant_id, cor, policy)
    else:
        cor.current_level += 1
        cor.status = approval_flow.pending_status(cor.current_level)

    session.add(cor)
    await session.flush()
    return _cor_resp(cor, await _get_history(session, tenant_id, cor.id))


@router.post("/{correction_id}/reject", response_model=CorrectionResponse)
async def reject_correction(
    correction_id: str,
    body: CorrectionApprovalRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> CorrectionResponse:
    cor = await _get_cor(session, tenant_id, correction_id)
    if await approval_flow.current_instance(session, tenant_id, "CORRECTION", cor.id) is None:
        scope = scope.for_permission("corrections.approve")
        await authorize_employment(session, tenant_id, scope, cor.employment_id)
    _assert_pending(cor)
    await _check_reviewer(session, tenant_id, principal, scope, cor)

    action = CorrectionApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        correction_id=cor.id,
        action="REJECT",
        level=cor.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)
    await approval_flow.record_decision(
        session, tenant_id, "CORRECTION", cor.id, principal, "REJECT", body.comments
    )
    cor.status = CorrectionStatus.REJECTED
    session.add(cor)
    await session.flush()
    return _cor_resp(cor, await _get_history(session, tenant_id, cor.id))


@router.post("/{correction_id}/cancel", response_model=CorrectionResponse)
async def cancel_correction(
    correction_id: str,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> CorrectionResponse:
    cor = await _get_cor(session, tenant_id, correction_id)
    await authorize_write(
        session,
        tenant_id,
        scope,
        principal,
        cor.employment_id,
        "corrections.write",
        "corrections.request",
    )
    if cor.status not in (
        CorrectionStatus.DRAFT,
        CorrectionStatus.PENDING_L1,
        CorrectionStatus.PENDING_L2,
        CorrectionStatus.PENDING_L3,
        "PENDING",
    ):
        raise HTTPException(400, f"Cannot cancel correction in status {cor.status}")
    await approval_flow.finish(session, tenant_id, "CORRECTION", cor.id, "CANCELLED")
    cor.status = CorrectionStatus.CANCELLED
    session.add(cor)
    await session.flush()
    return _cor_resp(cor, await _get_history(session, tenant_id, cor.id))


# ─── Apply correction to attendance ───────────────────────────────────────────


async def _apply_correction(session, tenant_id, cor: AttendanceCorrectionRequest, policy) -> None:
    ad = await lock_day(session, tenant_id, cor.employment_id, cor.work_date)
    events = await events_for_day(session, tenant_id, cor.employment_id, cor.work_date, policy)
    replacements = []
    if cor.correction_type == "MARK_ABSENT":
        replacements = [("VOID", e.punched_at, e.id) for e in events]
    else:
        for kind, stamp in (("IN", cor.requested_punch_in), ("OUT", cor.requested_punch_out)):
            if stamp:
                start, end = work_bounds(cor.work_date, policy)
                if not start <= stamp < end:
                    raise HTTPException(422, "Punch is outside the requested work day")
                if kind == "IN" and work_date_for(stamp, policy) != cor.work_date:
                    raise HTTPException(422, "Punch IN is outside the requested work date")
                existing = [e for e in events if e.punch_type == kind]
                original = (existing[0] if kind == "IN" else existing[-1]) if existing else None
                replacements.append((kind, stamp, original.id if original else None))
    for kind, stamp, original in replacements:
        session.add(
            Punch(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=cor.employment_id,
                work_date=cor.work_date,
                punch_type=kind,
                punched_at=stamp,
                source="MANUAL",
                is_corrected=True,
                original_punch_id=original,
                correction_reason=cor.reason[:255],
                recorded_at=now_utc(),
            )
        )
    await session.flush()
    await recompute_day(session, tenant_id, cor.employment_id, cor.work_date, policy, ad)


async def _check_reviewer(session, tenant_id, principal, scope, cor):
    if await approval_flow.require_actor(session, tenant_id, "CORRECTION", cor.id, principal):
        return
    history = list(
        (
            await session.execute(
                select(CorrectionApprovalAction)
                .where(CorrectionApprovalAction.tenant_id == tenant_id)
                .where(CorrectionApprovalAction.correction_id == cor.id)
            )
        ).scalars()
    )
    await require_reviewer(
        session,
        tenant_id,
        principal,
        scope,
        cor.employment_id,
        cor.current_level,
        {a.approver_user_account_id for a in history},
        {a.approver_employment_id for a in history},
        "corrections.write",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _cor_resp(cor: AttendanceCorrectionRequest, history: list) -> CorrectionResponse:
    return CorrectionResponse(
        id=to_typed_id("attendance_correction", cor.id),
        employment_id=to_typed_id("employment", cor.employment_id),
        work_date=cor.work_date,
        correction_type=cor.correction_type,
        requested_punch_in=cor.requested_punch_in,
        requested_punch_out=cor.requested_punch_out,
        reason=cor.reason,
        status=cor.status,
        current_level=cor.current_level,
        total_levels=cor.total_levels,
        submitted_at=cor.submitted_at,
        approval_history=history,
    )


async def _get_cor(session, tenant_id, cor_id: str) -> AttendanceCorrectionRequest:
    uid = to_uuid(cor_id)
    row = await session.execute(
        select(AttendanceCorrectionRequest)
        .where(AttendanceCorrectionRequest.tenant_id == tenant_id)
        .where(AttendanceCorrectionRequest.id == uid)
        .with_for_update()
    )
    cor = row.scalars().first()
    if not cor:
        raise HTTPException(404, "Correction request not found")
    return cor


async def _get_history(session, tenant_id, cor_id) -> list[CorrectionApprovalActionResponse]:
    rows = await session.execute(
        select(CorrectionApprovalAction)
        .where(CorrectionApprovalAction.tenant_id == tenant_id)
        .where(CorrectionApprovalAction.correction_id == cor_id)
        .order_by(CorrectionApprovalAction.actioned_at)
    )
    return [
        CorrectionApprovalActionResponse(
            id=to_typed_id("correction_approval", a.id),
            correction_id=to_typed_id("attendance_correction", a.correction_id),
            action=a.action,
            level=a.level,
            approver_employment_id=to_typed_id("employment", a.approver_employment_id)
            if a.approver_employment_id
            else None,
            comments=a.comments,
            actioned_at=a.actioned_at,
        )
        for a in rows.scalars()
    ]


def _assert_pending(cor: AttendanceCorrectionRequest) -> None:
    if cor.status not in (
        CorrectionStatus.PENDING_L1,
        CorrectionStatus.PENDING_L2,
        CorrectionStatus.PENDING_L3,
        "PENDING",
    ):
        raise HTTPException(400, f"Correction not pending approval (status: {cor.status})")
