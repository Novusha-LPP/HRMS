"""Attendance report filters and PostgreSQL historical joins."""

import os
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.ids import to_typed_id
from hrms.modules.reports.router import RunRequest, _attendance_filters, _run_attendance


def test_date_operators_and_native_bindings():
    for op in ("eq", "gte", "lte", "between"):
        value = ["2026-09-01", "2026-09-30"] if op == "between" else "2026-09-01"
        clauses, params = _attendance_filters([dict(field="work_date", op=op, value=value)])
        assert len(clauses) == 1
        assert all(isinstance(v, date) for v in params.values())


@pytest.mark.parametrize(
    "spec",
    [
        dict(field="work_date", op="eq", value="2026-02-30"),
        dict(field="work_date", op="between", value="2026-09-01"),
        dict(field="work_date", op="between", value=["2026-09-30", "2026-09-01"]),
        dict(field="work_date", op="contains", value="2026"),
        dict(field="status", op="eq", value="UNKNOWN"),
        dict(field="status", op="in", value=[]),
        dict(field="department", op="eq", value=["A", "B"]),
        dict(field="location", op="in", value=[None]),
        dict(field="employment_id", op="eq", value="bad"),
        dict(field="unrecognized", op="eq", value="x"),
    ],
)
def test_invalid_filters_are_rejected(spec):
    with pytest.raises(HTTPException) as exc:
        _attendance_filters([spec])
    assert exc.value.status_code == 422


def test_contradictory_ranges():
    with pytest.raises(HTTPException):
        _attendance_filters(
            [
                dict(field="work_date", op="gte", value="2026-09-30"),
                dict(field="work_date", op="lte", value="2026-09-01"),
            ]
        )


def test_all_attendance_filters_and_empty_defaults():
    uid = uuid4()
    clauses, params = _attendance_filters(
        [
            dict(field="work_date", op="gte", value=""),
            dict(field="status", op="in", value=["WEEKEND", "EARLY_DEPARTURE", "PENDING"]),
            dict(field="department", op="eq", value="O'Brien"),
            dict(field="location", op="in", value=["A", "B"]),
            dict(field="employment_id", op="eq", value=to_typed_id("employment", uid)),
        ]
    )
    assert len(clauses) == 4
    assert params["f4"] == str(uid)
    assert "O'Brien" not in " ".join(clauses)


@pytest.mark.parametrize("limit", [0, -1, 10001])
def test_limits_are_bounded(limit):
    with pytest.raises(ValidationError):
        RunRequest(limit=limit)


@pytest.mark.database
async def test_historical_assignment_and_filters_in_postgres():
    engine = create_async_engine(os.environ["HRMS_TEST_DATABASE_URL"])
    tenant, employee, person, old_dept, new_dept, location = [uuid4() for _ in range(6)]
    # Temporary tables isolate this query from the persistent schema and test data.
    async with engine.connect() as conn:
        definitions = {
            "persons": "tenant_id uuid, id uuid, legal_first_name text, legal_last_name text",
            "employments": "tenant_id uuid, id uuid, person_id uuid, employee_number text",
            "org_units": "tenant_id uuid, id uuid, name text",
            "locations": "tenant_id uuid, id uuid, name text",
            "assignments": "tenant_id uuid, id uuid, employment_id uuid, "
            "effective_from date, effective_to date, org_unit_id uuid, location_id "
            "uuid, recorded_at timestamptz",
            "attendance_days": "tenant_id uuid, id uuid, employment_id uuid, "
            "work_date date, status text, first_punch_in timestamptz, "
            "last_punch_out timestamptz, effective_minutes int, late_by_minutes "
            "int, early_departure_minutes int",
        }
        for table, definition in definitions.items():
            await conn.execute(text(f"CREATE TEMP TABLE {table} ({definition})"))
        params = dict(t=tenant, e=employee, p=person, o=old_dept, n=new_dept, l=location)
        for query in [
            "INSERT INTO persons VALUES (:t,:p,'Jane','Doe')",
            "INSERT INTO employments VALUES (:t,:e,:p,'001')",
            "INSERT INTO org_units VALUES (:t,:o,'Old'), (:t,:n,'New')",
            "INSERT INTO locations VALUES (:t,:l,'HQ')",
            "INSERT INTO assignments VALUES "
            "(:t,gen_random_uuid(),:e,'2026-01-01','2026-09-02',:o,:l,now()), "
            "(:t,gen_random_uuid(),:e,'2026-09-02',NULL,:n,:l,now())",
            "INSERT INTO attendance_days VALUES "
            "(:t,gen_random_uuid(),:e,'2026-09-01','PRESENT','2026-09-01 "
            "16:30+00','2026-09-02 00:30+00',450,0,0), "
            "(:t,gen_random_uuid(),:e,'2026-09-02','PENDING','2026-09-02 "
            "16:30+00',NULL,0,0,0)",
        ]:
            await conn.execute(text(query), params)
        scope = SimpleNamespace(employment_filter_sql=lambda alias: ("", {}))
        rows = await _run_attendance(conn, tenant, [], [], 100, scope)
        assert len(rows) == 2
        assert [r["department"] for r in rows] == ["New", "Old"]
        assert rows[0]["last_punch_out"] is None
        assert rows[1]["last_punch_out"].date() > rows[1]["work_date"]
        for field, op, value, expected in [
            ("work_date", "eq", "2026-09-01", 1),
            ("work_date", "between", ["2026-09-01", "2026-09-02"], 2),
            ("department", "eq", "Old", 1),
            ("location", "in", ["HQ"], 2),
            ("status", "eq", "PENDING", 1),
            ("employment_id", "eq", to_typed_id("employment", uuid4()), 0),
        ]:
            selected = await _run_attendance(
                conn, tenant, [], [dict(field=field, op=op, value=value)], 100, scope
            )
            assert len(selected) == expected
        restricted = SimpleNamespace(
            employment_filter_sql=lambda alias: ("AND e.id = :allowed", {"allowed": uuid4()})
        )
        assert await _run_attendance(conn, tenant, [], [], 100, restricted) == []
        assert await _run_attendance(conn, uuid4(), [], [], 100, scope) == []
    await engine.dispose()


