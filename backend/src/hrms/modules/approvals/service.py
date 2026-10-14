"""Route selection and exact-request authorization; no role names encode levels."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authz import authorize_employment, authorize_org_unit
from hrms.core.datetime_utils import business_today
from hrms.modules.approvals.models import (
    ApprovalDelegation,
    ApprovalEvent,
    ApprovalFlow,
    ApprovalInstance,
    EmployeeApprovalFlow,
)


def now():
    return datetime.now(UTC)


def pending_status(level, cancel=False):
    prefix = "CANCEL_PENDING" if cancel else "PENDING"
    return f"{prefix}_L{level}" if level <= 3 else prefix


async def event(session, tenant_id, flow_id, actor, action, details, instance_id=None):
    session.add(
        ApprovalEvent(
            tenant_id=tenant_id,
            id=uuid4(),
            flow_id=flow_id,
            instance_id=instance_id,
            actor_user_id=actor,
            action=action,
            details=details,
        )
    )


async def people_of_accounts(session, tenant_id, account_ids) -> dict[UUID, UUID]:
    """
    Account id -> the person behind it. One person can hold several employments, each with its
    own login, so "the same person" means the same person_id, not the same employment. An
    account without an employment stands for itself.
    """
    ids = list(account_ids)
    if not ids:
        return {}
    rows = await session.execute(
        text("""
        SELECT ua.id, e.person_id FROM user_accounts ua
        LEFT JOIN employments e ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
        WHERE ua.tenant_id=:tid AND ua.id = ANY(:ids)
    """),
        dict(tid=tenant_id, ids=ids),
    )
    return {uid: person or uid for uid, person in rows}


async def person_of_employment(session, tenant_id, employment_id) -> UUID | None:
    if employment_id is None:
        return None
    return (
        await session.execute(
            text("SELECT person_id FROM employments WHERE tenant_id=:tid AND id=:eid"),
            dict(tid=tenant_id, eid=employment_id),
        )
    ).scalar()


async def active_account(session, tenant_id, account_id):
    row = (
        await session.execute(
            text("""
        SELECT ua.id, ua.employment_id, e.person_id FROM user_accounts ua
        LEFT JOIN employments e ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
        WHERE ua.tenant_id=:tid AND ua.id=:uid AND ua.status='ACTIVE'
          AND (ua.employment_id IS NULL OR (e.archived_at IS NULL
               AND e.employment_state <> 'SEPARATED'))
    """),
            dict(tid=tenant_id, uid=account_id),
        )
    ).first()
    if not row:
        raise HTTPException(422, "Approver account must be active in this tenant")
    return row


async def authorize_flow(session, tenant_id, scope, flow):
    scope.require("approvals.manage")
    if getattr(flow, "reusable", False):
        if scope.has("approvals.admin"):
            admin = scope.for_permission("approvals.admin")
            if (
                admin.is_all
                or flow.legal_entity_id is None
                or (flow.legal_entity_id and admin.covers_entity(flow.legal_entity_id))
            ):
                return
        if flow.owner_employment_id and flow.owner_employment_id == scope.own_employment_id:
            return
        raise HTTPException(
            403, "Only the workflow creator or scoped HR/admin can edit this workflow"
        )
    if scope.has("approvals.admin"):
        try:
            await authorize_admin_flow(session, tenant_id, scope, flow)
            return
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
    if flow.employment_id is not None or flow.org_unit_id is None:
        raise HTTPException(
            403, "Only HR or administrators can manage individual or group workflows"
        )
    await authorize_team_workflow(
        session, tenant_id, scope.for_permission("approvals.manage"), flow.org_unit_id
    )


async def authorize_admin_flow(session, tenant_id, scope, flow):
    # Keep HR's administration grant separate from other roles' broader visibility.
    scope = scope.for_permission("approvals.admin")
    if flow.employment_id is not None:
        from hrms.modules.people.models import Employment

        employee = (
            await session.execute(
                select(Employment.id).where(
                    Employment.tenant_id == tenant_id, Employment.id == flow.employment_id
                )
            )
        ).first()
        if not employee:
            raise HTTPException(404, "Employee not found")
        await authorize_employment(session, tenant_id, scope, flow.employment_id)
    elif flow.org_unit_id is None:
        if not scope.is_all:
            raise HTTPException(
                403, "Tenant-wide flows require tenant-wide approval administration"
            )
    else:
        from hrms.modules.org.models import OrgUnit

        exists = (
            await session.execute(
                select(OrgUnit.id).where(
                    OrgUnit.tenant_id == tenant_id,
                    OrgUnit.id == flow.org_unit_id,
                    col(OrgUnit.type).in_(["DEPARTMENT", "TEAM"]),
                    col(OrgUnit.archived_at).is_(None),
                    OrgUnit.status == "ACTIVE",
                )
            )
        ).first()
        if not exists:
            raise HTTPException(404, "Department/team not found")
        await authorize_org_unit(session, tenant_id, scope, flow.org_unit_id)


async def authorize_team_workflow(session, tenant_id, scope, unit_id):
    """Leadership grants never authorize an individual or another group's workflow."""
    from hrms.modules.org.models import OrgUnit

    unit = (
        (
            await session.execute(
                select(OrgUnit).where(OrgUnit.tenant_id == tenant_id, OrgUnit.id == unit_id)
            )
        )
        .scalars()
        .first()
    )
    if unit is None:
        raise HTTPException(404, "Department/team not found")
    if unit.type not in ("DEPARTMENT", "TEAM"):
        raise HTTPException(403, "Choose a department or team workflow")
    if unit.id in scope.org_unit_ids:
        return
    if scope.own_employment_id is not None:
        head_id = unit.head_employment_id
        if unit.type == "TEAM" and unit.parent_id:
            head_id = (
                await session.execute(
                    select(OrgUnit.head_employment_id).where(
                        OrgUnit.tenant_id == tenant_id,
                        OrgUnit.id == unit.parent_id,
                        OrgUnit.type == "DEPARTMENT",
                        col(OrgUnit.archived_at).is_(None),
                    )
                )
            ).scalar()
        if head_id == scope.own_employment_id:
            return
    if (
        unit.type == "TEAM"
        and scope.own_employment_id is not None
        and (scope.own_employment_id in (unit.lead_employment_id, unit.pm_employment_id))
    ):
        return
    # A HOD's reporting grant must cover the whole group, not merely one employee.
    members = set(
        (
            await session.execute(
                text("""
        WITH RECURSIVE descendants AS (
            SELECT id FROM org_units WHERE tenant_id=:tid AND id=:unit
            UNION
            SELECT ou.id FROM org_units ou JOIN descendants d ON ou.parent_id=d.id
            WHERE ou.tenant_id=:tid
        )
        SELECT DISTINCT a.employment_id FROM assignments a JOIN descendants d ON d.id=a.org_unit_id
        WHERE a.tenant_id=:tid AND a.effective_from<=:day
          AND (a.effective_to IS NULL OR a.effective_to>:day)
    """),
                dict(tid=tenant_id, unit=unit_id, day=business_today()),
            )
        )
        .scalars()
        .all()
    )
    reports = (scope.employment_ids or frozenset()) - {scope.own_employment_id}
    group_members = members - {scope.own_employment_id}
    if group_members and group_members <= reports:
        return
    raise HTTPException(
        403, "You can manage only teams you lead or groups fully in your reporting scope"
    )


