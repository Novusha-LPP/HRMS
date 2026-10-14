"""
Holiday calendars: one shared holiday list, calendars assigned to the whole company, a legal
entity, a department (with its sub-units) or one employee — most specific wins — and the
mapping of the EXIM holiday policies onto that model.
"""

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from hrms.core.ids import to_uuid
from hrms.modules.time.models import Holiday, HolidayCalendar, HolidayCalendarAssignment
from tests.helpers import ok, org_basics
from tests.test_attendance_cases import at, company, punch, staff, stored

pytestmark = pytest.mark.database

spec = importlib.util.spec_from_file_location(
    "map_holiday_calendars",
    Path(__file__).resolve().parents[1] / "scripts/map_holiday_calendars.py",
)
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)

URL = "/v1/time/holiday-calendars"


async def holiday_on(client, emp, day: str) -> bool:
    reg = await ok(client, "GET", f"/v1/time/register/{emp['id']}?from_date={day}&to_date={day}")
    return reg["days"][0]["status"] == "HOLIDAY"


async def unit(client, le, name, parent=None):
    return await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": name,
            "type": "DEPARTMENT",
            "legal_entity_id": le,
            "effective_from": "2020-01-01",
            **({"parent_id": parent} if parent else {}),
        },
    )


async def calendar(client, name, days, **kw):
    cal = await ok(client, "POST", URL, json={"name": name, "year": 2026, **kw})
    for day, label, *optional in days:
        cal = await ok(
            client,
            "POST",
            f"{URL}/{cal['id']}/days",
            json={"holiday_date": day, "name": label, "is_optional": bool(optional)},
        )
    return cal


async def test_calendars_follow_the_most_specific_assignment(api):
    client, _ = api
    admin, le, placement, _ = await company(client, {})
    other = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Branch Co"})
    other_place = await org_basics(client, other["id"])
    plant = await unit(client, le, "Plant")
    line = await unit(client, le, "Line 1", parent=plant["id"])
    people = {
        "head_office": (await staff(client, le, placement, "HC-A"))[0],
        "branch": (await staff(client, other["id"], other_place, "HC-B"))[0],
        "plant": (await staff(client, le, {**placement, "org_unit_id": plant["id"]}, "HC-C"))[0],
        "line": (await staff(client, le, {**placement, "org_unit_id": line["id"]}, "HC-D"))[0],
        "exception": (await staff(client, le, {**placement, "org_unit_id": plant["id"]}, "HC-E"))[
            0
        ],
    }

    main = await calendar(
        client,
        "Main",
        [("2026-01-26", "Republic Day"), ("2026-11-08", "Diwali")],
        assign_company=True,
    )
    branch = await calendar(client, "Branch", [("2026-11-08", "Deepavali"), ("2026-03-04", "Holi")])
    # The same date is one shared holiday: added by date, it keeps the existing name.
    diwali = next(d for d in branch["days"] if d["holiday_date"] == "2026-11-08")
    assert (diwali["name"], diwali["shared_with"]) == ("Diwali", ["Main"])
    assert diwali["holiday_id"] == next(
        d["holiday_id"] for d in main["days"] if d["holiday_date"] == "2026-11-08"
    )
    plant_cal = await calendar(
        client, "Plant", [("2026-03-04", "Holi"), ("2026-06-26", "Muharram", "optional")]
    )
    personal = await calendar(client, "Personal", [("2026-12-25", "Christmas")])

    for cal, target, target_id in [
        (branch, "LEGAL_ENTITY", other["id"]),
        (plant_cal, "DEPARTMENT", plant["id"]),
        (personal, "EMPLOYEE", people["exception"]["id"]),
    ]:
        await ok(
            client,
            "POST",
            f"{URL}/{cal['id']}/assignments",
            json={"target": target, "target_id": target_id},
        )

    listed = await ok(client, "GET", "/v1/time/holidays?year=2026")
    assert [(h["holiday_date"], h["calendar_name"]) for h in listed if h["name"] == "Diwali"] == [
        ("2026-11-08", "Branch, Main")
    ]

    expect = {
        "head_office": {"2026-01-26": True, "2026-03-04": False, "2026-11-08": True},
        "branch": {"2026-01-26": False, "2026-03-04": True, "2026-11-08": True},
        "plant": {"2026-01-26": False, "2026-03-04": True, "2026-06-26": False},
        "line": {"2026-03-04": True, "2026-11-08": False},
        "exception": {"2026-12-25": True, "2026-03-04": False},
    }
    for who, days in expect.items():
        for day, holiday in days.items():
            assert await holiday_on(client, people[who], day) is holiday, (who, day)

    coverage = {c["name"]: c["people"] for c in await ok(client, "GET", f"{URL}/coverage")}
    assert coverage == {"Main": 1, "Branch": 1, "Plant": 2, "Personal": 1}

    # Re-pointing the whole company asks first, then hands over from the new start date.
    later = await calendar(client, "Main from July", [("2026-11-10", "New Year")])
    clash = await client.post(
        f"{URL}/{later['id']}/assignments",
        json={"target": "COMPANY", "effective_from": "2026-07-01"},
    )
    assert clash.status_code == 409 and clash.json()["code"] == "CALENDAR_ASSIGNED"
    await ok(
        client,
        "POST",
        f"{URL}/{later['id']}/assignments",
        json={"target": "COMPANY", "effective_from": "2026-07-01", "replace": True},
    )
    main = next(c for c in await ok(client, "GET", f"{URL}?year=2026") if c["name"] == "Main")
    assert [(a["target"], a["effective_to"]) for a in main["assignments"]] == [
        ("COMPANY", "2026-06-30")
    ]
    assert await holiday_on(client, people["head_office"], "2026-01-26")
    assert not await holiday_on(client, people["head_office"], "2026-11-08")
    assert await holiday_on(client, people["head_office"], "2026-11-10")

    # Taking a holiday off one calendar leaves it on the others; off the last, it stays on the
    # holiday list but is nobody's day off.
    holi = lambda cal: next(d for d in cal["days"] if d["name"] == "Holi")  # noqa: E731
    plant_cal = await ok(client, "DELETE", f"{URL}/{plant_cal['id']}/days/{holi(plant_cal)['id']}")
    assert await holiday_on(client, people["branch"], "2026-03-04")
    await ok(client, "DELETE", f"{URL}/{branch['id']}/days/{holi(branch)['id']}")
    library = await ok(client, "GET", f"{URL}/library?year=2026")
    assert [(h["name"], h["calendars"]) for h in library if h["name"] == "Holi"] == [("Holi", [])]
    for who in people:
        assert not await holiday_on(client, people[who], "2026-03-04"), who

    wrong_year = await client.post(
        f"{URL}/{personal['id']}/days", json={"holiday_date": "2027-01-26", "name": "Republic Day"}
    )
    assert wrong_year.status_code == 422

    # Archiving a calendar drops its people back to the next level (here, their department).
    await ok(client, "DELETE", f"{URL}/{personal['id']}")
    await ok(
        client,
        "POST",
        f"{URL}/{plant_cal['id']}/days",
        json={"holiday_date": "2026-05-01", "name": "May Day"},
    )
    assert await holiday_on(client, people["exception"], "2026-05-01")
    assert not await holiday_on(client, people["exception"], "2026-12-25")


