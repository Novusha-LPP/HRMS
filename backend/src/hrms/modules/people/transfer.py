"""Moving a person to another company of the group (docs/REJOIN_DEVELOPMENT_PLAN.md, R7).

A transfer ends the employment in the first company and starts a new one in the second on the
same day, so each company keeps its own attendance, payroll and history. What follows the
person: their login, their identity record (copied, so the first company keeps its own) and
their uploaded documents including the photo (moved), their service for leave (when leave is
carried) and, with CARRY, their unused leave balances. With SETTLE the first company's leave
rules for leavers apply instead and the new employment starts empty.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.metrics import COMPANY_TRANSFERS
from hrms.modules.kernel.models import UserAccount
from hrms.modules.kyc.models import EmployeeKycRecord
from hrms.modules.leave.engine import record_transaction
from hrms.modules.leave.models import LeaveTransactionType
from hrms.modules.leave.policy_resolver import resolve_employee_fy_start_month
from hrms.modules.people import rejoin, spells
from hrms.modules.people.models import (
    CompanyTransfer,
    Employment,
    EmploymentState,
    PersonnelAction,
    PersonnelActionStatus,
    PersonnelActionType,
    TransferLeaveMode,
)


@dataclass
class TransferPlan:
    from_company: str
    to_company: str
    leave: list[rejoin.LeaveEffect] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


async def _company_name(session, tenant_id: UUID, entity_id: UUID) -> str | None:
    return (
        await session.execute(
            text("SELECT name FROM legal_entities WHERE tenant_id = :t AND id = :i"),
            {"t": tenant_id, "i": entity_id},
        )
    ).scalar()


async def plan_transfer(
    session,
    tenant_id: UUID,
    emp: Employment,
    to_entity_id: UUID,
    effective_date: date,
    today: date,
) -> TransferPlan:
    """Check a transfer and describe what it would do. Writes nothing."""
    from_name = await _company_name(session, tenant_id, emp.legal_entity_id) or "this company"
    to_name = await _company_name(session, tenant_id, to_entity_id)
    plan = TransferPlan(from_company=from_name, to_company=to_name or "")
    if to_name is None:
        plan.blocked.append("That company doesn't exist.")
    if to_entity_id == emp.legal_entity_id:
        plan.blocked.append("They already work for that company.")
    if emp.employment_state == EmploymentState.SEPARATED:
        plan.blocked.append("They have left. Rehire them instead.")
    if effective_date > today:
        plan.blocked.append("A transfer takes effect today or earlier. Enter it on the day.")
    if effective_date < emp.hire_date:
        plan.blocked.append(f"The date can't be before they joined ({emp.hire_date}).")
    scheduled = (
        await session.execute(
            select(col(PersonnelAction.type), col(PersonnelAction.effective_date))
            .where(col(PersonnelAction.tenant_id) == tenant_id)
            .where(col(PersonnelAction.employment_id) == emp.id)
            .where(col(PersonnelAction.status) == PersonnelActionStatus.SCHEDULED)
        )
    ).all()
    if scheduled:
        plan.blocked.append(
            "A change is already scheduled for them. Cancel it before transferring."
        )
    if emp.employment_state == EmploymentState.NOTICE:
        plan.warnings.append("They are serving notice.")
    plan.leave = await rejoin._balances(session, tenant_id, emp, effective_date)
    return plan


async def execute_transfer(
    session,
    tenant_id: UUID,
    emp: Employment,
    *,
    to_entity_id: UUID,
    effective_date: date,
    leave_mode: TransferLeaveMode,
    placement: dict[str, Any],
    employee_number: str | None,
    reason: str | None,
    actor_user: UUID | None,
) -> tuple[Employment, CompanyTransfer]:
    # Imported here: the router imports this module's callers.
    from hrms.modules.people.router import (
        _apply_personnel_action,
        _generate_employee_number,
    )

    carried: list[rejoin.LeaveEffect] = []
    if leave_mode == TransferLeaveMode.CARRY:
        carried = await rejoin._balances(session, tenant_id, emp, effective_date)
    old_continuity = emp.continuity_start_date or emp.hire_date
    # Someone confirmed stays confirmed; someone still on probation starts probation again.
    keeps_status = emp.employment_state in (EmploymentState.ACTIVE, EmploymentState.NOTICE)
    old_service_stage = emp.service_stage
    person_id = emp.person_id
    to_name = await _company_name(session, tenant_id, to_entity_id) or "another company"

    # 1. End the employment here. With CARRY the leave is moved below, not settled.
    separation = PersonnelAction(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp.id,
        type=PersonnelActionType.SEPARATION,
        reason_code="TRANSFER",
        effective_date=effective_date,
        changes={
            "last_working_day": effective_date.isoformat(),
            "skip_leave_settlement": leave_mode == TransferLeaveMode.CARRY,
        },
        status=PersonnelActionStatus.PENDING_APPROVAL,
    )
    session.add(separation)
    await session.flush()
    await _apply_personnel_action(session, tenant_id, separation, emp)
    separation.status = PersonnelActionStatus.APPLIED
    session.add(separation)

    # 2. Start the employment there.
    number = employee_number or await _generate_employee_number(session, tenant_id, to_entity_id)
    if not number:
        raise HTTPException(
            400,
            "No employee ID scheme is configured for that company. Enter an employee ID.",
        )
    new = Employment(
        tenant_id=tenant_id,
        id=uuid4(),
        person_id=person_id,
        legal_entity_id=to_entity_id,
        employee_number=number,
        hire_date=effective_date,
        service_stage=old_service_stage,
        employment_state=EmploymentState.ACTIVE if keeps_status else EmploymentState.PROBATION,
    )
    session.add(new)
    await session.flush()
    await spells.open_first_spell(session, tenant_id, new, actor_user)
    if leave_mode == TransferLeaveMode.CARRY:
        new.continuity_start_date = old_continuity  # service goes with the person
        session.add(new)
    hire = PersonnelAction(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=new.id,
        type=PersonnelActionType.HIRE,
        reason_code="TRANSFER",
        effective_date=effective_date,
        changes=placement,
        status=PersonnelActionStatus.PENDING_APPROVAL,
    )
    session.add(hire)
    await session.flush()
    await _apply_personnel_action(session, tenant_id, hire, new)
    hire.status = PersonnelActionStatus.APPLIED
    session.add(hire)

    # 3. Leave: close the balances here and open the same amounts there.
    if carried:
        recorded_by = actor_user or SYSTEM_ACTOR
        fy_old = await resolve_employee_fy_start_month(session, tenant_id, emp.id)
        fy_new = await resolve_employee_fy_start_month(session, tenant_id, new.id)
        note = f"Transferred to {to_name}"
        for effect in carried:
            await record_transaction(
                session,
                tenant_id,
                employment_id=emp.id,
                bucket_id=effect.bucket_id,
                leave_type_id=effect.leave_type_id,
                transaction_type=LeaveTransactionType.LAPSE,
                quantity=effect.days,
                effective_date=effective_date,
                reason=note,
                reference_id=new.id,
                reference_type="TRANSFER",
                recorded_by=recorded_by,
                fy_start_month=fy_old,
            )
            await record_transaction(
                session,
                tenant_id,
                employment_id=new.id,
                bucket_id=effect.bucket_id,
                leave_type_id=effect.leave_type_id,
                transaction_type=LeaveTransactionType.OPENING,
                quantity=effect.days,
                effective_date=effective_date,
                reason="Carried over from the previous company",
                reference_id=emp.id,
                reference_type="TRANSFER",
                recorded_by=recorded_by,
                fy_start_month=fy_new,
            )

    # 4. What follows the person.
    account = (
        (
            await session.execute(
                select(UserAccount)
                .where(col(UserAccount.tenant_id) == tenant_id)
                .where(col(UserAccount.employment_id) == emp.id)
            )
        )
        .scalars()
        .first()
    )
    if account is not None:
        account.employment_id = new.id
        account.employee_code = number
        session.add(account)
    record = (
        (
            await session.execute(
                select(EmployeeKycRecord)
                .where(col(EmployeeKycRecord.tenant_id) == tenant_id)
                .where(col(EmployeeKycRecord.employment_id) == emp.id)
            )
        )
        .scalars()
        .first()
    )
    if record is not None:
        values = {
            c.name: getattr(record, c.name)
            for c in EmployeeKycRecord.__table__.columns  # type: ignore[attr-defined]
            if c.name not in ("tenant_id", "id", "employment_id", "version")
        }
        session.add(
            EmployeeKycRecord(
                tenant_id=tenant_id, id=uuid4(), employment_id=new.id, version=0, **values
            )
        )
    await session.execute(
        text(
            "UPDATE employee_kyc_documents SET employment_id = :new "
            "WHERE tenant_id = :t AND employment_id = :old"
        ),
        {"t": tenant_id, "new": new.id, "old": emp.id},
    )

    link = CompanyTransfer(
        tenant_id=tenant_id,
        id=uuid4(),
        person_id=person_id,
        from_employment_id=emp.id,
        to_employment_id=new.id,
        effective_date=effective_date,
        leave_mode=leave_mode.value,
        reason=reason,
        created_by=actor_user,
    )
    session.add(link)
    await session.flush()
    COMPANY_TRANSFERS.labels(leave_mode.value).inc()
    return new, link