async def manages(session, tenant_id, scope, flow):
    try:
        await authorize_flow(session, tenant_id, scope, flow)
        return True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False


async def manages_request(session, tenant_id, scope, flow, employment_id):
    # Designing a reusable chain does not grant visibility to every assigned employee.
    if not scope.has("approvals.admin"):
        return False
    try:
        await authorize_employment(
            session, tenant_id, scope.for_permission("approvals.admin"), employment_id
        )
        return await manages(session, tenant_id, scope, flow)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False


async def current_instance(session, tenant_id, kind, request_id, lock=False):
    query = (
        select(ApprovalInstance)
        .where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.request_type == kind,
            ApprovalInstance.request_id == request_id,
        )
        .order_by(col(ApprovalInstance.generation).desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(query)).scalars().first()


async def resolve_flow(session, tenant_id, employment_id, kind):
    # Employee selection is the sole routing source; placement is irrelevant.
    row = (
        (
            await session.execute(
                select(ApprovalFlow)
                .join(
                    EmployeeApprovalFlow,
                    (col(EmployeeApprovalFlow.tenant_id) == col(ApprovalFlow.tenant_id))
                    & (col(EmployeeApprovalFlow.flow_id) == col(ApprovalFlow.id)),
                )
                .where(
                    ApprovalFlow.tenant_id == tenant_id,
                    EmployeeApprovalFlow.employment_id == employment_id,
                    EmployeeApprovalFlow.request_type == kind,
                )
            )
        )
        .scalars()
        .first()
    )
    if row and not row.enabled:
        raise HTTPException(
            409, "The employee’s assigned workflow is disabled; select an enabled workflow"
        )
    return row


