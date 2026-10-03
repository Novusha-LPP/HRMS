"""Route selection and exact-request authorization; no role names encode levels."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authz import authorize_org_unit
from hrms.core.datetime_utils import business_today
from hrms.modules.approvals.models import (
    ApprovalDelegation,
    ApprovalEvent,
    ApprovalFlow,
    ApprovalInstance,
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


async def active_account(session, tenant_id, account_id):
    row = (
        await session.execute(
            text("""
        SELECT ua.id, ua.employment_id FROM user_accounts ua
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
    scope = scope.for_permission("approvals.manage")
    if flow.org_unit_id is None:
        if not scope.is_all:
            raise HTTPException(
                403, "Tenant-wide flows require tenant-wide approval administration"
            )
    else:
        from hrms.modules.org.models import OrgUnit

        exists = (
            await session.execute(
                select(OrgUnit.id).where(
                    OrgUnit.tenant_id == tenant_id, OrgUnit.id == flow.org_unit_id
                )
            )
        ).first()
        if not exists:
            raise HTTPException(404, "Department/team not found")
        await authorize_org_unit(session, tenant_id, scope, flow.org_unit_id)


async def manages(session, tenant_id, scope, flow):
    try:
        await authorize_flow(session, tenant_id, scope, flow)
        return True
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
    # Assignment and ancestry are evaluated at submission, not at future leave date.
    # The closest active team/department route wins over its ancestors/default.
    row = (
        await session.execute(
            text("""
        WITH RECURSIVE chain AS (
            SELECT ou.id, ou.parent_id, 0 AS depth, ARRAY[ou.id] AS path
            FROM assignments a JOIN org_units ou ON ou.tenant_id=a.tenant_id AND ou.id=a.org_unit_id
            WHERE a.tenant_id=:tid AND a.employment_id=:eid AND a.effective_from<=:day
              AND (a.effective_to IS NULL OR a.effective_to>:day)
              AND ou.archived_at IS NULL AND ou.status='ACTIVE'
            UNION ALL
            SELECT ou.id,ou.parent_id,c.depth+1,c.path||ou.id
            FROM org_units ou JOIN chain c ON ou.id=c.parent_id
            WHERE ou.tenant_id=:tid AND NOT ou.id=ANY(c.path)
              AND ou.archived_at IS NULL AND ou.status='ACTIVE'
        )
        SELECT f.id FROM approval_flows f LEFT JOIN chain c ON c.id=f.org_unit_id
        WHERE f.tenant_id=:tid AND f.request_type=:kind AND f.enabled
          AND (f.org_unit_id IS NULL OR c.id IS NOT NULL)
        ORDER BY COALESCE(c.depth,2147483647), f.id LIMIT 1
    """),
            dict(tid=tenant_id, eid=employment_id, kind=kind, day=business_today()),
        )
    ).scalar()
    if row is None:
        return None
    return (
        (
            await session.execute(
                select(ApprovalFlow).where(
                    ApprovalFlow.tenant_id == tenant_id, ApprovalFlow.id == row
                )
            )
        )
        .scalars()
        .one()
    )


async def start(session, tenant_id, kind, request_id, employment_id, request_snapshot=None):
    from hrms.modules.kernel.models import UserAccount

    flow = await resolve_flow(session, tenant_id, employment_id, kind)
    if flow is None:
        return None
    previous = await current_instance(session, tenant_id, kind, request_id, lock=True)
    if previous and previous.status == "PENDING":
        return previous
    steps = []
    account_ids = {UUID(uid) for step in flow.steps for uid in step["approver_ids"]}
    accounts = dict(
        (
            await session.execute(
                select(UserAccount.id, UserAccount.employment_id).where(
                    UserAccount.tenant_id == tenant_id, col(UserAccount.id).in_(account_ids)
                )
            )
        ).all()
    )
    for step in flow.steps:
        eligible = []
        for uid in step["approver_ids"]:
            if UUID(uid) not in accounts:
                raise HTTPException(409, "An assigned approver account no longer exists")
            # Preserve inactive originals so an upper level can authorize cover.
            # Active-account validation is enforced again when someone acts.
            if accounts[UUID(uid)] != employment_id:
                eligible.append(uid)
        if not eligible:
            raise HTTPException(
                409, f'Approval stage "{step["name"]}" has no eligible non-requester'
            )
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
