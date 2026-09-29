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

from datetime import date, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.approvals import require_reviewer
from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    authorize_write,
    read_scope,
    require_global_permission,
    require_permission,
    resolve_acting_employment_id,
    visible_employment_ids,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.leave.models import (
    CompOffGrant,
    LeaveApplication,
    LeaveApplicationStatus,
    LeaveApprovalAction,
    LeaveApprovalActionType,
    LeaveBalance,
    LeaveBalanceBucket,
    LeaveBalanceTransaction,
    LeaveBucketPolicy,
    LeaveEncashment,
    LeaveMonthlyLedger,
    LeavePolicyAssignment,
    LeavePolicySet,
    LeaveType,
    LeaveTypeBucketMapping,
)
from hrms.modules.leave.schemas import (
    AccrualRunResponse,
    CompOffGrantRequest,
    CompOffGrantResponse,
    LeaveApplicationResponse,
    LeaveApplyRequest,
    LeaveApprovalActionRequest,
    LeaveApprovalActionResponse,
    LeaveBalanceBucketCreate,
    LeaveBalanceBucketResponse,
    LeaveBalanceBucketUpdate,
    LeaveBalanceResponse,
    LeaveBalanceTransactionResponse,
    LeaveBucketPolicyCreate,
    LeaveBucketPolicyResponse,
    LeaveBucketPolicyUpdate,
    LeaveCancelRequest,
    LeaveEncashmentRequest,
    LeaveEncashmentResponse,
    LeaveMonthlyLedgerResponse,
    LeavePolicyAssignmentCreate,
    LeavePolicyAssignmentResponse,
    LeavePolicySetCreate,
    LeavePolicySetResponse,
    LeavePolicySetUpdate,
    LeaveTypeBucketMappingCreate,
    LeaveTypeBucketMappingResponse,
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
)
from hrms.modules.policy.engine import resolve_policy

router = APIRouter(prefix="/v1/leave", tags=["Leave Management"])


# ─── Leave types ──────────────────────────────────────────────────────────────


@router.get("/types", response_model=list[LeaveTypeResponse])
async def list_leave_types(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeaveTypeResponse]:
    rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.archived_at == None)  # noqa: E711
        .order_by(LeaveType.name)
    )
    return [_lt_resp(t) for t in rows.scalars()]


