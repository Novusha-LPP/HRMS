"""
Marked attendance — the daily sheet of people whose attendance is marked, not punched.

GET  /v1/time/marking?work_date=…      the day for everyone in the groups the caller can see
PUT  /v1/time/marking/{work_date}      mark (or clear) that day for many people at once
GET  /v1/time/marking/leave-types      the leave types a marker can record
POST /v1/time/marking/leave            record leave as a from–to range

Whose days are marked is decided by attendance groups (time/groups.py): being in a group on a
day makes that day marked. The caller sees the groups they were given (VIEW) and marks those
they may MARK; HR managing groups sees and marks every group, for the people in their scope.

A mark is present or absent. Present may carry in and out times: they are stored as punches
with source MARKED and the day is worked out from them exactly like punched days (hours, late,
half day, overtime, off-day work under the person's policy). Without times the day carries the
status as its status_override. Either way the register, the reports and the dashboards read it
like any other day, and a working day nobody marked shows NOT_MARKED, never ABSENT. Every change
is an append-only AttendanceMark. The rules:

- nobody marks their own attendance;
- only today or earlier (and no time later than now), for people employed that day, never a
  locked (closed) day;
- a day with the person's own punches is computed from them, and a day on approved leave shows
  the leave: neither can be marked;
- present on a weekly off or holiday is off-day work; absent on one is refused;
- a save is checked as a whole before anything is written: one refused row refuses the save.

Leave becomes an approved leave application through the leave engine
(leave/router.py, record_approved_leave): type, length, overlap and balance are checked as for
any application. An absent mark on those days is cleared with the leave; a present one refuses it.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import RowMapping, text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, is_working_day, now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.leave.models import LeaveType
from hrms.modules.leave.router import record_approved_leave
from hrms.modules.leave.schemas import LeaveApplicationResponse, LeaveApplyRequest
from hrms.modules.policy.engine import PolicyResolver, ResolvedPolicy
from hrms.modules.time.groups import MANAGE, access_levels, can_manage, group_on, group_spans
from hrms.modules.time.holidays import holiday_scope_sql
from hrms.modules.time.models import (
    AttendanceDay,
    AttendanceMark,
    AttendanceStatus,
    GroupAccess,
    MarkSource,
    MarkStatus,
    Punch,
    PunchSource,
)
from hrms.modules.time.schemas import (
    MarkEntry,
    MarkInfo,
    MarkingLeaveRequest,
    MarkingLeaveType,
    MarkingResponse,
    MarkingResult,
    MarkingRow,
    MarkingUpdate,
)
from hrms.modules.time.service import lock_day, recompute_day

router = APIRouter(prefix="/v1/time/marking", tags=["Time & Attendance"])

NOT_MARKED = "NOT_MARKED"
MAX_ERRORS_SHOWN = 10

# People in a group on :d with their placement that day. Team members belong to their parent
# department, as in the attendance register.
_PEOPLE_SQL = """
    SELECT e.id, e.employee_number, e.legal_entity_id, le.name AS company,
           p.legal_first_name || ' ' || p.legal_last_name AS name,
           a.org_unit_id,
           CASE WHEN ou.type = 'TEAM' THEN parent_ou.name ELSE ou.name END AS department,
           g.id AS group_id, g.name AS group_name
    FROM attendance_group_members m
    JOIN attendance_groups g ON g.tenant_id = m.tenant_id AND g.id = m.group_id
    JOIN employments e ON e.tenant_id = m.tenant_id AND e.id = m.employment_id
    JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
         AND a.effective_from <= :d AND (a.effective_to IS NULL OR a.effective_to > :d)
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
    LEFT JOIN org_units parent_ou ON parent_ou.tenant_id = ou.tenant_id
         AND parent_ou.id = ou.parent_id
    WHERE m.tenant_id = :tid AND m.effective_from <= :d
      AND (m.effective_to IS NULL OR m.effective_to > :d)
      AND e.archived_at IS NULL
      AND e.hire_date <= :d AND (e.separation_date IS NULL OR e.separation_date > :d)
      AND g.id = ANY(:groups)
"""


@dataclass
class _Person:
    id: UUID
    employee_number: str | None
    name: str
    company: str
    department: str | None
    group_id: UUID
    group_name: str
    access: str
    policy: ResolvedPolicy


@dataclass
class _Mark:
    """A day's current mark: the status and any times a marker entered."""

    status: str | None
    punch_in: datetime | None = None
    punch_out: datetime | None = None