def test_breaks_in_incomplete_session_do_not_reduce_completed_work():
    from datetime import UTC, datetime

    from hrms.modules.time.service import event_minutes

    events = [
        SimpleNamespace(punch_type=kind, punched_at=datetime(2026, 9, 1, h, m, tzinfo=UTC))
        for kind, h, m in [
            ("IN", 9, 0),
            ("OUT", 12, 0),
            ("IN", 13, 0),
            ("BREAK_START", 14, 0),
            ("BREAK_END", 14, 30),
        ]
    ]
    assert event_minutes(events) == (180, 0, True, 180)


def test_event_duration_across_dst_fallback():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from hrms.modules.time.service import event_minutes

    tz = ZoneInfo("America/New_York")
    events = [
        SimpleNamespace(
            punch_type="IN", punched_at=datetime(2026, 11, 1, 1, 30, tzinfo=tz, fold=0)
        ),
        SimpleNamespace(
            punch_type="OUT", punched_at=datetime(2026, 11, 1, 1, 30, tzinfo=tz, fold=1)
        ),
    ]
    assert event_minutes(events) == (60, 0, False, 60)


@pytest.mark.database
async def test_reports_match_punches_and_approved_corrections(api):
    from datetime import timedelta

    from tests.helpers import bearer, employee, ok, tenant

    client, _ = api
    admin = await tenant(client)
    emp, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = bearer(login["access_token"])
    columns = [
        dict(field=f, label=f, visible=True)
        for f in ["work_date", "first_punch_in", "last_punch_out", "effective_minutes", "status"]
    ]
    report = await ok(
        client,
        "POST",
        "/v1/reports",
        json=dict(
            name="Punch audit", module="ATTENDANCE", columns=columns, filters=[], owner_type="HR"
        ),
    )
    await ok(client, "POST", "/v1/time/punches", headers=headers, json={"punch_type": "IN"})
    response = await client.post("/v1/time/punches", headers=headers, json={"punch_type": "IN"})
    assert response.status_code == 409
    today = await ok(client, "GET", "/v1/time/today", headers=headers)
    result = await ok(
        client,
        "POST",
        f"/v1/reports/{report['id']}/run",
        json={
            "filters": [
                dict(field="employment_id", op="eq", value=emp["id"]),
                dict(field="work_date", op="eq", value=today["work_date"]),
            ]
        },
    )
    assert len(result["rows"]) == 1
    assert result["rows"][0]["first_punch_in"] == today["first_punch_in"]
    assert result["rows"][0]["last_punch_out"] is None
    day = date.fromisoformat(today["work_date"]) - timedelta(days=1)
    correction = await ok(
        client,
        "POST",
        "/v1/corrections",
        headers=headers,
        json={
            "work_date": str(day),
            "correction_type": "REGULARIZE",
            "requested_punch_in": f"{day}T09:00:00Z",
            "requested_punch_out": f"{day}T18:00:00Z",
            "reason": "Report regression",
        },
    )
    await ok(
        client, "POST", f"/v1/corrections/{correction['id']}/approve", json={"action": "APPROVE"}
    )
    result = await ok(client, "POST", f"/v1/reports/{report['id']}/run", json={"limit": 1})
    assert result["total_rows"] == 1 and result["truncated"] is True
    result = await ok(
        client,
        "POST",
        f"/v1/reports/{report['id']}/run",
        json={"filters": [dict(field="work_date", op="eq", value=str(day))]},
    )
    assert result["rows"][0]["effective_minutes"] == 540
    assert result["rows"][0]["last_punch_out"] is not None
    invalid = await client.post(
        f"/v1/reports/{report['id']}/run",
        json={"filters": [dict(field="work_date", op="eq", value="not-a-date")]},
    )
    assert invalid.status_code == 422
