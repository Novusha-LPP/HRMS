"""Teams must stay attached to a department within their company."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hrms.core.ids import to_typed_id
from hrms.modules.org.models import OrgUnit
from hrms.modules.org.router import create_org_unit
from hrms.modules.org.schemas import OrgUnitCreate


@pytest.mark.parametrize("case", ["valid", "missing_parent", "team_parent", "other_company"])
async def test_team_department_relationship(case, monkeypatch):
    tid, company, parent_id = uuid4(), uuid4(), uuid4()
    parent = OrgUnit(
        tenant_id=tid,
        id=parent_id,
        name="Engineering",
        type="TEAM" if case == "team_parent" else "DEPARTMENT",
        legal_entity_id=uuid4() if case == "other_company" else company,
        effective_from=date.today(),
    )
    result = MagicMock()
    result.scalars.return_value.first.return_value = parent
    session = MagicMock(execute=AsyncMock(return_value=result), flush=AsyncMock())
    scope = MagicMock()
    scope.for_permission.return_value = scope
    scope.covers_entity.return_value = True
    audit = AsyncMock()
    monkeypatch.setattr("hrms.modules.org.router.record_change", audit)
    body = OrgUnitCreate(
        name="Platform",
        type="TEAM",
        code="PLAT",
        parent_id=None if case == "missing_parent" else to_typed_id("org_unit", parent_id),
        legal_entity_id=to_typed_id("legal_entity", company),
        effective_from=date.today(),
    )
    principal = SimpleNamespace(user_account_id=uuid4())
    if case == "valid":
        team = await create_org_unit(body, principal, tid, session, scope)
        assert team.type == "TEAM" and team.parent_id == body.parent_id
        assert team.legal_entity_id == body.legal_entity_id
        audit.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await create_org_unit(body, principal, tid, session, scope)
        assert error.value.status_code == 422
        session.add.assert_not_called()
