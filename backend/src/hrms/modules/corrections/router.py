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
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, resolve_acting_employment_id
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
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
from hrms.modules.time.models import AttendanceDay, AttendanceStatus, apply_overtime

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
        if scope.employment_ids is not None:
            if not scope.employment_ids:
                return []
            q = q.where(AttendanceCorrectionRequest.employment_id.in_(scope.employment_ids))
        elif scope.legal_entity_ids:
            allowed = await session.execute(
                text("""
                    SELECT id FROM employments
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND legal_entity_id = ANY(CAST(:ids AS uuid[]))
                """),
                {"tid": str(tenant_id), "ids": [str(i) for i in scope.legal_entity_ids]},
            )
            allowed_ids = [r[0] for r in allowed]
            if not allowed_ids:
                return []
            q = q.where(AttendanceCorrectionRequest.employment_id.in_(allowed_ids))
        else:
            return []
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

    policy = await resolve_policy(emp_uuid, body.work_date, session, tenant_id)
    total_levels = policy.correction_approval_levels if policy.correction_requires_approval else 0

    uid = uuid4()
    status = CorrectionStatus.PENDING_L1 if policy.correction_requires_approval else CorrectionStatus.APPROVED
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
        current_level=1 if policy.correction_requires_approval else 0,
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
    scope.require("corrections.approve")
    cor = await _get_cor(session, tenant_id, correction_id)
    await authorize_employment(session, tenant_id, scope, cor.employment_id)
    _assert_pending(cor)
    approver_uuid = _require_approver(principal)

    action = CorrectionApprovalAction(
        tenant_id=tenant_id, id=uuid4(), correction_id=cor.id,
        action="APPROVE", level=cor.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)

    if cor.current_level >= cor.total_levels:
        cor.status = CorrectionStatus.APPROVED
        policy = await resolve_policy(cor.employment_id, cor.work_date, session, tenant_id)
        await _apply_correction(session, tenant_id, cor, policy)
    else:
        cor.current_level += 1
        next_statuses = [None, CorrectionStatus.PENDING_L1, CorrectionStatus.PENDING_L2, CorrectionStatus.PENDING_L3]
        cor.status = next_statuses[cor.current_level]

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
    scope.require("corrections.approve")
    cor = await _get_cor(session, tenant_id, correction_id)
    await authorize_employment(session, tenant_id, scope, cor.employment_id)
    _assert_pending(cor)
    approver_uuid = _require_approver(principal)

    action = CorrectionApprovalAction(
        tenant_id=tenant_id, id=uuid4(), correction_id=cor.id,
        action="REJECT", level=cor.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)
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
) -> CorrectionResponse:
    cor = await _get_cor(session, tenant_id, correction_id)
    await authorize_employment(session, tenant_id, scope, cor.employment_id)
    if cor.status not in (CorrectionStatus.DRAFT, CorrectionStatus.PENDING_L1, CorrectionStatus.PENDING_L2, CorrectionStatus.PENDING_L3):
        raise HTTPException(400, f"Cannot cancel correction in status {cor.status}")
    cor.status = CorrectionStatus.CANCELLED
    session.add(cor)
    await session.flush()
    return _cor_resp(cor, await _get_history(session, tenant_id, cor.id))


# ─── Apply correction to attendance ───────────────────────────────────────────

async def _apply_correction(session, tenant_id, cor: AttendanceCorrectionRequest, policy) -> None:
    """
    Once a correction is approved, update the AttendanceDay and Punch records.
    All recalculation is driven by the resolved policy — no hard-coded rules.
    """
    from hrms.core.datetime_utils import compute_day
    from uuid import uuid4

    ad_row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == cor.employment_id)
        .where(AttendanceDay.work_date == cor.work_date)
    )
    ad = ad_row.scalars().first()
    if ad is None:
        ad = AttendanceDay(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=cor.employment_id,
            work_date=cor.work_date,
            status=AttendanceStatus.PENDING,
            recorded_at=now_utc(),
        )

    if cor.correction_type == "MARK_ABSENT":
        ad.status = AttendanceStatus.ABSENT
        ad.first_punch_in = None
        ad.last_punch_out = None
        ad.gross_minutes = 0
        ad.effective_minutes = 0
        ad.late_by_minutes = 0
        ad.early_departure_minutes = 0
        apply_overtime(ad, 0)
        session.add(ad)
        return

    if cor.correction_type == "MARK_PRESENT" and cor.requested_punch_in and cor.requested_punch_out:
        punch_in = cor.requested_punch_in
        punch_out = cor.requested_punch_out
    elif cor.correction_type in ("PUNCH_IN", "MISSED_PUNCH", "REGULARIZE") and cor.requested_punch_in:
        punch_in = cor.requested_punch_in
        punch_out = cor.requested_punch_out or ad.last_punch_out
    elif cor.correction_type == "PUNCH_OUT" and cor.requested_punch_out:
        punch_in = ad.first_punch_in or cor.requested_punch_in
        punch_out = cor.requested_punch_out
    else:
        session.add(ad)
        return

    if punch_in and punch_out:
        result = compute_day(
            punch_in=punch_in,
            punch_out=punch_out,
            break_minutes=policy.break_minutes,
            expected_start=policy.expected_start_time,
            expected_end=policy.expected_end_time,
            grace_late_minutes=policy.grace_late_minutes,
            grace_early_departure_minutes=policy.grace_early_departure_minutes,
            half_day_threshold_pct=policy.half_day_threshold_pct,
            ot_enabled=policy.ot_enabled,
            ot_qualifying_minutes=policy.ot_qualifying_minutes,
            ot_daily_cap_minutes=policy.ot_daily_cap_minutes,
            tz_name=policy.timezone,
            punch_rounding_minutes=policy.punch_rounding_minutes,
            punch_rounding_direction=policy.punch_rounding_direction,
            break_auto_deduct=policy.break_auto_deduct,
        )
        ad.first_punch_in = punch_in
        ad.last_punch_out = punch_out
        ad.gross_minutes = result.gross_minutes
        ad.break_minutes = result.break_minutes
        ad.effective_minutes = result.effective_minutes
        ad.late_by_minutes = result.late_by_minutes
        ad.early_departure_minutes = result.early_departure_minutes
        ad.status = getattr(AttendanceStatus, result.status, AttendanceStatus.PRESENT)
        apply_overtime(ad, result.ot_minutes)

    session.add(ad)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _require_approver(principal: CurrentUser):
    if principal.employment_id is None:
        raise HTTPException(400, "This account has no employment record and cannot approve requests")
    return principal.employment_id


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
            approver_employment_id=to_typed_id("employment", a.approver_employment_id) if a.approver_employment_id else None,
            comments=a.comments,
            actioned_at=a.actioned_at,
        )
        for a in rows.scalars()
    ]


def _assert_pending(cor: AttendanceCorrectionRequest) -> None:
    if cor.status not in (CorrectionStatus.PENDING_L1, CorrectionStatus.PENDING_L2, CorrectionStatus.PENDING_L3):
        raise HTTPException(400, f"Correction not pending approval (status: {cor.status})")