@router.post(
    "/types",
    response_model=LeaveTypeResponse,
    status_code=201,
    dependencies=[require_global_permission("leave.write")],
)
async def create_leave_type(
    body: LeaveTypeCreate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveTypeResponse:
    uid = uuid4()
    lt = LeaveType(tenant_id=tenant_id, id=uid, recorded_at=now_utc(), **body.model_dump())
    session.add(lt)
    await session.flush()
    return _lt_resp(lt)


@router.patch(
    "/types/{leave_type_id}",
    response_model=LeaveTypeResponse,
    dependencies=[require_global_permission("leave.write")],
)
async def update_leave_type(
    leave_type_id: str,
    body: LeaveTypeUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
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
    scope = read_scope(scope, "leave.read", "leave.approve")
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    if year is None:
        year = now_utc().year
    rows = await session.execute(
        select(LeaveBalance, LeaveType)
        .join(LeaveType, col(LeaveType.id) == LeaveBalance.leave_type_id)
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
            available_days=max(
                0.0, b.allocated_days + b.carry_forward_days - b.used_days - b.pending_days
            ),
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
    scope = scope.for_permission("leave.write")
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    await lock_resource(session, tenant_id, f"leave:{emp_uuid}")

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


# ─── Comp-off, encashment & accrual ────────────────────────────────────────────
#
# All three are direct HR/admin balance adjustments with an audit-trail row,
# not a second approval chain mirroring leave applications — comp-off and
# encashment are one-shot credits/debits an HR user enters after the fact,
# and accrual is a scheduled top-up. None of this needs multi-level review.


@router.post(
    "/comp-off",
    response_model=CompOffGrantResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def grant_comp_off(
    body: CompOffGrantRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> CompOffGrantResponse:
    scope = scope.for_permission("leave.write")
    emp_uuid = to_uuid(body.employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    await lock_resource(session, tenant_id, f"leave:{emp_uuid}")

    existing = await session.execute(
        select(CompOffGrant)
        .where(CompOffGrant.tenant_id == tenant_id)
        .where(CompOffGrant.employment_id == emp_uuid)
        .where(CompOffGrant.work_date == body.work_date)
    )
    if existing.scalars().first():
        raise HTTPException(400, f"Comp-off already granted for {body.work_date}")

    lt = await _get_or_create_comp_off_type(session, tenant_id)

    grant = CompOffGrant(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp_uuid,
        work_date=body.work_date,
        days_granted=body.days_granted,
        notes=body.notes,
        granted_by=principal.employment_id,
        recorded_at=now_utc(),
    )
    session.add(grant)
    await _adjust_balance(
        session,
        tenant_id,
        emp_uuid,
        lt.id,
        body.work_date.year,
        allocated_delta=body.days_granted,
        create_if_missing=True,
    )
    await session.flush()
    return CompOffGrantResponse(
        id=to_typed_id("comp_off_grant", grant.id),
        employment_id=to_typed_id("employment", emp_uuid),
        work_date=grant.work_date,
        days_granted=grant.days_granted,
        notes=grant.notes,
        granted_by=to_typed_id("employment", grant.granted_by) if grant.granted_by else None,
        recorded_at=grant.recorded_at,
    )


@router.post(
    "/encashment",
    response_model=LeaveEncashmentResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def encash_leave(
    body: LeaveEncashmentRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveEncashmentResponse:
    scope = scope.for_permission("leave.write")
    emp_uuid = to_uuid(body.employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    await lock_resource(session, tenant_id, f"leave:{emp_uuid}")

    lt = await _get_lt(session, tenant_id, body.leave_type_id)
    if not lt.encashable:
        raise HTTPException(400, f"{lt.name} is not marked encashable")

    effective_date = body.effective_date or now_utc().date()
    row = await session.execute(
        select(LeaveBalance)
        .where(LeaveBalance.tenant_id == tenant_id)
        .where(LeaveBalance.employment_id == emp_uuid)
        .where(LeaveBalance.leave_type_id == lt.id)
        .where(LeaveBalance.year == effective_date.year)
    )
    lb = row.scalars().first()
    available = (
        (lb.allocated_days + lb.carry_forward_days - lb.used_days - lb.pending_days) if lb else 0.0
    )
    if body.days > available:
        raise HTTPException(
            400, f"Only {available} days available to encash, requested {body.days}"
        )

    enc = LeaveEncashment(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp_uuid,
        leave_type_id=lt.id,
        days=body.days,
        effective_date=effective_date,
        notes=body.notes,
        processed_by=principal.employment_id,
        recorded_at=now_utc(),
    )
    session.add(enc)
    await _adjust_balance(
        session, tenant_id, emp_uuid, lt.id, effective_date.year, allocated_delta=-body.days
    )
    await session.flush()
    return LeaveEncashmentResponse(
        id=to_typed_id("leave_encashment", enc.id),
        employment_id=to_typed_id("employment", emp_uuid),
        leave_type_id=to_typed_id("leave_type", lt.id),
        leave_type_name=lt.name,
        days=enc.days,
        effective_date=enc.effective_date,
        notes=enc.notes,
        processed_by=to_typed_id("employment", enc.processed_by) if enc.processed_by else None,
        recorded_at=enc.recorded_at,
    )


@router.post(
    "/accrual/run",
    response_model=AccrualRunResponse,
    dependencies=[require_permission("leave.write")],
)
async def run_accrual(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    period: str | None = Query(
        default=None, description='"YYYY-MM", defaults to the current month'
    ),
) -> AccrualRunResponse:
    """
    Credits days_per_year / 12 to every active employee's balance for every
    leave type with accrual_enabled. last_accrued_period is a high-water
    mark (compared as a "YYYY-MM" string), not a set of periods ever run —
    so this is safe to call more than once for the same or an earlier
    month, but a month that's already behind the mark is skipped rather
    than re-credited; it does not backfill a month that was skipped by
    mistake. Meant to be triggered by an external cron; there is no in-app
    scheduler (see RUNBOOK.md).
    """
    scope = scope.for_permission("leave.write")
    if period is None:
        period = now_utc().strftime("%Y-%m")
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise HTTPException(422, "period must be YYYY-MM")
    if period > now_utc().strftime("%Y-%m"):
        raise HTTPException(422, "Cannot accrue a future period")
    await lock_resource(session, tenant_id, "leave-accrual")
    year = int(period[:4])

    lt_rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.accrual_enabled == True)  # noqa: E712
        .where(LeaveType.archived_at == None)  # noqa: E711
    )
    leave_types = list(lt_rows.scalars())
    if not leave_types:
        return AccrualRunResponse(period=period, balances_credited=0, days_credited_total=0.0)

    clause, params = scope.employment_filter_sql("e")
    emp_rows = await session.execute(
        text(f"""
            SELECT e.id FROM employments e
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state NOT IN ('SEPARATED')
            {clause}
        """),
        {"tid": str(tenant_id), **params},
    )
    employment_ids = [r[0] for r in emp_rows]

    credited = 0
    total_days = 0.0
    for lt in leave_types:
        monthly = round(lt.days_per_year / 12, 4)
        if monthly <= 0:
            continue
        for emp_id in sorted(employment_ids):
            await lock_resource(session, tenant_id, f"leave:{emp_id}")
            row = await session.execute(
                select(LeaveBalance)
                .where(LeaveBalance.tenant_id == tenant_id)
                .where(LeaveBalance.employment_id == emp_id)
                .where(LeaveBalance.leave_type_id == lt.id)
                .where(LeaveBalance.year == year)
            )
            lb = row.scalars().first()
            if lb is None:
                lb = LeaveBalance(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    employment_id=emp_id,
                    leave_type_id=lt.id,
                    year=year,
                    recorded_at=now_utc(),
                )
            if lb.last_accrued_period is not None and lb.last_accrued_period >= period:
                continue
            lb.allocated_days += monthly
            lb.last_accrued_period = period
            session.add(lb)
            credited += 1
            total_days += monthly

    await session.flush()
    return AccrualRunResponse(
        period=period, balances_credited=credited, days_credited_total=round(total_days, 2)
    )


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
    scope = read_scope(scope, "leave.read", "leave.approve")
    q = (
        select(LeaveApplication, LeaveType)
        .join(LeaveType, col(LeaveType.id) == LeaveApplication.leave_type_id)
        .where(LeaveApplication.tenant_id == tenant_id)
        .where(LeaveApplication.archived_at == None)  # noqa: E711
    )
    if employment_id:
        emp_uuid = to_uuid(employment_id)
        await authorize_employment(session, tenant_id, scope, emp_uuid)
        q = q.where(LeaveApplication.employment_id == emp_uuid)
    elif not scope.is_all:
        allowed_ids = await visible_employment_ids(session, tenant_id, scope)
        q = q.where(col(LeaveApplication.employment_id).in_(allowed_ids))
    if status:
        q = q.where(LeaveApplication.status == status)
    rows = await session.execute(q.order_by(col(LeaveApplication.applied_at).desc()))
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

    await authorize_write(
        session, tenant_id, scope, principal, emp_uuid, "leave.write", "leave.apply"
    )
    allocation = await _allocate_days(
        session, tenant_id, emp_uuid, body.from_date, body.to_date, body.half_day_option
    )
    days = sum(allocation.values())
    await _validate_application(session, tenant_id, emp_uuid, lt, body, days)
    uid = uuid4()
    app = LeaveApplication(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        leave_type_id=lt.id,
        from_date=body.from_date,
        to_date=body.to_date,
        days_requested=days,
        days_by_year=allocation,
        document_id=to_uuid(body.document_id) if body.document_id else None,
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
    await authorize_write(
        session, tenant_id, scope, principal, app.employment_id, "leave.write", "leave.apply"
    )
    if app.status != LeaveApplicationStatus.DRAFT:
        raise HTTPException(400, f"Cannot submit: status is {app.status}")

    await _validate_application(session, tenant_id, app.employment_id, lt, app, app.days_requested)
    await _check_overlap(session, tenant_id, app)
    app.days_by_year = await _allocate_days(
        session, tenant_id, app.employment_id, app.from_date, app.to_date, app.half_day_option
    )
    app.days_requested = sum(app.days_by_year.values())
    await _change_application_balance(session, tenant_id, app, lt, pending=1)

    if lt.requires_approval:
        app.status = LeaveApplicationStatus.PENDING_L1
        app.current_level = 1
    else:
        app.status = LeaveApplicationStatus.APPROVED
        await _change_application_balance(session, tenant_id, app, lt, pending=-1, used=1)
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
    scope = scope.for_permission("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_pending(app)

    await _check_reviewer(session, tenant_id, principal, scope, app, cancel=False)

    action = LeaveApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        application_id=app.id,
        action_type=LeaveApprovalActionType.APPROVE,
        level=app.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)

    if app.current_level >= app.total_levels:
        app.status = LeaveApplicationStatus.APPROVED
        await _change_application_balance(session, tenant_id, app, lt, pending=-1, used=1)
    else:
        app.current_level += 1
        next_status = [
            None,
            LeaveApplicationStatus.PENDING_L1,
            LeaveApplicationStatus.PENDING_L2,
            LeaveApplicationStatus.PENDING_L3,
        ]
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
    scope = scope.for_permission("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_pending(app)

    await _check_reviewer(session, tenant_id, principal, scope, app, cancel=False)

    action = LeaveApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        application_id=app.id,
        action_type=LeaveApprovalActionType.REJECT,
        level=app.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)

    app.status = LeaveApplicationStatus.REJECTED
    await _change_application_balance(session, tenant_id, app, lt, pending=-1)
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
    await authorize_write(
        session, tenant_id, scope, principal, app.employment_id, "leave.write", "leave.apply"
    )

    if app.status == LeaveApplicationStatus.DRAFT:
        app.status = LeaveApplicationStatus.CANCELLED
        session.add(app)
        await session.flush()
        return _app_resp(app, lt, [])

    if app.status in (
        LeaveApplicationStatus.PENDING_L1,
        LeaveApplicationStatus.PENDING_L2,
        LeaveApplicationStatus.PENDING_L3,
    ):
        app.status = LeaveApplicationStatus.CANCELLED
        app.cancel_reason = body.cancel_reason
        app.cancel_requested_at = now_utc()
        await _change_application_balance(session, tenant_id, app, lt, pending=-1)
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
            await _change_application_balance(session, tenant_id, app, lt, used=-1)
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
    scope = scope.for_permission("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_cancel_pending(app)

    await _check_reviewer(session, tenant_id, principal, scope, app, cancel=True)

    action = LeaveApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        application_id=app.id,
        action_type=LeaveApprovalActionType.CANCEL_APPROVE,
        level=app.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)

    if app.current_level >= app.total_levels:
        app.status = LeaveApplicationStatus.CANCELLED
        await _change_application_balance(session, tenant_id, app, lt, used=-1)
    else:
        app.current_level += 1
        cancel_statuses = [
            None,
            LeaveApplicationStatus.CANCEL_PENDING_L1,
            LeaveApplicationStatus.CANCEL_PENDING_L2,
            LeaveApplicationStatus.CANCEL_PENDING_L3,
        ]
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
    scope = scope.for_permission("leave.approve")
    app, lt = await _get_app_lt(session, tenant_id, app_id)
    await authorize_employment(session, tenant_id, scope, app.employment_id)
    _assert_cancel_pending(app)

    await _check_reviewer(session, tenant_id, principal, scope, app, cancel=True)

    action = LeaveApprovalAction(
        tenant_id=tenant_id,
        id=uuid4(),
        application_id=app.id,
        action_type=LeaveApprovalActionType.CANCEL_REJECT,
        level=app.current_level,
        approver_employment_id=principal.employment_id,
        approver_user_account_id=principal.user_account_id,
        comments=body.comments,
        actioned_at=now_utc(),
        recorded_at=now_utc(),
    )
    session.add(action)
    app.status = LeaveApplicationStatus.APPROVED
    session.add(app)
    await session.flush()
    return _app_resp(app, lt, await _get_history(session, tenant_id, app.id))


# ─── Helpers ──────────────────────────────────────────────────────────────────


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
        is_comp_off=lt.is_comp_off,
        encashable=lt.encashable,
        accrual_enabled=lt.accrual_enabled,
    )


def _app_resp(
    app: LeaveApplication, lt: LeaveType, history: list[LeaveApprovalActionResponse]
) -> LeaveApplicationResponse:
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


async def _get_or_create_comp_off_type(session, tenant_id) -> LeaveType:
    """The single leave type comp-off credits land in — auto-created on first
    use so tenants don't have to manually set one up before granting comp-off."""
    row = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.is_comp_off == True)  # noqa: E712
        .where(LeaveType.archived_at == None)  # noqa: E711
    )
    lt = row.scalars().first()
    if lt:
        return lt
    lt = LeaveType(
        tenant_id=tenant_id,
        id=uuid4(),
        name="Comp Off",
        code="COMPOFF",
        days_per_year=0,
        requires_approval=False,
        is_comp_off=True,
        is_paid=True,
        color="#8B5CF6",
        recorded_at=now_utc(),
    )
    session.add(lt)
    await session.flush()
    return lt


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
        .join(LeaveType, col(LeaveType.id) == LeaveApplication.leave_type_id)
        .where(LeaveApplication.tenant_id == tenant_id)
        .where(LeaveApplication.id == uid)
        .with_for_update(of=LeaveApplication)
    )
    result = row.first()
    if not result:
        raise HTTPException(404, "Leave application not found")
    await lock_resource(session, tenant_id, f"leave:{result[0].employment_id}")
    return result


async def _get_history(session, tenant_id, app_id) -> list[LeaveApprovalActionResponse]:
    rows = await session.execute(
        select(LeaveApprovalAction)
        .where(LeaveApprovalAction.tenant_id == tenant_id)
        .where(LeaveApprovalAction.application_id == app_id)
        .order_by(col(LeaveApprovalAction.actioned_at))
    )
    return [
        LeaveApprovalActionResponse(
            id=to_typed_id("leave_approval", a.id),
            application_id=to_typed_id("leave_application", a.application_id),
            action_type=a.action_type,
            level=a.level,
            approver_employment_id=to_typed_id("employment", a.approver_employment_id)
            if a.approver_employment_id
            else None,
            comments=a.comments,
            actioned_at=a.actioned_at,
        )
        for a in rows.scalars()
    ]


async def _adjust_balance(
    session,
    tenant_id,
    employment_id,
    leave_type_id,
    year: int,
    pending_delta: float = 0.0,
    used_delta: float = 0.0,
    allocated_delta: float = 0.0,
    create_if_missing: bool = False,
) -> None:
    row = await session.execute(
        select(LeaveBalance)
        .where(LeaveBalance.tenant_id == tenant_id)
        .where(LeaveBalance.employment_id == employment_id)
        .where(LeaveBalance.leave_type_id == leave_type_id)
        .where(LeaveBalance.year == year)
    )
    lb = row.scalars().first()
    if not lb and create_if_missing:
        lb = LeaveBalance(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=employment_id,
            leave_type_id=leave_type_id,
            year=year,
            recorded_at=now_utc(),
        )
    if not lb:
        raise HTTPException(409, f"Initialize the leave balance for {year} first")
    if lb:
        if (
            pending_delta > 0
            and pending_delta
            > lb.allocated_days + lb.carry_forward_days - lb.used_days - lb.pending_days
        ):
            raise HTTPException(409, f"Insufficient leave balance for {year}")
        if pending_delta:
            lb.pending_days = max(0.0, lb.pending_days + pending_delta)
        if used_delta:
            lb.used_days = max(0.0, lb.used_days + used_delta)
        if allocated_delta:
            lb.allocated_days = max(0.0, lb.allocated_days + allocated_delta)
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


async def _allocate_days(session, tenant_id, employment_id, start, end, half_day):
    from hrms.core.datetime_utils import is_working_day

    holidays = (
        await session.execute(
            text("""
        SELECT holiday_date FROM holidays WHERE tenant_id = :tid AND archived_at IS NULL
          AND (legal_entity_id IS NULL OR legal_entity_id =
              (SELECT legal_entity_id FROM employments WHERE tenant_id = :tid AND id = :eid))
          AND holiday_date BETWEEN :start AND :end AND is_optional = false
    """),
            {"tid": tenant_id, "eid": employment_id, "start": start, "end": end},
        )
    ).all()
    holidays = {r[0] for r in holidays}
    allocation = {}
    day = start
    while day <= end:
        policy = await resolve_policy(employment_id, day, session, tenant_id)
        if day not in holidays and is_working_day(day, policy.work_days, policy.saturday_pattern):
            key = str(day.year)
            allocation[key] = allocation.get(key, 0.0) + (0.5 if half_day != "NONE" else 1.0)
        day += timedelta(days=1)
    return allocation


async def _validate_application(session, tenant_id, employment_id, lt, body, days):
    if not lt.is_active or lt.archived_at:
        raise HTTPException(422, "This leave type is inactive")
    if days <= 0 or days < lt.min_days_per_application:
        raise HTTPException(422, "Leave must cover the minimum number of working days")
    if lt.max_days_per_application is not None and days > lt.max_days_per_application:
        raise HTTPException(422, "Leave exceeds the maximum application duration")
    if lt.advance_notice_days and body.from_date < now_utc().date() + timedelta(
        days=lt.advance_notice_days
    ):
        raise HTTPException(422, "This leave type requires more advance notice")
    document = getattr(body, "document_id", None)
    if lt.requires_document and not document:
        raise HTTPException(422, "This leave type requires a supporting KYC document")
    if document:
        document = to_uuid(document) if isinstance(document, str) else document
        found = (
            await session.execute(
                text("""
            SELECT id FROM employee_kyc_documents WHERE tenant_id = :tid AND id = :id AND
            employment_id = :eid
        """),
                {"tid": tenant_id, "id": document, "eid": employment_id},
            )
        ).first()
        if not found:
            raise HTTPException(422, "Supporting document does not belong to this employee")


async def _check_overlap(session, tenant_id, app):
    rows = (
        await session.execute(
            select(LeaveApplication)
            .where(LeaveApplication.tenant_id == tenant_id)
            .where(LeaveApplication.employment_id == app.employment_id)
            .where(LeaveApplication.id != app.id)
            .where(LeaveApplication.from_date <= app.to_date)
            .where(LeaveApplication.to_date >= app.from_date)
            .where(col(LeaveApplication.status).notin_(["DRAFT", "REJECTED", "CANCELLED"]))
        )
    ).scalars()
    for other in rows:
        if app.from_date == app.to_date == other.from_date == other.to_date and {
            app.half_day_option,
            other.half_day_option,
        } == {"FIRST_HALF", "SECOND_HALF"}:
            continue
        raise HTTPException(409, "This leave overlaps an existing application")


async def _change_application_balance(session, tenant_id, app, lt, pending=0, used=0):
    if not lt.is_paid and not lt.is_comp_off:
        return
    allocation = app.days_by_year
    if not allocation:
        # Legacy single-year applications retain their recorded entitlement amount.
        if app.from_date.year != app.to_date.year:
            raise HTTPException(409, "A legacy cross-year application needs balance reconciliation")
        allocation = {str(app.from_date.year): app.days_requested}
    for year, days in sorted(allocation.items()):
        await _adjust_balance(
            session,
            tenant_id,
            app.employment_id,
            lt.id,
            int(year),
            pending_delta=pending * days,
            used_delta=used * days,
        )


async def _check_reviewer(session, tenant_id, principal, scope, app, cancel=False):
    history = (
        await session.execute(
            select(LeaveApprovalAction)
            .where(LeaveApprovalAction.tenant_id == tenant_id)
            .where(LeaveApprovalAction.application_id == app.id)
        )
    ).scalars()
    history = [a for a in history if a.action_type.startswith("CANCEL_") == cancel]
    await require_reviewer(
        session,
        tenant_id,
        principal,
        scope,
        app.employment_id,
        app.current_level,
        {a.approver_user_account_id for a in history},
        {a.approver_employment_id for a in history},
        "leave.write",
    )


# ─── Balance Buckets CRUD ─────────────────────────────────────────────────────


@router.get(
    "/buckets",
    response_model=list[LeaveBalanceBucketResponse],
    dependencies=[require_permission("leave.read")],
)
async def list_buckets(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeaveBalanceBucketResponse]:
    rows = await session.execute(
        select(LeaveBalanceBucket)
        .where(LeaveBalanceBucket.tenant_id == tenant_id)
        .where(LeaveBalanceBucket.archived_at == None)  # noqa: E711
        .order_by(LeaveBalanceBucket.name)
    )
    return [
        LeaveBalanceBucketResponse(
            id=to_typed_id("leave_bucket", b.id),
            name=b.name,
            code=b.code,
            is_unlimited=b.is_unlimited,
            is_active=b.is_active,
        )
        for b in rows.scalars()
    ]


@router.post(
    "/buckets",
    response_model=LeaveBalanceBucketResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_bucket(
    body: LeaveBalanceBucketCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> LeaveBalanceBucketResponse:
    existing = await session.execute(
        select(LeaveBalanceBucket)
        .where(LeaveBalanceBucket.tenant_id == tenant_id)
        .where(LeaveBalanceBucket.code == body.code.strip())
        .where(LeaveBalanceBucket.archived_at == None)  # noqa: E711
    )
    if existing.scalars().first():
        raise HTTPException(400, f"Bucket code '{body.code}' already exists")

    bucket = LeaveBalanceBucket(
        tenant_id=tenant_id,
        id=uuid4(),
        recorded_at=now_utc(),
        recorded_by=principal.id if hasattr(principal, "id") else None,
        name=body.name.strip(),
        code=body.code.strip(),
        is_unlimited=body.is_unlimited,
        is_active=True,
    )
    session.add(bucket)
    await session.flush()
    return LeaveBalanceBucketResponse(
        id=to_typed_id("leave_bucket", bucket.id),
        name=bucket.name,
        code=bucket.code,
        is_unlimited=bucket.is_unlimited,
        is_active=bucket.is_active,
    )


@router.patch(
    "/buckets/{bucket_id}",
    response_model=LeaveBalanceBucketResponse,
    dependencies=[require_permission("leave.write")],
)
async def update_bucket(
    bucket_id: str,
    body: LeaveBalanceBucketUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveBalanceBucketResponse:
    uid = to_uuid(bucket_id)
    bucket = await session.get(LeaveBalanceBucket, (tenant_id, uid))
    if not bucket or bucket.archived_at:
        raise HTTPException(404, "Leave bucket not found")
    if body.name is not None:
        bucket.name = body.name.strip()
    if body.is_active is not None:
        bucket.is_active = body.is_active
    session.add(bucket)
    await session.flush()
    return LeaveBalanceBucketResponse(
        id=to_typed_id("leave_bucket", bucket.id),
        name=bucket.name,
        code=bucket.code,
        is_unlimited=bucket.is_unlimited,
        is_active=bucket.is_active,
    )


@router.delete(
    "/buckets/{bucket_id}",
    status_code=204,
    dependencies=[require_permission("leave.write")],
)
async def delete_bucket(
    bucket_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    uid = to_uuid(bucket_id)
    bucket = await session.get(LeaveBalanceBucket, (tenant_id, uid))
    if not bucket or bucket.archived_at:
        raise HTTPException(404, "Leave bucket not found")
    bucket.archived_at = now_utc()
    session.add(bucket)
    await session.flush()


# ─── Bucket Mappings CRUD ─────────────────────────────────────────────────────


@router.get(
    "/bucket-mappings",
    response_model=list[LeaveTypeBucketMappingResponse],
    dependencies=[require_permission("leave.read")],
)
async def list_bucket_mappings(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeaveTypeBucketMappingResponse]:
    rows = await session.execute(
        select(LeaveTypeBucketMapping, LeaveType, LeaveBalanceBucket)
        .join(LeaveType, col(LeaveType.id) == LeaveTypeBucketMapping.leave_type_id)
        .join(LeaveBalanceBucket, col(LeaveBalanceBucket.id) == LeaveTypeBucketMapping.bucket_id)
        .where(LeaveTypeBucketMapping.tenant_id == tenant_id)
    )
    return [
        LeaveTypeBucketMappingResponse(
            id=to_typed_id("leave_mapping", m.id),
            leave_type_id=to_typed_id("leave_type", lt.id),
            leave_type_name=lt.name,
            leave_type_code=lt.code,
            bucket_id=to_typed_id("leave_bucket", b.id),
            bucket_name=b.name,
            bucket_code=b.code,
        )
        for m, lt, b in rows
    ]


@router.post(
    "/bucket-mappings",
    response_model=LeaveTypeBucketMappingResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_or_update_bucket_mapping(
    body: LeaveTypeBucketMappingCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> LeaveTypeBucketMappingResponse:
    lt_id = to_uuid(body.leave_type_id)
    bucket_id = to_uuid(body.bucket_id)

    lt = await session.get(LeaveType, (tenant_id, lt_id))
    if not lt or lt.archived_at:
        raise HTTPException(404, "Leave type not found")
    bucket = await session.get(LeaveBalanceBucket, (tenant_id, bucket_id))
    if not bucket or bucket.archived_at:
        raise HTTPException(404, "Leave bucket not found")

    existing = (
        (
            await session.execute(
                select(LeaveTypeBucketMapping)
                .where(LeaveTypeBucketMapping.tenant_id == tenant_id)
                .where(LeaveTypeBucketMapping.leave_type_id == lt_id)
            )
        )
        .scalars()
        .first()
    )

    if existing:
        existing.bucket_id = bucket_id
        session.add(existing)
        m = existing
    else:
        m = LeaveTypeBucketMapping(
            tenant_id=tenant_id,
            id=uuid4(),
            leave_type_id=lt_id,
            bucket_id=bucket_id,
            recorded_at=now_utc(),
            recorded_by=principal.id if hasattr(principal, "id") else None,
        )
        session.add(m)
    await session.flush()

    return LeaveTypeBucketMappingResponse(
        id=to_typed_id("leave_mapping", m.id),
        leave_type_id=to_typed_id("leave_type", lt.id),
        leave_type_name=lt.name,
        leave_type_code=lt.code,
        bucket_id=to_typed_id("leave_bucket", bucket.id),
        bucket_name=bucket.name,
        bucket_code=bucket.code,
    )


@router.delete(
    "/bucket-mappings/{mapping_id}",
    status_code=204,
    dependencies=[require_permission("leave.write")],
)
async def delete_bucket_mapping(
    mapping_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    uid = to_uuid(mapping_id)
    m = await session.get(LeaveTypeBucketMapping, (tenant_id, uid))
    if not m:
        raise HTTPException(404, "Leave type bucket mapping not found")
    await session.delete(m)
    await session.flush()


# ─── Leave Policy Sets CRUD ───────────────────────────────────────────────────


@router.get(
    "/policy-sets",
    response_model=list[LeavePolicySetResponse],
    dependencies=[require_permission("leave.write")],
)
async def list_policy_sets(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeavePolicySetResponse]:
    rows = await session.execute(
        select(LeavePolicySet)
        .where(LeavePolicySet.tenant_id == tenant_id)
        .where(LeavePolicySet.archived_at == None)  # noqa: E711
        .order_by(LeavePolicySet.name)
    )
    return [
        LeavePolicySetResponse(
            id=to_typed_id("leave_policy_set", ps.id),
            name=ps.name,
            description=ps.description,
            is_default=ps.is_default,
        )
        for ps in rows.scalars()
    ]


@router.post(
    "/policy-sets",
    response_model=LeavePolicySetResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_policy_set(
    body: LeavePolicySetCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> LeavePolicySetResponse:
    if body.is_default:
        existing_defaults = await session.execute(
            select(LeavePolicySet)
            .where(LeavePolicySet.tenant_id == tenant_id)
            .where(LeavePolicySet.is_default == True)  # noqa: E712
        )
        for d in existing_defaults.scalars():
            d.is_default = False
            session.add(d)

    pset = LeavePolicySet(
        tenant_id=tenant_id,
        id=uuid4(),
        recorded_at=now_utc(),
        recorded_by=principal.id if hasattr(principal, "id") else None,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        is_default=body.is_default,
    )
    session.add(pset)
    await session.flush()
    return LeavePolicySetResponse(
        id=to_typed_id("leave_policy_set", pset.id),
        name=pset.name,
        description=pset.description,
        is_default=pset.is_default,
    )


@router.patch(
    "/policy-sets/{policy_set_id}",
    response_model=LeavePolicySetResponse,
    dependencies=[require_permission("leave.write")],
)
async def update_policy_set(
    policy_set_id: str,
    body: LeavePolicySetUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeavePolicySetResponse:
    uid = to_uuid(policy_set_id)
    pset = await session.get(LeavePolicySet, (tenant_id, uid))
    if not pset or pset.archived_at:
        raise HTTPException(404, "Leave policy set not found")
    if body.name is not None:
        pset.name = body.name.strip()
    if body.description is not None:
        pset.description = body.description.strip()
    if body.is_default is not None:
        if body.is_default:
            existing_defaults = await session.execute(
                select(LeavePolicySet)
                .where(LeavePolicySet.tenant_id == tenant_id)
                .where(LeavePolicySet.is_default == True)  # noqa: E712
            )
            for d in existing_defaults.scalars():
                d.is_default = False
                session.add(d)
        pset.is_default = body.is_default
    session.add(pset)
    await session.flush()
    return LeavePolicySetResponse(
        id=to_typed_id("leave_policy_set", pset.id),
        name=pset.name,
        description=pset.description,
        is_default=pset.is_default,
    )


# ─── Leave Bucket Policies CRUD ───────────────────────────────────────────────


@router.get(
    "/policy-sets/{set_id}/bucket-policies",
    response_model=list[LeaveBucketPolicyResponse],
    dependencies=[require_permission("leave.write")],
)
async def list_bucket_policies_for_set(
    set_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeaveBucketPolicyResponse]:
    pset_id = to_uuid(set_id)
    rows = await session.execute(
        select(LeaveBucketPolicy, LeaveBalanceBucket)
        .join(LeaveBalanceBucket, col(LeaveBalanceBucket.id) == LeaveBucketPolicy.bucket_id)
        .where(LeaveBucketPolicy.tenant_id == tenant_id)
        .where(LeaveBucketPolicy.policy_set_id == pset_id)
    )
    return [
        LeaveBucketPolicyResponse(
            id=to_typed_id("leave_bucket_policy", bp.id),
            policy_set_id=to_typed_id("leave_policy_set", bp.policy_set_id),
            bucket_id=to_typed_id("leave_bucket", b.id),
            bucket_name=b.name,
            bucket_code=b.code,
            accrual_type=bp.accrual_type,
            days_per_year=bp.days_per_year,
            carry_forward_enabled=bp.carry_forward_enabled,
            max_carry_forward_days=bp.max_carry_forward_days,
            lapse_enabled=bp.lapse_enabled,
            encashment_enabled=bp.encashment_enabled,
            max_encashment_days=bp.max_encashment_days,
            probation_eligible=bp.probation_eligible,
            min_service_months=bp.min_service_months,
            pro_rate_first_year=bp.pro_rate_first_year,
        )
        for bp, b in rows
    ]


@router.post(
    "/policy-sets/{set_id}/bucket-policies",
    response_model=LeaveBucketPolicyResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_bucket_policy(
    set_id: str,
    body: LeaveBucketPolicyCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> LeaveBucketPolicyResponse:
    pset_id = to_uuid(set_id)
    b_id = to_uuid(body.bucket_id)

    pset = await session.get(LeavePolicySet, (tenant_id, pset_id))
    if not pset or pset.archived_at:
        raise HTTPException(404, "Leave policy set not found")
    bucket = await session.get(LeaveBalanceBucket, (tenant_id, b_id))
    if not bucket or bucket.archived_at:
        raise HTTPException(404, "Leave bucket not found")

    existing = (
        (
            await session.execute(
                select(LeaveBucketPolicy)
                .where(LeaveBucketPolicy.tenant_id == tenant_id)
                .where(LeaveBucketPolicy.policy_set_id == pset_id)
                .where(LeaveBucketPolicy.bucket_id == b_id)
            )
        )
        .scalars()
        .first()
    )
    if existing:
        raise HTTPException(400, "A policy for this bucket already exists in this policy set")

    bp = LeaveBucketPolicy(
        tenant_id=tenant_id,
        id=uuid4(),
        policy_set_id=pset_id,
        bucket_id=b_id,
        accrual_type=body.accrual_type,
        days_per_year=body.days_per_year,
        carry_forward_enabled=body.carry_forward_enabled,
        max_carry_forward_days=body.max_carry_forward_days,
        lapse_enabled=body.lapse_enabled,
        encashment_enabled=body.encashment_enabled,
        max_encashment_days=body.max_encashment_days,
        probation_eligible=body.probation_eligible,
        min_service_months=body.min_service_months,
        pro_rate_first_year=body.pro_rate_first_year,
        recorded_at=now_utc(),
        recorded_by=principal.id if hasattr(principal, "id") else None,
    )
    session.add(bp)
    await session.flush()
    return LeaveBucketPolicyResponse(
        id=to_typed_id("leave_bucket_policy", bp.id),
        policy_set_id=to_typed_id("leave_policy_set", bp.policy_set_id),
        bucket_id=to_typed_id("leave_bucket", bucket.id),
        bucket_name=bucket.name,
        bucket_code=bucket.code,
        accrual_type=bp.accrual_type,
        days_per_year=bp.days_per_year,
        carry_forward_enabled=bp.carry_forward_enabled,
        max_carry_forward_days=bp.max_carry_forward_days,
        lapse_enabled=bp.lapse_enabled,
        encashment_enabled=bp.encashment_enabled,
        max_encashment_days=bp.max_encashment_days,
        probation_eligible=bp.probation_eligible,
        min_service_months=bp.min_service_months,
        pro_rate_first_year=bp.pro_rate_first_year,
    )


@router.patch(
    "/bucket-policies/{policy_id}",
    response_model=LeaveBucketPolicyResponse,
    dependencies=[require_permission("leave.write")],
)
async def update_bucket_policy(
    policy_id: str,
    body: LeaveBucketPolicyUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveBucketPolicyResponse:
    uid = to_uuid(policy_id)
    bp = await session.get(LeaveBucketPolicy, (tenant_id, uid))
    if not bp:
        raise HTTPException(404, "Leave bucket policy not found")
    bucket = await session.get(LeaveBalanceBucket, (tenant_id, bp.bucket_id))
    assert bucket is not None

    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(bp, k, v)
    session.add(bp)
    await session.flush()

    return LeaveBucketPolicyResponse(
        id=to_typed_id("leave_bucket_policy", bp.id),
        policy_set_id=to_typed_id("leave_policy_set", bp.policy_set_id),
        bucket_id=to_typed_id("leave_bucket", bucket.id),
        bucket_name=bucket.name,
        bucket_code=bucket.code,
        accrual_type=bp.accrual_type,
        days_per_year=bp.days_per_year,
        carry_forward_enabled=bp.carry_forward_enabled,
        max_carry_forward_days=bp.max_carry_forward_days,
        lapse_enabled=bp.lapse_enabled,
        encashment_enabled=bp.encashment_enabled,
        max_encashment_days=bp.max_encashment_days,
        probation_eligible=bp.probation_eligible,
        min_service_months=bp.min_service_months,
        pro_rate_first_year=bp.pro_rate_first_year,
    )


@router.delete(
    "/bucket-policies/{policy_id}",
    status_code=204,
    dependencies=[require_permission("leave.write")],
)
async def delete_bucket_policy(
    policy_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    uid = to_uuid(policy_id)
    bp = await session.get(LeaveBucketPolicy, (tenant_id, uid))
    if not bp:
        raise HTTPException(404, "Leave bucket policy not found")
    await session.delete(bp)
    await session.flush()


# ─── Leave Policy Assignments CRUD ────────────────────────────────────────────


@router.get(
    "/policy-assignments",
    response_model=list[LeavePolicyAssignmentResponse],
    dependencies=[require_permission("leave.write")],
)
async def list_policy_assignments(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[LeavePolicyAssignmentResponse]:
    rows = await session.execute(
        select(LeavePolicyAssignment, LeavePolicySet)
        .join(LeavePolicySet, col(LeavePolicySet.id) == LeavePolicyAssignment.leave_policy_set_id)
        .where(LeavePolicyAssignment.tenant_id == tenant_id)
        .where(LeavePolicyAssignment.archived_at == None)  # noqa: E711
        .order_by(col(LeavePolicyAssignment.effective_from).desc())
    )
    return [
        LeavePolicyAssignmentResponse(
            id=to_typed_id("leave_policy_assignment", a.id),
            leave_policy_set_id=to_typed_id("leave_policy_set", ps.id),
            leave_policy_set_name=ps.name,
            effective_from=a.effective_from,
            effective_to=a.effective_to,
            employment_id=to_typed_id("employment", a.employment_id) if a.employment_id else None,
            org_unit_id=to_typed_id("org_unit", a.org_unit_id) if a.org_unit_id else None,
            legal_entity_id=(
                to_typed_id("legal_entity", a.legal_entity_id) if a.legal_entity_id else None
            ),
        )
        for a, ps in rows
    ]


@router.post(
    "/policy-assignments",
    response_model=LeavePolicyAssignmentResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_policy_assignment(
    body: LeavePolicyAssignmentCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    principal: CurrentUser,
) -> LeavePolicyAssignmentResponse:
    pset_id = to_uuid(body.leave_policy_set_id)
    pset = await session.get(LeavePolicySet, (tenant_id, pset_id))
    if not pset or pset.archived_at:
        raise HTTPException(404, "Leave policy set not found")

    emp_id = to_uuid(body.employment_id) if body.employment_id else None
    ou_id = to_uuid(body.org_unit_id) if body.org_unit_id else None
    le_id = to_uuid(body.legal_entity_id) if body.legal_entity_id else None

    assignment = LeavePolicyAssignment(
        tenant_id=tenant_id,
        id=uuid4(),
        recorded_at=now_utc(),
        recorded_by=principal.id if hasattr(principal, "id") else None,
        leave_policy_set_id=pset_id,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        employment_id=emp_id,
        org_unit_id=ou_id,
        legal_entity_id=le_id,
    )
    session.add(assignment)
    await session.flush()

    return LeavePolicyAssignmentResponse(
        id=to_typed_id("leave_policy_assignment", assignment.id),
        leave_policy_set_id=to_typed_id("leave_policy_set", pset.id),
        leave_policy_set_name=pset.name,
        effective_from=assignment.effective_from,
        effective_to=assignment.effective_to,
        employment_id=to_typed_id("employment", emp_id) if emp_id else None,
        org_unit_id=to_typed_id("org_unit", ou_id) if ou_id else None,
        legal_entity_id=to_typed_id("legal_entity", le_id) if le_id else None,
    )


@router.delete(
    "/policy-assignments/{assignment_id}",
    status_code=204,
    dependencies=[require_permission("leave.write")],
)
async def delete_policy_assignment(
    assignment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    uid = to_uuid(assignment_id)
    a = await session.get(LeavePolicyAssignment, (tenant_id, uid))
    if not a or a.archived_at:
        raise HTTPException(404, "Leave policy assignment not found")
    a.archived_at = now_utc()
    session.add(a)
    await session.flush()


# ─── Monthly Ledger & Audit Transactions ─────────────────────────────────────


@router.get(
    "/ledger",
    response_model=list[LeaveMonthlyLedgerResponse],
    dependencies=[require_permission("leave.read")],
)
async def get_leave_ledger(
    employment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    bucket_id: str | None = None,
    fy_year: int | None = None,
    calendar_year: int | None = None,
) -> list[LeaveMonthlyLedgerResponse]:
    emp_uuid = to_uuid(employment_id)
    stmt = (
        select(LeaveMonthlyLedger, LeaveBalanceBucket)
        .join(
            LeaveBalanceBucket,
            (col(LeaveBalanceBucket.tenant_id) == LeaveMonthlyLedger.tenant_id)
            & (col(LeaveBalanceBucket.id) == LeaveMonthlyLedger.bucket_id),
        )
        .where(LeaveMonthlyLedger.tenant_id == tenant_id)
        .where(LeaveMonthlyLedger.employment_id == emp_uuid)
    )
    if bucket_id:
        stmt = stmt.where(LeaveMonthlyLedger.bucket_id == to_uuid(bucket_id))
    if fy_year is not None:
        stmt = stmt.where(LeaveMonthlyLedger.fy_year == fy_year)
    if calendar_year is not None:
        stmt = stmt.where(LeaveMonthlyLedger.calendar_year == calendar_year)

    stmt = stmt.order_by(
        col(LeaveMonthlyLedger.calendar_year).asc(),
        col(LeaveMonthlyLedger.calendar_month).asc(),
        col(LeaveBalanceBucket.name).asc(),
    )
    rows = (await session.execute(stmt)).all()
    return [
        LeaveMonthlyLedgerResponse(
            id=to_typed_id("leave_ledger", ledger_row.id),
            employment_id=to_typed_id("employment", ledger_row.employment_id),
            bucket_id=to_typed_id("leave_bucket", bucket.id),
            bucket_name=bucket.name,
            bucket_code=bucket.code,
            calendar_year=ledger_row.calendar_year,
            calendar_month=ledger_row.calendar_month,
            fy_year=ledger_row.fy_year,
            opening=float(ledger_row.opening),
            accrued=float(ledger_row.accrued),
            granted=float(ledger_row.granted),
            held=float(ledger_row.held),
            adjustment=float(ledger_row.adjustment),
            taken=float(ledger_row.taken),
            lapsed=float(ledger_row.lapsed),
            encashed=float(ledger_row.encashed),
            closing=float(ledger_row.closing),
            available=float(ledger_row.closing - ledger_row.held),
        )
        for ledger_row, bucket in rows
    ]


@router.get(
    "/transactions",
    response_model=list[LeaveBalanceTransactionResponse],
    dependencies=[require_permission("leave.read")],
)
async def get_leave_transactions(
    employment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    bucket_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[LeaveBalanceTransactionResponse]:
    emp_uuid = to_uuid(employment_id)
    stmt = (
        select(LeaveBalanceTransaction, LeaveBalanceBucket, LeaveType)
        .join(
            LeaveBalanceBucket,
            (col(LeaveBalanceBucket.tenant_id) == LeaveBalanceTransaction.tenant_id)
            & (col(LeaveBalanceBucket.id) == LeaveBalanceTransaction.bucket_id),
        )
        .outerjoin(
            LeaveType,
            (col(LeaveType.tenant_id) == LeaveBalanceTransaction.tenant_id)
            & (col(LeaveType.id) == LeaveBalanceTransaction.leave_type_id),
        )
        .where(LeaveBalanceTransaction.tenant_id == tenant_id)
        .where(LeaveBalanceTransaction.employment_id == emp_uuid)
    )
    if bucket_id:
        stmt = stmt.where(LeaveBalanceTransaction.bucket_id == to_uuid(bucket_id))
    if from_date:
        stmt = stmt.where(LeaveBalanceTransaction.effective_date >= from_date)
    if to_date:
        stmt = stmt.where(LeaveBalanceTransaction.effective_date <= to_date)

    stmt = stmt.order_by(
        col(LeaveBalanceTransaction.effective_date).desc(),
        col(LeaveBalanceTransaction.recorded_at).desc(),
    )
    rows = (await session.execute(stmt)).all()
    return [
        LeaveBalanceTransactionResponse(
            id=to_typed_id("leave_transaction", tx.id),
            employment_id=to_typed_id("employment", tx.employment_id),
            bucket_id=to_typed_id("leave_bucket", b.id),
            bucket_name=b.name,
            bucket_code=b.code,
            leave_type_id=to_typed_id("leave_type", lt.id) if lt else None,
            leave_type_name=lt.name if lt else None,
            leave_type_code=lt.code if lt else None,
            transaction_type=tx.transaction_type,
            quantity=float(tx.quantity),
            previous_balance=float(tx.previous_balance),
            new_balance=float(tx.new_balance),
            effective_date=tx.effective_date,
            reason=tx.reason,
            reference_id=str(tx.reference_id) if tx.reference_id else None,
            reference_type=tx.reference_type,
            recorded_by=str(tx.recorded_by),
            approved_by=str(tx.approved_by) if tx.approved_by else None,
            recorded_at=tx.recorded_at,
        )
        for tx, b, lt in rows
    ]
