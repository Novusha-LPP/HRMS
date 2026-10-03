"""Shared definitions produce independent, scoped company departments."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from hrms.core.ids import to_typed_id, to_uuid
from hrms.modules.org.models import OrgUnit
from hrms.modules.org.router import assign_departments, create_org_unit, update_org_unit
from hrms.modules.org.schemas import AssignDepartmentsRequest, OrgUnitCreate, OrgUnitUpdate
from hrms.modules.people.router import _validate_assignment_references


def scope(all_scope=True, allowed=True):
    value = MagicMock()
    value.for_permission.return_value = value
    value.is_all = all_scope
    value.covers_entity.return_value = allowed
    return value


def result(row=None):
    value = MagicMock()
    value.scalars.return_value.first.return_value = row
    return value


async def test_same_shared_department_assigned_to_two_companies_is_independent(monkeypatch):
    tid, company_a, company_b = uuid4(), uuid4(), uuid4()
    template = OrgUnit(
        tenant_id=tid,
        id=uuid4(),
        name="Sales",
        code="SAL",
        type="DEPARTMENT_TEMPLATE",
        effective_from=date.today(),
    )
    monkeypatch.setattr("hrms.modules.org.router._get_org_unit", AsyncMock(return_value=template))
    monkeypatch.setattr("hrms.modules.org.router._get_legal_entity", AsyncMock())
    monkeypatch.setattr("hrms.modules.org.router.lock_resource", AsyncMock())
    monkeypatch.setattr("hrms.modules.org.router.record_change", AsyncMock())
    session = MagicMock(execute=AsyncMock(return_value=result()), flush=AsyncMock())
    principal = SimpleNamespace(user_account_id=uuid4())
    body = AssignDepartmentsRequest(department_ids=[to_typed_id("org_unit", template.id)])
    first = (
        await assign_departments(
            to_typed_id("legal_entity", company_a), body, principal, tid, session, scope()
        )
    )[0]
    second = (
        await assign_departments(
            to_typed_id("legal_entity", company_b), body, principal, tid, session, scope()
        )
    )[0]
    assert first.department_template_id == second.department_template_id == body.department_ids[0]
    assert first.id != second.id
    assert to_uuid(first.legal_entity_id) == company_a
    assert to_uuid(second.legal_entity_id) == company_b
    assert first.name == second.name == "Sales"
    session.execute.return_value = result(session.add.call_args_list[0].args[0])
    again = await assign_departments(first.legal_entity_id, body, principal, tid, session, scope())
    assert again[0].id == first.id
    assert session.add.call_count == 2


async def test_company_assignment_checks_permission_before_reads(monkeypatch):
    session = MagicMock()
    with pytest.raises(HTTPException) as error:
        await assign_departments(
            to_typed_id("legal_entity", uuid4()),
            AssignDepartmentsRequest(department_ids=["unused"]),
            SimpleNamespace(user_account_id=uuid4()),
            uuid4(),
            session,
            scope(False, False),
        )
    assert error.value.status_code == 403
    session.execute.assert_not_called()


async def test_shared_catalog_requires_group_scope():
    session = MagicMock()
    with pytest.raises(HTTPException) as error:
        await create_org_unit(
            OrgUnitCreate(name="Sales", type="DEPARTMENT_TEMPLATE", effective_from=date.today()),
            SimpleNamespace(user_account_id=uuid4()),
            uuid4(),
            session,
            scope(False),
        )
    assert error.value.status_code == 403
    session.add.assert_not_called()


async def test_catalog_edits_propagate_without_changing_company_assignment_ids(monkeypatch):
    tid, template_id = uuid4(), uuid4()
    template = OrgUnit(
        tenant_id=tid,
        id=template_id,
        name="Sales",
        type="DEPARTMENT_TEMPLATE",
        effective_from=date.today(),
    )
    departments = [
        OrgUnit(
            tenant_id=tid,
            id=uuid4(),
            name="Sales",
            type="DEPARTMENT",
            legal_entity_id=uuid4(),
            department_template_id=template_id,
            effective_from=date.today(),
        )
        for _ in range(2)
    ]
    ids = [d.id for d in departments]
    monkeypatch.setattr("hrms.modules.org.router._get_org_unit", AsyncMock(return_value=template))
    monkeypatch.setattr("hrms.modules.org.router.lock_resource", AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr("hrms.modules.org.router.record_change", audit)
    linked = MagicMock()
    linked.scalars.return_value = departments
    session = MagicMock(execute=AsyncMock(side_effect=[result(), linked]), flush=AsyncMock())
    await update_org_unit(
        to_typed_id("org_unit", template_id),
        OrgUnitUpdate(name="Business Development", code="BD"),
        SimpleNamespace(user_account_id=uuid4()),
        tid,
        session,
        scope(),
    )
    assert [d.id for d in departments] == ids
    assert all(d.name == "Business Development" and d.code == "BD" for d in departments)
    assert audit.await_count == 3


async def test_catalog_definition_cannot_be_used_as_employee_placement():
    reference = MagicMock()
    reference.mappings.return_value.first.return_value = {
        "type": "DEPARTMENT_TEMPLATE",
        "legal_entity_id": None,
        "archived_at": None,
    }
    session = MagicMock(execute=AsyncMock(return_value=reference))
    with pytest.raises(HTTPException) as error:
        await _validate_assignment_references(
            session,
            uuid4(),
            SimpleNamespace(legal_entity_id=uuid4()),
            {"org_unit_id": to_typed_id("org_unit", uuid4())},
            scope(),
        )
    assert error.value.status_code == 422


@pytest.mark.database
async def test_assign_shared_department_to_two_companies_api(api):
    from tests.helpers import ok, tenant

    client, _ = api
    login = await tenant(client)
    company_a = login["user"]["legal_entities"][0]["id"]
    company_b = (await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Company B"}))[
        "id"
    ]
    template = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Shared Sales",
            "type": "DEPARTMENT_TEMPLATE",
            "effective_from": date.today().isoformat(),
        },
    )
    assigned = []
    for company in [company_a, company_b]:
        path = f"/v1/org/legal-entities/{company}/departments"
        body = {"department_ids": [template["id"]]}
        row = (await ok(client, "POST", path, json=body))[0]
        assert (await ok(client, "POST", path, json=body))[0]["id"] == row["id"]
        assigned.append(row)
        team = await ok(
            client,
            "POST",
            "/v1/org/org-units",
            json={
                "name": "Local Team",
                "type": "TEAM",
                "parent_id": row["id"],
                "legal_entity_id": company,
                "effective_from": date.today().isoformat(),
            },
        )
        assert team["legal_entity_id"] == company
    assert assigned[0]["id"] != assigned[1]["id"]
    await ok(client, "PATCH", f"/v1/org/org-units/{template['id']}", json={"name": "Renamed Sales"})
    units = await ok(client, "GET", "/v1/org/org-units")
    assert all(
        u["name"] == "Renamed Sales" for u in units if u["department_template_id"] == template["id"]
    )