@router.get(
    "",
    response_model=MarkingResponse,
    summary="A day's marked attendance for the groups you can see",
)
async def marking_day(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    work_date: date = Query(...),
    group_id: str | None = Query(default=None),
    legal_entity_id: str | None = Query(default=None),
) -> MarkingResponse:
    people = await _people(
        session,
        tenant_id,
        principal,
        scope,
        work_date,
        group_id=to_uuid(group_id) if group_id else None,
        legal_entity_id=to_uuid(legal_entity_id) if legal_entity_id else None,
    )
    rows = await _rows(session, tenant_id, principal, work_date, people)
    return MarkingResponse(
        work_date=work_date, rows=rows, counts=dict(Counter(r.status for r in rows))
    )


@router.put(
    "/{work_date}",
    response_model=MarkingResult,
    summary="Mark a day present or absent (or clear it) for many people at once",
)
async def mark_day(
    work_date: date,
    body: MarkingUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> MarkingResult:
    ids = [to_uuid(m.employment_id) for m in body.marks]
    people = {
        p.id: p for p in await _people(session, tenant_id, principal, scope, work_date, ids=ids)
    }
    if not people and not await access_levels(session, tenant_id, principal, scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't mark attendance")
    rows = {
        to_uuid(r.employment_id): r
        for r in await _rows(session, tenant_id, principal, work_date, list(people.values()))
    }
    now = now_utc()

    errors: list[str] = []
    planned = []
    for entry, emp in zip(body.marks, ids, strict=True):
        person = people.get(emp)
        if person is None:
            errors.append(
                f"{entry.employment_id}: not in a group you can mark on that day, or not employed"
            )
            continue
        row = rows[emp]
        target = _wanted(entry, work_date, person.policy)
        if not row.can_mark:
            errors.append(f"{person.name}: {row.blocked_reason}")
        elif entry.status == MarkStatus.ABSENT and row.is_off_day:
            errors.append(f"{person.name}: a day off can't be marked absent")
        elif target.punch_in and target.punch_in > now:
            errors.append(f"{person.name}: the in time is later than now")
        elif target.punch_out and target.punch_out > now:
            errors.append(f"{person.name}: the out time is later than now")
        elif target.punch_in and (
            clash := await _neighbour_clash(
                session, tenant_id, person.id, work_date, target.punch_in, target.punch_out
            )
        ):
            errors.append(f"{person.name}: these times overlap the shift on {clash:%d %b}")
        else:
            planned.append((person, row, entry, target))
    if errors:
        shown = "; ".join(errors[:MAX_ERRORS_SHOWN])
        more = (
            f" (and {len(errors) - MAX_ERRORS_SHOWN} more)"
            if len(errors) > MAX_ERRORS_SHOWN
            else ""
        )
        raise HTTPException(
            422, f"Nothing was saved. {len(errors)} row(s) can't be marked: {shown}{more}"
        )

    source = MarkSource.INTEGRATION if principal.via_key_id else MarkSource.MANUAL
    changed = unchanged = 0
    for person, row, entry, target in planned:
        ad = await lock_day(session, tenant_id, person.id, work_date)
        if ad and ad.is_locked:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A day was locked while you were marking. Reload."
            )
        if await _own_punches(session, tenant_id, [person.id], work_date):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Someone punched while you were marking. Reload."
            )
        if await _approved_leave_on(session, tenant_id, person.id, work_date):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Leave was approved for {person.name} while you were marking. Reload.",
            )
        current = await _current_mark(session, tenant_id, person.id, work_date, ad)
        if current == target:
            unchanged += 1
            continue
        await _apply(session, tenant_id, principal, person, work_date, ad, current, target, row)
        session.add(
            AttendanceMark(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=person.id,
                work_date=work_date,
                status=target.status,
                punch_in=target.punch_in,
                punch_out=target.punch_out,
                remark=entry.remark or body.remark,
                source=source,
                marked_by=principal.user_account_id,
                marked_at=now,
            )
        )
        changed += 1
    await session.flush()

    refreshed = await _rows(session, tenant_id, principal, work_date, [p for p, *_ in planned])
    return MarkingResult(work_date=work_date, changed=changed, unchanged=unchanged, rows=refreshed)