async def visible_template(session, tenant_id, scope, flow):
    if not flow.reusable:
        return await manages(session, tenant_id, scope, flow)
    if flow.legal_entity_id is None:
        return True
    if scope.is_all or scope.covers_entity(flow.legal_entity_id):
        return True
    if scope.own_employment_id:
        company = (
            await session.execute(
                text("SELECT legal_entity_id FROM employments WHERE tenant_id=:tid AND id=:eid"),
                dict(tid=tenant_id, eid=scope.own_employment_id),
            )
        ).scalar()
        return company == flow.legal_entity_id
    return False


async def authorize_employee_assignment(session, tenant_id, scope, employment_id):
    scope.require("approvals.manage")
    if scope.has("approvals.admin"):
        await authorize_employment(
            session, tenant_id, scope.for_permission("approvals.admin"), employment_id
        )
        return
    if employment_id == scope.own_employment_id:
        raise HTTPException(403, "HR/admin assigns leaders’ own workflows")
    leader = (
        await session.execute(
            text("""
        SELECT EXISTS (
            SELECT 1 FROM org_units WHERE tenant_id=:tid AND archived_at IS NULL
            AND (head_employment_id=:eid OR lead_employment_id=:eid OR pm_employment_id=:eid)
            UNION ALL
            SELECT 1 FROM user_accounts ua JOIN role_assignments ra
              ON ra.tenant_id=ua.tenant_id AND ra.user_account_id=ua.id
            JOIN roles r ON r.tenant_id=ra.tenant_id AND r.id=ra.role_id
            WHERE ua.tenant_id=:tid AND ua.employment_id=:eid
              AND (ra.expires_at IS NULL OR ra.expires_at>now())
              AND r.name IN ('MANAGER','HR_MANAGER','SUPER_ADMIN')
        )
    """),
            dict(tid=tenant_id, eid=employment_id),
        )
    ).scalar()
    if leader:
        raise HTTPException(403, "HR/admin assigns HOD, PM and lead workflows")
    management = scope.for_permission("approvals.manage")
    if employment_id in (management.employment_ids or ()):
        return
    unit = (
        await session.execute(
            text("""
        SELECT org_unit_id FROM assignments WHERE tenant_id=:tid AND employment_id=:eid
        AND effective_from<=:day AND (effective_to IS NULL OR effective_to>:day)
    """),
            dict(tid=tenant_id, eid=employment_id, day=business_today()),
        )
    ).scalar()
    if unit:
        await authorize_team_workflow(session, tenant_id, management, unit)
        return
    raise HTTPException(403, "This employee is outside your management scope")


