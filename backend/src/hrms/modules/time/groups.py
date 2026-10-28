"""
Attendance groups — guards, drivers, cleaners: people whose days are marked, not punched.

GET    /v1/time/attendance-groups                                   groups the caller can see
POST   /v1/time/attendance-groups                                   create one (manage)
PATCH  /v1/time/attendance-groups/{id}                              rename / describe (manage)
DELETE /v1/time/attendance-groups/{id}                              retire an empty one (manage)
GET    /v1/time/attendance-groups/{id}/members?on=…                 who is in it on a day
POST   /v1/time/attendance-groups/{id}/members                      add people from a date (manage)
DELETE /v1/time/attendance-groups/{id}/members/{employment_id}      take someone out (manage)
GET    /v1/time/attendance-groups/{id}/access                       who may view / mark (manage)
PUT    /v1/time/attendance-groups/{id}/access/{user_id}             grant VIEW or MARK (manage)
DELETE /v1/time/attendance-groups/{id}/access/{user_id}             withdraw it (manage)

Being in a group on a day is what makes that day marked (time/marking.py); the person's policy
still gives their shift, holidays and weekly offs. Membership is effective-dated and a person
is in at most one group on a day (the database enforces it), so the past keeps its meaning when
someone moves.

Who may do what:
- attendance.groups.manage (HR): create and change groups, members and access, and view and mark
  every group, for the people in their own scope;
- everyone else: only the groups they were given, VIEW (see the daily sheet) or MARK (also
  mark days and record leave). A group grant is the whole permission: it isn't narrowed further
  by the person's role scope, so a guard supervisor needs no HR role to keep the guards' sheet.
"""

from datetime import date, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import Scope, ScopeDep, authorize_employment, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.time.models import (
    AttendanceGroup,
    AttendanceGroupAccess,
    AttendanceGroupMember,
    GroupAccess,
)
from hrms.modules.time.schemas import (
    AttendanceGroupCreate,
    AttendanceGroupResponse,
    AttendanceGroupUpdate,
    GroupAccessEntry,
    GroupAccessGrant,
    GroupMember,
    GroupMembersAdd,
)

router = APIRouter(prefix="/v1/time/attendance-groups", tags=["Time & Attendance"])

MANAGE = "attendance.groups.manage"


# ─── Membership and access (used by marking, the register and the reports) ──────