async def test_only_hr_manages_calendars(api):
    client, _ = api
    admin, le, placement, _ = await company(client, {})
    _, headers = await staff(client, le, placement, "HC-X")
    assert (await client.get(URL, headers=headers)).status_code == 403
    assert (
        await client.post(URL, json={"name": "X", "year": 2026}, headers=headers)
    ).status_code == 403


def test_exim_policy_normalization_uses_synthetic_source(tmp_path):
    import json

    source_file = tmp_path / "holidays.json"
    source_file.write_text(json.dumps([{
        "_id": "synthetic-policy", "company_id": next(iter(mapping.SOURCE_TENANT)),
        "status": "active", "applicability": {"teams": {"all": True}},
        "policy_name": "  Synthetic   Calendar  ", "year": 2026,
        "holidays": [
            {"holiday_date": "0206-10-02", "holiday_name": "Gandhi Jayanti"},
            {"holiday_date": "2026-12-25", "holiday_name": "Christmas Day"},
        ],
    }]))
    calendars = mapping.load_source(source_file)
    calendar = next(iter(calendars.values()))[0]
    assert calendar["name"] == "Synthetic Calendar"
    assert calendar["days"][0]["date"] == date(2026, 10, 2)
    assert calendar["days"][0]["note"] == "0206-10-02 read as 2026-10-02"
    assert calendar["days"][1]["name"] == "Christmas"