@router.get(
    "/leave-types",
    response_model=list[MarkingLeaveType],
    summary="Leave types a marker can record",
)
async def marking_leave_types(
    principal: CurrentUser, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> list[MarkingLeaveType]:
    levels = await access_levels(session, tenant_id, principal, scope)
    if GroupAccess.MARK not in levels.values():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't record leave")
    types = (
        await session.execute(
            select(LeaveType)
            .where(LeaveType.tenant_id == tenant_id)
            .where(LeaveType.is_active == True)  # noqa: E712
            .where(LeaveType.archived_at == None)  # noqa: E711
            .order_by(LeaveType.name)
        )
    ).scalars()
    return [
        MarkingLeaveType(
            id=to_typed_id("leave_type", lt.id), name=lt.name, code=lt.code, is_paid=lt.is_paid
        )
        for lt in types
    ]


@router.post(
    "/leave",
    response_model=LeaveApplicationResponse,
    status_code=201,
    summary="Record leave from one date to another for someone whose attendance is marked",
)
async def record_leave(
    body: MarkingLeaveRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> LeaveApplicationResponse:
    emp = to_uuid(body.employment_id)
    if emp == principal.employment_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't record your own leave — apply for it instead"
        )
    for edge in {body.from_date, body.to_date}:
        found = await _people(session, tenant_id, principal, scope, edge, ids=[emp])
        if not found or found[0].access != GroupAccess.MARK:
            raise HTTPException(
                422,
                f"On {edge:%d %b %Y} this person is not employed, or not in a group you can mark "
                "(people who punch apply for leave themselves)",
            )
    # Every day in between too: someone who left the group for a while punched those days.
    levels = await access_levels(session, tenant_id, principal, scope, include_archived=True)
    spans = (await group_spans(session, tenant_id, [emp], body.from_date, body.to_date)).get(emp)
    outside = []
    day = body.from_date
    while day <= body.to_date:
        group = group_on(spans, day)
        if group is None or levels.get(group) != GroupAccess.MARK:
            outside.append(day)
        day += timedelta(days=1)
    if outside:
        listed = ", ".join(f"{d:%d %b}" for d in outside[:10])
        raise HTTPException(
            422, f"Not in a group you can mark on {listed}: record leave only for those days"
        )

    present, absent = [], []
    day = body.from_date
    while day <= body.to_date:
        ad = await lock_day(session, tenant_id, emp, day)
        if ad and ad.is_locked:
            raise HTTPException(409, f"{day:%d %b %Y} is locked (period closed)")
        if await _own_punches(session, tenant_id, [emp], day):
            raise HTTPException(409, f"{day:%d %b %Y} has punches; leave can't cover it")
        mark = await _current_mark(session, tenant_id, emp, day, ad)
        if mark.status == MarkStatus.PRESENT:
            present.append(day)
        elif mark.status == MarkStatus.ABSENT and ad is not None:
            absent.append(ad)
        day += timedelta(days=1)
    if present:
        listed = ", ".join(f"{d:%d %b}" for d in present)
        raise HTTPException(
            409, f"Marked present on {listed}. Clear those marks first if the person was on leave."
        )

    result = await record_approved_leave(
        session,
        tenant_id,
        principal,
        emp,
        LeaveApplyRequest(
            leave_type_id=body.leave_type_id,
            from_date=body.from_date,
            to_date=body.to_date,
            half_day_option=body.half_day_option,
            reason=body.reason,
        ),
        comments="Recorded by the attendance marker",
    )
    stamp = now_utc()
    for ad in absent:
        # The leave says what the day was: the absent mark goes, and its history says why.
        session.add(
            AttendanceMark(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=emp,
                work_date=ad.work_date,
                status=None,
                remark="Cleared: leave recorded for this day",
                source=MarkSource.INTEGRATION if principal.via_key_id else MarkSource.MANUAL,
                marked_by=principal.user_account_id,
                marked_at=stamp,
            )
        )
        await session.delete(ad)
    await session.flush()
    return result


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _wanted(entry: MarkEntry, day: date, policy: ResolvedPolicy) -> _Mark:
    """The mark a row asks for, with its times placed on the person's clock."""
    if not entry.punch_in:
        return _Mark(entry.status)
    zone = ZoneInfo(policy.timezone)
    start = datetime.combine(day, time.fromisoformat(entry.punch_in), zone)
    end = None
    if entry.punch_out:
        end = datetime.combine(day, time.fromisoformat(entry.punch_out), zone)
        if end <= start:
            end += timedelta(days=1)  # a night shift ends the next morning
    return _Mark(MarkStatus.PRESENT, start, end)


async def _marked_punches(session, tenant_id, emp, day) -> list[RowMapping]:
    """Times a marker entered for the day that are still in force (not voided)."""
    rows = await session.execute(
        text("""
            SELECT p.id, p.punch_type, p.punched_at FROM punches p
            WHERE p.tenant_id = :tid AND p.employment_id = :e AND p.work_date = :d
              AND p.source = 'MARKED' AND p.punch_type <> 'VOID'
              AND NOT EXISTS (SELECT 1 FROM punches v WHERE v.tenant_id = p.tenant_id
                              AND v.punch_type = 'VOID' AND v.original_punch_id = p.id)
        """),
        {"tid": tenant_id, "e": emp, "d": day},
    )
    return list(rows.mappings().all())


async def _approved_leave_on(session, tenant_id, emp, day) -> bool:
    found = await session.execute(
        text("""
            SELECT 1 FROM leave_applications WHERE tenant_id = :tid AND employment_id = :e
              AND status = 'APPROVED' AND from_date <= :d AND to_date >= :d LIMIT 1
        """),
        {"tid": tenant_id, "e": emp, "d": day},
    )
    return found.first() is not None


async def _neighbour_clash(session, tenant_id, emp, day, start, end) -> date | None:
    """The day before or after whose recorded shift overlaps start..end (a night shift's
    morning, say), if any. An open shift (no out yet) counts as a moment."""
    rows = await session.execute(
        text("""
            SELECT p.work_date,
                   min(p.punched_at) FILTER (WHERE p.punch_type = 'IN') AS first_in,
                   max(p.punched_at) FILTER (WHERE p.punch_type = 'OUT') AS last_out
            FROM punches p
            WHERE p.tenant_id = :tid AND p.employment_id = :e
              AND p.work_date IN (:before, :after) AND p.punch_type IN ('IN', 'OUT')
              AND NOT EXISTS (SELECT 1 FROM punches v WHERE v.tenant_id = p.tenant_id
                              AND v.punch_type = 'VOID' AND v.original_punch_id = p.id)
            GROUP BY p.work_date
        """),
        {
            "tid": tenant_id,
            "e": emp,
            "before": day - timedelta(days=1),
            "after": day + timedelta(days=1),
        },
    )
    finish = end or start + timedelta(minutes=1)
    for other_day, first_in, last_out in rows.all():
        if first_in is None:
            continue
        if first_in < finish and (last_out or first_in + timedelta(minutes=1)) > start:
            return other_day
    return None


async def _own_punches(session, tenant_id, ids: list[UUID], day: date) -> set[UUID]:
    """People who punched themselves (any source but MARKED) on the day, voided ones aside."""
    rows = await session.execute(
        text("""
            SELECT DISTINCT p.employment_id FROM punches p
            WHERE p.tenant_id = :tid AND p.employment_id = ANY(:ids) AND p.work_date = :d
              AND p.source <> 'MARKED' AND p.punch_type <> 'VOID'
              AND NOT EXISTS (SELECT 1 FROM punches v WHERE v.tenant_id = p.tenant_id
                              AND v.punch_type = 'VOID' AND v.original_punch_id = p.id)
        """),
        {"tid": tenant_id, "ids": ids, "d": day},
    )
    return {r[0] for r in rows.all()}


async def _current_mark(session, tenant_id, emp, day, ad: AttendanceDay | None) -> _Mark:
    punches = await _marked_punches(session, tenant_id, emp, day)
    if punches:
        ins = [p["punched_at"] for p in punches if p["punch_type"] == "IN"]
        outs = [p["punched_at"] for p in punches if p["punch_type"] == "OUT"]
        return _Mark(MarkStatus.PRESENT, min(ins) if ins else None, max(outs) if outs else None)
    if ad is None or not ad.status_override:
        return _Mark(None)
    if ad.status_override == AttendanceStatus.OFF_DAY_WORKED:
        return _Mark(MarkStatus.PRESENT)
    if ad.status_override in set(MarkStatus):
        return _Mark(ad.status_override)
    return _Mark(None)


async def _apply(session, tenant_id, principal, person, day, ad, current, target, row):
    stamp = now_utc()
    if current.punch_in is not None:
        # The marker's earlier times go (voided, never deleted, as in the register).
        for punch in await _marked_punches(session, tenant_id, person.id, day):
            session.add(
                Punch(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    employment_id=person.id,
                    work_date=day,
                    punch_type="VOID",
                    punched_at=punch["punched_at"],
                    source=PunchSource.MARKED,
                    is_corrected=True,
                    original_punch_id=punch["id"],
                    correction_reason="Changed on the marking sheet",
                    recorded_at=stamp,
                    recorded_by=principal.user_account_id,
                )
            )
        await session.flush()

    if target.status is None:
        if ad is not None:
            await session.delete(ad)  # nothing else lives on a marked day without punches
            await session.flush()
        return
    ad = ad or AttendanceDay(
        tenant_id=tenant_id, id=uuid4(), employment_id=person.id, work_date=day, recorded_at=stamp
    )
    if target.punch_in is not None:
        for kind, instant in (("IN", target.punch_in), ("OUT", target.punch_out)):
            if instant is None:
                continue
            session.add(
                Punch(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    employment_id=person.id,
                    work_date=day,
                    punch_type=kind,
                    punched_at=instant,
                    source=PunchSource.MARKED,
                    recorded_at=stamp,
                    recorded_by=principal.user_account_id,
                )
            )
        await session.flush()
        # Times decide the day, under the person's policy, like any punched day.
        await recompute_day(
            session, tenant_id, person.id, day, person.policy, ad, clear_override=True
        )
        return
    off_day_work = target.status == MarkStatus.PRESENT and row.is_off_day
    ad.status_override = AttendanceStatus.OFF_DAY_WORKED if off_day_work else target.status
    ad.override_note = "Marked present" if target.status == MarkStatus.PRESENT else "Marked absent"
    await recompute_day(session, tenant_id, person.id, day, person.policy, ad)


async def _people(
    session,
    tenant_id: UUID,
    principal,
    scope,
    day: date,
    *,
    ids: list[UUID] | None = None,
    group_id: UUID | None = None,
    legal_entity_id: UUID | None = None,
) -> list[_Person]:
    """People in the groups the caller can see on `day`, with what the caller may do.
    HR also reaches retired groups here: their members' past days stay correctable."""
    levels = await access_levels(session, tenant_id, principal, scope, include_archived=True)
    groups = [g for g in levels if group_id is None or g == group_id]
    if not groups:
        return []
    sql = _PEOPLE_SQL
    params: dict[str, object] = {"tid": tenant_id, "d": day, "groups": groups}
    if can_manage(scope):
        # HR sees every group, but only the people their own scope covers.
        clause, extra = scope.for_permission(MANAGE).employment_filter_sql("e")
        sql += f" {clause}"
        params.update(extra)
    if ids is not None:
        sql += " AND e.id = ANY(:ids)"
        params["ids"] = ids
    if legal_entity_id:
        sql += " AND e.legal_entity_id = :le"
        params["le"] = legal_entity_id
    rows = (await session.execute(text(sql + " ORDER BY name, e.id"), params)).mappings().all()
    resolver = PolicyResolver(session, tenant_id, day)
    people = []
    for row in rows:
        policy = await resolver.resolve(
            row["id"], org_unit_id=row["org_unit_id"], legal_entity_id=row["legal_entity_id"]
        )
        people.append(
            _Person(
                id=row["id"],
                employee_number=row["employee_number"],
                name=row["name"],
                company=row["company"],
                department=row["department"],
                group_id=row["group_id"],
                group_name=row["group_name"],
                access=levels[row["group_id"]],
                policy=policy,
            )
        )
    return people


async def _rows(session, tenant_id, principal, day, people: list[_Person]) -> list[MarkingRow]:
    if not people:
        return []
    ids = [person.id for person in people]
    stored = {
        ad.employment_id: ad
        for ad in (
            await session.execute(
                select(AttendanceDay)
                .where(AttendanceDay.tenant_id == tenant_id)
                .where(AttendanceDay.work_date == day)
                .where(AttendanceDay.employment_id.in_(ids))  # type: ignore[attr-defined]
            )
        ).scalars()
    }
    holidays = dict(
        (
            await session.execute(
                text(f"""
                    SELECT e.id, h.name FROM employments e
                    JOIN holidays h ON h.tenant_id = e.tenant_id AND h.holiday_date = :d
                         AND h.archived_at IS NULL AND h.is_optional = false
                         AND {holiday_scope_sql("h", "e.id")}
                    WHERE e.tenant_id = :tid AND e.id = ANY(:ids)
                """),
                {"tid": tenant_id, "d": day, "ids": ids},
            )
        ).all()
    )
    leaves = dict(
        (
            await session.execute(
                text("""
                    SELECT la.employment_id, lt.name FROM leave_applications la
                    JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
                    WHERE la.tenant_id = :tid AND la.employment_id = ANY(:ids)
                      AND la.status = 'APPROVED' AND la.from_date <= :d AND la.to_date >= :d
                """),
                {"tid": tenant_id, "d": day, "ids": ids},
            )
        ).all()
    )
    own = await _own_punches(session, tenant_id, ids, day)
    marks: dict[UUID, RowMapping] = {}
    for m in (
        await session.execute(
            text("""
                SELECT m.employment_id, m.status, m.punch_in, m.punch_out, m.remark,
                       m.marked_at, m.source,
                       COALESCE(mp.legal_first_name || ' ' || mp.legal_last_name,
                                ua.employee_code, ua.email) AS marked_by
                FROM attendance_marks m
                JOIN user_accounts ua ON ua.tenant_id = m.tenant_id AND ua.id = m.marked_by
                LEFT JOIN employments me ON me.tenant_id = ua.tenant_id AND me.id = ua.employment_id
                LEFT JOIN persons mp ON mp.tenant_id = me.tenant_id AND mp.id = me.person_id
                WHERE m.tenant_id = :tid AND m.work_date = :d AND m.employment_id = ANY(:ids)
                ORDER BY m.marked_at DESC, m.id
            """),
            {"tid": tenant_id, "d": day, "ids": ids},
        )
    ).mappings():
        marks.setdefault(m["employment_id"], m)

    today = business_today()
    rows = []
    for person in people:
        ad = stored.get(person.id)
        holiday = holidays.get(person.id)
        leave = leaves.get(person.id)
        policy = person.policy
        working = is_working_day(day, policy.work_days, policy.saturday_pattern)
        punched = person.id in own
        timed = ad is not None and ad.first_punch_in is not None
        if ad is not None and timed:
            state = ad.status
        elif leave:
            state = "ON_LEAVE"
        elif ad is not None and ad.status_override:
            state = ad.status
        elif holiday:
            state = "HOLIDAY"
        elif not working:
            state = "WEEKEND"
        elif day > today:
            state = "UPCOMING"
        else:
            state = NOT_MARKED
        if person.access != GroupAccess.MARK:
            blocked = "View only"
        elif person.id == principal.employment_id:
            blocked = "You can't mark your own attendance"
        elif day > today:
            blocked = "A future day can't be marked"
        elif ad is not None and ad.is_locked:
            blocked = "The day is locked (period closed)"
        elif punched:
            blocked = "They punched this day; correct it in the attendance register"
        elif leave:
            blocked = f"On approved leave ({leave})"
        else:
            blocked = None
        mark = marks.get(person.id)
        rows.append(
            MarkingRow(
                employment_id=to_typed_id("employment", person.id),
                employee_number=person.employee_number,
                name=person.name,
                company=person.company,
                department=person.department,
                group_id=to_typed_id("attendance_group", person.group_id),
                group_name=person.group_name,
                access=person.access,
                status=state,
                is_off_day=bool(holiday) or not working,
                holiday_name=holiday,
                leave_type=leave,
                has_punches=punched,
                punch_in=ad.first_punch_in if ad is not None and not punched else None,
                punch_out=ad.last_punch_out if ad is not None and not punched else None,
                worked_minutes=ad.effective_minutes if ad is not None else 0,
                late_by_minutes=ad.late_by_minutes if ad is not None else 0,
                timezone=policy.timezone,
                is_locked=bool(ad is not None and ad.is_locked),
                can_mark=blocked is None,
                blocked_reason=blocked,
                mark=MarkInfo(
                    status=mark["status"],
                    punch_in=mark["punch_in"],
                    punch_out=mark["punch_out"],
                    remark=mark["remark"],
                    marked_by=mark["marked_by"],
                    marked_at=mark["marked_at"],
                    source=mark["source"],
                )
                if mark
                else None,
            )
        )
    return rows
