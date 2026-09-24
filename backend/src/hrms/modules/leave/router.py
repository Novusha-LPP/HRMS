"""
Leave module router.

Leave types (HR-managed, tenant-wide catalog — not per-employee data):
  GET    /v1/leave/types
  POST   /v1/leave/types                      (leave.write)
  PATCH  /v1/leave/types/{id}                 (leave.write)

Leave balances:
  GET    /v1/leave/balances          ?employment_id=&year=   (defaults to self)
  POST   /v1/leave/balances/init     — bulk-initialise balances for a year

Leave applications:
  GET    /v1/leave/applications      ?employment_id=&status= (defaults to
                                        everything the caller's scope covers)
  POST   /v1/leave/applications      — create (DRAFT), defaults to self
  POST   /v1/leave/applications/{id}/submit
  POST   /v1/leave/applications/{id}/cancel
  POST   /v1/leave/applications/{id}/approve         (leave.approve)
  POST   /v1/leave/applications/{id}/reject          (leave.approve)
  POST   /v1/leave/applications/{id}/cancel-approve  (leave.approve)
  POST   /v1/leave/applications/{id}/cancel-reject   (leave.approve)

Every employment_id / approver_employment_id used to be a bare, trusted
query parameter — any signed-in user could read or act on any other
employee's leave by changing it. employment_id now defaults to the caller's
own and is checked against their scope if they name someone else; approver
identity is always the caller (from the verified token), never a parameter.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission, resolve_acting_employment_id
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc, working_days_between
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.leave.models import (
    LeaveApprovalAction,
    LeaveApprovalActionType,
    LeaveApplication,
    LeaveApplicationStatus,
    LeaveBalance,
    LeaveType,
)
from hrms.modules.leave.schemas import (
    LeaveApplyRequest,
    LeaveApprovalActionRequest,
    LeaveApprovalActionResponse,
    LeaveApplicationResponse,
    LeaveBalanceResponse,
    LeaveCancelRequest,
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
)

router = APIRouter(prefix="/v1/leave", tags=["Leave Management"])


# ─── Leave types ──────────────────────────────────────────────────────────────

@router.get("/types", response_model=list[LeaveTypeResponse])
async def list_leave_types(
    tenant_id: TenantDep = None,
    session: SessionDep = None,
) -> list[LeaveTypeResponse]:
    rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.archived_at == None)  # noqa: E711
        .order_by(LeaveType.name)
    )
    return [_lt_resp(t) for t in rows.scalars()]


@router.post("/types", response_model=LeaveTypeResponse, status_code=201,
             dependencies=[require_permission("leave.write")])
async def create_leave_type(
    body: LeaveTypeCreate,
    tenant_id: TenantDep = None,
    session: SessionDep = None,
) -> LeaveTypeResponse:
    uid = uuid4()
    lt = LeaveType(tenant_id=tenant_id, id=uid, recorded_at=now_utc(), **body.model_dump())
    session.add(lt)
    await session.flush()
    return _lt_resp(lt)


@router.patch("/types/{leave_type_id}", response_model=LeaveTypeResponse,
              dependencies=[require_permission("leave.write")])
async def update_leave_type(
    leave_type_id: str,
    body: LeaveTypeUpdate,
    tenant_id: TenantDep = None,
    session: SessionDep = None,
) -> LeaveTypeResponse:
    lt = await _get_lt(session, tenant_id, leave_type_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(lt, k, v)
    session.add(lt)
    await session.flush()
    return _lt_resp(lt)


# ─── Leave balances ───────────────────────────────────────────────────────────

@router.get("/balances", response_model=list[LeaveBalanceResponse])
async def list_balances(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
    year: int | None = Query(default=None),
) -> list[LeaveBalanceResponse]:
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    if year is None:
        year = now_utc().year
    rows = await session.execute(
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .where(LeaveBalance.tenant_id == tenant_id)
        .where(LeaveBalance.employment_id == emp_uuid)
        .where(LeaveBalance.year == year)
    )
    return [
        LeaveBalanceResponse(
            id=to_typed_id("leave_balance", b.id),
            employment_id=to_typed_id("employment", emp_uuid),
            leave_type_id=to_typed_id("leave_type", b.leave_type_id),
            leave_type_name=lt.name,
            leave_type_code=lt.code,
            year=b.year,
            allocated_days=b.allocated_days,
            carry_forward_days=b.carry_forward_days,
            used_days=b.used_days,
            pending_days=b.pending_days,
            available_days=max(0.0, b.allocated_days + b.carry_forward_days - b.used_days - b.pending_days),
            color=lt.color,
        )
        for b, lt in rows
    ]


@router.post("/balances/init", status_code=201, dependencies=[require_permission("leave.write")])
async def init_balances(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    employment_id: str = Query(...),
    year: int = Query(...),
) -> dict:
    """Create leave balance records for all active leave types for one employee/year."""
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    lt_rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.is_active == True)  # noqa: E712
        .where(LeaveType.archived_at == None)  # noqa: E711
    )
    created = 0
    for lt in lt_rows.scalars():
        existing = await session.execute(
            select(LeaveBalance)
            .where(LeaveBalance.tenant_id == tenant_id)
            .where(LeaveBalance.employment_id == emp_uuid)
            .where(LeaveBalance.leave_type_id == lt.id)
            .where(LeaveBalance.year == year)
        )
        if existing.scalars().first():
            continue
        lb = LeaveBalance(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=emp_uuid,
            leave_type_id=lt.id,
            year=year,
            allocated_days=lt.days_per_year,
            recorded_at=now_utc(),
        )
        session.add(lb)
        created += 1
    await session.flush()
    return {"created": created, "employment_id": employment_id, "year": year}


# ─── Leave applications ───────────────────────────────────────────────────────

@router.get("/applications", response_model=list[LeaveApplicationResponse])
async def list_applications(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[LeaveApplicationResponse]:
    q = (
        select(LeaveApplication, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveApplication.leave_type_id)
        .where(LeaveApplication.tenant_id == tenant_id)
        .where(LeaveApplication.archived_at == None)  # noqa: E711
    )
    if employment_id:
        emp_uuid = to_uuid(employment_id)
        await authorize_employment(session, tenant_id, scope, emp_uuid)
        q = q.where(LeaveApplication.employment_id == emp_uuid)
    elif not scope.is_all:
        if scope.employment_ids is not None:
            if not scope.employment_ids:
                return []
            q = q.where(LeaveApplication.employment_id.in_(scope.employment_ids))
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
            q = q.where(LeaveApplication.employment_id.in_(allowed_ids))
        else:
            return []
    if status:
        q = q.where(LeaveApplication.status == status)
    rows = await session.execute(q.order_by(LeaveApplication.applied_at.desc()))
    results = []
    for app, lt in rows:
        history = await _get_history(session, tenant_id, app.id)
        results.append(_app_resp(app, lt, history))
    return results


@router.post("/applications", response_model=LeaveApplicationResponse, status_code=201)
async def create_application(
    body: LeaveApplyRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> LeaveApplicationResponse:
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    lt = await _get_lt(session, tenant_id, body.leave_type_id)

    days = working_days_between(body.from_date, body.to_date, "1111100")
    if body.half_day_option != "NONE":
        days = 0.5

    uid = uuid4()
    app = LeaveApplication(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        leave_type_id=lt.id,
        from_date=body.from_date,
        to_date=body.to_date,
        days_requested=days,
        half_day_option=body.half_day_option,
        reason=body.reason,
        status=LeaveApplicationStatus.DRAFT,
        total_levels=lt.approval_levels,
        recorded_at=now_utc(),
    )
    session.add(app)
    await session.flush()
    return _app_resp(app, lt, [])


@router.post("/applications/{app_id}/submit", response_model=LeaveApplicationResponse)
async def submit_application(
    app_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    if app.status != LeaveApplicationStatus.DRAFT:
        raise HTTPException(400, f"Cannot submit: status is {app.status}")

    await _adjust_balance(session, tenant_id, app.employment_id, lt.id, now_utc().year, pending_delta=app.days_requested)

    if lt.requires_approval:
        app.status = LeaveApplicationStatus.PENDING_L1
        app.current_level = 1
    else:
        app.status = LeaveApplicationStatus.APPROVED
        await _adjust_balance(session, tenant_id, app.employment_id, lt.id, now_utc().year,
                              pending_delta=-app.days_requested, used_delta=app.days_requested)
    app.applied_at = now_utc()
    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


@router.post("/applications/{app_id}/approve", response_model=LeaveApplicationResponse)
async def approve_application(
    app_id: str,
    body: LeaveApprovalActionRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    scope.require("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_pending(app)
    approver_uuid = _require_approver(principal)

    action = LeaveApprovalAction(
        tenant_id=tenant_id, id=uuid4(), application_id=app.id,
        action_type=LeaveApprovalActionType.APPROVE, level=app.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)

    if app.current_level >= app.total_levels:
        app.status = LeaveApplicationStatus.APPROVED
        await _adjust_balance(session, tenant_id, app.employment_id, lt.id, app.from_date.year,
                              pending_delta=-app.days_requested, used_delta=app.days_requested)
    else:
        app.current_level += 1
        next_status = [None, LeaveApplicationStatus.PENDING_L1, LeaveApplicationStatus.PENDING_L2, LeaveApplicationStatus.PENDING_L3]
        app.status = next_status[app.current_level]

    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


@router.post("/applications/{app_id}/reject", response_model=LeaveApplicationResponse)
async def reject_application(
    app_id: str,
    body: LeaveApprovalActionRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    scope.require("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_pending(app)
    approver_uuid = _require_approver(principal)

    action = LeaveApprovalAction(
        tenant_id=tenant_id, id=uuid4(), application_id=app.id,
        action_type=LeaveApprovalActionType.REJECT, level=app.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)

    app.status = LeaveApplicationStatus.REJECTED
    await _adjust_balance(session, tenant_id, app.employment_id, lt.id, app.from_date.year,
                          pending_delta=-app.days_requested)
    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


@router.post("/applications/{app_id}/cancel", response_model=LeaveApplicationResponse)
async def cancel_application(
    app_id: str,
    body: LeaveCancelRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)

    if app.status == LeaveApplicationStatus.DRAFT:
        app.status = LeaveApplicationStatus.CANCELLED
        session.add(app)
        await session.flush()
        return _app_resp(app, lt, [])

    if app.status in (LeaveApplicationStatus.PENDING_L1, LeaveApplicationStatus.PENDING_L2, LeaveApplicationStatus.PENDING_L3):
        app.status = LeaveApplicationStatus.CANCELLED
        app.cancel_reason = body.cancel_reason
        app.cancel_requested_at = now_utc()
        await _adjust_balance(session, tenant_id, app.employment_id, lt.id, app.from_date.year,
                              pending_delta=-app.days_requested)
        session.add(app)
        await session.flush()
        return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))

    if app.status == LeaveApplicationStatus.APPROVED:
        if lt.cancel_requires_approval:
            app.status = LeaveApplicationStatus.CANCEL_PENDING_L1
            app.current_level = 1
            app.total_levels = lt.cancel_approval_levels
        else:
            app.status = LeaveApplicationStatus.CANCELLED
            await _adjust_balance(session, tenant_id, app.employment_id, lt.id, app.from_date.year,
                                  used_delta=-app.days_requested)
        app.cancel_reason = body.cancel_reason
        app.cancel_requested_at = now_utc()
        session.add(app)
        await session.flush()
        return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))

    raise HTTPException(400, f"Cannot cancel leave in status {app.status}")


@router.post("/applications/{app_id}/cancel-approve", response_model=LeaveApplicationResponse)
async def approve_cancellation(
    app_id: str,
    body: LeaveApprovalActionRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    scope.require("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_cancel_pending(app)
    approver_uuid = _require_approver(principal)

    action = LeaveApprovalAction(
        tenant_id=tenant_id, id=uuid4(), application_id=app.id,
        action_type=LeaveApprovalActionType.CANCEL_APPROVE, level=app.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)

    if app.current_level >= app.total_levels:
        app.status = LeaveApplicationStatus.CANCELLED
        await _adjust_balance(session, tenant_id, app.employment_id, lt.id, app.from_date.year,
                              used_delta=-app.days_requested)
    else:
        app.current_level += 1
        cancel_statuses = [None, LeaveApplicationStatus.CANCEL_PENDING_L1, LeaveApplicationStatus.CANCEL_PENDING_L2, LeaveApplicationStatus.CANCEL_PENDING_L3]
        app.status = cancel_statuses[app.current_level]

    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


@router.post("/applications/{app_id}/cancel-reject", response_model=LeaveApplicationResponse)
async def reject_cancellation(
    app_id: str,
    body: LeaveApprovalActionRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    scope.require("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_cancel_pending(app)
    approver_uuid = _require_approver(principal)

    action = LeaveApprovalAction(
        tenant_id=tenant_id, id=uuid4(), application_id=app.id,
        action_type=LeaveApprovalActionType.CANCEL_REJECT, level=app.current_level,
        approver_employment_id=approver_uuid, comments=body.comments,
        actioned_at=now_utc(), recorded_at=now_utc(),
    )
    session.add(action)
    app.status = LeaveApplicationStatus.APPROVED
    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _require_approver(principal: CurrentUser) -> UUID:
    if principal.employment_id is None:
        raise HTTPException(400, "This account has no employment record and cannot approve requests")
    return principal.employment_id


def _lt_resp(lt: LeaveType) -> LeaveTypeResponse:
    return LeaveTypeResponse(
        id=to_typed_id("leave_type", lt.id),
        name=lt.name,
        code=lt.code,
        days_per_year=lt.days_per_year,
        carry_forward=lt.carry_forward,
        max_carry_forward_days=lt.max_carry_forward_days,
        requires_approval=lt.requires_approval,
        approval_levels=lt.approval_levels,
        cancel_requires_approval=lt.cancel_requires_approval,
        cancel_approval_levels=lt.cancel_approval_levels,
        min_days_per_application=lt.min_days_per_application,
        max_days_per_application=lt.max_days_per_application,
        advance_notice_days=lt.advance_notice_days,
        requires_document=lt.requires_document,
        is_paid=lt.is_paid,
        is_active=lt.is_active,
        color=lt.color,
    )


def _app_resp(app: LeaveApplication, lt: LeaveType, history: list[LeaveApprovalActionResponse]) -> LeaveApplicationResponse:
    return LeaveApplicationResponse(
        id=to_typed_id("leave_application", app.id),
        employment_id=to_typed_id("employment", app.employment_id),
        leave_type_id=to_typed_id("leave_type", lt.id),
        leave_type_name=lt.name,
        leave_type_code=lt.code,
        leave_type_color=lt.color,
        from_date=app.from_date,
        to_date=app.to_date,
        days_requested=app.days_requested,
        half_day_option=app.half_day_option,
        reason=app.reason,
        status=app.status,
        current_level=app.current_level,
        total_levels=app.total_levels,
        applied_at=app.applied_at,
        cancel_reason=app.cancel_reason,
        cancel_requested_at=app.cancel_requested_at,
        approval_history=history,
    )


async def _get_lt(session, tenant_id, lt_id: str) -> LeaveType:
    uid = to_uuid(lt_id)
    row = await session.execute(
        select(LeaveType).where(LeaveType.tenant_id == tenant_id).where(LeaveType.id == uid)
    )
    lt = row.scalars().first()
    if not lt:
        raise HTTPException(404, "Leave type not found")
    return lt


async def _get_app_lt(session, tenant_id, app_id: str):
    uid = to_uuid(app_id)
    row = await session.execute(
        select(LeaveApplication, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveApplication.leave_type_id)
        .where(LeaveApplication.tenant_id == tenant_id)
        .where(LeaveApplication.id == uid)
    )
    result = row.first()
    if not result:
        raise HTTPException(404, "Leave application not found")
    return result


async def _get_history(session, tenant_id, app_id) -> list[LeaveApprovalActionResponse]:
    rows = await session.execute(
        select(LeaveApprovalAction)
        .where(LeaveApprovalAction.tenant_id == tenant_id)
        .where(LeaveApprovalAction.application_id == app_id)
        .order_by(LeaveApprovalAction.actioned_at)
    )
    return [
        LeaveApprovalActionResponse(
            id=to_typed_id("leave_approval", a.id),
            application_id=to_typed_id("leave_application", a.application_id),
            action_type=a.action_type,
            level=a.level,
            approver_employment_id=to_typed_id("employment", a.approver_employment_id) if a.approver_employment_id else None,
            comments=a.comments,
            actioned_at=a.actioned_at,
        )
        for a in rows.scalars()
    ]


async def _adjust_balance(
    session, tenant_id, employment_id, leave_type_id, year: int,
    pending_delta: float = 0.0, used_delta: float = 0.0,
) -> None:
    row = await session.execute(
        select(LeaveBalance)
        .where(LeaveBalance.tenant_id == tenant_id)
        .where(LeaveBalance.employment_id == employment_id)
        .where(LeaveBalance.leave_type_id == leave_type_id)
        .where(LeaveBalance.year == year)
    )
    lb = row.scalars().first()
    if lb:
        if pending_delta:
            lb.pending_days = max(0.0, lb.pending_days + pending_delta)
        if used_delta:
            lb.used_days = max(0.0, lb.used_days + used_delta)
        session.add(lb)


def _assert_pending(app: LeaveApplication) -> None:
    if app.status not in (
        LeaveApplicationStatus.PENDING_L1,
        LeaveApplicationStatus.PENDING_L2,
        LeaveApplicationStatus.PENDING_L3,
    ):
        raise HTTPException(400, f"Application not pending approval (status: {app.status})")


def _assert_cancel_pending(app: LeaveApplication) -> None:
    if app.status not in (
        LeaveApplicationStatus.CANCEL_PENDING_L1,
        LeaveApplicationStatus.CANCEL_PENDING_L2,
        LeaveApplicationStatus.CANCEL_PENDING_L3,
    ):
        raise HTTPException(400, f"Application cancellation not pending (status: {app.status})")