async def test_mapping_dedupes_holidays_and_assigns_by_scope(api, monkeypatch):
    client, engine = api
    admin, le, placement, _ = await company(client, {})
    tid = to_uuid(admin["user"]["tenant_id"])
    async with engine.connect() as conn:
        slug = (
            await conn.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": tid})
        ).scalar()
    ops_unit = await unit(client, le, "Operations")
    admin_place = placement
    ops_place = {**placement, "org_unit_id": ops_unit["id"]}
    office = [(await staff(client, le, admin_place, f"MAP-A{i}"))[0] for i in range(4)]
    ops = [(await staff(client, le, ops_place, f"MAP-O{i}"))[0] for i in range(3)]
    newcomer, newcomer_headers = await staff(client, le, admin_place, "MAP-NEW")

    # Before: per-calendar copies of the same dates, a stray calendar from the other company,
    # and one assignment per person — as the attendance import left them.
    ho_days = [(date(2026, 1, 26), "Republic Day"), (date(2026, 10, 2), "Gandhi Jayanti")]
    ops_days = [
        (date(2026, 1, 26), "Republic Day"),
        (date(2026, 10, 2), "Mahatma Gandhi's Birthday"),
        (date(2026, 3, 21), "Id-ul-Fitr"),
    ]
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        cals = {}
        for name, days in (
            ("HO Holiday", ho_days),
            ("Operations Holiday", ops_days),
            ("Holiday", [(date(2026, 1, 1), "NEW YEAR")]),
        ):
            cal = HolidayCalendar(
                tenant_id=tid, id=mapping.sid(tid, "t", name), name=name, year=2026
            )
            session.add(cal)
            await session.flush()
            cals[name] = cal
            for day, label in days:
                session.add(
                    Holiday(
                        tenant_id=tid,
                        id=mapping.sid(tid, name, day),
                        holiday_date=day,
                        name=label,
                        calendar_id=cal.id,
                    )
                )
        follows = [(e, "HO Holiday") for e in office] + [
            (ops[0], "Operations Holiday"),
            (ops[1], "Operations Holiday"),
            (ops[2], "HO Holiday"),
        ]
        for emp, name in follows:
            session.add(
                HolidayCalendarAssignment(
                    tenant_id=tid,
                    id=mapping.sid(tid, "a", emp["id"]),
                    employment_id=to_uuid(emp["id"]),
                    calendar_id=cals[name].id,
                    effective_from=date(2026, 10, 1),
                    effective_to=date(2026, 12, 31),
                )
            )
    # The newcomer worked on 2 Oct, a day the HO calendar will make a holiday for them.
    await punch(client, monkeypatch, newcomer_headers, "IN", at(date(2026, 10, 2), "10:00"))
    await punch(client, monkeypatch, newcomer_headers, "OUT", at(date(2026, 10, 2), "14:00"))
    assert (await stored(engine, tid, to_uuid(newcomer["id"]), date(2026, 10, 2)))[5] == "LATE"

    source = [
        {
            "source_id": "ops",
            "name": "Operations Holiday",
            "year": 2026,
            "days": [
                {
                    "date": d,
                    "source_name": n,
                    "name": mapping.canonical(n),
                    "type": "national",
                    "optional": False,
                    "note": None,
                }
                for d, n in ops_days
            ],
        },
        {
            "source_id": "ho",
            "name": "HO Holiday",
            "year": 2026,
            "days": [
                {
                    "date": d,
                    "source_name": n,
                    "name": mapping.canonical(n),
                    "type": "national",
                    "optional": False,
                    "note": None,
                }
                for d, n in ho_days
            ],
        },
    ]
    names = {("operations holiday", 2026), ("ho holiday", 2026), ("holiday", 2026)}

    async def run():
        stats = {}
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            await mapping.map_tenant(session, slug, source, names, stats)
        return stats[slug]

    entities = await ok(client, "GET", "/v1/org/legal-entities")
    le_name = next(e["name"] for e in entities if e["id"] == le)
    first = await run()
    assert first["calendars_archived_from_other_company"] == ["Holiday"]
    assert sorted(first["duplicates_archived"]) == [
        "2026-01-26 Republic Day",
        "2026-10-02 Gandhi Jayanti",
    ]
    assert first["renamed"] == ["2026-10-02: Mahatma Gandhi's Birthday → Gandhi Jayanti"]
    assert sorted(first["assignments"]) == [
        "HO Holiday → one employee (exception)",
        "HO Holiday → whole company",
        f"Operations Holiday → department Operations ({le_name})",
    ]
    assert first["people_without_a_calendar_until_now"] == {f"{le_name} / Ops": 1}
    assert first["days_recalculated"] == ["2026-10-02: now OFF_DAY_WORKED"]

    holidays = await ok(client, "GET", "/v1/time/holidays?year=2026")
    assert [(h["holiday_date"], h["name"], h["calendar_name"]) for h in holidays] == [
        ("2026-01-26", "Republic Day", "HO Holiday, Operations Holiday"),
        ("2026-03-21", "Id-ul-Fitr", "Operations Holiday"),
        ("2026-10-02", "Gandhi Jayanti", "HO Holiday, Operations Holiday"),
    ]
    coverage = {c["name"]: c["people"] for c in await ok(client, "GET", f"{URL}/coverage")}
    assert coverage == {"HO Holiday": 6, "Operations Holiday": 2}
    assert await holiday_on(client, ops[0], "2026-03-21")
    assert not await holiday_on(client, ops[2], "2026-03-21")
    assert await holiday_on(client, office[0], "2026-01-26")

    again = await run()
    assert {
        k: v
        for k, v in again.items()
        if v and k not in {"calendars", "shared_holidays", "people_without_a_calendar_until_now"}
    } == {}


