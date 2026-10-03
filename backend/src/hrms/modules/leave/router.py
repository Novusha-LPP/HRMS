"""
Leave module router.

Leave types (HR-managed, tenant-wide catalog — not per-employee data):
  GET    /v1/leave/types
  POST   /v1/leave/types                      (leave.write)
  PATCH  /v1/leave/types/{id}                 (leave.write)

Leave balances — summarised from the ledger (buckets/policies/monthly ledger/
transaction journal live further down this file; see leave/engine.py and
leave/policy_resolver.py for the accounting itself). Nothing to "initialise" —
a balance's first row is created lazily by whatever touches it first (an
accrual run, a hold, a grant):
  GET    /v1/leave/balances          ?employment_id=&year=   (year = an FY
                                        label, e.g. 2026 for FY2026-27;
                                        defaults to self, current FY)
  POST   /v1/leave/accrual/run       ?period=YYYY-MM          (leave.write)
  POST   /v1/leave/year-end-close    ?fy_year=                (leave.write)

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

import re
import time
from datetime import date, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Uuid, and_, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
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
    visible_employments_select,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc, tenure_months
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.metrics import ACCRUAL_RUN, ACCRUALS_CREDITED
from hrms.core.tenancy import TenantDep
from hrms.modules.leave.engine import (
    compute_fy_year,
    get_or_create_ledger_row,
    lock_leave_bucket,
    record_accruals,
    record_transaction,
)
from hrms.modules.leave.models import (
    CompOffGrant,
    LeaveApplication,
    LeaveApplicationStatus,
    LeaveApprovalAction,
    LeaveApprovalActionType,
    LeaveBalanceBucket,
    LeaveBalanceTransaction,
    LeaveBucketPolicy,
    LeaveEncashment,
    LeaveMonthlyLedger,
    LeavePolicyAssignment,
    LeavePolicySet,
    LeaveTransactionType,
    LeaveType,
    LeaveTypeBucketMapping,
)
from hrms.modules.leave.policy_resolver import (
    resolve_bucket_policy,
    resolve_employee_bucket_policy,
    resolve_employee_fy_start_month,
    resolve_fy_start_months_bulk,
    resolve_leave_policy_sets_bulk,
)
from hrms.modules.leave.schemas import (
    AccrualRunResponse,
    CompOffGrantRequest,
    CompOffGrantResponse,
    LeaveApplicationResponse,
    LeaveApplicationSummary,
    LeaveApplyRequest,
    LeaveApprovalActionRequest,
    LeaveApprovalActionResponse,
    LeaveBalanceAdjustmentRequest,
    LeaveBalanceAdjustmentResponse,
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
    LeaveTypeDays,
    LeaveTypeResponse,
    LeaveTypeUpdate,
    YearEndCloseResponse,
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
    year: int | None = Query(
        default=None,
        description="A financial-year label (e.g. 2026 for FY2026-27), not a calendar year",
    ),
) -> list[LeaveBalanceResponse]:
    """
    One row per leave type with an active balance, summed from the ledger for
    the given financial year (the employee's own, via their legal entity's
    financial_year_start_month). carry_forward_days is the FY's opening
    balance; allocated_days is what was credited (accrual + grants) during
    the FY itself — the two used to be two separate stored numbers, they're
    now two different aggregates over the same ledger rows. A type with no
    ledger activity yet in this FY (e.g. never accrued) doesn't appear —
    same as when this read the old, now-retired leave_balances table.
    """
    scope = read_scope(scope, "leave.read", "leave.approve")
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp_uuid)
    if year is None:
        today = now_utc().date()
        year = compute_fy_year(today.year, today.month, fy_start_month)

    lt_rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.is_active == True)  # noqa: E712
        .where(LeaveType.archived_at == None)  # noqa: E711
    )
    results: list[LeaveBalanceResponse] = []
    for lt in lt_rows.scalars():
        resolved = await _resolve_bucket_for_type(session, tenant_id, lt, create_if_missing=False)
        if resolved is None:
            continue
        bucket_id, _ = resolved
        ledger_rows = (
            (
                await session.execute(
                    select(LeaveMonthlyLedger)
                    .where(LeaveMonthlyLedger.tenant_id == tenant_id)
                    .where(LeaveMonthlyLedger.employment_id == emp_uuid)
                    .where(LeaveMonthlyLedger.bucket_id == bucket_id)
                    .where(LeaveMonthlyLedger.fy_year == year)
                    .order_by(
                        col(LeaveMonthlyLedger.calendar_year),
                        col(LeaveMonthlyLedger.calendar_month),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not ledger_rows:
            continue
        carry_forward_days = ledger_rows[0].opening
        allocated_days = sum(r.accrued + r.granted for r in ledger_rows)
        used_days = sum(r.taken for r in ledger_rows)
        pending_days = sum(r.held for r in ledger_rows)
        available_days = max(0.0, ledger_rows[-1].closing - pending_days)
        results.append(
            LeaveBalanceResponse(
                id=to_typed_id("leave_ledger", ledger_rows[-1].id),
                employment_id=to_typed_id("employment", emp_uuid),
                leave_type_id=to_typed_id("leave_type", lt.id),
                leave_type_name=lt.name,
                leave_type_code=lt.code,
                year=year,
                allocated_days=round(allocated_days, 4),
                carry_forward_days=round(carry_forward_days, 4),
                used_days=round(used_days, 4),
                pending_days=round(pending_days, 4),
                available_days=round(available_days, 4),
                color=lt.color,
            )
        )
    return results


# ─── Comp-off, encashment, manual adjustment & accrual ─────────────────────────
#
# All four are direct HR/admin balance adjustments with an audit-trail row,
# not a second approval chain mirroring leave applications — comp-off,
# encashment and manual adjustment are one-shot credits/debits an HR user
# enters after the fact, and accrual is a scheduled top-up. None of this
# needs multi-level review.


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
    await session.flush()

    resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
    if (
        resolved is not None
    ):  # always true for the comp-off type, kept for symmetry with other call sites
        bucket_id, _ = resolved
        fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp_uuid)
        await record_transaction(
            session,
            tenant_id,
            employment_id=emp_uuid,
            bucket_id=bucket_id,
            leave_type_id=lt.id,
            transaction_type=LeaveTransactionType.GRANT,
            quantity=body.days_granted,
            effective_date=body.work_date,
            reference_id=grant.id,
            reference_type="COMP_OFF",
            recorded_by=principal.user_account_id,
            fy_start_month=fy_start_month,
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
    resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
    if resolved is None:
        raise HTTPException(400, f"{lt.name} has no balance bucket to encash from")
    bucket_id, _ = resolved
    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp_uuid)

    await lock_leave_bucket(session, tenant_id, emp_uuid, bucket_id)
    ledger_row = await get_or_create_ledger_row(
        session,
        tenant_id,
        emp_uuid,
        bucket_id,
        effective_date.year,
        effective_date.month,
        fy_start_month=fy_start_month,
    )
    available = ledger_row.closing - ledger_row.held
    if body.days > available:
        raise HTTPException(
            400, f"Only {available:g} days available to encash, requested {body.days:g}"
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
    await session.flush()
    await record_transaction(
        session,
        tenant_id,
        employment_id=emp_uuid,
        bucket_id=bucket_id,
        leave_type_id=lt.id,
        transaction_type=LeaveTransactionType.ENCASHMENT,
        quantity=body.days,
        effective_date=effective_date,
        reference_id=enc.id,
        reference_type="ENCASHMENT",
        recorded_by=principal.user_account_id,
        fy_start_month=fy_start_month,
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
    "/balances/adjust",
    response_model=LeaveBalanceAdjustmentResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def adjust_balance(
    body: LeaveBalanceAdjustmentRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveBalanceAdjustmentResponse:
    """
    One-shot manual credit or debit to an employee's leave balance, for cases
    the normal flows don't cover: seeding an opening balance carried over
    from a previous system (kind="OPENING"), or correcting a mistake
    (kind="ADJUSTMENT"). Posts a single transaction through the same ledger
    every other write path uses — the two kinds differ only in which ledger
    column and audit label they post under; the balance math is identical.
    """
    scope = scope.for_permission("leave.write")
    emp_uuid = to_uuid(body.employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    await lock_resource(session, tenant_id, f"leave:{emp_uuid}")

    lt = await _get_lt(session, tenant_id, body.leave_type_id)
    resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
    if resolved is None:
        raise HTTPException(400, f"{lt.name} has no balance bucket to adjust")
    bucket_id, _ = resolved
    effective_date = body.effective_date or now_utc().date()
    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp_uuid)

    tx, _ledger_row = await record_transaction(
        session,
        tenant_id,
        employment_id=emp_uuid,
        bucket_id=bucket_id,
        leave_type_id=lt.id,
        transaction_type=LeaveTransactionType(body.kind),
        quantity=body.quantity,
        effective_date=effective_date,
        reference_type="MANUAL",
        recorded_by=principal.user_account_id,
        reason=body.reason,
        fy_start_month=fy_start_month,
    )
    await session.flush()
    return LeaveBalanceAdjustmentResponse(
        employment_id=body.employment_id,
        leave_type_id=body.leave_type_id,
        leave_type_name=lt.name,
        kind=tx.transaction_type,
        quantity=body.quantity,
        new_balance=tx.new_balance,
        effective_date=effective_date,
        reason=body.reason,
    )


@router.post(
    "/accrual/run",
    response_model=AccrualRunResponse,
    dependencies=[require_permission("leave.write")],
)
async def run_accrual(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    period: str | None = Query(
        default=None, description='"YYYY-MM", defaults to the current month'
    ),
) -> AccrualRunResponse:
    """
    Credits every eligible employee's bucket, per resolved entitlement, for
    every paid or comp-off leave type. "Resolved entitlement" is an explicit
    LeaveBucketPolicy if one applies to that employee, else the leave type's
    own days_per_year/accrual_enabled fields — a tenant that's never touched
    Policy -> Leave policies gets exactly today's behaviour, just posted
    through the ledger. Idempotency is a journal lookup (an ACCRUAL
    transaction already dated this exact period) rather than a separate
    marker field, so this is safe to call more than once for the same or an
    earlier period; it does not backfill a month that was skipped by
    mistake. Meant to be triggered by an external cron; there is no in-app
    scheduler (see RUNBOOK.md).
    """
    scope = scope.for_permission("leave.write")
    clause, params = scope.employment_filter_sql("e")
    return await accrue_period(
        session, tenant_id, period, recorded_by=principal.user_account_id,
        employment_clause=clause, employment_params=params,
    )


async def accrue_period(
    session: AsyncSession,
    tenant_id: UUID,
    period: str | None,
    *,
    recorded_by: UUID,
    employment_clause: str = "",
    employment_params: dict | None = None,
) -> AccrualRunResponse:
    """
    The accrual itself, shared by POST /accrual/run and the daily job (hrms.jobs), which runs
    it for every employee as SYSTEM_ACTOR. Idempotent per period.
    """
    if period is None:
        period = now_utc().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise HTTPException(422, "period must be YYYY-MM")
    if period > now_utc().strftime("%Y-%m"):
        raise HTTPException(422, "Cannot accrue a future period")
    await lock_resource(session, tenant_id, "leave-accrual")
    started = time.perf_counter()
    year, month = int(period[:4]), int(period[5:7])
    as_of = date(year, month, 1)

    lt_rows = await session.execute(
        select(LeaveType)
        .where(LeaveType.tenant_id == tenant_id)
        .where(LeaveType.archived_at == None)  # noqa: E711
        .where(col(LeaveType.is_paid) | col(LeaveType.is_comp_off))
        # Deterministic: when several types share a bucket, the oldest type is the one the
        # period's accrual is recorded against (the order used to be whatever Postgres chose).
        .order_by(col(LeaveType.recorded_at), col(LeaveType.id))
    )
    leave_types = list(lt_rows.scalars())
    if not leave_types:
        return AccrualRunResponse(period=period, balances_credited=0, days_credited_total=0.0)

    clause, params = employment_clause, employment_params or {}
    emp_rows = await session.execute(
        text(f"""
            SELECT e.id, e.hire_date, e.employment_state FROM employments e
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state NOT IN ('SEPARATED')
            {clause}
        """),
        {"tid": str(tenant_id), **params},
    )
    employees = sorted(((UUID(str(r[0])), r[1], r[2]) for r in emp_rows), key=lambda e: str(e[0]))

    # Everything per employee is resolved up front in a handful of queries (policy sets
    # once per placement, not per person), then each leave type is credited with one
    # set-based write — see engine.record_accruals. A 2,000-person run used to be ~100k
    # statements in one request.
    emp_ids = [emp_id for emp_id, _, _ in employees]
    fy_months = await resolve_fy_start_months_bulk(session, tenant_id, emp_ids)
    policy_sets = await resolve_leave_policy_sets_bulk(session, tenant_id, emp_ids, as_of)
    bucket_policies: dict[tuple, LeaveBucketPolicy | None] = {}
    # (employment, bucket) pairs that already hold an ACCRUAL for this period — before this
    # run, or from an earlier leave type in it that maps to the same bucket.
    accrued_for: dict[UUID, set[UUID]] = {}

    credited = 0
    total_days = 0.0
    for lt in leave_types:
        resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
        if resolved is None:
            continue
        bucket_id, _ = resolved
        if bucket_id not in accrued_for:
            accrued_for[bucket_id] = {
                UUID(str(r[0]))
                for r in await session.execute(
                    select(LeaveBalanceTransaction.employment_id)
                    .where(LeaveBalanceTransaction.tenant_id == tenant_id)
                    .where(LeaveBalanceTransaction.bucket_id == bucket_id)
                    .where(
                        LeaveBalanceTransaction.transaction_type
                        == LeaveTransactionType.ACCRUAL.value
                    )
                    .where(LeaveBalanceTransaction.effective_date == as_of)
                )
            }
        already = accrued_for[bucket_id]
        credits: list[tuple[UUID, float, int]] = []
        for emp_id, hire_date, emp_state in employees:
            pset = policy_sets.get(emp_id)
            key = (pset.id if pset else None, bucket_id)
            if key not in bucket_policies:
                bucket_policies[key] = (
                    await resolve_bucket_policy(session, tenant_id, pset.id, bucket_id)
                    if pset
                    else None
                )
            entitlement = _entitlement_from(bucket_policies[key], lt)
            if entitlement.accrual_type != "MONTHLY_PRORATE":
                continue
            monthly = round(entitlement.days_per_year / 12, 4)
            if monthly <= 0:
                continue
            eligible = (
                entitlement.probation_eligible or emp_state != "PROBATION"
            ) and tenure_months(hire_date, as_of) >= entitlement.min_service_months
            if not eligible or emp_id in already:
                continue
            credits.append((emp_id, monthly, fy_months[emp_id]))
            already.add(emp_id)
            credited += 1
            total_days += monthly
        await record_accruals(
            session,
            tenant_id,
            bucket_id=bucket_id,
            leave_type_id=lt.id,
            credits=credits,
            effective_date=as_of,
            reference_type="ACCRUAL_RUN",
            recorded_by=recorded_by,
        )

    await session.flush()
    ACCRUAL_RUN.observe(time.perf_counter() - started)
    ACCRUALS_CREDITED.inc(credited)
    return AccrualRunResponse(
        period=period, balances_credited=credited, days_credited_total=round(total_days, 2)
    )


@router.post(
    "/year-end-close",
    response_model=YearEndCloseResponse,
    dependencies=[require_permission("leave.write")],
)
async def close_year_end(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    fy_year: int = Query(..., description="e.g. 2026 for FY2026-27 under an April-start policy"),
) -> YearEndCloseResponse:
    """
    For every (employment, bucket) with ledger activity in fy_year: cap the
    FY's closing balance at the resolved policy's max_carry_forward_days
    (posting a LAPSE for the excess) or leave it uncapped if no cap resolves
    — the remainder simply IS next FY's opening, the same way every other
    month-to-month transition already works, via the ordinary prior-row
    lookup in get_or_create_ledger_row/the forward cascade. No separate
    CARRY_FORWARD transaction is posted: doing so on top of the LAPSE would
    double the balance (CARRY_FORWARD's effect is additive), and posting it
    on the new FY's row instead only works when that row doesn't already
    exist (an advance-dated hold can create it first) — the LAPSE + cascade
    path handles both cases correctly with one transaction.

    Idempotent per (employment, bucket): skipped if a YEAR_END-referenced
    transaction already exists dated this FY's closing month.
    """
    scope = scope.for_permission("leave.write")
    clause, params = scope.employment_filter_sql("e")
    combos = (
        await session.execute(
            text(f"""
                SELECT DISTINCT lml.employment_id, lml.bucket_id
                FROM leave_monthly_ledger lml
                JOIN employments e ON e.tenant_id = lml.tenant_id AND e.id = lml.employment_id
                WHERE lml.tenant_id = CAST(:tid AS uuid) AND lml.fy_year = :fy_year
                {clause}
            """),
            {"tid": str(tenant_id), "fy_year": fy_year, **params},
        )
    ).all()

    closed = 0
    lapsed_total = 0.0
    close_run_id = uuid4()
    for employment_id, bucket_id in combos:
        fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, employment_id)
        if fy_start_month == 1:
            last_year, last_month = fy_year, 12
        else:
            last_year, last_month = fy_year + 1, fy_start_month - 1
        closing_effective_date = date(last_year, last_month, 1)

        already = await session.execute(
            select(LeaveBalanceTransaction.id)
            .where(LeaveBalanceTransaction.tenant_id == tenant_id)
            .where(LeaveBalanceTransaction.employment_id == employment_id)
            .where(LeaveBalanceTransaction.bucket_id == bucket_id)
            .where(LeaveBalanceTransaction.reference_type == "YEAR_END")
            .where(LeaveBalanceTransaction.effective_date == closing_effective_date)
        )
        if already.scalar():
            continue

        await lock_leave_bucket(session, tenant_id, employment_id, bucket_id)
        last_row = await get_or_create_ledger_row(
            session,
            tenant_id,
            employment_id,
            bucket_id,
            last_year,
            last_month,
            fy_start_month=fy_start_month,
        )
        closing = last_row.closing
        cap = await _resolve_bucket_carry_forward_cap(
            session, tenant_id, employment_id, bucket_id, closing_effective_date
        )

        if cap is not None and closing > cap:
            lapse_amount = closing - cap
            await record_transaction(
                session,
                tenant_id,
                employment_id=employment_id,
                bucket_id=bucket_id,
                transaction_type=LeaveTransactionType.LAPSE,
                quantity=lapse_amount,
                effective_date=closing_effective_date,
                reference_id=close_run_id,
                reference_type="YEAR_END",
                recorded_by=principal.user_account_id,
                reason=f"FY{fy_year} year-end close: capped at {cap:g}, {lapse_amount:g} lapsed",
                fy_start_month=fy_start_month,
            )
            lapsed_total += lapse_amount
        else:
            # Nothing to lapse, but still stamp this (employment, bucket) as
            # closed for this FY — a zero-effect marker, purely for the
            # idempotency check above.
            await record_transaction(
                session,
                tenant_id,
                employment_id=employment_id,
                bucket_id=bucket_id,
                transaction_type=LeaveTransactionType.ADJUSTMENT,
                quantity=0.0,
                effective_date=closing_effective_date,
                reference_id=close_run_id,
                reference_type="YEAR_END",
                recorded_by=principal.user_account_id,
                reason=(
                    f"FY{fy_year} year-end close: {max(0.0, closing):g} carried "
                    "forward, nothing lapsed"
                ),
                fy_start_month=fy_start_month,
            )
        closed += 1

    return YearEndCloseResponse(
        fy_year=fy_year, buckets_closed=closed, days_lapsed=round(lapsed_total, 2)
    )


# ─── Leave applications ───────────────────────────────────────────────────────


@router.get("/applications", response_model=list[LeaveApplicationResponse])
async def list_applications(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None),
    status: str | None = Query(
        default=None, description="One status, or several comma-separated (PENDING_L1,PENDING_L2)"
    ),
    limit: int = Query(default=100, ge=1, le=200),
    after: str | None = Query(
        default=None,
        description="Id of the last application on the previous page; returns the next page. "
        "A page shorter than `limit` is the last one.",
    ),
) -> list[LeaveApplicationResponse]:
    """
    Newest first: drafts (not yet applied) at the top, then by applied_at. Paged by keyset
    on (applied_at, id), so any page costs the same however deep it is.
    """
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
        q = q.where(
            col(LeaveApplication.employment_id).in_(visible_employments_select(tenant_id, scope))
        )
    if status:
        q = q.where(col(LeaveApplication.status).in_([s.strip() for s in status.split(",")]))
    if after:
        q = q.where(await _after_application(session, tenant_id, after))
    rows = (
        await session.execute(
            q.order_by(
                col(LeaveApplication.applied_at).desc().nulls_first(),
                col(LeaveApplication.id).desc(),
            ).limit(limit)
        )
    ).all()
    histories = await _get_histories(session, tenant_id, [app.id for app, _ in rows])
    return [_app_resp(app, lt, histories.get(app.id, [])) for app, lt in rows]


@router.get("/applications/summary", response_model=LeaveApplicationSummary)
async def application_summary(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    legal_entity_id: str | None = Query(
        default=None, description="Narrow to one company within the caller's scope"
    ),
) -> LeaveApplicationSummary:
    """Application counts by status and approved days by leave type, across the caller's scope."""
    scope = read_scope(scope, "leave.read", "leave.approve")
    base = [
        LeaveApplication.tenant_id == tenant_id,
        LeaveApplication.archived_at == None,  # noqa: E711
    ]
    if not scope.is_all:
        base.append(
            col(LeaveApplication.employment_id).in_(visible_employments_select(tenant_id, scope))
        )
    if legal_entity_id:  # an extra AND: narrows the scope above, never widens it
        base.append(
            col(LeaveApplication.employment_id).in_(
                text(
                    "SELECT id FROM employments WHERE tenant_id = :focus_tid"
                    " AND legal_entity_id = :focus_le"
                )
                .bindparams(focus_tid=tenant_id, focus_le=to_uuid(legal_entity_id))
                .columns(id=Uuid)
            )
        )
    by_status = await session.execute(
        select(LeaveApplication.status, func.count()).where(*base).group_by(LeaveApplication.status)
    )
    by_type = await session.execute(
        select(
            LeaveType.id, LeaveType.name, LeaveType.color, func.sum(LeaveApplication.days_requested)
        )
        .join(LeaveType, col(LeaveType.id) == LeaveApplication.leave_type_id)
        .where(*base, LeaveApplication.status == LeaveApplicationStatus.APPROVED)
        .group_by(LeaveType.id, LeaveType.name, LeaveType.color)
        .order_by(LeaveType.name)
    )
    return LeaveApplicationSummary(
        by_status={s: n for s, n in by_status.all()},
        approved_days_by_type=[
            LeaveTypeDays(
                leave_type_id=to_typed_id("leave_type", lt_id), name=name, color=color, days=days
            )
            for lt_id, name, color, days in by_type.all()
        ],
    )


async def _after_application(session, tenant_id, after: str):
    """Keyset condition: rows after this application in (applied_at DESC NULLS FIRST, id DESC)."""
    cursor_id = to_uuid(after)
    applied_at = (
        await session.execute(
            select(LeaveApplication.applied_at)
            .where(LeaveApplication.tenant_id == tenant_id)
            .where(LeaveApplication.id == cursor_id)
        )
    ).first()
    if applied_at is None:
        raise HTTPException(422, "`after` is not a leave application id")
    cursor_at = applied_at[0]
    app_at, app_id = col(LeaveApplication.applied_at), col(LeaveApplication.id)
    if cursor_at is None:
        # Still among the drafts: later drafts by id, then every applied row.
        return or_(and_(app_at.is_(None), app_id < cursor_id), app_at.is_not(None))
    # `app_at <= cursor_at` on its own lets the index range-scan straight to the position.
    return and_(app_at <= cursor_at, or_(app_at < cursor_at, app_id < cursor_id))


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
        days_by_month=allocation,
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
    app.days_by_month = await _allocate_days(
        session, tenant_id, app.employment_id, app.from_date, app.to_date, app.half_day_option
    )
    app.days_requested = sum(app.days_by_month.values())
    await _hold_leave_balance(session, tenant_id, principal, app, lt)

    if lt.requires_approval:
        app.status = LeaveApplicationStatus.PENDING_L1
        app.current_level = 1
    else:
        app.status = LeaveApplicationStatus.APPROVED
        await _post_leave_transaction(
            session,
            tenant_id,
            principal,
            app,
            lt,
            LeaveTransactionType.LEAVE_TAKEN,
            approved_by=principal.user_account_id,
        )
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
        await _post_leave_transaction(
            session,
            tenant_id,
            principal,
            app,
            lt,
            LeaveTransactionType.LEAVE_TAKEN,
            approved_by=principal.user_account_id,
        )
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
    await _post_leave_transaction(
        session, tenant_id, principal, app, lt, LeaveTransactionType.RELEASE
    )
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
        await _post_leave_transaction(
            session, tenant_id, principal, app, lt, LeaveTransactionType.RELEASE
        )
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
            await _post_leave_transaction(
                session, tenant_id, principal, app, lt, LeaveTransactionType.LEAVE_REVERSED
            )
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
        await _post_leave_transaction(
            session,
            tenant_id,
            principal,
            app,
            lt,
            LeaveTransactionType.LEAVE_REVERSED,
            approved_by=principal.user_account_id,
        )
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
    return (await _get_histories(session, tenant_id, [app_id])).get(app_id, [])


async def _get_histories(
    session, tenant_id, app_ids: list[UUID]
) -> dict[UUID, list[LeaveApprovalActionResponse]]:
    """Approval history for many applications in one query (a list page, not one per row)."""
    if not app_ids:
        return {}
    rows = await session.execute(
        select(LeaveApprovalAction)
        .where(LeaveApprovalAction.tenant_id == tenant_id)
        .where(col(LeaveApprovalAction.application_id).in_(app_ids))
        .order_by(col(LeaveApprovalAction.actioned_at))
    )
    out: dict[UUID, list[LeaveApprovalActionResponse]] = {}
    for a in rows.scalars():
        out.setdefault(a.application_id, []).append(
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
        )
    return out


class _Entitlement:
    """What an employee gets for one bucket — an explicit LeaveBucketPolicy if
    one resolves, else the owning leave type's own fields (see _resolve_entitlement)."""

    __slots__ = (
        "accrual_type",
        "days_per_year",
        "carry_forward_enabled",
        "max_carry_forward_days",
        "probation_eligible",
        "min_service_months",
    )

    def __init__(
        self,
        accrual_type: str,
        days_per_year: float,
        carry_forward_enabled: bool,
        max_carry_forward_days: float | None,
        probation_eligible: bool,
        min_service_months: int,
    ) -> None:
        self.accrual_type = accrual_type
        self.days_per_year = days_per_year
        self.carry_forward_enabled = carry_forward_enabled
        self.max_carry_forward_days = max_carry_forward_days
        self.probation_eligible = probation_eligible
        self.min_service_months = min_service_months


async def _resolve_bucket_for_type(
    session, tenant_id, lt: LeaveType, *, create_if_missing: bool = True
) -> tuple[UUID, bool] | None:
    """
    The bucket this leave type's balance lives in.

    An explicit leave_type_bucket_mapping row if one already exists (Policy
    Sets creates one automatically the first time a leave type gets an
    entitlement rule); otherwise, on a WRITE path (create_if_missing=True), a
    1:1 bucket is auto-created on first use and mapped — so a tenant that's
    never touched Policy Sets still gets a real, ledger-backed balance per
    leave type, same as before buckets existed. On a READ path
    (list_balances), create_if_missing=False so just looking at balances
    never fabricates a bucket that's never had any activity.

    Unpaid leave (LWP) with no explicit mapping returns None — not tracked,
    matching today's behaviour; map it to an is_unlimited bucket yourself if
    you want it logged (e.g. for payroll export).

    Returns (bucket_id, is_unlimited), or None if this type isn't tracked.
    """
    found = (
        await session.execute(
            select(LeaveTypeBucketMapping, LeaveBalanceBucket)
            .join(
                LeaveBalanceBucket,
                col(LeaveBalanceBucket.id) == LeaveTypeBucketMapping.bucket_id,
            )
            .where(LeaveTypeBucketMapping.tenant_id == tenant_id)
            .where(LeaveTypeBucketMapping.leave_type_id == lt.id)
        )
    ).first()
    if found:
        _mapping, bucket = found
        return bucket.id, bucket.is_unlimited

    if not create_if_missing or (not lt.is_paid and not lt.is_comp_off):
        return None

    code = lt.code[:20]
    if (
        await session.execute(
            select(LeaveBalanceBucket.id)
            .where(LeaveBalanceBucket.tenant_id == tenant_id)
            .where(LeaveBalanceBucket.code == code)
        )
    ).scalar():
        code = f"{code[:16]}-{uuid4().hex[:3]}"

    bucket_id = uuid4()
    session.add(
        LeaveBalanceBucket(
            tenant_id=tenant_id,
            id=bucket_id,
            name=lt.name,
            code=code,
            is_unlimited=False,
            recorded_at=now_utc(),
        )
    )
    session.add(
        LeaveTypeBucketMapping(
            tenant_id=tenant_id,
            id=uuid4(),
            leave_type_id=lt.id,
            bucket_id=bucket_id,
            recorded_at=now_utc(),
        )
    )
    await session.flush()
    return bucket_id, False


async def _resolve_entitlement(
    session, tenant_id, employment_id: UUID, bucket_id: UUID, lt: LeaveType, as_of: date
) -> _Entitlement:
    """Bucket policy if one resolves for this employee, else the leave type's own
    flat fields — the zero-config default so accrual works with no policy setup."""
    bp = await resolve_employee_bucket_policy(session, tenant_id, employment_id, bucket_id, as_of)
    return _entitlement_from(bp, lt)


def _entitlement_from(bp: LeaveBucketPolicy | None, lt: LeaveType) -> _Entitlement:
    if bp is not None:
        return _Entitlement(
            bp.accrual_type,
            bp.days_per_year,
            bp.carry_forward_enabled,
            bp.max_carry_forward_days,
            bp.probation_eligible,
            bp.min_service_months,
        )
    return _Entitlement(
        "MONTHLY_PRORATE" if lt.accrual_enabled else "NONE",
        lt.days_per_year,
        lt.carry_forward,
        lt.max_carry_forward_days,
        True,  # no eligibility gate today -> preserve "accrual runs for everyone active"
        0,
    )


async def _resolve_bucket_carry_forward_cap(
    session, tenant_id, employment_id: UUID, bucket_id: UUID, as_of: date
) -> float | None:
    """
    max_carry_forward_days for this bucket at year-end: an explicit
    LeaveBucketPolicy if one resolves (0.0 if it has carry-forward disabled
    entirely), else — only when the bucket has exactly one mapped leave type,
    so there's no ambiguity about which type's rule applies — that type's own
    max_carry_forward_days. None means uncapped: when nothing configured
    says otherwise, year-end close carries everything forward rather than
    guessing what to lapse.
    """
    bp = await resolve_employee_bucket_policy(session, tenant_id, employment_id, bucket_id, as_of)
    if bp is not None:
        return bp.max_carry_forward_days if bp.carry_forward_enabled else 0.0

    mapped_types = (
        (
            await session.execute(
                select(LeaveTypeBucketMapping.leave_type_id)
                .where(LeaveTypeBucketMapping.tenant_id == tenant_id)
                .where(LeaveTypeBucketMapping.bucket_id == bucket_id)
            )
        )
        .scalars()
        .all()
    )
    if len(mapped_types) == 1:
        lt = (
            (
                await session.execute(
                    select(LeaveType)
                    .where(LeaveType.tenant_id == tenant_id)
                    .where(LeaveType.id == mapped_types[0])
                )
            )
            .scalars()
            .first()
        )
        if lt is not None:
            return lt.max_carry_forward_days if lt.carry_forward else 0.0
    return None


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
    """
    Split [start, end] into working days, keyed "YYYY-MM" — one entry per
    calendar month touched, matching leave_monthly_ledger's grain. A leave
    spanning a month (or financial-year) boundary posts one engine
    transaction per key; see _post_leave_transaction / _hold_leave_balance.
    """
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
            key = f"{day.year:04d}-{day.month:02d}"
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


def _application_allocation(app: LeaveApplication) -> dict[str, float]:
    allocation = app.days_by_month
    if allocation:
        return allocation
    # Legacy applications recorded before this column existed: recover a single
    # "YYYY-MM" key from from_date, provided the whole thing fits one month.
    if app.from_date.year != app.to_date.year or app.from_date.month != app.to_date.month:
        raise HTTPException(409, "A legacy cross-month application needs balance reconciliation")
    return {f"{app.from_date.year:04d}-{app.from_date.month:02d}": app.days_requested}


async def _post_leave_transaction(
    session,
    tenant_id,
    principal,
    app: LeaveApplication,
    lt: LeaveType,
    transaction_type: LeaveTransactionType,
    *,
    approved_by: UUID | None = None,
) -> None:
    """Post RELEASE / LEAVE_TAKEN / LEAVE_REVERSED, one transaction per (year,
    month) segment. For the balance-checked HOLD, see _hold_leave_balance."""
    if not lt.is_paid and not lt.is_comp_off:
        return
    resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
    if resolved is None:
        return
    bucket_id, _ = resolved
    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, app.employment_id)
    for period, days in sorted(_application_allocation(app).items()):
        if days <= 0:
            continue
        year, month = int(period[:4]), int(period[5:7])
        await record_transaction(
            session,
            tenant_id,
            employment_id=app.employment_id,
            bucket_id=bucket_id,
            leave_type_id=lt.id,
            transaction_type=transaction_type,
            quantity=days,
            effective_date=date(year, month, 1),
            reference_id=app.id,
            reference_type="LEAVE_APPLICATION",
            recorded_by=principal.user_account_id,
            approved_by=approved_by,
            fy_start_month=fy_start_month,
        )


async def _hold_leave_balance(
    session, tenant_id, principal, app: LeaveApplication, lt: LeaveType
) -> None:
    """Balance-checked HOLD at submission — checks every segment before posting
    any of them, so a partial failure never leaves some months held and others not."""
    if not lt.is_paid and not lt.is_comp_off:
        return
    resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
    if resolved is None:
        return
    bucket_id, is_unlimited = resolved
    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, app.employment_id)
    allocation = _application_allocation(app)
    if not is_unlimited:
        for period, days in sorted(allocation.items()):
            if days <= 0:
                continue
            year, month = int(period[:4]), int(period[5:7])
            await lock_leave_bucket(session, tenant_id, app.employment_id, bucket_id)
            row = await get_or_create_ledger_row(
                session,
                tenant_id,
                app.employment_id,
                bucket_id,
                year,
                month,
                fy_start_month=fy_start_month,
            )
            available = row.closing - row.held
            if days > available:
                raise HTTPException(
                    409, f"Insufficient leave balance for {period} ({available:g} day(s) available)"
                )
    await _post_leave_transaction(session, tenant_id, principal, app, lt, LeaveTransactionType.HOLD)


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
