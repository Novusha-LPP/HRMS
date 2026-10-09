"""
Comp-off earned by working a weekly off or holiday under a COMP_OFF attendance policy.

The attendance day says how much it earned (AttendanceDay.comp_off_days, recomputed with every
punch or correction); this keeps the employee's comp-off grant and leave balance in step with
it. A correction that changes the worked time posts an ADJUSTMENT for the difference rather
than rewriting history. A comp-off HR granted by hand for the same date is never touched.
"""

from uuid import uuid4

from sqlmodel import select

from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.datetime_utils import now_utc
from hrms.core.locking import lock_resource
from hrms.modules.leave.engine import record_transaction
from hrms.modules.leave.models import CompOffGrant, LeaveTransactionType
from hrms.modules.leave.policy_resolver import resolve_employee_fy_start_month

AUTO_NOTE = "Worked on an off day"


def earned_comp_off(worked_minutes: int, standard_minutes: int, half_day_pct: int) -> float:
    """A full day for a standard day's work, half for at least the half-day share of it."""
    if standard_minutes <= 0 or worked_minutes <= 0:
        return 0.0
    if worked_minutes >= standard_minutes:
        return 1.0
    if worked_minutes >= standard_minutes * half_day_pct / 100:
        return 0.5
    return 0.0


async def sync_attendance_comp_off(session, tenant_id, employment_id, work_date, days: float):
    grant = (
        (
            await session.execute(
                select(CompOffGrant)
                .where(CompOffGrant.tenant_id == tenant_id)
                .where(CompOffGrant.employment_id == employment_id)
                .where(CompOffGrant.work_date == work_date)
            )
        )
        .scalars()
        .first()
    )
    if grant is not None and (grant.granted_by is not None or grant.notes != AUTO_NOTE):
        return  # granted by hand
    current = grant.days_granted if grant else 0.0
    if current == days:
        return

    from hrms.modules.leave.router import _get_or_create_comp_off_type, _resolve_bucket_for_type

    await lock_resource(session, tenant_id, f"leave:{employment_id}")
    leave_type = await _get_or_create_comp_off_type(session, tenant_id)
    if grant is None:
        grant = CompOffGrant(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=employment_id,
            work_date=work_date,
            days_granted=days,
            notes=AUTO_NOTE,
            recorded_at=now_utc(),
        )
        session.add(grant)
    elif days:
        grant.days_granted = days
        session.add(grant)
    else:
        await session.delete(grant)
    await session.flush()

    resolved = await _resolve_bucket_for_type(session, tenant_id, leave_type)
    if resolved is None:
        return
    bucket_id, _ = resolved
    await record_transaction(
        session,
        tenant_id,
        employment_id=employment_id,
        bucket_id=bucket_id,
        leave_type_id=leave_type.id,
        transaction_type=(
            LeaveTransactionType.GRANT if current == 0 else LeaveTransactionType.ADJUSTMENT
        ),
        quantity=days - current,
        effective_date=work_date,
        reason=AUTO_NOTE if current == 0 else "Off-day attendance recalculated",
        reference_id=grant.id,
        reference_type="COMP_OFF",
        recorded_by=SYSTEM_ACTOR,
        fy_start_month=await resolve_employee_fy_start_month(session, tenant_id, employment_id),
    )
