"""Map the EXIM holiday policies onto shared holidays and scoped holiday calendars.

Source: exim.holidaypolicies.json (three 2026 calendars from two ERP companies). For each tenant:

1. Each holiday date becomes one shared holiday row (named consistently); the calendars that
   observe it link to it. Duplicate per-calendar copies are archived, never deleted.
2. Each calendar holds exactly the days the source lists (the Gandhi Jayanti date stored as
   year 206 in the source is read as 2 Oct 2026, as approved for the attendance import).
3. A calendar imported into the wrong tenant (the RABS "Holiday" calendar inside Suraj Group)
   is archived there and created in its own tenant.
4. Who follows which calendar is expressed by scope instead of per employee: the calendar most
   people follow becomes the company-wide one, a department where most people follow another
   calendar gets that one, and anyone who still differs keeps a personal assignment — so
   nobody's current calendar changes. People who had none get the company-wide calendar.
5. Stored attendance days whose holiday status changes are recalculated.

Dry-run by default (one transaction, rolled back). Run from backend:
  .venv/bin/python scripts/map_holiday_calendars.py \
      --report storage/migration-backups/holiday-map-dry-run.json
Add --apply to commit; a JSON copy of the holiday tables is written to --backup first.
Running it again after applying changes nothing.
"""

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import col, select

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import (
    AttendanceDay,
    Holiday,
    HolidayCalendar,
    HolidayCalendarAssignment,
    HolidayCalendarDay,
)
from hrms.modules.time.service import is_off_day, recompute_day

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = UUID("8f0c7a52-2f8e-4b8e-9a0e-6b2a3c1d5e47")

# ERP company → tenant. 918 holds the HO and Operations calendars (Suraj Group);
# 926 is RABS Industries (see docs/legacy-mongo-analysis).
SOURCE_TENANT = {
    "69cd1e3b50e6c73acc73a918": "suraj-group",
    "69cd1e3b50e6c73acc73a926": "rabs-industries-india-private-limited",
}

# One name per holiday. Keys are the source names, case-folded and space-normalised.
CANONICAL = {
    "mahatma gandhi's birthday": "Gandhi Jayanti",
    "christmas day": "Christmas",
    "dashera": "Dussehra",
    "ambedkar jayant": "Ambedkar Jayanti",
    "budha purnima": "Buddha Purnima",
    "id-ul-zuha(bakrid)": "Id-ul-Zuha (Bakrid)",
    "milad-un nabi /id-e-milad": "Milad-un-Nabi / Id-e-Milad",
}


def unwrap(value):
    while isinstance(value, dict):
        key = next((k for k in ("$oid", "$date", "$numberLong") if k in value), None)
        if key is None:
            raise ValueError(f"Unsupported Extended JSON value: {value}")
        value = value[key]
    return value


def source_date(value, year):
    raw = unwrap(value)
    if isinstance(raw, int) or (isinstance(raw, str) and raw.lstrip("-").isdigit()):
        day = (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(raw))).date()
    else:
        day = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    if day.year == year:
        return day, None
    if day == date(206, 10, 2) and year == 2026:
        return date(2026, 10, 2), "0206-10-02 read as 2026-10-02"
    raise ValueError(f"Holiday outside its policy year: {day} in {year}")


def canonical(name: str) -> str:
    tidy = " ".join(name.split())
    named = CANONICAL.get(tidy.casefold())
    if named:
        return named
    return tidy.title().replace("'S ", "'s ") if tidy.isupper() else tidy


def load_source(path: Path) -> dict:
    """tenant slug → [calendar {source_id, name, year, days: [{date, name, ...}]}]"""
    out = defaultdict(list)
    for policy in json.loads(path.read_text()):
        if policy.get("status") != "active":
            continue
        if not policy["applicability"]["teams"]["all"]:
            raise ValueError("Team-restricted holiday policies are not supported")
        slug = SOURCE_TENANT[unwrap(policy["company_id"])]
        days = []
        for entry in policy["holidays"]:
            day, note = source_date(entry["holiday_date"], policy["year"])
            days.append(
                {
                    "date": day,
                    "source_name": entry["holiday_name"],
                    "name": canonical(entry["holiday_name"]),
                    "type": entry.get("holiday_type"),
                    "optional": bool(entry.get("is_optional")),
                    "note": note,
                }
            )
        out[slug].append(
            {
                "source_id": unwrap(policy["_id"]),
                "name": " ".join(policy["policy_name"].split()),
                "year": policy["year"],
                "days": sorted(days, key=lambda d: d["date"]),
            }
        )
    for calendars in out.values():
        # The biggest calendar first: it names shared holidays and is the likely default.
        calendars.sort(key=lambda c: -len(c["days"]))
    return out