async def group_spans(
    session, tenant_id: UUID, ids: list[UUID], first: date, last: date
) -> dict[UUID, list[tuple[date, date | None, UUID]]]:
    """Each person's group memberships touching first..last: (from, to exclusive, group)."""
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT employment_id, effective_from, effective_to, group_id
            FROM attendance_group_members
            WHERE tenant_id = :tid AND employment_id = ANY(:ids)
              AND effective_from <= :last AND (effective_to IS NULL OR effective_to > :first)
        """),
        {"tid": tenant_id, "ids": ids, "first": first, "last": last},
    )
    spans: dict[UUID, list[tuple[date, date | None, UUID]]] = {}
    for eid, start, end, group in rows.all():
        spans.setdefault(eid, []).append((start, end, group))
    return spans


def group_on(spans: list[tuple[date, date | None, UUID]] | None, day: date) -> UUID | None:
    """The group someone is in on `day`, if any (their attendance that day is marked)."""
    for start, end, group in spans or ():
        if start <= day and (end is None or day < end):
            return group
    return None


async def marked_on(session, tenant_id: UUID, employment_id: UUID, day: date) -> bool:
    spans = await group_spans(session, tenant_id, [employment_id], day, day)
    return group_on(spans.get(employment_id), day) is not None


def can_manage(scope: Scope) -> bool:
    return scope.has(MANAGE)


async def access_levels(
    session, tenant_id: UUID, principal, scope: Scope, *, include_archived: bool = False
) -> dict[UUID, str]:
    """
    Group id -> VIEW / MARK for the caller. HR managing groups may mark every group; with
    `include_archived` that includes retired groups, so HR can still correct their past days.
    Access granted per group ends when the group is retired.
    """
    if can_manage(scope):
        groups = await session.execute(
            text(
                "SELECT id FROM attendance_groups WHERE tenant_id = :tid "
                "AND (archived_at IS NULL OR CAST(:archived AS boolean))"
            ),
            {"tid": tenant_id, "archived": include_archived},
        )
        return {g: GroupAccess.MARK for (g,) in groups.all()}
    rows = await session.execute(
        text("""
            SELECT a.group_id, a.access_level FROM attendance_group_access a
            JOIN attendance_groups g ON g.tenant_id = a.tenant_id AND g.id = a.group_id
            WHERE a.tenant_id = :tid AND a.user_account_id = :uid AND g.archived_at IS NULL
        """),
        {"tid": tenant_id, "uid": principal.user_account_id},
    )
    return {g: level for g, level in rows.all()}


async def require_group_access(session, tenant_id, principal, scope, group_id: UUID, level: str):
    levels = await access_levels(session, tenant_id, principal, scope)
    have = levels.get(group_id)
    if have is None or (level == GroupAccess.MARK and have != GroupAccess.MARK):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can't mark this group" if level == GroupAccess.MARK else "Group not available",
        )


# ─── Groups ─────────────────────────────────────────────────────────────────────


@router.get(
    "", response_model=list[AttendanceGroupResponse], summary="Attendance groups you can see"
)
async def list_groups(
    principal: CurrentUser, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> list[AttendanceGroupResponse]:
    levels = await access_levels(session, tenant_id, principal, scope)
    if not levels:
        return []
    rows = await session.execute(
        text("""
            SELECT g.id, g.name, g.description, g.legal_entity_id, le.name AS company,
                   (SELECT count(*) FROM attendance_group_members m
                    WHERE m.tenant_id = g.tenant_id AND m.group_id = g.id
                      AND m.effective_from <= :today
                      AND (m.effective_to IS NULL OR m.effective_to > :today)) AS members
            FROM attendance_groups g
            LEFT JOIN legal_entities le ON le.tenant_id = g.tenant_id AND le.id = g.legal_entity_id
            WHERE g.tenant_id = :tid AND g.id = ANY(:ids)
            ORDER BY lower(g.name)
        """),
        {"tid": tenant_id, "ids": list(levels), "today": business_today()},
    )
    manage = can_manage(scope)
    return [
        AttendanceGroupResponse(
            id=to_typed_id("attendance_group", r["id"]),
            name=r["name"],
            description=r["description"],
            legal_entity_id=to_typed_id("legal_entity", r["legal_entity_id"])
            if r["legal_entity_id"]
            else None,
            company=r["company"],
            member_count=r["members"],
            my_access=levels[r["id"]],
            can_manage=manage,
        )
        for r in rows.mappings()
    ]


@router.post(
    "",
    response_model=AttendanceGroupResponse,
    status_code=201,
    summary="Create an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def create_group(
    body: AttendanceGroupCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> AttendanceGroupResponse:
    group = AttendanceGroup(
        tenant_id=tenant_id,
        id=uuid4(),
        name=body.name.strip(),
        description=body.description,
        legal_entity_id=await _entity(session, tenant_id, scope, body.legal_entity_id),
        created_by=principal.user_account_id,
        created_at=now_utc(),
    )
    await _unique_name(session, tenant_id, group.name, None)
    session.add(group)
    await session.flush()
    return await _one(session, tenant_id, principal, scope, group.id)


@router.patch(
    "/{group_id}",
    response_model=AttendanceGroupResponse,
    summary="Rename or describe an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def update_group(
    group_id: str,
    body: AttendanceGroupUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> AttendanceGroupResponse:
    group = await _group(session, tenant_id, group_id)
    fields = body.model_fields_set
    if "name" in fields and body.name:
        await _unique_name(session, tenant_id, body.name.strip(), group.id)
        group.name = body.name.strip()
    if "description" in fields:
        group.description = body.description
    if "legal_entity_id" in fields:
        entity = await _entity(session, tenant_id, scope, body.legal_entity_id)
        if entity:
            outside = await session.execute(
                text("""
                    SELECT 1 FROM attendance_group_members m
                    JOIN employments e ON e.tenant_id = m.tenant_id AND e.id = m.employment_id
                    WHERE m.tenant_id = :tid AND m.group_id = :g AND e.legal_entity_id <> :le
                      AND (m.effective_to IS NULL OR m.effective_to > :today)
                    LIMIT 1
                """),
                {"tid": tenant_id, "g": group.id, "le": entity, "today": business_today()},
            )
            if outside.first():
                raise HTTPException(409, "Some members belong to another company")
        group.legal_entity_id = entity
    group.version += 1
    session.add(group)
    await session.flush()
    return await _one(session, tenant_id, principal, scope, group.id)


@router.delete(
    "/{group_id}",
    status_code=204,
    summary="Retire an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def archive_group(group_id: str, tenant_id: TenantDep, session: SessionDep) -> None:
    group = await _group(session, tenant_id, group_id)
    current = await session.execute(
        text("""
            SELECT 1 FROM attendance_group_members WHERE tenant_id = :tid AND group_id = :g
              AND (effective_to IS NULL OR effective_to > :today) LIMIT 1
        """),
        {"tid": tenant_id, "g": group.id, "today": business_today()},
    )
    if current.first():
        raise HTTPException(409, "Take everyone out of the group before retiring it")
    group.archived_at = now_utc()
    session.add(group)
    await session.flush()


# ─── Members ────────────────────────────────────────────────────────────────────


@router.get(
    "/{group_id}/members",
    response_model=list[GroupMember],
    summary="Who is in an attendance group on a day",
)
async def list_members(
    group_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    on: date | None = Query(default=None),
) -> list[GroupMember]:
    group = await _group(session, tenant_id, group_id)
    await require_group_access(session, tenant_id, principal, scope, group.id, GroupAccess.VIEW)
    # HR sees every group, but only the people their own scope covers (as on the sheet); a
    # person given the group sees all of it.
    clause, params = (
        scope.for_permission(MANAGE).employment_filter_sql("e") if can_manage(scope) else ("", {})
    )
    rows = await session.execute(
        text(f"""
            SELECT e.id, e.employee_number, le.name AS company,
                   p.legal_first_name || ' ' || p.legal_last_name AS name,
                   CASE WHEN ou.type = 'TEAM' THEN parent_ou.name ELSE ou.name END AS department,
                   m.effective_from
            FROM attendance_group_members m
            JOIN employments e ON e.tenant_id = m.tenant_id AND e.id = m.employment_id
            JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
                 AND a.effective_from <= :on AND (a.effective_to IS NULL OR a.effective_to > :on)
            LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
            LEFT JOIN org_units parent_ou ON parent_ou.tenant_id = ou.tenant_id
                 AND parent_ou.id = ou.parent_id
            WHERE m.tenant_id = :tid AND m.group_id = :g AND m.effective_from <= :on
              AND (m.effective_to IS NULL OR m.effective_to > :on)
              {clause}
            ORDER BY name, e.id
        """),
        {"tid": tenant_id, "g": group.id, "on": on or business_today(), **params},
    )
    return [
        GroupMember(
            employment_id=to_typed_id("employment", r["id"]),
            employee_number=r["employee_number"],
            name=r["name"],
            company=r["company"],
            department=r["department"],
            effective_from=r["effective_from"],
        )
        for r in rows.mappings()
    ]


@router.post(
    "/{group_id}/members",
    response_model=list[GroupMember],
    summary="Add people to an attendance group from a date",
    dependencies=[require_permission(MANAGE)],
)
async def add_members(
    group_id: str,
    body: GroupMembersAdd,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[GroupMember]:
    group = await _group(session, tenant_id, group_id)
    ids = list(dict.fromkeys(to_uuid(e) for e in body.employment_ids))
    people_scope = scope.for_permission(MANAGE)
    for emp in ids:
        await authorize_employment(session, tenant_id, people_scope, emp)
    people = {
        r["id"]: r
        for r in (
            await session.execute(
                text("""
                    SELECT e.id, e.legal_entity_id, e.separation_date,
                           p.legal_first_name || ' ' || p.legal_last_name AS name
                    FROM employments e JOIN persons p ON p.tenant_id = e.tenant_id
                         AND p.id = e.person_id
                    WHERE e.tenant_id = :tid AND e.id = ANY(:ids) AND e.archived_at IS NULL
                """),
                {"tid": tenant_id, "ids": ids},
            )
        )
        .mappings()
        .all()
    }
    taken = await session.execute(
        text("""
            SELECT m.employment_id, m.group_id, g.name, m.id FROM attendance_group_members m
            JOIN attendance_groups g ON g.tenant_id = m.tenant_id AND g.id = m.group_id
            WHERE m.tenant_id = :tid AND m.employment_id = ANY(:ids)
              AND (m.effective_to IS NULL OR m.effective_to > :from)
        """),
        {"tid": tenant_id, "ids": ids, "from": body.effective_from},
    )
    already: dict[UUID, tuple[UUID, str]] = {}
    same_group: dict[UUID, list[UUID]] = {}
    for eid, gid, gname, mid in taken.all():
        if gid == group.id:
            same_group.setdefault(eid, []).append(mid)
        else:
            already[eid] = (gid, gname)
    errors = []
    adding = []
    for emp in ids:
        person = people.get(emp)
        if person is None:
            errors.append(f"{to_typed_id('employment', emp)}: not found")
        elif person["separation_date"] and person["separation_date"] <= body.effective_from:
            errors.append(f"{person['name']}: has left by then")
        elif group.legal_entity_id and person["legal_entity_id"] != group.legal_entity_id:
            errors.append(f"{person['name']}: belongs to another company")
        elif emp in already:
            errors.append(f"{person['name']}: already in {already[emp][1]}; take them out first")
        else:
            adding.append(emp)
    if errors:
        raise HTTPException(409, "Nobody was added. " + "; ".join(errors[:10]))
    for emp in adding:
        start = body.effective_from
        rows = [
            row
            for mid in same_group.get(emp, [])
            if (row := await session.get(AttendanceGroupMember, (tenant_id, mid))) is not None
        ]
        if any(r.effective_from <= start and r.effective_to is None for r in rows):
            continue  # in the group since before `start` and still in it: nothing to do
        # Otherwise one open membership from the earliest start replaces the rows that touch
        # `start` onwards, so a gap after leaving closes.
        for row in rows:
            start = min(start, row.effective_from)
            await session.delete(row)
        await session.flush()
        session.add(
            AttendanceGroupMember(
                tenant_id=tenant_id,
                id=uuid4(),
                group_id=group.id,
                employment_id=emp,
                effective_from=start,
                created_by=principal.user_account_id,
                created_at=now_utc(),
            )
        )
    await session.flush()
    return await list_members(
        group_id,
        principal,
        scope,
        tenant_id,
        session,
        on=max(body.effective_from, business_today()),
    )


@router.delete(
    "/{group_id}/members/{employment_id}",
    status_code=204,
    summary="Take someone out of an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def remove_member(
    group_id: str,
    employment_id: str,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    last_day: date | None = Query(
        default=None, description="Their last day in the group (default today)"
    ),
) -> None:
    group = await _group(session, tenant_id, group_id)
    emp = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope.for_permission(MANAGE), emp)
    last = last_day or business_today()
    member = (
        await session.execute(
            select(AttendanceGroupMember)
            .where(AttendanceGroupMember.tenant_id == tenant_id)
            .where(AttendanceGroupMember.group_id == group.id)
            .where(AttendanceGroupMember.employment_id == emp)
            .where(
                (AttendanceGroupMember.effective_to == None)  # noqa: E711
                | (AttendanceGroupMember.effective_to > last)  # type: ignore[operator]
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(404, "Not in this group on that day")
    if member.effective_from > last:
        await session.delete(member)  # it never started
    else:
        member.effective_to = last + timedelta(days=1)
        session.add(member)
    await session.flush()


# ─── Access ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{group_id}/access",
    response_model=list[GroupAccessEntry],
    summary="Who may view or mark an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def list_access(
    group_id: str, tenant_id: TenantDep, session: SessionDep
) -> list[GroupAccessEntry]:
    group = await _group(session, tenant_id, group_id)
    rows = await session.execute(
        text("""
            SELECT a.user_account_id, a.access_level, ua.email, ua.employee_code,
                   p.legal_first_name || ' ' || p.legal_last_name AS person
            FROM attendance_group_access a
            JOIN user_accounts ua ON ua.tenant_id = a.tenant_id AND ua.id = a.user_account_id
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            WHERE a.tenant_id = :tid AND a.group_id = :g
            ORDER BY a.access_level DESC, person, ua.email
        """),
        {"tid": tenant_id, "g": group.id},
    )
    return [
        GroupAccessEntry(
            user_account_id=to_typed_id("user", r["user_account_id"]),
            name=r["person"] or r["email"] or r["employee_code"] or "Unnamed user",
            email=r["email"],
            access_level=r["access_level"],
        )
        for r in rows.mappings()
    ]


@router.put(
    "/{group_id}/access/{user_account_id}",
    response_model=list[GroupAccessEntry],
    summary="Let someone view or mark an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def grant_access(
    group_id: str,
    user_account_id: str,
    body: GroupAccessGrant,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[GroupAccessEntry]:
    group = await _group(session, tenant_id, group_id)
    uid = to_uuid(user_account_id)
    account = await session.execute(
        text("SELECT status FROM user_accounts WHERE tenant_id = :tid AND id = :uid"),
        {"tid": tenant_id, "uid": uid},
    )
    found = account.first()
    if found is None:
        raise HTTPException(404, "User not found")
    if found[0] != "ACTIVE":
        raise HTTPException(422, "This login is not active")
    existing = (
        await session.execute(
            select(AttendanceGroupAccess)
            .where(AttendanceGroupAccess.tenant_id == tenant_id)
            .where(AttendanceGroupAccess.group_id == group.id)
            .where(AttendanceGroupAccess.user_account_id == uid)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = AttendanceGroupAccess(
            tenant_id=tenant_id,
            id=uuid4(),
            group_id=group.id,
            user_account_id=uid,
            access_level=body.access_level,
            created_by=principal.user_account_id,
            created_at=now_utc(),
        )
    existing.access_level = body.access_level
    session.add(existing)
    await session.flush()
    return await list_access(group_id, tenant_id, session)


@router.delete(
    "/{group_id}/access/{user_account_id}",
    status_code=204,
    summary="Withdraw someone's access to an attendance group",
    dependencies=[require_permission(MANAGE)],
)
async def revoke_access(
    group_id: str, user_account_id: str, tenant_id: TenantDep, session: SessionDep
) -> None:
    group = await _group(session, tenant_id, group_id)
    await session.execute(
        text(
            "DELETE FROM attendance_group_access "
            "WHERE tenant_id = :tid AND group_id = :g AND user_account_id = :uid"
        ),
        {"tid": tenant_id, "g": group.id, "uid": to_uuid(user_account_id)},
    )


# ─── Helpers ────────────────────────────────────────────────────────────────────


async def _group(session, tenant_id, group_id: str) -> AttendanceGroup:
    group = await session.get(AttendanceGroup, (tenant_id, to_uuid(group_id)))
    if group is None or group.archived_at is not None:
        raise HTTPException(404, "Attendance group not found")
    return group


async def _one(session, tenant_id, principal, scope, gid: UUID) -> AttendanceGroupResponse:
    return next(
        g
        for g in await list_groups(principal, scope, tenant_id, session)
        if g.id == to_typed_id("attendance_group", gid)
    )


async def _unique_name(session, tenant_id, name: str, keep: UUID | None) -> None:
    clash = await session.execute(
        text("""
            SELECT 1 FROM attendance_groups WHERE tenant_id = :tid AND archived_at IS NULL
              AND lower(name) = lower(:n) AND (CAST(:keep AS uuid) IS NULL OR id <> :keep)
        """),
        {"tid": tenant_id, "n": name, "keep": keep},
    )
    if clash.first():
        raise HTTPException(409, f"A group called “{name}” already exists")


async def _entity(session, tenant_id, scope: Scope, legal_entity_id: str | None) -> UUID | None:
    if not legal_entity_id:
        return None
    entity = to_uuid(legal_entity_id)
    people_scope = scope.for_permission(MANAGE)
    if not people_scope.is_all and entity not in people_scope.legal_entity_ids:
        raise HTTPException(403, "That company is outside your scope")
    found = await session.execute(
        text("SELECT 1 FROM legal_entities WHERE tenant_id = :tid AND id = :id"),
        {"tid": tenant_id, "id": entity},
    )
    if found.first() is None:
        raise HTTPException(404, "Company not found")
    return entity
