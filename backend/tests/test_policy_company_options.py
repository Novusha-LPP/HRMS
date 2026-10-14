"""Regression checks for leave archiving and company anniversary dates."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hrms.core.ids import to_typed_id
from hrms.modules.leave.models import LeaveType
from hrms.modules.leave.router import remove_leave_type
from hrms.modules.org.models import LegalEntity
from hrms.modules.org.router import _le_fields, _le_response
from hrms.modules.org.schemas import LegalEntityCreate, LegalEntityUpdate


@pytest.mark.parametrize(
    "comp_off,archived,expected", [(False, False, None), (True, False, 409), (False, True, 404)]
)
async def test_remove_preserves_row_and_protects_system_type(comp_off, archived, expected):
    from hrms.core.datetime_utils import now_utc

    tid = uuid4()
    lt = LeaveType(
        tenant_id=tid,
        id=uuid4(),
        name="Casual",
        code="CL",
        is_comp_off=comp_off,
        archived_at=now_utc() if archived else None,
    )
    result = MagicMock()
    result.scalars.return_value.first.return_value = lt
    session = MagicMock(
        execute=AsyncMock(return_value=result), flush=AsyncMock(), refresh=AsyncMock()
    )
    if expected:
        with pytest.raises(HTTPException) as error:
            await remove_leave_type(to_typed_id("leave_type", lt.id), tid, session)
        assert error.value.status_code == expected
        session.add.assert_not_called()
    else:
        await remove_leave_type(to_typed_id("leave_type", lt.id), tid, session)
        assert lt.archived_at is not None
        assert not lt.is_active
        session.add.assert_called_once_with(lt)
        session.delete.assert_not_called()


def test_establishment_date_round_trip_and_clear():
    body = LegalEntityCreate(name="Company", establishment_date="2000-10-03")
    entity = LegalEntity(tenant_id=uuid4(), id=uuid4(), **body.model_dump())
    assert _le_response(entity).establishment_date == date(2000, 10, 3)
    assert _le_fields(entity)["establishment_date"] == date(2000, 10, 3)
    assert LegalEntityUpdate(establishment_date=None).model_dump(exclude_unset=True) == {
        "establishment_date": None
    }
    assert "establishment_date" not in LegalEntityUpdate(name="Rename").model_dump(
        exclude_unset=True
    )


@pytest.mark.database
async def test_company_date_is_audited_and_celebrated_on_dashboard(api):
    from hrms.core.datetime_utils import business_today
    from tests.helpers import ok, tenant

    client, _ = api
    await tenant(client)
    company = (await ok(client, "GET", "/v1/org/legal-entities"))[0]
    today = business_today()
    established = today.replace(year=today.year - 4).isoformat()
    path = f"/v1/org/legal-entities/{company['id']}"
    updated = await ok(client, "PATCH", path, json={"establishment_date": established})
    assert updated["establishment_date"] == established
    history = await ok(client, "GET", path + "/history")
    assert history[0]["changes"]["establishment_date"] == {"old": None, "new": established}
    dashboard = await ok(client, "GET", "/v1/dashboard/hr?sections=highlights_today")
    celebrations = dashboard["highlights_today"]["company_anniversaries"]
    assert [(c["name"], c["years"]) for c in celebrations] == [(company["name"], 4)]
    await ok(client, "PATCH", path, json={"establishment_date": None})
    dashboard = await ok(client, "GET", "/v1/dashboard/hr?sections=highlights_today")
    assert dashboard["highlights_today"]["company_anniversaries"] == []


async def test_restore_reuses_existing_type_and_rejects_second_restore():
    from hrms.core.datetime_utils import now_utc
    from hrms.modules.leave.router import restore_leave_type

    tid = uuid4()
    lt = LeaveType(
        tenant_id=tid,
        id=uuid4(),
        name="Casual",
        code="CL",
        days_per_year=12,
        archived_at=now_utc(),
        is_active=False,
    )
    result = MagicMock()
    result.scalars.return_value.first.return_value = lt
    session = MagicMock(
        execute=AsyncMock(return_value=result), flush=AsyncMock(), refresh=AsyncMock()
    )
    identifier = to_typed_id("leave_type", lt.id)
    restored = await restore_leave_type(identifier, tid, session)
    assert restored.id == identifier
    assert lt.is_active and lt.archived_at is None
    with pytest.raises(HTTPException) as error:
        await restore_leave_type(identifier, tid, session)
    assert error.value.status_code == 409


async def test_edit_updates_details_but_requires_restore_for_archived_type():
    from hrms.core.datetime_utils import now_utc
    from hrms.modules.leave.router import update_leave_type
    from hrms.modules.leave.schemas import LeaveTypeUpdate

    tid = uuid4()
    lt = LeaveType(tenant_id=tid, id=uuid4(), name="Casual", code="CL")
    result = MagicMock()
    result.scalars.return_value.first.return_value = lt
    session = MagicMock(
        execute=AsyncMock(return_value=result), flush=AsyncMock(), refresh=AsyncMock()
    )
    identifier = to_typed_id("leave_type", lt.id)
    body = LeaveTypeUpdate(name="Annual", code="AL", days_per_year=18, is_paid=False)
    edited = await update_leave_type(identifier, body, tid, session)
    assert (edited.name, edited.code, edited.days_per_year, edited.is_paid) == (
        "Annual",
        "AL",
        18,
        False,
    )
    lt.archived_at = now_utc()
    with pytest.raises(HTTPException) as error:
        await update_leave_type(identifier, body, tid, session)
    assert error.value.status_code == 409
