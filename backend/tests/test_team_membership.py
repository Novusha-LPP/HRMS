"""Changing teams keeps an employee's other placement fields and history."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.ids import to_typed_id
from hrms.modules.people.models import Assignment, AssignmentManager
from hrms.modules.people.router import _place_assignment


@pytest.mark.parametrize("move", ["assign", "change", "remove"])
async def test_team_move_preserves_employee_placement_and_manager(move, monkeypatch):
    today = date.today()
    tid, employee, department, team_a, team_b, manager = [uuid4() for _ in range(6)]
    source = department if move == "assign" else team_a
    target = department if move == "remove" else team_b
    current = Assignment(
        tenant_id=tid,
        id=uuid4(),
        employment_id=employee,
        effective_from=today - timedelta(days=10),
        org_unit_id=source,
        location_id=uuid4(),
        job_id=uuid4(),
        grade_id=uuid4(),
        position_id=uuid4(),
        cost_centre_id=uuid4(),
    )
    old_manager = AssignmentManager(
        tenant_id=tid,
        id=uuid4(),
        assignment_id=current.id,
        manager_employment_id=manager,
        manager_type="LINE",
        effective_from=current.effective_from,
    )
    result = MagicMock()
    result.scalars.return_value = [old_manager]
    session = MagicMock(execute=AsyncMock(return_value=result), flush=AsyncMock())
    monkeypatch.setattr(
        "hrms.modules.people.router._current_line_manager", AsyncMock(return_value=manager)
    )
    placed = await _place_assignment(
        session, tid, employee, today, {"org_unit_id": to_typed_id("org_unit", target)}, current
    )
    assert placed.org_unit_id == target
    assert current.effective_to == today and old_manager.effective_to == today
    for field in ["location_id", "job_id", "grade_id", "position_id", "cost_centre_id"]:
        assert getattr(placed, field) == getattr(current, field)
    new_managers = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], AssignmentManager) and call.args[0] is not old_manager
    ]
    assert len(new_managers) == 1
    assert new_managers[0].manager_employment_id == manager
    assert new_managers[0].assignment_id == placed.id
