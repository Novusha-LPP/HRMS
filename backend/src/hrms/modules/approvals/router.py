"""No-code approval configuration, inbox, decisions and temporary delegation."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from sqlalchemy import exists, or_, text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.approvals import policy_corrections, service
from hrms.modules.approvals.models import (
    ApprovalDelegation,
    ApprovalEvent,
    ApprovalFlow,
    ApprovalInstance,
    EmployeeApprovalFlow,
)
from hrms.modules.approvals.schemas import (
    Decision,
    DelegationWrite,
    EmployeeFlowWrite,
    FlowWrite,
    RequestType,
)
from hrms.modules.kernel.models import UserAccount

router = APIRouter(prefix="/v1/approvals", tags=["Approval workflows"])


def steps_public(steps):
    return [
        {
            **s,
            "id": to_typed_id("approval_step", UUID(s["id"])),
            "approver_ids": [to_typed_id("user", UUID(uid)) for uid in s["approver_ids"]],
        }
        for s in steps
    ]


def flow_public(flow):
    return dict(
        id=to_typed_id("approval_flow", flow.id),
        name=flow.name,
        request_type=flow.request_type,
        org_unit_id=to_typed_id("org_unit", flow.org_unit_id) if flow.org_unit_id else None,
        employment_id=to_typed_id("employment", flow.employment_id) if flow.employment_id else None,
        reusable=flow.reusable,
        enabled=flow.enabled,
        steps=steps_public(flow.steps),
        version=flow.version,
        updated_at=flow.updated_at,
    )


async def flow_get(session, tenant_id, uid, lock=False):
    query = select(ApprovalFlow).where(ApprovalFlow.tenant_id == tenant_id, ApprovalFlow.id == uid)
    if lock:
        query = query.with_for_update()
    flow = (await session.execute(query)).scalars().first()
    if flow is None:
        raise HTTPException(404, "Approval flow not found")
    return flow


async def instance_get(session, tenant_id, uid, lock=False):
    query = select(ApprovalInstance).where(
        ApprovalInstance.tenant_id == tenant_id, ApprovalInstance.id == uid
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    instance = (await session.execute(query)).scalars().first()
    if instance is None:
        raise HTTPException(404, "Approval request not found")
    return instance


async def may_view(session, tenant_id, scope, principal, instance):
    if principal.employment_id == instance.employment_id or any(
        str(principal.user_account_id) in step["approver_ids"] for step in instance.steps
    ):
        return True
    flow = await flow_get(session, tenant_id, instance.flow_id)
    if await service.manages_request(session, tenant_id, scope, flow, instance.employment_id):
        return True
    for step in instance.steps:
        if any(
            d.delegate_user_id == principal.user_account_id
            for d in await service.live_delegations(session, tenant_id, instance, step)
        ):
            return True
    return False


async def instance_public(session, tenant_id, scope, principal, instance):
    flow = await flow_get(session, tenant_id, instance.flow_id)
    management = await service.manages_request(
        session, tenant_id, scope, flow, instance.employment_id
    )
    can_act = False
    try:
        await service.actor_for(session, tenant_id, instance, principal)
        can_act = True
    except HTTPException as exc:
        if exc.status_code not in (403, 409, 422):
            raise
    account = str(principal.user_account_id)
    upper_levels = [i + 1 for i, s in enumerate(instance.steps) if account in s["approver_ids"]]
    delegable = [
        i + 1
        for i in range(len(instance.steps))
        if i + 1 >= instance.current_level and (management or any(j > i + 1 for j in upper_levels))
    ]
    person = (
        (
            await session.execute(
                text("""
        SELECT e.employee_number,p.legal_first_name || ' ' || p.legal_last_name AS employee_name
        FROM employments e JOIN persons p ON p.tenant_id=e.tenant_id AND p.id=e.person_id
        WHERE e.tenant_id=:tid AND e.id=:eid
    """),
                dict(tid=tenant_id, eid=instance.employment_id),
            )
        )
        .mappings()
        .one()
    )
    if instance.request_type in ("LEAVE", "LEAVE_CANCELLATION"):
        query = (
            "SELECT from_date,to_date,reason,cancel_reason,days_requested FROM leave_applications"
        )
    elif instance.request_type == "CORRECTION":
        query = (
            "SELECT work_date,correction_type,requested_punch_in,requested_punch_out,reason "
            "FROM attendance_correction_requests"
        )
    elif instance.request_type == "FIELD_OVERRIDE":
        query = (
            "SELECT type AS action_type,effective_date,changes,status AS action_status "
            "FROM personnel_actions"
        )
    elif instance.request_type == "JOB_REQUISITION":
        query = (
            "SELECT code,title,positions,priority,employment_type,work_mode,target_start_date,"
            "status AS opening_status FROM job_openings"
        )
    else:
        query = (
            "SELECT work_date,first_punch_in,last_punch_out,effective_minutes,ot_minutes,ot_status "
            "FROM attendance_days"
        )
    payload = (
        (
            await session.execute(
                text(query + " WHERE tenant_id=:tid AND id=:rid"),
                dict(tid=tenant_id, rid=instance.request_id),
            )
        )
        .mappings()
        .one()
    )
    if instance.request_type in ("OVERTIME", "FIELD_OVERRIDE"):
        snapshot = (
            (
                await session.execute(
                    select(ApprovalEvent).where(
                        ApprovalEvent.tenant_id == tenant_id,
                        ApprovalEvent.instance_id == instance.id,
                        ApprovalEvent.action == "SUBMITTED",
                    )
                )
            )
            .scalars()
            .first()
        )
        if snapshot:
            payload = (
                {**dict(payload), **snapshot.details["request"]}
                if instance.request_type == "FIELD_OVERRIDE"
                else snapshot.details["request"]
            )
    return dict(
        approval_mode="FLOW",
        employee_name=person["employee_name"],
        employee_number=person["employee_number"],
        request=dict(payload),
        id=to_typed_id("approval_instance", instance.id),
        flow_id=to_typed_id("approval_flow", flow.id),
        flow_name=flow.name,
        flow_version=instance.flow_version,
        request_type=instance.request_type,
        request_id=to_typed_id(
            {
                "LEAVE": "leave_application",
                "LEAVE_CANCELLATION": "leave_application",
                "CORRECTION": "attendance_correction",
                "OVERTIME": "attendance_day",
                "JOB_REQUISITION": "job_opening",
                "FIELD_OVERRIDE": "personnel_action",
            }[instance.request_type],
            instance.request_id,
        ),
        employment_id=to_typed_id("employment", instance.employment_id),
        steps=steps_public(instance.steps),
        current_level=instance.current_level,
        status=instance.status,
        can_act=can_act,
        delegable_levels=delegable if instance.status == "PENDING" else [],
        can_manage_flow=management,
        created_at=instance.created_at,
    )


@router.get("/flows")
async def flows(tenant_id: TenantDep, session: SessionDep, scope: ScopeDep):
    scope.require("approvals.manage")
    rows = (
        await session.execute(
            select(ApprovalFlow)
            .where(ApprovalFlow.tenant_id == tenant_id, ApprovalFlow.reusable == True)  # noqa: E712
            .order_by(col(ApprovalFlow.name))
        )
    ).scalars()
    return [
        {**flow_public(f), "can_manage": await service.manages(session, tenant_id, scope, f)}
        for f in rows
        if await service.visible_template(session, tenant_id, scope, f)
    ]


@router.get("/directory")
async def directory(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
    instance_id: str | None = None,
):
    if instance_id:
        instance = await instance_get(session, tenant_id, to_uuid(instance_id))
        public = await instance_public(session, tenant_id, scope, principal, instance)
        if not public["delegable_levels"]:
            raise HTTPException(403, "Only an authorized upper level may choose delegates")
    else:
        scope.require("approvals.manage")
    rows = (
        await session.execute(
            text("""
        SELECT ua.id, ua.email, ua.employment_id, p.legal_first_name, p.legal_last_name
        FROM user_accounts ua
        LEFT JOIN employments e ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
        LEFT JOIN persons p ON p.tenant_id=e.tenant_id AND p.id=e.person_id
        WHERE ua.tenant_id=:tid AND ua.status='ACTIVE'
          AND (ua.employment_id IS NULL OR (e.archived_at IS NULL
               AND e.employment_state <> 'SEPARATED'))
        ORDER BY p.legal_first_name, p.legal_last_name, ua.email, ua.id
    """),
            dict(tid=tenant_id),
        )
    ).mappings()
    return [
        dict(
            id=to_typed_id("user", row["id"]),
            employment_id=to_typed_id("employment", row["employment_id"])
            if row["employment_id"]
            else None,
            name=" · ".join(
                part
                for part in (
                    " ".join(p for p in (row["legal_first_name"], row["legal_last_name"]) if p),
                    row["email"] or to_typed_id("user", row["id"]),
                )
                if part
            ),
        )
        for row in rows
    ]


async def write_flow(body, flow, principal, scope, tenant_id, session):
    await service.authorize_flow(session, tenant_id, scope, flow)
    steps: list[dict] = []
    seen = set()
    employee_levels: dict[UUID, int] = {}
    requester = await service.person_of_employment(session, tenant_id, flow.employment_id)
    previous_ids = {s["id"] for s in flow.steps}
    sources = set()
    for level, step in enumerate(body.steps):
        if step.approver_source != "PEOPLE":
            if step.approver_source in sources:
                raise HTTPException(422, "A team role can appear only once in a chain")
            sources.add(step.approver_source)
        ids = []
        for typed in step.approver_ids:
            if not typed.startswith("usr_"):
                raise HTTPException(422, "Use account identifiers for approvers")
            uid = to_uuid(typed)
            account = await service.active_account(session, tenant_id, uid)
            if requester and account.person_id == requester:
                raise HTTPException(
                    422, "An individual workflow cannot include its requester as approver"
                )
            if uid in seen:
                raise HTTPException(422, "An account can appear only once in an approval chain")
            seen.add(uid)
            if account.person_id:
                # Keyed by person: one person's logins for different employments count as one.
                previous_level = employee_levels.setdefault(account.person_id, level)
                if previous_level != level:
                    raise HTTPException(422, "A person can appear only at one approval level")
            ids.append(str(uid))
        sid = str(to_uuid(step.id)) if step.id else str(uuid4())
        if step.id and sid not in previous_ids:
            raise HTTPException(422, "Unknown stage identifier")
        if any(s["id"] == sid for s in steps):
            raise HTTPException(422, "Stage identifiers must be unique")
        steps.append(
            dict(
                id=sid,
                name=step.name.strip(),
                approver_ids=ids,
                approver_source=step.approver_source,
            )
        )
    flow.name = body.name.strip()
    flow.steps = steps
    flow.enabled = body.enabled
    flow.updated_by = principal.user_account_id
    flow.updated_at = service.now()
    await lock_resource(
        session,
        tenant_id,
        f"approval-flow:{flow.request_type}:{flow.org_unit_id}:{flow.employment_id}",
    )
    duplicate = (
        None
        if flow.reusable
        else (
            await session.execute(
                select(ApprovalFlow.id).where(
                    ApprovalFlow.tenant_id == tenant_id,
                    ApprovalFlow.request_type == flow.request_type,
                    ApprovalFlow.org_unit_id == flow.org_unit_id,
                    ApprovalFlow.employment_id == flow.employment_id,
                    ApprovalFlow.id != flow.id,
                )
            )
        ).first()
    )
    if duplicate:
        raise HTTPException(
            409, "A flow already exists for this request type and selected assignment"
        )
    session.add(flow)
    await service.event(
        session,
        tenant_id,
        flow.id,
        principal.user_account_id,
        "FLOW_SAVED",
        dict(version=flow.version, name=flow.name, enabled=flow.enabled, steps=steps),
    )
    await session.flush()
    return flow_public(flow)


@router.post("/flows", status_code=201)
async def create_flow(
    body: FlowWrite,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
):
    if not body.reusable:
        raise HTTPException(422, "Create reusable workflows and assign them from employee profiles")
    company = None
    if body.reusable:
        scope.require("approvals.manage")
        if principal.employment_id:
            company = (
                await session.execute(
                    text(
                        "SELECT legal_entity_id FROM employments WHERE tenant_id=:tid AND id=:eid"
                    ),
                    dict(tid=tenant_id, eid=principal.employment_id),
                )
            ).scalar()
        elif not scope.is_all:
            granted = scope.for_permission("approvals.admin")
            if len(granted.legal_entity_ids) != 1:
                raise HTTPException(
                    422, "Create workflows with a single-company or group administration grant"
                )
            company = next(iter(granted.legal_entity_ids))
    flow = ApprovalFlow(
        reusable=body.reusable,
        owner_employment_id=principal.employment_id,
        legal_entity_id=company,
        tenant_id=tenant_id,
        id=uuid4(),
        name=body.name,
        request_type=body.request_type,
        org_unit_id=to_uuid(body.org_unit_id) if body.org_unit_id else None,
        employment_id=to_uuid(body.employment_id) if body.employment_id else None,
        steps=[],
        updated_by=principal.user_account_id,
    )
    return await write_flow(body, flow, principal, scope, tenant_id, session)


@router.put("/flows/{flow_id}")
async def update_flow(
    flow_id: str,
    body: FlowWrite,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
):
    flow = await flow_get(session, tenant_id, to_uuid(flow_id), lock=True)
    await service.authorize_flow(session, tenant_id, scope, flow)
    if body.version != flow.version:
        raise HTTPException(409, "Flow changed; reload before saving")
    target = to_uuid(body.org_unit_id) if body.org_unit_id else None
    employee = to_uuid(body.employment_id) if body.employment_id else None
    if (
        target != flow.org_unit_id
        or employee != flow.employment_id
        or body.request_type != flow.request_type
    ):
        raise HTTPException(422, "Flow request type and department/team cannot be changed")
    if body.reusable != flow.reusable:
        raise HTTPException(422, "Workflow kind cannot be changed")
    flow.version += 1
    return await write_flow(body, flow, principal, scope, tenant_id, session)


@router.get("/inbox")
async def inbox(tenant_id: TenantDep, session: SessionDep, scope: ScopeDep, principal: CurrentUser):
    # Filter before returning data. Only participants, delegates and scoped managers see requests.
    managed = []
    if scope.has("approvals.manage"):
        tenant_flows = (
            await session.execute(select(ApprovalFlow).where(ApprovalFlow.tenant_id == tenant_id))
        ).scalars()
        managed = [
            f.id for f in tenant_flows if await service.manages(session, tenant_id, scope, f)
        ]
    visibility = [
        col(ApprovalInstance.steps).contains([{"approver_ids": [str(principal.user_account_id)]}]),
        col(ApprovalInstance.flow_id).in_(managed),
        exists(
            select(ApprovalDelegation.id).where(
                ApprovalDelegation.tenant_id == tenant_id,
                ApprovalDelegation.flow_id == ApprovalInstance.flow_id,
                (col(ApprovalDelegation.instance_id).is_(None))
                | (ApprovalDelegation.instance_id == ApprovalInstance.id),
                ApprovalDelegation.delegate_user_id == principal.user_account_id,
                ApprovalDelegation.revoked_at == None,  # noqa: E711
                ApprovalDelegation.valid_from <= service.now(),
                ApprovalDelegation.valid_until > service.now(),
            )
        ),
    ]
    if principal.employment_id:
        visibility.append(col(ApprovalInstance.employment_id) == principal.employment_id)
    rows = (
        await session.execute(
            select(ApprovalInstance)
            .where(
                ApprovalInstance.tenant_id == tenant_id,
                ApprovalInstance.status == "PENDING",
                or_(*visibility),
            )
            .order_by(col(ApprovalInstance.created_at))
        )
    ).scalars()
    result = []
    for instance in rows:
        if await may_view(session, tenant_id, scope, principal, instance):
            result.append(await instance_public(session, tenant_id, scope, principal, instance))
    result.extend(await policy_corrections.inbox(session, tenant_id, scope, principal))
    return result


@router.get("/requests/{instance_id}")
async def request_detail(
    instance_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    if instance_id.startswith("cor_"):
        cor = await policy_corrections.get(session, tenant_id, scope, principal, instance_id)
        return await policy_corrections.public(session, tenant_id, scope, principal, cor)
    instance = await instance_get(session, tenant_id, to_uuid(instance_id))
    if not await may_view(session, tenant_id, scope, principal, instance):
        raise HTTPException(403, "This approval request is outside your authority")
    response = await instance_public(session, tenant_id, scope, principal, instance)
    events = (
        await session.execute(
            select(ApprovalEvent, UserAccount.email)
            .outerjoin(
                UserAccount,
                (col(UserAccount.tenant_id) == col(ApprovalEvent.tenant_id))
                & (col(UserAccount.id) == col(ApprovalEvent.actor_user_id)),
            )
            .where(ApprovalEvent.tenant_id == tenant_id, ApprovalEvent.instance_id == instance.id)
            .order_by(col(ApprovalEvent.created_at))
        )
    ).all()
    response["history"] = [
        dict(
            action=e.action,
            actor_id=to_typed_id("user", e.actor_user_id) if e.actor_user_id else None,
            actor_name=(email or to_typed_id("user", e.actor_user_id))
            if e.actor_user_id
            else "Attendance calculation",
            details=details_public(e.details),
            created_at=e.created_at,
        )
        for e, email in events
    ]
    return response


@router.post("/requests/{instance_id}/decision")
async def decide(
    instance_id: str,
    body: Decision,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    if instance_id.startswith("cor_"):
        return await policy_corrections.decide(
            session, tenant_id, scope, principal, instance_id, body
        )
    instance = await instance_get(session, tenant_id, to_uuid(instance_id))
    # Domain routers lock their business record before locking the approval snapshot.
    if not await may_view(session, tenant_id, scope, principal, instance):
        raise HTTPException(403, "This approval request is outside your authority")
    if instance.status != "PENDING":
        raise HTTPException(409, "This approval route is no longer pending")
    latest = await service.current_instance(
        session, tenant_id, instance.request_type, instance.request_id
    )
    if latest.id != instance.id:
        raise HTTPException(409, "This approval route was superseded")
    await service.actor_for(session, tenant_id, instance, principal)
    kind = instance.request_type
    if kind in ("LEAVE", "LEAVE_CANCELLATION"):
        from hrms.modules.leave import router as leave
        from hrms.modules.leave.schemas import LeaveApprovalActionRequest

        funcs = {
            "LEAVE": (leave.approve_application, leave.reject_application),
            "LEAVE_CANCELLATION": (leave.approve_cancellation, leave.reject_cancellation),
        }
        handler = funcs[kind][0 if body.action == "APPROVE" else 1]
        await handler(
            to_typed_id("leave_application", instance.request_id),
            LeaveApprovalActionRequest(action=body.action, comments=body.comments),
            principal,
            scope,
            tenant_id,
            session,
        )
    elif kind == "FIELD_OVERRIDE":
        from hrms.modules.people.router import decide_field_override

        await decide_field_override(
            session, tenant_id, principal, instance.request_id, body.action, body.comments
        )
    elif kind == "JOB_REQUISITION":
        from hrms.modules.recruitment import router as recruitment
        from hrms.modules.recruitment import service as recruitment_service

        opening = await recruitment_service.get_opening(
            session, tenant_id, to_typed_id("job_opening", instance.request_id), lock=True
        )
        await recruitment.decide(
            session, tenant_id, principal, scope, opening, body.action, body.comments
        )
        await session.flush()
    elif kind == "CORRECTION":
        from hrms.modules.corrections import router as corrections
        from hrms.modules.corrections.schemas import CorrectionApprovalRequest

        correction_handler = (
            corrections.approve_correction
            if body.action == "APPROVE"
            else corrections.reject_correction
        )
        await correction_handler(
            to_typed_id("attendance_correction", instance.request_id),
            CorrectionApprovalRequest(action=body.action, comments=body.comments),
            principal,
            scope,
            tenant_id,
            session,
        )
    else:
        from hrms.modules.time.router import review_overtime
        from hrms.modules.time.schemas import OvertimeReviewRequest

        await review_overtime(
            to_typed_id("attendance_day", instance.request_id),
            OvertimeReviewRequest(
                status="APPROVED" if body.action == "APPROVE" else "REJECTED", notes=body.comments
            ),
            principal,
            scope,
            tenant_id,
            session,
        )
    return await request_detail(instance_id, tenant_id, session, scope, principal)


def delegation_public(d):
    return dict(
        id=to_typed_id("approval_delegation", d.id),
        flow_id=to_typed_id("approval_flow", d.flow_id),
        instance_id=to_typed_id("approval_instance", d.instance_id) if d.instance_id else None,
        original_user_id=to_typed_id("user", d.original_user_id),
        delegate_user_id=to_typed_id("user", d.delegate_user_id),
        valid_from=d.valid_from,
        valid_until=d.valid_until,
        reason=d.reason,
        revoked_at=d.revoked_at,
        created_by=to_typed_id("user", d.created_by),
    )


def details_public(details):
    result = dict(details)
    for key, kind in {
        "original_user_id": "user",
        "delegate_user_id": "user",
        "delegation_id": "approval_delegation",
        "actor_employment_id": "employment",
    }.items():
        if result.get(key):
            result[key] = to_typed_id(kind, UUID(result[key]))
    if "steps" in result:
        result["steps"] = steps_public(result["steps"])
    return result


@router.post("/delegations", status_code=201)
async def delegate(
    body: DelegationWrite,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    instance = await instance_get(session, tenant_id, to_uuid(body.instance_id), lock=True)
    if (
        instance.status != "PENDING"
        or body.level > len(instance.steps)
        or body.level < instance.current_level
    ):
        raise HTTPException(409, "Choose an uncompleted level of a pending request")
    flow = await flow_get(session, tenant_id, instance.flow_id)
    admin = await service.manages_request(session, tenant_id, scope, flow, instance.employment_id)
    if not admin and not any(
        str(principal.user_account_id) in step["approver_ids"]
        for step in instance.steps[body.level :]
    ):
        raise HTTPException(403, "A designated upper-level approver must authorize delegation")
    if body.flow_wide and not admin:
        raise HTTPException(403, "Flow-wide delegation requires workflow administration")
    step = instance.steps[body.level - 1]
    original = to_uuid(body.original_user_id)
    replacement = to_uuid(body.delegate_user_id)
    if str(original) not in step["approver_ids"]:
        raise HTTPException(422, "Original approver is not assigned to this stage")
    if body.valid_until <= service.now():
        raise HTTPException(422, "Delegation must expire in the future")
    account = await service.active_account(session, tenant_id, replacement)
    requester = await service.person_of_employment(session, tenant_id, instance.employment_id)
    if replacement == original or (account.person_id and account.person_id == requester):
        raise HTTPException(422, "Delegate cannot be the original approver or requester")
    # A delegate cannot silently become a participant at two stages in this chain.
    if any(str(replacement) in s["approver_ids"] for s in instance.steps):
        raise HTTPException(422, "Delegate is already assigned to a level of this chain")
    if account.person_id:
        # Every login of the same person, across all their employments.
        assigned = {UUID(uid) for s in instance.steps for uid in s["approver_ids"]}
        people = await service.people_of_accounts(session, tenant_id, assigned)
        if account.person_id in people.values():
            raise HTTPException(422, "Delegate already holds a level through another account")
    record = ApprovalDelegation(
        tenant_id=tenant_id,
        id=uuid4(),
        flow_id=flow.id,
        instance_id=None if body.flow_wide else instance.id,
        step_id=UUID(step["id"]),
        original_user_id=original,
        delegate_user_id=replacement,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        reason=body.reason,
        created_by=principal.user_account_id,
    )
    session.add(record)
    await service.event(
        session,
        tenant_id,
        flow.id,
        principal.user_account_id,
        "DELEGATION_CREATED",
        dict(
            delegation_id=str(record.id),
            level=body.level,
            original_user_id=str(original),
            delegate_user_id=str(replacement),
            flow_wide=body.flow_wide,
            reason=body.reason,
            valid_from=body.valid_from.isoformat(),
            valid_until=body.valid_until.isoformat(),
        ),
        instance.id,
    )
    await session.flush()
    return delegation_public(record)


@router.get("/delegations")
async def delegations(
    instance_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    instance = await instance_get(session, tenant_id, to_uuid(instance_id))
    if not await may_view(session, tenant_id, scope, principal, instance):
        raise HTTPException(403, "This request is outside your authority")
    rows = (
        await session.execute(
            select(ApprovalDelegation).where(
                ApprovalDelegation.tenant_id == tenant_id,
                ApprovalDelegation.flow_id == instance.flow_id,
                (col(ApprovalDelegation.instance_id).is_(None))
                | (ApprovalDelegation.instance_id == instance.id),  # noqa: E711
            )
        )
    ).scalars()
    return [
        delegation_public(d) for d in rows if str(d.step_id) in {s["id"] for s in instance.steps}
    ]


@router.post("/delegations/{delegation_id}/revoke")
async def revoke(
    delegation_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    record = (
        (
            await session.execute(
                select(ApprovalDelegation)
                .where(
                    ApprovalDelegation.tenant_id == tenant_id,
                    ApprovalDelegation.id == to_uuid(delegation_id),
                )
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if record is None:
        raise HTTPException(404, "Delegation not found")
    flow = await flow_get(session, tenant_id, record.flow_id)
    if (
        not await service.manages(session, tenant_id, scope, flow)
        and record.created_by != principal.user_account_id
    ):
        raise HTTPException(
            403, "Only its authorizer or workflow administrator can revoke delegation"
        )
    if record.revoked_at is None:
        record.revoked_at = service.now()
        record.revoked_by = principal.user_account_id
        session.add(record)
        await service.event(
            session,
            tenant_id,
            flow.id,
            principal.user_account_id,
            "DELEGATION_REVOKED",
            dict(delegation_id=str(record.id)),
            record.instance_id,
        )
    return delegation_public(record)


@router.get("/employees/{employment_id}/flows")
async def employee_flows(
    employment_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
):
    eid = to_uuid(employment_id)
    from hrms.core.authz import authorize_employment

    can_manage = True
    try:
        await service.authorize_employee_assignment(session, tenant_id, scope, eid)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        can_manage = False
        await authorize_employment(session, tenant_id, scope, eid)
    rows = (
        await session.execute(
            select(EmployeeApprovalFlow, ApprovalFlow)
            .outerjoin(
                ApprovalFlow,
                (col(ApprovalFlow.tenant_id) == col(EmployeeApprovalFlow.tenant_id))
                & (col(ApprovalFlow.id) == col(EmployeeApprovalFlow.flow_id)),
            )
            .where(
                EmployeeApprovalFlow.tenant_id == tenant_id,
                EmployeeApprovalFlow.employment_id == eid,
            )
        )
    ).all()
    return dict(
        can_manage=can_manage,
        assignments=[
            dict(
                request_type=assignment.request_type,
                version=assignment.version,
                flow=flow_public(flow) if flow else None,
            )
            for assignment, flow in rows
        ],
    )


@router.put("/employees/{employment_id}/flows/{request_type}")
async def assign_employee_flow(
    employment_id: str,
    request_type: RequestType,
    body: EmployeeFlowWrite,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    principal: CurrentUser,
):
    eid = to_uuid(employment_id)
    await service.authorize_employee_assignment(session, tenant_id, scope, eid)
    await lock_resource(session, tenant_id, f"employee-approval:{eid}:{request_type}")
    assignment = (
        (
            await session.execute(
                select(EmployeeApprovalFlow)
                .where(
                    EmployeeApprovalFlow.tenant_id == tenant_id,
                    EmployeeApprovalFlow.employment_id == eid,
                    EmployeeApprovalFlow.request_type == request_type,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    if body.version != (assignment.version if assignment else 0):
        raise HTTPException(409, "Employee workflow changed; reload before saving")
    employee_exists = (
        await session.execute(
            text(
                "SELECT id FROM employments WHERE tenant_id=:tid AND id=:eid "
                "AND archived_at IS NULL"
            ),
            dict(tid=tenant_id, eid=eid),
        )
    ).scalar()
    if not employee_exists:
        raise HTTPException(404, "Employee not found")
    if body.flow_id is None:
        if assignment and assignment.flow_id:
            await service.event(
                session,
                tenant_id,
                assignment.flow_id,
                principal.user_account_id,
                "EMPLOYEE_UNASSIGNED",
                dict(employment_id=str(eid), request_type=request_type),
            )
        if assignment is None:
            assignment = EmployeeApprovalFlow(
                tenant_id=tenant_id,
                employment_id=eid,
                request_type=request_type,
                flow_id=None,
                updated_by=principal.user_account_id,
            )
        else:
            assignment.flow_id = None
            assignment.version += 1
            assignment.updated_by = principal.user_account_id
            assignment.updated_at = service.now()
        session.add(assignment)
        await session.flush()
        return await employee_flows(employment_id, tenant_id, session, scope)
    flow = await flow_get(session, tenant_id, to_uuid(body.flow_id), lock=True)
    if not flow.reusable or flow.request_type != request_type or not flow.enabled:
        raise HTTPException(422, "Choose an enabled reusable workflow for this request type")
    if not await service.visible_template(session, tenant_id, scope, flow):
        raise HTTPException(403, "Workflow is outside your company scope")
    company = (
        await session.execute(
            text(
                "SELECT legal_entity_id FROM employments WHERE tenant_id=:tid AND id=:eid "
                "AND archived_at IS NULL"
            ),
            dict(tid=tenant_id, eid=eid),
        )
    ).scalar()
    if not company:
        raise HTTPException(404, "Employee not found")
    if flow.legal_entity_id and flow.legal_entity_id != company:
        raise HTTPException(422, "Choose a workflow available to this employee’s company")
    for step in flow.steps:
        if step.get("approver_source", "PEOPLE") != "PEOPLE":
            raise HTTPException(422, "Choose a workflow with specific approvers")
        eligible = []
        for uid in step["approver_ids"]:
            account = await service.active_account(session, tenant_id, UUID(uid))
            if account.employment_id != eid:
                eligible.append(uid)
        if not eligible:
            raise HTTPException(
                422, f'Stage "{step["name"]}" has no approver other than this employee'
            )
    if assignment is None:
        assignment = EmployeeApprovalFlow(
            tenant_id=tenant_id,
            employment_id=eid,
            request_type=request_type,
            flow_id=flow.id,
            updated_by=principal.user_account_id,
        )
    else:
        assignment.version += 1
        assignment.flow_id = flow.id
        assignment.updated_by = principal.user_account_id
        assignment.updated_at = service.now()
    session.add(assignment)
    await service.event(
        session,
        tenant_id,
        flow.id,
        principal.user_account_id,
        "EMPLOYEE_ASSIGNED",
        dict(employment_id=str(eid), request_type=request_type, version=assignment.version),
    )
    await session.flush()
    return await employee_flows(employment_id, tenant_id, session, scope)
