"""A minimal company celebration roster must not grant broader personnel access."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from hrms.core import datetime_utils
from hrms.core.ids import to_uuid
from tests.helpers import bearer, make_user, ok, person_and_employment, tenant

pytestmark = pytest.mark.database

PATH = "/v1/dashboard/celebrations"
TODAY = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def business_clock(monkeypatch):
    monkeypatch.setattr(datetime_utils, "now_utc", lambda: datetime(2026, 10, 9, 12, tzinfo=UTC))


async def staff(
    client,
    engine,
    company,
    name,
    *,
    birthday=None,
    hired=date(2020, 1, 1),
    state="ACTIVE",
    archived=False,
    person_archived=False,
):
    employee = await person_and_employment(
        client,
        company,
        legal_first_name=name,
        legal_last_name="Person",
        date_of_birth=birthday.isoformat() if birthday else None,
    )
    async with engine.begin() as conn:
        await conn.execute(
            text("""UPDATE employments SET hire_date=:hired, employment_state=:state,
                    archived_at=CASE WHEN :archived THEN now() ELSE NULL END WHERE id=:eid"""),
            {"hired": hired, "state": state, "archived": archived, "eid": to_uuid(employee["id"])},
        )
        if person_archived:
            await conn.execute(
                text("UPDATE persons SET archived_at=now() WHERE id=:pid"),
                {"pid": to_uuid(employee["person_id"])},
            )
    return employee


async def employee_login(client, employment, role="EMPLOYEE"):
    email, password, _ = await make_user(client, employment["id"], role=role)
    return await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )


@pytest.mark.parametrize("role", ["EMPLOYEE", "MANAGER", "HR_MANAGER"])
async def test_company_roster_is_available_to_employee_roles_and_preserves_privacy(api, role):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    self = await staff(
        client, engine, company, "Zed", birthday=date(1990, 10, 9), hired=date(2023, 10, 9)
    )
    colleague = await staff(
        client,
        engine,
        company,
        "Ana",
        birthday=date(1988, 10, 9),
        hired=date(2024, 10, 9),
        state="PROBATION",
    )
    other_company = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": "Sister company", "country_code": "IN"},
        )
    )["id"]
    await staff(
        client,
        engine,
        other_company,
        "Hidden company",
        birthday=date(1985, 10, 9),
        hired=date(2022, 10, 9),
    )
    login = await employee_login(client, self, role)

    # Matching celebrations in another tenant must also be invisible under real RLS.
    outsider = await tenant(client)
    await staff(
        client,
        engine,
        outsider["user"]["legal_entities"][0]["id"],
        "Hidden tenant",
        birthday=date(1985, 10, 9),
        hired=date(2022, 10, 9),
    )
    headers = bearer(login["access_token"])
    result = await ok(client, "GET", PATH, headers=headers)
    assert result["date"] == "2026-10-09" and result["timezone"] == "Asia/Kolkata"
    assert result["personal"] == {"birthday": True, "anniversary_years": 3}
    assert [p["id"] for p in result["birthdays"]] == [self["person_id"], colleague["person_id"]]
    assert [p["id"] for p in result["anniversaries"]] == [self["id"], colleague["id"]]
    assert [p["is_self"] for p in result["birthdays"]] == [True, False]
    assert [p["years"] for p in result["anniversaries"]] == [3, 2]
    for birthday in result["birthdays"]:
        assert set(birthday) == {"id", "name", "company", "is_self"}
    for anniversary in result["anniversaries"]:
        assert set(anniversary) == {"id", "name", "company", "is_self", "years"}
    if role == "EMPLOYEE":
        assert (await client.get("/v1/dashboard/hr", headers=headers)).status_code == 403
        visible = await ok(client, "GET", "/v1/employees", headers=headers)
        assert [p["id"] for p in visible] == [self["id"]]
    # Extra identity selectors cannot widen the company derived from the caller.
    assert (
        await ok(client, "GET", PATH + "?legal_entity_id=" + other_company, headers=headers)
        == result
    )


async def test_only_current_people_appear_and_birthdays_are_deduplicated(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    self = await staff(client, engine, company, "Viewer")
    for name, state in [("Ana", "PROBATION"), ("Bea", "NOTICE"), ("Cy", "ON_HOLD")]:
        await staff(
            client,
            engine,
            company,
            name,
            birthday=date(1990, 10, 9),
            hired=date(2020, 10, 9),
            state=state,
        )
    new_hire = await staff(client, engine, company, "New", birthday=date(1990, 10, 9), hired=TODAY)
    await staff(
        client, engine, company, "Future", birthday=date(1990, 10, 9), hired=date(2027, 10, 9)
    )
    await staff(
        client,
        engine,
        company,
        "Gone",
        birthday=date(1990, 10, 9),
        hired=date(2020, 10, 9),
        state="SEPARATED",
    )
    await staff(
        client,
        engine,
        company,
        "Archived employment",
        birthday=date(1990, 10, 9),
        hired=date(2020, 10, 9),
        archived=True,
    )
    await staff(
        client,
        engine,
        company,
        "Archived person",
        birthday=date(1990, 10, 9),
        hired=date(2020, 10, 9),
        person_archived=True,
    )
    # A person may have a second employment; they still have one birthday.
    await ok(
        client,
        "POST",
        "/v1/employees",
        json={
            "person_id": new_hire["person_id"],
            "legal_entity_id": company,
            "employee_number": "duplicate-person",
            "hire_date": "2020-01-01",
            "confirm_new_employment": True,  # deliberately a second employment for the person
        },
    )
    login = await employee_login(client, self)
    result = await ok(client, "GET", PATH, headers=bearer(login["access_token"]))
    assert result["personal"] == {"birthday": False, "anniversary_years": None}
    assert [p["name"] for p in result["birthdays"]] == [
        "Ana Person",
        "Bea Person",
        "Cy Person",
        "New Person",
    ]
    assert [p["name"] for p in result["anniversaries"]] == ["Ana Person", "Bea Person", "Cy Person"]
    assert len({p["id"] for p in result["birthdays"]}) == 4


async def test_empty_day_and_accounts_without_employment_are_quiet(api):
    client, engine = api
    admin = await tenant(client)
    empty = await ok(client, "GET", PATH)
    assert empty == {
        "date": "2026-10-09",
        "timezone": "Asia/Kolkata",
        "personal": {"birthday": False, "anniversary_years": None},
        "birthdays": [],
        "anniversaries": [],
    }
    self = await staff(client, engine, admin["user"]["legal_entities"][0]["id"], "Viewer")
    login = await employee_login(client, self)
    assert await ok(client, "GET", PATH, headers=bearer(login["access_token"])) == empty
    assert (await client.get(PATH, headers={"Authorization": "Bearer invalid"})).status_code == 401


@pytest.mark.parametrize(
    "day,celebrates",
    [
        (date(2027, 2, 28), True),
        (date(2028, 2, 28), False),
        (date(2028, 2, 29), True),
    ],
)
async def test_leap_day_birthdays_and_anniversaries(api, monkeypatch, day, celebrates):
    monkeypatch.setattr(
        datetime_utils, "now_utc", lambda: datetime.combine(day, datetime.min.time(), UTC)
    )
    client, engine = api
    admin = await tenant(client)
    self = await staff(
        client,
        engine,
        admin["user"]["legal_entities"][0]["id"],
        "Leap",
        birthday=date(1992, 2, 29),
        hired=date(2020, 2, 29),
    )
    login = await employee_login(client, self)
    result = await ok(client, "GET", PATH, headers=bearer(login["access_token"]))
    assert result["date"] == day.isoformat()
    assert result["personal"] == {
        "birthday": celebrates,
        "anniversary_years": day.year - 2020 if celebrates else None,
    }
    assert len(result["birthdays"]) == len(result["anniversaries"]) == int(celebrates)


async def test_business_date_uses_tenant_timezone_near_utc_midnight(api, monkeypatch):
    monkeypatch.setattr(
        datetime_utils, "now_utc", lambda: datetime(2026, 10, 8, 23, 30, tzinfo=UTC)
    )
    client, engine = api
    admin = await tenant(client)
    self = await staff(
        client,
        engine,
        admin["user"]["legal_entities"][0]["id"],
        "Birthday",
        birthday=date(1992, 10, 9),
        hired=date(2020, 10, 9),
    )
    login = await employee_login(client, self)
    headers = bearer(login["access_token"])
    india = await ok(client, "GET", PATH, headers=headers)
    assert india["date"] == "2026-10-09" and india["personal"]["birthday"]
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET timezone='America/Los_Angeles' WHERE id=:tid"),
            {"tid": to_uuid(admin["user"]["tenant_id"])},
        )
    west = await ok(client, "GET", PATH, headers=headers)
    assert west["date"] == "2026-10-08" and west["timezone"] == "America/Los_Angeles"
    assert west["personal"] == {"birthday": False, "anniversary_years": None}
    assert west["birthdays"] == west["anniversaries"] == []