async def test_holiday_list_then_calendars_then_assignment(api):
    """The setup order HR follows: list the year's holidays, build calendars from that list,
    then give each calendar to the company, an entity or a department."""
    client, _ = api
    admin, le, placement, _ = await company(client, {})
    ops_unit = await unit(client, le, "Operations")
    office = (await staff(client, le, placement, "LIB-A"))[0]
    plant = (await staff(client, le, {**placement, "org_unit_id": ops_unit["id"]}, "LIB-B"))[0]

    # 1. The holiday list. On no calendar yet, nobody gets these days off.
    added = {}
    for day, name in [
        ("2026-01-26", "Republic Day"),
        ("2026-03-04", "Holi"),
        ("2026-11-08", "Diwali"),
        ("2026-03-21", "Id-ul-Fitr"),
    ]:
        added[name] = await ok(
            client, "POST", f"{URL}/library", json={"holiday_date": day, "name": name}
        )
    clash = await client.post(f"{URL}/library", json={"holiday_date": "2026-11-08", "name": "X"})
    assert clash.status_code == 409 and "Diwali" in clash.json()["detail"]
    assert not await holiday_on(client, office, "2026-01-26")
    renamed = await ok(
        client, "PATCH", f"{URL}/library/{added['Diwali']['id']}", json={"name": "Deepavali"}
    )
    assert renamed["name"] == "Deepavali"

    # 2. Calendars pick from the list.
    ho = await ok(
        client,
        "POST",
        URL,
        json={
            "name": "HO",
            "year": 2026,
            "holiday_ids": [added[n]["id"] for n in ("Republic Day", "Diwali")],
        },
    )
    ops = await ok(client, "POST", URL, json={"name": "Operations", "year": 2026})
    ops = await ok(
        client,
        "PUT",
        f"{URL}/{ops['id']}/days",
        json={
            "holidays": [{"holiday_id": added[n]["id"]} for n in ("Republic Day", "Holi", "Diwali")]
            + [{"holiday_id": added["Id-ul-Fitr"]["id"], "is_optional": True}]
        },
    )
    assert [(d["name"], d["is_optional"]) for d in ops["days"]] == [
        ("Republic Day", False),
        ("Holi", False),
        ("Id-ul-Fitr", True),
        ("Deepavali", False),
    ]
    library = {
        h["name"]: [c["name"] for c in h["calendars"]]
        for h in await ok(client, "GET", f"{URL}/library?year=2026")
    }
    assert library == {
        "Republic Day": ["HO", "Operations"],
        "Holi": ["Operations"],
        "Id-ul-Fitr": ["Operations"],
        "Deepavali": ["HO", "Operations"],
    }

    # 3. Who follows which.
    await ok(client, "POST", f"{URL}/{ho['id']}/assignments", json={"target": "COMPANY"})
    await ok(
        client,
        "POST",
        f"{URL}/{ops['id']}/assignments",
        json={"target": "DEPARTMENT", "target_id": ops_unit["id"]},
    )
    assert await holiday_on(client, office, "2026-01-26")
    assert not await holiday_on(client, office, "2026-03-04")
    assert await holiday_on(client, plant, "2026-03-04")
    assert not await holiday_on(client, plant, "2026-03-21")  # optional on that calendar

    # Deleting from the list takes it off every calendar.
    await ok(client, "DELETE", f"{URL}/library/{added['Republic Day']['id']}")
    assert not await holiday_on(client, office, "2026-01-26")
    assert not await holiday_on(client, plant, "2026-01-26")