async def resolved_steps(session, tenant_id, employment_id, flow):
    """Resolve team roles once so future staffing changes cannot alter a pending request."""
    steps = []
    for step in flow.steps:
        source = step.get("approver_source", "PEOPLE")
        if source == "PEOPLE":
            steps.append(dict(step))
            continue
        column = {"TEAM_LEAD": "lead_employment_id", "TEAM_PM": "pm_employment_id"}[source]
        rows = (
            (
                await session.execute(
                    text(f"""
            SELECT ua.id FROM assignments a
            JOIN org_units team ON team.tenant_id=a.tenant_id AND team.id=a.org_unit_id
            JOIN user_accounts ua ON ua.tenant_id=team.tenant_id AND ua.employment_id=team.{column}
            JOIN employments e ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
            WHERE a.tenant_id=:tid AND a.employment_id=:eid
              AND a.effective_from<=:day AND (a.effective_to IS NULL OR a.effective_to>:day)
              AND team.type='TEAM' AND team.status='ACTIVE' AND team.archived_at IS NULL
              AND ua.status='ACTIVE' AND e.archived_at IS NULL AND e.employment_state<>'SEPARATED'
            ORDER BY ua.id
        """),
                    dict(tid=tenant_id, eid=employment_id, day=business_today()),
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise HTTPException(
                409,
                f"Configure an active {source.replace('_', ' ').lower()} "
                "with login access for this employee’s team",
            )
        steps.append({**step, "approver_ids": [str(uid) for uid in rows]})
    return steps


async def start(session, tenant_id, kind, request_id, employment_id, request_snapshot=None):
    from hrms.modules.kernel.models import UserAccount

    flow = await resolve_flow(session, tenant_id, employment_id, kind)
    if flow is None:
        return None
    previous = await current_instance(session, tenant_id, kind, request_id, lock=True)
    if previous and previous.status == "PENDING":
        return previous
    steps = []
    resolved = await resolved_steps(session, tenant_id, employment_id, flow)
    account_ids = {UUID(uid) for step in resolved for uid in step["approver_ids"]}
    accounts = dict(
        (
            await session.execute(
                select(UserAccount.id, UserAccount.employment_id).where(
                    UserAccount.tenant_id == tenant_id, col(UserAccount.id).in_(account_ids)
                )
            )
        ).all()
    )
    people_by_account = await people_of_accounts(session, tenant_id, account_ids)
    requester = await person_of_employment(session, tenant_id, employment_id)
    seen_employees: set[UUID] = set()
    for step in resolved:
        eligible = []
        for uid in step["approver_ids"]:
            if UUID(uid) not in accounts:
                raise HTTPException(409, "An assigned approver account no longer exists")
            # Preserve inactive originals so an upper level can authorize cover.
            # Active-account validation is enforced again when someone acts.
            # The requester can't approve, through this employment's login or another one.
            if people_by_account[UUID(uid)] != requester:
                eligible.append(uid)
        if not eligible:
            raise HTTPException(
                409, f'Approval stage "{step["name"]}" has no eligible non-requester'
            )
        people = {people_by_account[UUID(uid)] for uid in eligible}
        if seen_employees & people:
            raise HTTPException(
                409, "The same person resolves to multiple stages; edit the workflow or team roles"
            )
        seen_employees.update(people)
        steps.append({**step, "approver_ids": eligible})
    instance = ApprovalInstance(
        tenant_id=tenant_id,
        id=uuid4(),
        flow_id=flow.id,
        request_type=kind,
        request_id=request_id,
        employment_id=employment_id,
        generation=previous.generation + 1 if previous else 1,
        flow_version=flow.version,
        steps=steps,
    )
    session.add(instance)
    if request_snapshot is not None:
        # Retain the amount/times that were actually submitted for overtime
        # review even when a later attendance recomputation changes the day.
        await event(
            session,
            tenant_id,
            flow.id,
            None,
            "SUBMITTED",
            dict(request=request_snapshot),
            instance.id,
        )
    await session.flush()
    return instance


async def live_delegations(session, tenant_id, instance, step, lock=False):
    query = select(ApprovalDelegation).where(
        ApprovalDelegation.tenant_id == tenant_id,
        ApprovalDelegation.flow_id == instance.flow_id,
        ApprovalDelegation.step_id == UUID(step["id"]),
        (col(ApprovalDelegation.instance_id).is_(None))
        | (ApprovalDelegation.instance_id == instance.id),  # noqa: E711
        ApprovalDelegation.revoked_at == None,  # noqa: E711
        ApprovalDelegation.valid_from <= now(),
        ApprovalDelegation.valid_until > now(),
    )
    if lock:
        # Hold delegation authority until the decision commits. A concurrent
        # revocation either precedes this check or follows the committed decision.
        query = (
            query.order_by(col(ApprovalDelegation.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return list((await session.execute(query)).scalars())


async def actor_for(session, tenant_id, instance, principal, lock_delegations=False):
    if instance.status != "PENDING" or principal.employment_id == instance.employment_id:
        raise HTTPException(403, "You cannot act on this approval stage")
    step = instance.steps[instance.current_level - 1]
    uid = str(principal.user_account_id)
    await active_account(session, tenant_id, principal.user_account_id)
    # Prior use as delegate counts as acting at a level, too.
    prior = (
        await session.execute(
            select(ApprovalEvent).where(
                ApprovalEvent.tenant_id == tenant_id,
                ApprovalEvent.instance_id == instance.id,
                ApprovalEvent.action == "APPROVE",
            )
        )
    ).scalars()
    if any(
        e.actor_user_id == principal.user_account_id
        or (
            principal.employment_id
            and e.details.get("actor_employment_id") == str(principal.employment_id)
        )
        for e in prior
    ):
        raise HTTPException(409, "A different reviewer is required at each approval level")
    if uid in step["approver_ids"]:
        return dict(original_user_id=uid, delegation_id=None)
    for delegation in await live_delegations(
        session, tenant_id, instance, step, lock=lock_delegations
    ):
        if (
            delegation.delegate_user_id == principal.user_account_id
            and str(delegation.original_user_id) in step["approver_ids"]
            and delegation.revoked_at is None
            and delegation.valid_from <= now() < delegation.valid_until
        ):
            return dict(
                original_user_id=str(delegation.original_user_id), delegation_id=str(delegation.id)
            )
    raise HTTPException(403, "Only the designated stage approver or an active delegate can act")


async def require_actor(session, tenant_id, kind, request_id, principal):
    instance = await current_instance(session, tenant_id, kind, request_id, lock=True)
    if instance is None:
        return False
    await actor_for(session, tenant_id, instance, principal)
    return True


async def record_decision(session, tenant_id, kind, request_id, principal, action, comments=None):
    instance = await current_instance(session, tenant_id, kind, request_id, lock=True)
    if instance is None:
        return None
    authority = await actor_for(session, tenant_id, instance, principal, lock_delegations=True)
    await event(
        session,
        tenant_id,
        instance.flow_id,
        principal.user_account_id,
        action,
        dict(
            level=instance.current_level,
            step_name=instance.steps[instance.current_level - 1]["name"],
            actor_employment_id=str(principal.employment_id) if principal.employment_id else None,
            comments=comments,
            **authority,
        ),
        instance.id,
    )
    final = action == "REJECT" or instance.current_level == len(instance.steps)
    if final:
        instance.status = "REJECTED" if action == "REJECT" else "APPROVED"
    else:
        instance.current_level += 1
    instance.updated_at = now()
    session.add(instance)
    return final


async def finish(session, tenant_id, kind, request_id, status):
    instance = await current_instance(session, tenant_id, kind, request_id, lock=True)
    if instance and instance.status == "PENDING":
        instance.status = status
        instance.updated_at = now()
        session.add(instance)
