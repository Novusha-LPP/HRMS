"""
Holiday calendars — named lists of holidays, each followed by the whole company, a legal entity,
a department (with its sub-units) or one employee. The most specific assignment wins.

GET    /v1/time/holiday-calendars?year=                     calendars with days and assignments
POST   /v1/time/holiday-calendars                           create (optionally copy another)
PATCH  /v1/time/holiday-calendars/{id}                      rename
DELETE /v1/time/holiday-calendars/{id}                      archive (and its assignments)
POST   /v1/time/holiday-calendars/{id}/days                 add a holiday
PATCH  /v1/time/holiday-calendars/{id}/days/{day_id}        optional / rename
DELETE /v1/time/holiday-calendars/{id}/days/{day_id}        remove from this calendar
POST   /v1/time/holiday-calendars/{id}/assignments          assign to company/entity/dept/person
DELETE /v1/time/holiday-calendars/{id}/assignments/{aid}    remove an assignment
GET    /v1/time/holiday-calendars/coverage?on=              how many people follow each calendar

Holidays are one shared list per tenant: a date several calendars observe (Diwali, Republic Day)
is a single row linked from each calendar, so renaming it renames it everywhere.
Managed with leave.write, like the rest of the holiday and leave catalog.
"""

from collections import defaultdict
from datetime import date, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authz import require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, now_utc
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.time.models import (
    Holiday,
    HolidayCalendar,
    HolidayCalendarAssignment,
    HolidayCalendarDay,
)
from hrms.modules.time.schemas import (
    CalendarAssignmentCreate,
    CalendarAssignmentOut,
    CalendarCoverage,
    CalendarDayCreate,
    CalendarDayOut,
    CalendarDaysSet,
    CalendarDayUpdate,
    HolidayCalendarCreate,
    HolidayCalendarOut,
    HolidayCalendarUpdate,
    LibraryCalendarRef,
    LibraryHoliday,
    LibraryHolidayCreate,
    LibraryHolidayUpdate,
)

router = APIRouter(
    prefix="/v1/time/holiday-calendars",
    tags=["Holiday calendars"],
    dependencies=[require_permission("leave.write")],
)

TARGET_COLUMN = {
    "LEGAL_ENTITY": "legal_entity_id",
    "DEPARTMENT": "org_unit_id",
    "EMPLOYEE": "employment_id",
}