def sid(tenant_id, *parts) -> UUID:
    return uuid5(NAMESPACE, ":".join([str(tenant_id), *map(str, parts)]))


async def off_day_snapshot(session, tid, year) -> dict:
    rows = await session.execute(
        select(AttendanceDay.employment_id, AttendanceDay.work_date).where(
            AttendanceDay.tenant_id == tid,
            AttendanceDay.work_date >= date(year, 1, 1),
            AttendanceDay.work_date <= date(year, 12, 31),
        )
    )
    result = {}
    for eid, day in rows:
        policy = await resolve_policy(eid, day, session, tid)
        result[(eid, day)] = await is_off_day(session, tid, eid, day, policy)
    return result


async def map_tenant(session, slug, calendars, all_source_names, stats):
    tid = (
        await session.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
    ).scalar()
    if tid is None:
        raise ValueError(f"Tenant {slug} not found")
    await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
    t = stats.setdefault(slug, defaultdict(list))
    year = calendars[0]["year"]
    before = await off_day_snapshot(session, tid, year)
    stamp = datetime.now(UTC)

    live = list(
        (
            await session.execute(
                select(HolidayCalendar).where(
                    HolidayCalendar.tenant_id == tid,
                    HolidayCalendar.archived_at == None,  # noqa: E711
                )
            )
        ).scalars()
    )
    by_key = {(c.name.casefold(), c.year): c for c in live}
    own_names = {(c["name"].casefold(), c["year"]) for c in calendars}

    # 1. Calendars: reuse by name and year, create what is missing.
    cals = {}
    for c in calendars:
        cal = by_key.get((c["name"].casefold(), c["year"]))
        if cal is None:
            cal = HolidayCalendar(
                tenant_id=tid,
                id=sid(tid, "calendar", c["source_id"]),
                name=c["name"],
                year=c["year"],
                recorded_at=stamp,
            )
            session.add(cal)
            t["calendars_created"].append(c["name"])
        cals[c["name"]] = cal
    await session.flush()
    wanted = {cal.id for cal in cals.values()}

    # A calendar that belongs to another company's file has no place here.
    for cal in live:
        if (cal.name.casefold(), cal.year) in all_source_names - own_names:
            cal.archived_at = stamp
            session.add(cal)
            for a in (
                await session.execute(
                    select(HolidayCalendarAssignment).where(
                        HolidayCalendarAssignment.tenant_id == tid,
                        HolidayCalendarAssignment.calendar_id == cal.id,
                        HolidayCalendarAssignment.archived_at == None,  # noqa: E711
                    )
                )
            ).scalars():
                a.archived_at = stamp
                session.add(a)
            for h in (
                await session.execute(
                    select(Holiday).where(
                        Holiday.tenant_id == tid,
                        Holiday.calendar_id == cal.id,
                        Holiday.archived_at == None,  # noqa: E711
                    )
                )
            ).scalars():
                h.archived_at = stamp
                session.add(h)
            t["calendars_archived_from_other_company"].append(cal.name)

    # 2. One shared holiday per date.
    linked = {
        d.holiday_id
        for d in (
            await session.execute(
                select(HolidayCalendarDay).where(
                    HolidayCalendarDay.tenant_id == tid,
                    col(HolidayCalendarDay.calendar_id).in_(wanted),
                )
            )
        ).scalars()
    }
    candidates = defaultdict(list)
    for h in (
        await session.execute(
            select(Holiday).where(
                Holiday.tenant_id == tid,
                Holiday.archived_at == None,  # noqa: E711
                Holiday.holiday_date >= date(year, 1, 1),
                Holiday.holiday_date <= date(year, 12, 31),
            )
        )
    ).scalars():
        if h.calendar_id in wanted or h.id in linked:
            candidates[h.holiday_date].append(h)
    order = {cal.id: i for i, cal in enumerate(cals.values())}
    shared = {}
    for c in calendars:
        for d in c["days"]:
            if d["date"] in shared:
                continue
            pool = sorted(
                candidates.get(d["date"], []),
                key=lambda h: (h.id not in linked, order.get(h.calendar_id, 99), str(h.id)),
            )
            master = (
                pool[0]
                if pool
                else Holiday(
                    tenant_id=tid,
                    id=sid(tid, "holiday", d["date"]),
                    holiday_date=d["date"],
                    name=d["name"],
                    recorded_at=stamp,
                )
            )
            if not pool:
                t["holidays_created"].append(f"{d['date']} {d['name']}")
            if master.name != d["name"]:
                t["renamed"].append(f"{d['date']}: {master.name} → {d['name']}")
            master.name = d["name"]
            master.holiday_type = d["type"]
            master.is_optional = False
            master.is_library = True
            master.legal_entity_id = None
            master.calendar_id = None
            session.add(master)
            for dup in pool[1:]:
                dup.archived_at = stamp
                session.add(dup)
                t["duplicates_archived"].append(f"{dup.holiday_date} {dup.name}")
            shared[d["date"]] = master
            if d["note"]:
                t["date_corrections"].append(f"{d['source_name']}: {d['note']}")
    await session.flush()

    # 3. Each calendar holds exactly the source's days.
    for c in calendars:
        cal = cals[c["name"]]
        want = {shared[d["date"]].id: d["optional"] for d in c["days"]}
        have = {
            d.holiday_id: d
            for d in (
                await session.execute(
                    select(HolidayCalendarDay).where(
                        HolidayCalendarDay.tenant_id == tid,
                        HolidayCalendarDay.calendar_id == cal.id,
                    )
                )
            ).scalars()
        }
        for hid, day in have.items():
            if hid not in want:
                await session.delete(day)
                t["days_removed"].append(f"{cal.name}: {hid}")
            elif day.is_optional != want[hid]:
                day.is_optional = want[hid]
                session.add(day)
        for hid, optional in want.items():
            if hid not in have:
                session.add(
                    HolidayCalendarDay(
                        tenant_id=tid,
                        id=sid(tid, "calendar-day", cal.id, hid),
                        calendar_id=cal.id,
                        holiday_id=hid,
                        is_optional=optional,
                        recorded_at=stamp,
                    )
                )
                t["days_linked"].append(f"{cal.name}: {shared_name(shared, hid)}")
        t["calendars"].append({"name": cal.name, "days": len(want)})
    await session.flush()

    # 4. Assignments by scope.
    people = (
        (
            await session.execute(
                text("""
                SELECT e.id, e.legal_entity_id, le.name AS company, a.org_unit_id,
                       coalesce(ou.name, '(no department)') AS department
                FROM employments e
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
                     AND a.effective_from <= CURRENT_DATE
                     AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
                LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
                WHERE e.tenant_id = :tid AND e.archived_at IS NULL
                  AND (e.separation_date IS NULL OR e.separation_date > CURRENT_DATE)
            """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    existing = list(
        (
            await session.execute(
                select(HolidayCalendarAssignment).where(
                    HolidayCalendarAssignment.tenant_id == tid,
                    HolidayCalendarAssignment.archived_at == None,  # noqa: E711
                    col(HolidayCalendarAssignment.calendar_id).in_(wanted),
                )
            )
        ).scalars()
    )
    # The calendar each person follows today, however it is assigned (per person after the
    # attendance import; by scope once this has run, so a second run changes nothing).
    personal = {}
    for p in people:
        cal_id = (
            await session.execute(
                text("SELECT holiday_calendar_for(:tid, :eid, CURRENT_DATE)"),
                {"tid": tid, "eid": p["id"]},
            )
        ).scalar()
        if cal_id in wanted:
            personal[p["id"]] = cal_id
    counts = Counter(personal.values())
    default = counts.most_common(1)[0][0] if counts else cals[calendars[0]["name"]].id
    by_unit = defaultdict(list)
    for p in people:
        if p["org_unit_id"]:
            by_unit[p["org_unit_id"]].append(p["id"])
    unit_cal = {}
    for unit, members in by_unit.items():
        top, n = Counter(personal.get(m) for m in members).most_common(1)[0]
        if top and top != default and n * 2 > len(members):
            unit_cal[unit] = top
    start = date(year, 1, 1)
    desired = [("company", None, default)]
    desired += [("org_unit_id", unit, cal) for unit, cal in unit_cal.items()]
    for p in people:
        current = personal.get(p["id"])
        resolved = unit_cal.get(p["org_unit_id"], default)
        if current and current != resolved:
            desired.append(("employment_id", p["id"], current))
    names = {cal.id: cal.name for cal in cals.values()}
    units = {p["org_unit_id"]: f"{p['department']} ({p['company']})" for p in people}
    keep = set()
    for column, target, cal_id in desired:
        aid = sid(tid, "calendar-assignment", column, target, cal_id, start)
        keep.add(aid)
        if await session.get(HolidayCalendarAssignment, (tid, aid)):
            continue
        session.add(
            HolidayCalendarAssignment(
                tenant_id=tid,
                id=aid,
                calendar_id=cal_id,
                effective_from=start,
                recorded_at=stamp,
                **({column: target} if column != "company" else {}),
            )
        )
        t["assignments"].append(
            f"{names[cal_id]} → "
            + {
                "company": "whole company",
                "org_unit_id": f"department {units.get(target)}",
                "employment_id": "one employee (exception)",
            }[column]
        )
    for a in existing:
        if a.id not in keep:
            a.archived_at = stamp
            session.add(a)
            t["personal_assignments_replaced"].append(str(a.id))
    gaining = Counter(
        f"{p['company']} / {p['department']}" for p in people if p["id"] not in personal
    )
    t["people_without_a_calendar_until_now"] = dict(sorted(gaining.items()))
    await session.flush()

    # 5. Recalculate stored days whose holiday status changed.
    after = await off_day_snapshot(session, tid, year)
    for (eid, day), was in sorted(before.items(), key=lambda kv: kv[0][1]):
        if after.get((eid, day)) == was:
            continue
        policy = await resolve_policy(eid, day, session, tid)
        try:
            ad = await recompute_day(session, tid, eid, day, policy)
            t["days_recalculated"].append(f"{day}: now {ad.status}")
        except HTTPException as e:
            t["days_not_recalculated"].append(f"{day}: {e.detail}")
    t["shared_holidays"] = [f"{d} {h.name}" for d, h in sorted(shared.items())]


def shared_name(shared, hid):
    return next((f"{d} {h.name}" for d, h in shared.items() if h.id == hid), str(hid))


async def backup(session, path: Path):
    tables = [
        "holidays",
        "holiday_calendars",
        "holiday_calendar_assignments",
        "holiday_calendar_days",
    ]
    data = {}
    for table in tables:
        rows = await session.execute(text(f"SELECT * FROM {table}"))  # noqa: S608 (fixed names)
        data[table] = [dict(r) for r in rows.mappings()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str) + "\n")
    path.chmod(0o600)


async def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", type=Path, default=ROOT / "exim.holidaypolicies.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-holiday-map.json"))
    parser.add_argument(
        "--backup",
        type=Path,
        default=Path("storage/migration-backups")
        / f"holidays-before-map-{datetime.now(UTC):%Y%m%d-%H%M%S}.json",
    )
    args = parser.parse_args()
    source = load_source(args.source)
    all_names = {(c["name"].casefold(), c["year"]) for cals in source.values() for c in cals}
    engine = create_async_engine(settings.database_url)
    stats = {}
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            if args.apply:
                await backup(session, args.backup)
            for slug, calendars in source.items():
                await map_tenant(session, slug, calendars, all_names, stats)
            if not args.apply:
                await session.rollback()
        report = {"mode": "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK", "tenants": stats}
        if args.apply:
            report["backup"] = str(args.backup)
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps(report, indent=2, default=str))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
