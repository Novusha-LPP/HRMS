"""Independent employee routes and resolved role snapshots retain approval safeguards."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hrms.core.ids import to_typed_id
from hrms.modules.approvals import service
from hrms.modules.approvals.schemas import FlowWrite, StepSpec
from hrms.modules.org.router import _team_roles


def result(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    r.all.return_value = values
    return r


def test_target_and_stage_validation():
    with pytest.raises(ValidationError):
        FlowWrite(
            name="Invalid",
            request_type="LEAVE",
            org_unit_id="team",
            employment_id="person",
            steps=[StepSpec(name="Review", approver_ids=["user"])],
        )
    with pytest.raises(ValidationError):
        StepSpec(name="Review")
    with pytest.raises(ValidationError):
        StepSpec(name="Lead", approver_source="TEAM_LEAD", approver_ids=["user"])
    assert StepSpec(name="PM first", approver_source="TEAM_PM").approver_ids == []


async def test_role_snapshot_uses_selected_order(monkeypatch):
    tid, employee, pm, lead = (uuid4() for _ in range(4))
    flow = SimpleNamespace(
        steps=[
            dict(id=str(uuid4()), name="PM", approver_source="TEAM_PM", approver_ids=[]),
            dict(id=str(uuid4()), name="Lead", approver_source="TEAM_LEAD", approver_ids=[]),
        ]
    )
    session = SimpleNamespace(execute=AsyncMock(side_effect=[result([pm]), result([lead])]))
    steps = await service.resolved_steps(session, tid, employee, flow)
    assert [s["approver_ids"] for s in steps] == [[str(pm)], [str(lead)]]
    assert all(s["approver_ids"] == [] for s in flow.steps)
    assert "team.pm_employment_id" in str(session.execute.call_args_list[0].args[0])
    assert "team.lead_employment_id" in str(session.execute.call_args_list[1].args[0])


async def test_unassigned_role_blocks_submission():
    session = SimpleNamespace(execute=AsyncMock(return_value=result([])))
    with pytest.raises(HTTPException) as error:
        await service.resolved_steps(
            session,
            uuid4(),
            uuid4(),
            SimpleNamespace(
                steps=[dict(name="Lead", approver_source="TEAM_LEAD", approver_ids=[])]
            ),
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize("case", ["valid", "self", "duplicate"])
async def test_start_role_self_and_repeated_person_protection(case, monkeypatch):
    tid, employee, approver, approver_employee = (uuid4() for _ in range(4))
    step = dict(id=str(uuid4()), name="Review", approver_ids=[str(approver)])
    flow = SimpleNamespace(id=uuid4(), version=1, steps=[step])
    monkeypatch.setattr(service, "resolve_flow", AsyncMock(return_value=flow))
    monkeypatch.setattr(service, "current_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "resolved_steps",
        AsyncMock(return_value=[step, step] if case == "duplicate" else [step]),
    )
    session = MagicMock(
        execute=AsyncMock(
            return_value=result([(approver, employee if case == "self" else approver_employee)])
        ),
        flush=AsyncMock(),
    )
    # "Self" is decided by person: the approver's login belongs to the requester's person.
    requester_person, approver_person = uuid4(), uuid4()
    monkeypatch.setattr(
        service,
        "people_of_accounts",
        AsyncMock(return_value={approver: requester_person if case == "self" else approver_person}),
    )
    monkeypatch.setattr(service, "person_of_employment", AsyncMock(return_value=requester_person))
    if case == "valid":
        instance = await service.start(session, tid, "LEAVE", uuid4(), employee)
        assert instance.steps == [step]
        assert instance.flow_id == flow.id
    else:
        with pytest.raises(HTTPException) as error:
            await service.start(session, tid, "LEAVE", uuid4(), employee)
        assert error.value.status_code == 409
        session.add.assert_not_called()


async def test_team_role_rejects_wrong_company_or_nonteam():
    row = MagicMock()
    row.first.return_value = None
    session = SimpleNamespace(execute=AsyncMock(return_value=row))
    for kind in ("TEAM", "DEPARTMENT"):
        with pytest.raises(HTTPException) as error:
            await _team_roles(session, uuid4(), kind, uuid4(), {"lead_employment_id": str(uuid4())})
        assert error.value.status_code == 422


async def check_routing_on_temporary_tables(connection):
    """Exercise PostgreSQL resolution without changing real HRMS records."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    for table in ("approval_flows", "org_units", "assignments", "employee_approval_flows"):
        await connection.execute(
            text(
                f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
        )
    tid, dept, team_a, team_b, worker_a, worker_b, lead = (uuid4() for _ in range(7))
    ids = {name: uuid4() for name in ("default", "department", "a", "b", "lead")}
    for uid, parent, kind in [
        (dept, None, "DEPARTMENT"),
        (team_a, dept, "TEAM"),
        (team_b, dept, "TEAM"),
    ]:
        await connection.execute(
            text("""
            INSERT INTO org_units (tenant_id,id,name,type,parent_id,effective_from,status)
            VALUES (:tid,:id,'Fixture',:kind,:parent,'2020-01-01','ACTIVE')
        """),
            dict(tid=tid, id=uid, kind=kind, parent=parent),
        )
    for employee, unit in [(worker_a, team_a), (worker_b, team_b), (lead, team_a)]:
        await connection.execute(
            text("""
            INSERT INTO assignments
            (tenant_id,id,employment_id,org_unit_id,job_id,location_id,effective_from)
            VALUES (:tid,:id,:employee,:unit,:job,:location,'2020-01-01')
        """),
            dict(tid=tid, id=uuid4(), employee=employee, unit=unit, job=uuid4(), location=uuid4()),
        )
    for name, unit, employee in [
        ("default", None, None),
        ("department", dept, None),
        ("a", team_a, None),
        ("b", team_b, None),
        ("lead", None, lead),
    ]:
        await connection.execute(
            text("""
            INSERT INTO approval_flows
            (tenant_id,id,name,request_type,org_unit_id,employment_id,steps,updated_by,
             enabled,version,updated_at)
            VALUES (:tid,:id,:name,'LEAVE',:unit,:employee,'[]',:actor,true,1,now())
        """),
            dict(tid=tid, id=ids[name], name=name, unit=unit, employee=employee, actor=uuid4()),
        )
    for employee, name in [(worker_a, "a"), (worker_b, "b"), (lead, "lead")]:
        await connection.execute(
            text("""
            INSERT INTO employee_approval_flows
              (tenant_id,employment_id,request_type,flow_id,version,updated_by,updated_at)
            VALUES (:tid,:eid,'LEAVE',:flow,1,:actor,now())
        """),
            dict(tid=tid, eid=employee, flow=ids[name], actor=uuid4()),
        )
    async with AsyncSession(bind=connection, expire_on_commit=False) as session:

        async def expect(employee, name):
            actual = await service.resolve_flow(session, tid, employee, "LEAVE")
            assert actual.id == ids[name]

        await expect(worker_a, "a")
        await expect(worker_b, "b")
        await expect(lead, "lead")
        assert await service.resolve_flow(session, uuid4(), worker_a, "LEAVE") is None
        assert await service.resolve_flow(session, tid, worker_a, "OVERTIME") is None
        await connection.execute(
            text("UPDATE assignments SET org_unit_id=:unit WHERE employment_id=:eid"),
            dict(unit=team_b, eid=worker_a),
        )
        await expect(worker_a, "a")
        await connection.execute(
            text("UPDATE employee_approval_flows SET flow_id=:flow WHERE employment_id=:eid"),
            dict(flow=ids["a"], eid=worker_b),
        )
        await expect(worker_b, "a")
        await connection.execute(
            text("UPDATE approval_flows SET enabled=false WHERE id=:id"), dict(id=ids["a"])
        )
        with pytest.raises(HTTPException) as error:
            await service.resolve_flow(session, tid, worker_a, "LEAVE")
        assert error.value.status_code == 409
        await connection.execute(
            text("UPDATE employee_approval_flows SET flow_id=NULL WHERE employment_id=:eid"),
            dict(eid=worker_a),
        )
        assert await service.resolve_flow(session, tid, worker_a, "LEAVE") is None
        await expect(lead, "lead")


@pytest.mark.database
async def test_postgres_routing(api):
    _, engine = api
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await check_routing_on_temporary_tables(connection)
        finally:
            await transaction.rollback()


def owner_scope(own, *, admin=False, employees=(), units=()):
    from hrms.core.authz import Scope

    return Scope(
        is_all=admin,
        legal_entity_ids=frozenset(),
        employment_ids=frozenset(employees),
        permissions=frozenset(
            {"approvals.manage", "approvals.admin"} if admin else {"approvals.manage"}
        ),
        own_employment_id=own,
        role_names=frozenset({"HR_MANAGER"} if admin else {"MANAGER"}),
        org_unit_ids=frozenset(units),
    )


@pytest.mark.parametrize("individual", [True, False])
async def test_leader_cannot_manage_individual_or_group_default(individual):
    session = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await service.authorize_flow(
            session,
            uuid4(),
            owner_scope(uuid4()),
            SimpleNamespace(org_unit_id=None, employment_id=uuid4() if individual else None),
        )
    assert error.value.status_code == 403
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("role", ["lead", "pm", "hod", "unrelated", "partial"])
async def test_team_workflow_ownership(role):
    from datetime import date

    from hrms.modules.org.models import OrgUnit

    tid, own, worker, other = (uuid4() for _ in range(4))
    unit = OrgUnit(
        tenant_id=tid,
        id=uuid4(),
        name="Team",
        type="TEAM",
        effective_from=date.today(),
        lead_employment_id=own if role == "lead" else other,
        pm_employment_id=own if role == "pm" else other,
    )
    first = MagicMock()
    first.scalars.return_value.first.return_value = unit
    session = SimpleNamespace(execute=AsyncMock(side_effect=[first, result([own, worker, other])]))
    reports = (
        [own, worker, other] if role == "hod" else [own, worker] if role == "partial" else [own]
    )
    scope = owner_scope(own, employees=reports)
    flow = SimpleNamespace(org_unit_id=unit.id, employment_id=None)
    if role in ("lead", "pm", "hod"):
        await service.authorize_flow(session, tid, scope, flow)
    else:
        with pytest.raises(HTTPException) as error:
            await service.authorize_flow(session, tid, scope, flow)
        assert error.value.status_code == 403


async def test_hr_can_manage_individual_route():
    employee = uuid4()
    row = MagicMock()
    row.first.return_value = (employee,)
    session = SimpleNamespace(execute=AsyncMock(return_value=row))
    await service.authorize_flow(
        session,
        uuid4(),
        owner_scope(uuid4(), admin=True),
        SimpleNamespace(org_unit_id=None, employment_id=employee),
    )


async def test_assigned_hod_can_manage_empty_department_team():
    from datetime import date

    from hrms.modules.org.models import OrgUnit

    tid, own, department = uuid4(), uuid4(), uuid4()
    team = OrgUnit(
        tenant_id=tid,
        id=uuid4(),
        name="New team",
        type="TEAM",
        parent_id=department,
        effective_from=date.today(),
    )
    first = MagicMock()
    first.scalars.return_value.first.return_value = team
    parent = MagicMock()
    parent.scalar.return_value = own
    session = SimpleNamespace(execute=AsyncMock(side_effect=[first, parent]))
    await service.authorize_flow(
        session, tid, owner_scope(own), SimpleNamespace(org_unit_id=team.id, employment_id=None)
    )
    assert session.execute.await_count == 2


def test_reusable_workflows_do_not_accept_implicit_team_roles():
    with pytest.raises(ValidationError):
        FlowWrite(
            name="Independent",
            request_type="LEAVE",
            steps=[StepSpec(name="Lead", approver_source="TEAM_LEAD")],
        )


@pytest.mark.parametrize("case", ["creator", "other_manager", "hr"])
async def test_reusable_workflow_ownership(case):
    own, company = uuid4(), uuid4()
    scope = owner_scope(own, admin=case == "hr")
    flow = SimpleNamespace(
        reusable=True,
        owner_employment_id=own if case == "creator" else uuid4(),
        legal_entity_id=company,
    )
    if case == "other_manager":
        with pytest.raises(HTTPException) as error:
            await service.authorize_flow(SimpleNamespace(), uuid4(), scope, flow)
        assert error.value.status_code == 403
    else:
        await service.authorize_flow(SimpleNamespace(), uuid4(), scope, flow)


async def test_employee_selection_rejects_stale_version(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import EmployeeFlowWrite

    monkeypatch.setattr(service, "authorize_employee_assignment", AsyncMock())
    monkeypatch.setattr(router, "lock_resource", AsyncMock())
    first = MagicMock()
    first.scalars.return_value.first.return_value = SimpleNamespace(version=2)
    session = MagicMock(execute=AsyncMock(return_value=first))
    with pytest.raises(HTTPException) as error:
        await router.assign_employee_flow(
            to_typed_id("employment", uuid4()),
            "LEAVE",
            EmployeeFlowWrite(flow_id=None, version=1),
            uuid4(),
            session,
            owner_scope(uuid4(), admin=True),
            SimpleNamespace(),
        )
    assert error.value.status_code == 409
    session.add.assert_not_called()


async def test_employee_selection_rejects_self_only_approval_stage(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import EmployeeFlowWrite

    tid, eid, company, account = (uuid4() for _ in range(4))
    first = MagicMock()
    first.scalars.return_value.first.return_value = None
    exists = MagicMock()
    exists.scalar.return_value = eid
    entity = MagicMock()
    entity.scalar.return_value = company
    flow = SimpleNamespace(
        reusable=True,
        enabled=True,
        request_type="LEAVE",
        legal_entity_id=company,
        steps=[dict(name="Review", approver_ids=[str(account)])],
    )
    monkeypatch.setattr(service, "authorize_employee_assignment", AsyncMock())
    monkeypatch.setattr(service, "visible_template", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service, "active_account", AsyncMock(return_value=SimpleNamespace(employment_id=eid))
    )
    monkeypatch.setattr(router, "lock_resource", AsyncMock())
    monkeypatch.setattr(router, "flow_get", AsyncMock(return_value=flow))
    session = MagicMock(execute=AsyncMock(side_effect=[first, exists, entity]))
    with pytest.raises(HTTPException) as error:
        await router.assign_employee_flow(
            to_typed_id("employment", eid),
            "LEAVE",
            EmployeeFlowWrite(flow_id=to_typed_id("approval_flow", uuid4()), version=0),
            tid,
            session,
            owner_scope(uuid4(), admin=True),
            SimpleNamespace(),
        )
    assert error.value.status_code == 422
    session.add.assert_not_called()


async def test_employee_selection_allows_global_workflow(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import EmployeeFlowWrite

    tid, eid, company_a, approver_emp, approver_acc = (uuid4() for _ in range(5))
    first = MagicMock()
    first.scalars.return_value.first.return_value = None
    exists = MagicMock()
    exists.scalar.return_value = eid
    entity = MagicMock()
    entity.scalar.return_value = company_a
    flow = SimpleNamespace(
        id=uuid4(),
        reusable=True,
        enabled=True,
        request_type="LEAVE",
        legal_entity_id=None,  # Global workflow
        steps=[dict(name="Manager Approval", approver_ids=[str(approver_acc)])],
    )
    monkeypatch.setattr(service, "authorize_employee_assignment", AsyncMock())
    monkeypatch.setattr(service, "visible_template", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "active_account",
        AsyncMock(return_value=SimpleNamespace(employment_id=approver_emp)),
    )
    monkeypatch.setattr(router, "lock_resource", AsyncMock())
    monkeypatch.setattr(router, "flow_get", AsyncMock(return_value=flow))
    monkeypatch.setattr(service, "event", AsyncMock())
    monkeypatch.setattr(router, "employee_flows", AsyncMock(return_value={"assignments": []}))
    session = MagicMock(
        execute=AsyncMock(side_effect=[first, exists, entity]), flush=AsyncMock()
    )

    await router.assign_employee_flow(
        to_typed_id("employment", eid),
        "LEAVE",
        EmployeeFlowWrite(flow_id=to_typed_id("approval_flow", flow.id), version=0),
        tid,
        session,
        owner_scope(uuid4(), admin=True),
        SimpleNamespace(user_account_id=uuid4()),
    )
    session.add.assert_called_once()
    saved = session.add.call_args[0][0]
    assert saved.flow_id == flow.id
    assert saved.employment_id == eid


async def test_employee_selection_rejects_different_company_workflow(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import EmployeeFlowWrite

    tid, eid, company_a, company_b, approver_emp, approver_acc = (uuid4() for _ in range(6))
    first = MagicMock()
    first.scalars.return_value.first.return_value = None
    exists = MagicMock()
    exists.scalar.return_value = eid
    entity = MagicMock()
    entity.scalar.return_value = company_a  # Employee is in Company A
    flow = SimpleNamespace(
        id=uuid4(),
        reusable=True,
        enabled=True,
        request_type="LEAVE",
        legal_entity_id=company_b,  # Workflow is restricted to Company B
        steps=[dict(name="Manager Approval", approver_ids=[str(approver_acc)])],
    )
    monkeypatch.setattr(service, "authorize_employee_assignment", AsyncMock())
    monkeypatch.setattr(service, "visible_template", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "active_account",
        AsyncMock(return_value=SimpleNamespace(employment_id=approver_emp)),
    )
    monkeypatch.setattr(router, "lock_resource", AsyncMock())
    monkeypatch.setattr(router, "flow_get", AsyncMock(return_value=flow))
    session = MagicMock(execute=AsyncMock(side_effect=[first, exists, entity]))

    with pytest.raises(HTTPException) as error:
        await router.assign_employee_flow(
            to_typed_id("employment", eid),
            "LEAVE",
            EmployeeFlowWrite(flow_id=to_typed_id("approval_flow", flow.id), version=0),
            tid,
            session,
            owner_scope(uuid4(), admin=True),
            SimpleNamespace(user_account_id=uuid4()),
        )
    assert error.value.status_code == 422
    assert "restricted to a different company" in error.value.detail


async def test_employee_selection_accepts_same_company_workflow(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import EmployeeFlowWrite

    tid, eid, company_a, approver_emp, approver_acc = (uuid4() for _ in range(5))
    first = MagicMock()
    first.scalars.return_value.first.return_value = None
    exists = MagicMock()
    exists.scalar.return_value = eid
    entity = MagicMock()
    entity.scalar.return_value = company_a
    flow = SimpleNamespace(
        id=uuid4(),
        reusable=True,
        enabled=True,
        request_type="LEAVE",
        legal_entity_id=company_a,  # Workflow is restricted to Company A
        steps=[dict(name="Manager Approval", approver_ids=[str(approver_acc)])],
    )
    monkeypatch.setattr(service, "authorize_employee_assignment", AsyncMock())
    monkeypatch.setattr(service, "visible_template", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "active_account",
        AsyncMock(return_value=SimpleNamespace(employment_id=approver_emp)),
    )
    monkeypatch.setattr(router, "lock_resource", AsyncMock())
    monkeypatch.setattr(router, "flow_get", AsyncMock(return_value=flow))
    monkeypatch.setattr(service, "event", AsyncMock())
    monkeypatch.setattr(router, "employee_flows", AsyncMock(return_value={"assignments": []}))
    session = MagicMock(
        execute=AsyncMock(side_effect=[first, exists, entity]), flush=AsyncMock()
    )

    await router.assign_employee_flow(
        to_typed_id("employment", eid),
        "LEAVE",
        EmployeeFlowWrite(flow_id=to_typed_id("approval_flow", flow.id), version=0),
        tid,
        session,
        owner_scope(uuid4(), admin=True),
        SimpleNamespace(user_account_id=uuid4()),
    )
    session.add.assert_called_once()
    saved = session.add.call_args[0][0]
    assert saved.flow_id == flow.id
    assert saved.employment_id == eid


async def test_create_reusable_flow_is_global_by_group_admin(monkeypatch):
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import FlowWrite, StepSpec

    tid, creator_emp = uuid4(), uuid4()
    body = FlowWrite(
        name="Global Leave Flow",
        request_type="LEAVE",
        reusable=True,
        legal_entity_id=None,
        steps=[StepSpec(name="Approval", approver_ids=[to_typed_id("user_account", uuid4())])],
    )
    monkeypatch.setattr(router, "write_flow", AsyncMock(return_value={"id": "app_123"}))
    principal = SimpleNamespace(employment_id=creator_emp, user_account_id=uuid4())
    scope = owner_scope(creator_emp, admin=True)
    session = AsyncMock()

    await router.create_flow(body, principal, scope, tid, session)
    call_args = router.write_flow.call_args[0]
    created_flow = call_args[1]
    assert created_flow.reusable is True
    assert created_flow.legal_entity_id is None


async def test_create_reusable_flow_scoped_admin(monkeypatch):
    from hrms.core.authz import Scope
    from hrms.modules.approvals import router
    from hrms.modules.approvals.schemas import FlowWrite, StepSpec

    tid, creator_emp, company_a = uuid4(), uuid4(), uuid4()
    body = FlowWrite(
        name="Company A Flow",
        request_type="LEAVE",
        reusable=True,
        legal_entity_id=to_typed_id("legal_entity", company_a),
        steps=[StepSpec(name="Approval", approver_ids=[to_typed_id("user_account", uuid4())])],
    )
    monkeypatch.setattr(router, "write_flow", AsyncMock(return_value={"id": "app_123"}))
    principal = SimpleNamespace(employment_id=creator_emp, user_account_id=uuid4())
    scope = Scope(
        is_all=False,
        legal_entity_ids=frozenset({company_a}),
        employment_ids=frozenset(),
        permissions=frozenset({"approvals.manage", "approvals.admin"}),
        own_employment_id=creator_emp,
        role_names=frozenset({"HR_MANAGER"}),
        org_unit_ids=frozenset(),
    )
    session = AsyncMock()

    await router.create_flow(body, principal, scope, tid, session)
    call_args = router.write_flow.call_args[0]
    created_flow = call_args[1]
    assert created_flow.reusable is True
    assert created_flow.legal_entity_id == company_a

