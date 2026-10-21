"""Stints of an employment, and the record of what was decided when someone rejoined.

An employment is reused when a separated person rejoins; a "spell" is one stint inside it. The
helpers here are the only place spells are written, so hire, separation and rejoin all keep
employment_spells and employments.current_spell_no / continuity_start_date consistent.

Rejoining still continues the earlier service (RejoinMode.CONTINUE); choosing to start fresh
arrives with the rejoin screen (docs/REJOIN_DEVELOPMENT_PLAN.md, R3).
"""

from datetime import date
from uuid import UUID, uuid4

from sqlmodel import col, select

from hrms.modules.people.models import (
    Employment,
    EmploymentSpell,
    RejoinMode,
    RejoinRecord,
)


async def _spell(session, tenant_id: UUID, employment_id: UUID, spell_no: int):
    return (
        (
            await session.execute(
                select(EmploymentSpell)
                .where(col(EmploymentSpell.tenant_id) == tenant_id)
                .where(col(EmploymentSpell.employment_id) == employment_id)
                .where(col(EmploymentSpell.spell_no) == spell_no)
            )
        )
        .scalars()
        .first()
    )


async def open_first_spell(session, tenant_id: UUID, emp: Employment, actor: UUID | None = None):
    """The first stint of a new employment. Call after the employment row is flushed."""
    emp.continuity_start_date = emp.hire_date
    emp.current_spell_no = 1
    spell = EmploymentSpell(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp.id,
        spell_no=1,
        joined_on=emp.hire_date,
        created_by=actor,
    )
    session.add(spell)
    session.add(emp)
    await session.flush()
    return spell


async def close_current_spell(
    session,
    tenant_id: UUID,
    emp: Employment,
    left_on: date,
    reason: str | None = None,
    actor: UUID | None = None,
):
    """Record that the open stint ended. Creates the stint first if the row predates spells."""
    spell = await _spell(session, tenant_id, emp.id, emp.current_spell_no)
    if spell is None:
        spell = EmploymentSpell(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=emp.id,
            spell_no=emp.current_spell_no,
            joined_on=emp.hire_date,
            created_by=actor,
        )
    spell.left_on = left_on
    if reason:
        spell.exit_reason = reason[:100]
    session.add(spell)
    await session.flush()
    return spell


async def open_next_spell(
    session,
    tenant_id: UUID,
    emp: Employment,
    joined_on: date,
    *,
    mode: RejoinMode = RejoinMode.CONTINUE,
    reason: str | None = None,
    break_start: date | None = None,
    break_condoned: bool | None = None,
    restored_leave: dict | None = None,
    personnel_action_id: UUID | None = None,
    actor: UUID | None = None,
) -> RejoinRecord:
    """Open the next stint for a rejoining employee and record the decision."""
    previous = await _spell(session, tenant_id, emp.id, emp.current_spell_no)
    if previous is None:
        previous = await close_current_spell(
            session, tenant_id, emp, break_start or joined_on, actor=actor
        )
    emp.current_spell_no += 1
    if mode == RejoinMode.FRESH or emp.continuity_start_date is None:
        emp.continuity_start_date = joined_on if mode == RejoinMode.FRESH else emp.hire_date
    spell = EmploymentSpell(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp.id,
        spell_no=emp.current_spell_no,
        joined_on=joined_on,
        created_by=actor,
    )
    session.add(spell)
    session.add(emp)
    await session.flush()
    record = RejoinRecord(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp.id,
        personnel_action_id=personnel_action_id,
        previous_spell_id=previous.id,
        new_spell_id=spell.id,
        mode=mode.value,
        break_start=break_start,
        break_end=joined_on,
        break_condoned=(mode == RejoinMode.CONTINUE) if break_condoned is None else break_condoned,
        reason=reason,
        restored_leave=restored_leave,
        created_by=actor,
    )
    session.add(record)
    await session.flush()
    return record