@router.get("/coverage", response_model=list[CalendarCoverage])
async def coverage(
    tenant_id: TenantDep, session: SessionDep, on: date | None = Query(default=None)
) -> list[CalendarCoverage]:
    counts = await _people_per_calendar(session, tenant_id, on or business_today())
    names = {c.id: c.name for c in await _calendars(session, tenant_id)}
    return [
        CalendarCoverage(
            calendar_id=to_typed_id("holiday_calendar", cid) if cid else None,
            name=names.get(cid, "No calendar") if cid else "No calendar",
            people=n,
        )
        for cid, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


# ─── The holiday list ─────────────────────────────────────────────────────────


@router.get("/library", response_model=list[LibraryHoliday])
async def list_library(
    tenant_id: TenantDep, session: SessionDep, year: int = Query(...)
) -> list[LibraryHoliday]:
    rows = await session.execute(
        select(Holiday)
        .where(
            Holiday.tenant_id == tenant_id,
            Holiday.is_library == True,  # noqa: E712
            Holiday.archived_at == None,  # noqa: E711
            Holiday.holiday_date >= date(year, 1, 1),
            Holiday.holiday_date <= date(year, 12, 31),
        )
        .order_by(col(Holiday.holiday_date), col(Holiday.name))
    )
    holidays = list(rows.scalars())
    names = {c.id: c.name for c in await _calendars(session, tenant_id)}
    used = defaultdict(list)
    if holidays:
        for d in (
            await session.execute(
                select(HolidayCalendarDay).where(
                    HolidayCalendarDay.tenant_id == tenant_id,
                    col(HolidayCalendarDay.holiday_id).in_([h.id for h in holidays]),
                )
            )
        ).scalars():
            if d.calendar_id in names:
                used[d.holiday_id].append(
                    LibraryCalendarRef(
                        id=to_typed_id("holiday_calendar", d.calendar_id),
                        name=names[d.calendar_id],
                        is_optional=d.is_optional,
                    )
                )
    return [_library_out(h, sorted(used[h.id], key=lambda r: r.name)) for h in holidays]


@router.post("/library", response_model=LibraryHoliday, status_code=201)
async def add_library_holiday(
    body: LibraryHolidayCreate, tenant_id: TenantDep, session: SessionDep
) -> LibraryHoliday:
    existing = await _shared_holiday_on(session, tenant_id, body.holiday_date)
    if existing:
        raise HTTPException(
            409, f"{existing.name} is already on {body.holiday_date:%d %b %Y} — rename it instead"
        )
    holiday = Holiday(
        tenant_id=tenant_id,
        id=uuid4(),
        holiday_date=body.holiday_date,
        name=body.name.strip(),
        holiday_type="company",
        is_library=True,
        recorded_at=now_utc(),
    )
    session.add(holiday)
    await session.flush()
    return _library_out(holiday, [])


@router.patch("/library/{holiday_id}", response_model=LibraryHoliday)
async def update_library_holiday(
    holiday_id: str, body: LibraryHolidayUpdate, tenant_id: TenantDep, session: SessionDep
) -> LibraryHoliday:
    holiday = await _holiday(session, tenant_id, to_uuid(holiday_id))
    if body.holiday_date and body.holiday_date != holiday.holiday_date:
        if body.holiday_date.year != holiday.holiday_date.year:
            raise HTTPException(422, "Keep the holiday in the same year")
        clash = await _shared_holiday_on(session, tenant_id, body.holiday_date)
        if clash and clash.id != holiday.id:
            raise HTTPException(409, f"{clash.name} is already on {body.holiday_date:%d %b %Y}")
        holiday.holiday_date = body.holiday_date
    if body.name and body.name.strip():
        holiday.name = body.name.strip()
    session.add(holiday)
    await session.flush()
    return _library_out(holiday, [])


@router.delete("/library/{holiday_id}", status_code=204)
async def delete_library_holiday(
    holiday_id: str, tenant_id: TenantDep, session: SessionDep
) -> None:
    """Remove a holiday from the list — and from every calendar that included it."""
    holiday = await _holiday(session, tenant_id, to_uuid(holiday_id))
    holiday.archived_at = now_utc()
    session.add(holiday)
    for d in (
        await session.execute(
            select(HolidayCalendarDay).where(
                HolidayCalendarDay.tenant_id == tenant_id,
                HolidayCalendarDay.holiday_id == holiday.id,
            )
        )
    ).scalars():
        await session.delete(d)
    await session.flush()


def _library_out(h: Holiday, calendars) -> LibraryHoliday:
    return LibraryHoliday(
        id=to_typed_id("holiday", h.id),
        holiday_date=h.holiday_date,
        name=h.name,
        holiday_type=h.holiday_type,
        calendars=calendars,
    )


# ─── Calendars ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[HolidayCalendarOut])
async def list_calendars(
    tenant_id: TenantDep, session: SessionDep, year: int | None = Query(default=None)
) -> list[HolidayCalendarOut]:
    calendars = [c for c in await _calendars(session, tenant_id) if year is None or c.year == year]
    return await _render(session, tenant_id, calendars)


@router.post("", response_model=HolidayCalendarOut, status_code=201)
async def create_calendar(
    body: HolidayCalendarCreate, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    name = body.name.strip()
    await _unique_name(session, tenant_id, name, body.year)
    cal = HolidayCalendar(
        tenant_id=tenant_id, id=uuid4(), name=name, year=body.year, recorded_at=now_utc()
    )
    session.add(cal)
    await session.flush()
    for hid in dict.fromkeys(body.holiday_ids):
        holiday = await _holiday(session, tenant_id, to_uuid(hid))
        if holiday.holiday_date.year != cal.year:
            raise HTTPException(422, f"{holiday.name} isn't in {cal.year}")
        session.add(
            HolidayCalendarDay(
                tenant_id=tenant_id,
                id=uuid4(),
                calendar_id=cal.id,
                holiday_id=holiday.id,
                recorded_at=now_utc(),
            )
        )
    if body.copy_from:
        source = await _calendar(session, tenant_id, body.copy_from)
        for day in await _days(session, tenant_id, [source.id]):
            session.add(
                HolidayCalendarDay(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    calendar_id=cal.id,
                    holiday_id=day.holiday_id,
                    is_optional=day.is_optional,
                    recorded_at=now_utc(),
                )
            )
    if body.assign_company:
        await _assign(
            session,
            tenant_id,
            cal,
            CalendarAssignmentCreate(target="COMPANY", replace=True),
        )
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.patch("/{calendar_id}", response_model=HolidayCalendarOut)
async def rename_calendar(
    calendar_id: str, body: HolidayCalendarUpdate, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    name = body.name.strip()
    if name != cal.name:
        await _unique_name(session, tenant_id, name, cal.year)
        cal.name = name
        session.add(cal)
        await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.delete("/{calendar_id}", status_code=204)
async def archive_calendar(calendar_id: str, tenant_id: TenantDep, session: SessionDep) -> None:
    cal = await _calendar(session, tenant_id, calendar_id)
    stamp = now_utc()
    cal.archived_at = stamp
    session.add(cal)
    for a in await _assignments(session, tenant_id, [cal.id]):
        a.archived_at = stamp
        session.add(a)
    await session.flush()


@router.post("/{calendar_id}/days", response_model=HolidayCalendarOut, status_code=201)
async def add_day(
    calendar_id: str, body: CalendarDayCreate, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    if body.holiday_id:
        holiday = await _holiday(session, tenant_id, to_uuid(body.holiday_id))
    else:
        holiday = await _shared_holiday_on(session, tenant_id, body.holiday_date) or Holiday(
            tenant_id=tenant_id,
            id=uuid4(),
            holiday_date=body.holiday_date,
            name=body.name.strip(),
            holiday_type="company",
            is_library=True,
            recorded_at=now_utc(),
        )
        session.add(holiday)
        await session.flush()
    if holiday.holiday_date.year != cal.year:
        raise HTTPException(422, f"{cal.name} is the {cal.year} calendar")
    existing = await _days(session, tenant_id, [cal.id])
    if any(d.holiday_id == holiday.id for d in existing):
        raise HTTPException(409, f"{holiday.name} is already on {cal.name}")
    session.add(
        HolidayCalendarDay(
            tenant_id=tenant_id,
            id=uuid4(),
            calendar_id=cal.id,
            holiday_id=holiday.id,
            is_optional=body.is_optional,
            recorded_at=now_utc(),
        )
    )
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.patch("/{calendar_id}/days/{day_id}", response_model=HolidayCalendarOut)
async def update_day(
    calendar_id: str,
    day_id: str,
    body: CalendarDayUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    day = await _day(session, tenant_id, cal.id, day_id)
    if body.is_optional is not None:
        day.is_optional = body.is_optional
        session.add(day)
    if body.name and body.name.strip():
        holiday = await _holiday(session, tenant_id, day.holiday_id)
        holiday.name = body.name.strip()  # shared: renames it on every calendar
        session.add(holiday)
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.delete("/{calendar_id}/days/{day_id}", response_model=HolidayCalendarOut)
async def remove_day(
    calendar_id: str, day_id: str, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    day = await _day(session, tenant_id, cal.id, day_id)
    # The holiday stays on the holiday list; it just isn't a day off for this calendar's people.
    await session.delete(day)
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.put("/{calendar_id}/days", response_model=HolidayCalendarOut)
async def set_days(
    calendar_id: str, body: CalendarDaysSet, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    """Make the calendar's holidays exactly this selection from the holiday list."""
    cal = await _calendar(session, tenant_id, calendar_id)
    want = {}
    for choice in body.holidays:
        holiday = await _holiday(session, tenant_id, to_uuid(choice.holiday_id))
        if holiday.holiday_date.year != cal.year:
            raise HTTPException(422, f"{holiday.name} isn't in {cal.year}")
        want[holiday.id] = choice.is_optional
    have = {d.holiday_id: d for d in await _days(session, tenant_id, [cal.id])}
    for hid, day in have.items():
        if hid not in want:
            await session.delete(day)
        elif day.is_optional != want[hid]:
            day.is_optional = want[hid]
            session.add(day)
    for hid, optional in want.items():
        if hid not in have:
            session.add(
                HolidayCalendarDay(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    calendar_id=cal.id,
                    holiday_id=hid,
                    is_optional=optional,
                    recorded_at=now_utc(),
                )
            )
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.post("/{calendar_id}/assignments", response_model=HolidayCalendarOut, status_code=201)
async def assign_calendar(
    calendar_id: str, body: CalendarAssignmentCreate, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    await _assign(session, tenant_id, cal, body)
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


@router.delete("/{calendar_id}/assignments/{assignment_id}", response_model=HolidayCalendarOut)
async def unassign_calendar(
    calendar_id: str, assignment_id: str, tenant_id: TenantDep, session: SessionDep
) -> HolidayCalendarOut:
    cal = await _calendar(session, tenant_id, calendar_id)
    found = [
        a
        for a in await _assignments(session, tenant_id, [cal.id])
        if a.id == to_uuid(assignment_id)
    ]
    if not found:
        raise HTTPException(404, "Assignment not found")
    found[0].archived_at = now_utc()
    session.add(found[0])
    await session.flush()
    return (await _render(session, tenant_id, [cal]))[0]


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _assign(session, tenant_id, cal, body: CalendarAssignmentCreate) -> None:
    column = TARGET_COLUMN.get(body.target)
    target = to_uuid(body.target_id) if body.target_id else None
    if column:
        await _target_name(session, tenant_id, body.target, target)  # 404 when it doesn't exist
    start = body.effective_from or date(cal.year, 1, 1)
    end = body.effective_to
    same_target = (
        await session.execute(
            select(HolidayCalendarAssignment).where(
                HolidayCalendarAssignment.tenant_id == tenant_id,
                HolidayCalendarAssignment.archived_at == None,  # noqa: E711
                *[
                    (getattr(HolidayCalendarAssignment, c) == target)
                    if c == column
                    else (getattr(HolidayCalendarAssignment, c) == None)  # noqa: E711
                    for c in TARGET_COLUMN.values()
                ],
            )
        )
    ).scalars()
    live = {c.id for c in await _calendars(session, tenant_id)}
    clashes = [
        a
        for a in same_target
        if a.calendar_id in live
        and (end is None or a.effective_from <= end)
        and (a.effective_to is None or a.effective_to >= start)
    ]
    if any(a.calendar_id == cal.id for a in clashes):
        raise HTTPException(409, f"Already assigned to {cal.name}")
    if clashes and not body.replace:
        names = {c.id: c.name for c in await _calendars(session, tenant_id)}
        who = await _target_name(session, tenant_id, body.target, target)
        raise CodedHTTPException(
            409,
            f"{who[0]} already follows {names[clashes[0].calendar_id]}. Replace it with "
            f"{cal.name}?",
            code="CALENDAR_ASSIGNED",
        )
    for a in clashes:
        # The earlier calendar ends the day before this one starts (or goes, if it would be empty).
        if a.effective_from >= start:
            a.archived_at = now_utc()
        else:
            a.effective_to = start - timedelta(days=1)
        session.add(a)
    session.add(
        HolidayCalendarAssignment(
            tenant_id=tenant_id,
            id=uuid4(),
            calendar_id=cal.id,
            effective_from=start,
            effective_to=end,
            recorded_at=now_utc(),
            **({column: target} if column else {}),
        )
    )


async def _render(session, tenant_id, calendars) -> list[HolidayCalendarOut]:
    ids = [c.id for c in calendars]
    days = await _days(session, tenant_id, ids) if ids else []
    holidays = {}
    if days:
        rows = await session.execute(
            select(Holiday).where(
                Holiday.tenant_id == tenant_id, col(Holiday.id).in_({d.holiday_id for d in days})
            )
        )
        holidays = {h.id: h for h in rows.scalars()}
    # Which other calendars share each holiday.
    names = {c.id: c.name for c in await _calendars(session, tenant_id)}
    sharing: dict = defaultdict(set)
    if holidays:
        rows = await session.execute(
            select(HolidayCalendarDay).where(
                HolidayCalendarDay.tenant_id == tenant_id,
                col(HolidayCalendarDay.holiday_id).in_(list(holidays)),
            )
        )
        for d in rows.scalars():
            if d.calendar_id in names:
                sharing[d.holiday_id].add(d.calendar_id)
    assignments = await _assignments(session, tenant_id, ids) if ids else []
    people = await _people_per_calendar(session, tenant_id, business_today())
    out = []
    for cal in calendars:
        cal_days = sorted(
            (d for d in days if d.calendar_id == cal.id and d.holiday_id in holidays),
            key=lambda d: holidays[d.holiday_id].holiday_date,
        )
        out.append(
            HolidayCalendarOut(
                id=to_typed_id("holiday_calendar", cal.id),
                name=cal.name,
                year=cal.year,
                people=people.get(cal.id, 0),
                days=[
                    CalendarDayOut(
                        id=to_typed_id("holiday_calendar_day", d.id),
                        holiday_id=to_typed_id("holiday", d.holiday_id),
                        holiday_date=holidays[d.holiday_id].holiday_date,
                        name=holidays[d.holiday_id].name,
                        holiday_type=holidays[d.holiday_id].holiday_type,
                        is_optional=d.is_optional,
                        shared_with=sorted(names[c] for c in sharing[d.holiday_id] if c != cal.id),
                    )
                    for d in cal_days
                ],
                assignments=[
                    await _assignment_out(session, tenant_id, a)
                    for a in sorted(
                        (a for a in assignments if a.calendar_id == cal.id),
                        key=lambda a: (_rank(a), a.effective_from),
                    )
                ],
            )
        )
    return out


def _rank(a) -> int:
    return (
        0
        if a.employment_id is None and a.org_unit_id is None and a.legal_entity_id is None
        else (1 if a.legal_entity_id else 2 if a.org_unit_id else 3)
    )


async def _assignment_out(session, tenant_id, a) -> CalendarAssignmentOut:
    if a.legal_entity_id:
        target, uid, kind = "LEGAL_ENTITY", a.legal_entity_id, "legal_entity"
    elif a.org_unit_id:
        target, uid, kind = "DEPARTMENT", a.org_unit_id, "org_unit"
    elif a.employment_id:
        target, uid, kind = "EMPLOYEE", a.employment_id, "employment"
    else:
        target, uid, kind = "COMPANY", None, None
    name, detail = await _target_name(session, tenant_id, target, uid)
    return CalendarAssignmentOut(
        id=to_typed_id("holiday_calendar_assignment", a.id),
        target=target,
        target_id=to_typed_id(kind, uid) if uid else None,
        target_name=name,
        target_detail=detail,
        effective_from=a.effective_from,
        effective_to=a.effective_to,
    )


async def _target_name(session, tenant_id, target, uid) -> tuple[str, str | None]:
    if target == "COMPANY":
        return "Whole company", "Everyone without a more specific calendar"
    sql = {
        "LEGAL_ENTITY": "SELECT name, NULL AS detail FROM legal_entities "
        "WHERE tenant_id = :tid AND id = :id",
        "DEPARTMENT": "SELECT ou.name, le.name AS detail FROM org_units ou "
        "LEFT JOIN legal_entities le ON le.tenant_id = ou.tenant_id AND le.id = ou.legal_entity_id "
        "WHERE ou.tenant_id = :tid AND ou.id = :id",
        "EMPLOYEE": "SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, "
        "e.employee_number AS detail FROM employments e "
        "JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id "
        "WHERE e.tenant_id = :tid AND e.id = :id",
    }[target]
    row = (await session.execute(text(sql), {"tid": tenant_id, "id": uid})).first()
    if row is None:
        raise HTTPException(404, f"{target.replace('_', ' ').title()} not found")
    return row[0], row[1]


async def _people_per_calendar(session, tenant_id, on) -> dict:
    rows = await session.execute(
        text("""
            SELECT holiday_calendar_for(e.tenant_id, e.id, :on) AS calendar_id, count(*)
            FROM employments e
            WHERE e.tenant_id = :tid AND e.archived_at IS NULL AND e.hire_date <= :on
              AND (e.separation_date IS NULL OR e.separation_date > :on)
            GROUP BY 1
        """),
        {"tid": tenant_id, "on": on},
    )
    return {r[0]: r[1] for r in rows}


async def _calendars(session, tenant_id) -> list[HolidayCalendar]:
    rows = await session.execute(
        select(HolidayCalendar)
        .where(HolidayCalendar.tenant_id == tenant_id, HolidayCalendar.archived_at == None)  # noqa: E711
        .order_by(col(HolidayCalendar.year).desc(), col(HolidayCalendar.name))
    )
    return list(rows.scalars())


async def _calendar(session, tenant_id, calendar_id: str) -> HolidayCalendar:
    for cal in await _calendars(session, tenant_id):
        if cal.id == to_uuid(calendar_id):
            return cal
    raise HTTPException(404, "Holiday calendar not found")


async def _unique_name(session, tenant_id, name, year) -> None:
    if any(
        c.name.casefold() == name.casefold() and c.year == year
        for c in await _calendars(session, tenant_id)
    ):
        raise HTTPException(409, f"There is already a {year} calendar called {name}")


async def _days(session, tenant_id, calendar_ids) -> list[HolidayCalendarDay]:
    rows = await session.execute(
        select(HolidayCalendarDay).where(
            HolidayCalendarDay.tenant_id == tenant_id,
            col(HolidayCalendarDay.calendar_id).in_(calendar_ids),
        )
    )
    return list(rows.scalars())


async def _day(session, tenant_id, calendar_uuid, day_id: str) -> HolidayCalendarDay:
    for d in await _days(session, tenant_id, [calendar_uuid]):
        if d.id == to_uuid(day_id):
            return d
    raise HTTPException(404, "That holiday isn't on this calendar")


async def _assignments(session, tenant_id, calendar_ids) -> list[HolidayCalendarAssignment]:
    rows = await session.execute(
        select(HolidayCalendarAssignment).where(
            HolidayCalendarAssignment.tenant_id == tenant_id,
            HolidayCalendarAssignment.archived_at == None,  # noqa: E711
            col(HolidayCalendarAssignment.calendar_id).in_(calendar_ids),
        )
    )
    return list(rows.scalars())


async def _holiday(session, tenant_id, holiday_uuid) -> Holiday:
    row = (
        (
            await session.execute(
                select(Holiday).where(
                    Holiday.tenant_id == tenant_id,
                    Holiday.id == holiday_uuid,
                    Holiday.archived_at == None,  # noqa: E711
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Holiday not found")
    return row


async def _shared_holiday_on(session, tenant_id, day) -> Holiday | None:
    """The holiday list's entry for this date, if any — reused so each date exists once.
    Holidays for everyone (not on the list) are kept apart and never reused here."""
    rows = await session.execute(
        select(Holiday)
        .where(
            Holiday.tenant_id == tenant_id,
            Holiday.holiday_date == day,
            Holiday.is_library == True,  # noqa: E712
            Holiday.archived_at == None,  # noqa: E711
        )
        .order_by(col(Holiday.recorded_at))
        .limit(1)
    )
    return rows.scalars().first()
