"""Synthetic migration checks against the isolated test database only."""

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from hrms.core.datetime_utils import is_working_day
from hrms.core.ids import to_typed_id, to_uuid
from hrms.modules.leave.router import _allocate_days
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import Punch
from hrms.modules.time.service import is_off_day
from tests.helpers import make_user, ok, person_and_employment, tenant

spec = importlib.util.spec_from_file_location(
    "legacy_attendance",
    Path(__file__).resolve().parents[1] / "scripts/migrate_legacy_attendance.py",
)
imp = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    spec.loader.exec_module(imp)
finally:
    sys.path.pop(0)


def stamp(value):
    return {"$date": value}


def test_exact_second_saturday_and_extended_json_dates():
    record = {
        "policy_type": "fixed",
        "applicability": {"teams": {"all": True}},
        "day_rules": [
            {"day_index": 0, "rules": [{"week_number": 0, "off_type": "full_day"}]},
            {"day_index": 6, "rules": [{"week_number": 2, "off_type": "full_day"}]},
        ],
    }
    fields = imp.weekoff_fields(record)
    assert fields == {"work_days": "1111110", "saturday_pattern": "SECOND_OFF"}
    assert is_working_day(date(2026, 10, 3), **fields)
    assert not is_working_day(date(2026, 10, 10), **fields)
    assert is_working_day(date(2026, 10, 24), **fields)
    assert is_working_day(date(2026, 10, 31), **fields)
    assert not is_working_day(date(2026, 10, 4), **fields)
    entry = {
        "holiday_name": "Gandhi",
        "holiday_date": {"$date": {"$numberLong": "-55642809600000"}},
    }
    with pytest.raises(ValueError, match="Holiday year mismatch"):
        imp.holiday_date(entry, 2026, False)
    assert imp.holiday_date(entry, 2026, True) == (date(2026, 10, 2), True)
    assert imp.instant(stamp("2026-09-30T20:00:00Z")) == datetime(2026, 9, 30, 20, tzinfo=UTC)
    record["day_rules"][0]["rules"][0]["off_type"] = "half_day"
    with pytest.raises(ValueError, match="Unsupported source off_type"):
        imp.weekoff_fields(record)


@pytest.mark.database
async def test_weekoff_defaults_cover_linked_employees_without_october_punches(api, tmp_path):
    client, engine = api
    company = await tenant(client)
    tid = to_uuid(company["user"]["tenant_id"])
    entity = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Policy Audit Co"})
    users, employees = [], []
    for source_id, company_id in (
        ("company-default", "company-1"),
        ("sunday-default", "company-2"),
    ):
        emp = await person_and_employment(client, entity["id"])
        _, _, account = await make_user(client, emp["id"])
        employees.append(to_uuid(emp["id"]))
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE user_accounts SET erp_system='EXIM',erp_user_id=:sid "
                    "WHERE tenant_id=:tid AND id=:uid"
                ),
                {"sid": source_id, "tid": tid, "uid": to_uuid(account["id"])},
            )
        users.append(
            {
                "_id": {"$oid": source_id},
                "company": "Policy Audit Co",
                "company_id": {"$oid": company_id},
            }
        )
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json={
            "name": "Native shift",
            "is_default": True,
            "timezone": "Asia/Kolkata",
            "work_days": "1111100",
        },
    )
    week = {
        "_id": {"$oid": "company-weekoff"},
        "company_id": {"$oid": "company-1"},
        "policy_name": "HO Weekoff",
        "policy_type": "fixed",
        "status": "active",
        "applicability": {"teams": {"all": True}},
        "createdAt": stamp("2026-04-01T00:00:00Z"),
        "day_rules": [
            {"day_index": 0, "rules": [{"week_number": 0, "off_type": "full_day"}]},
            {"day_index": 6, "rules": [{"week_number": 2, "off_type": "full_day"}]},
        ],
    }
    for name, rows in (
        ("users", users),
        ("weekoffpolicies", [week]),
        ("holidaypolicies", []),
        ("attendancepunches", []),
    ):
        (tmp_path / f"exim.{name}.json").write_text(json.dumps(rows))
    async with AsyncSession(engine) as session:
        _, dry = await imp.migrate(session, str(tid), tmp_path)
        assert dry["created"]["employee_policy_assignments"] == 2
        assert dry["legacy_sunday_fallback_assignments"] == 1
        assert dry["recomputed_days"] == 0
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("SELECT count(*) FROM employee_policy_assignments WHERE tenant_id=:tid"),
                {"tid": tid},
            )
        ).scalar_one() == 0
    async with AsyncSession(engine) as session, session.begin():
        await imp.migrate(session, str(tid), tmp_path)
    async with AsyncSession(engine) as session:
        _, rerun = await imp.migrate(session, str(tid), tmp_path)
        assert sum(rerun["created"].values()) == 0
        # Company policy skips only its second Saturday; the fallback skips Sundays only.
        for eid, second_saturday_off in zip(employees, (True, False), strict=True):
            for day, expected_off in (
                (date(2026, 10, 3), False),
                (date(2026, 10, 4), True),
                (date(2026, 10, 10), second_saturday_off),
            ):
                policy = await resolve_policy(eid, day, session, tid)
                assert await is_off_day(session, tid, eid, day, policy) == expected_off
                assert sum(
                    (await _allocate_days(session, tid, eid, day, day, "NONE")).values()
                ) == (0 if expected_off else 1)
        await session.rollback()


@pytest.mark.database
async def test_import_rolls_back_reruns_and_keeps_calendars_separate(api, tmp_path):
    client, engine = api
    company = await tenant(client)
    tid = to_uuid(company["user"]["tenant_id"])
    entity = await ok(
        client, "POST", "/v1/org/legal-entities", json={"name": "Synthetic Import Co"}
    )
    employees = []
    for label in ("ho", "ops"):
        emp = await person_and_employment(client, entity["id"])
        _, _, account = await make_user(client, emp["id"])
        employees.append(to_uuid(emp["id"]))
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                UPDATE user_accounts SET erp_system='EXIM',erp_user_id=:sid
                WHERE tenant_id=:tid AND id=:uid
            """),
                {"sid": label, "tid": tid, "uid": to_uuid(account["id"])},
            )
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json={
            "name": "Existing shift",
            "is_default": True,
            "timezone": "Asia/Kolkata",
            "expected_start_time": "09:30:00",
            "expected_end_time": "18:30:00",
            "ot_enabled": False,
        },
    )
    users = [
        {
            "_id": {"$oid": label},
            "company": "Synthetic Import Co",
            "company_id": {"$oid": "source-company"},
            "weekoff_policy_id": {"$oid": "week"},
            "holiday_policy_id": {"$oid": label},
        }
        for label in ("ho", "ops")
    ]
    users.append({"_id": {"$oid": "rabs"}, "company": "RABS Industries India Private Limited"})
    week = {
        "_id": {"$oid": "week"},
        "policy_name": "Second Saturday",
        "description": "original",
        "policy_type": "fixed",
        "status": "active",
        "applicability": {"teams": {"all": True}},
        "createdAt": stamp("2026-04-01T00:00:00Z"),
        "day_rules": [
            {"day_index": 0, "rules": [{"week_number": 0, "off_type": "full_day"}]},
            {"day_index": 6, "rules": [{"week_number": 2, "off_type": "full_day"}]},
        ],
    }
    calendars = [
        {
            "_id": {"$oid": label},
            "policy_name": label.upper(),
            "year": 2026,
            "status": "active",
            "applicability": {"teams": {"all": True}},
            "createdAt": stamp("2026-04-01T00:00:00Z"),
            "holidays": [
                {
                    "holiday_name": label + " holiday",
                    "is_optional": False,
                    "holiday_type": "national",
                    "holiday_date": stamp(f"2026-10-0{day}T00:00:00Z"),
                }
            ],
        }
        for label, day in [("ho", 2), ("ops", 3)]
    ]
    punches = []
    for label in ("ho", "ops", "rabs"):
        for month, day, hour, kind in [
            ("09", "30", "04", "IN"),
            ("10", "01", "04", "IN"),
            ("10", "01", "13", "OUT"),
        ]:
            punches.append(
                {
                    "_id": {"$oid": f"{label}-{month}-{kind}"},
                    "employee_id": {"$oid": label},
                    "company_id": {"$oid": "source-company"},
                    "punch_date_str": f"2026-{month}-{day}",
                    "punch_time": stamp(f"2026-{month}-{day}T{hour}:00:00Z"),
                    "createdAt": stamp(f"2026-{month}-{day}T{hour}:00:00Z"),
                    "punch_type": kind,
                    "punch_method": "web",
                    "is_valid": True,
                    "is_regularized": False,
                }
            )
    for name, rows in [
        ("users", users),
        ("attendancepunches", punches),
        ("weekoffpolicies", [week]),
        ("holidaypolicies", calendars),
    ]:
        (tmp_path / f"exim.{name}.json").write_text(json.dumps(rows))

    # Exact migration path, including computation, leaves no data on rollback.
    async with AsyncSession(engine) as session:
        _, dry = await imp.migrate(session, str(tid), tmp_path)
        assert dry["created"]["punches"] == 4 and dry["recomputed_days"] == 2
        assert len(dry["deferred_rabs_punches"]) == 2
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(text("SELECT count(*) FROM punches WHERE tenant_id=:t"), {"t": tid})
        ).scalar() == 0

    async with AsyncSession(engine) as session, session.begin():
        _, applied = await imp.migrate(session, str(tid), tmp_path)
        assert applied["created"]["holidays"] == 2
    async with AsyncSession(engine) as session, session.begin():
        _, rerun = await imp.migrate(session, str(tid), tmp_path)
        assert sum(rerun["created"].values()) == 0
        assert rerun["existing"]["punches"] == 4
        for eid, own_day, other_day in [(employees[0], 2, 3), (employees[1], 3, 2)]:
            policy = await resolve_policy(eid, date(2026, 10, own_day), session, tid)
            assert await is_off_day(session, tid, eid, date(2026, 10, own_day), policy)
            assert not await is_off_day(session, tid, eid, date(2026, 10, other_day), policy)

    holidays = await ok(client, "GET", "/v1/time/holidays?year=2026")
    assert {h["calendar_name"] for h in holidays} == {"HO", "OPS"}
    for day, eid in [(2, employees[0]), (3, employees[1])]:
        records = await ok(client, "GET", f"/v1/time/daily-analysis?work_date=2026-10-0{day}")
        own = next(r for r in records["employees"] if to_uuid(r["employment_id"]) == eid)
        assert own["status"] == "HOLIDAY"
        reg = await ok(
            client,
            "GET",
            (
                f"/v1/time/register/{to_typed_id('employment', eid)}"
                "?from_date=2026-10-02&to_date=2026-10-03"
            ),
        )
        assert (
            next(r for r in reg["days"] if r["work_date"] == f"2026-10-0{day}")["status"]
            == "HOLIDAY"
        )
        async with AsyncSession(engine) as session:
            assert (
                await _allocate_days(
                    session, tid, eid, date(2026, 10, day), date(2026, 10, day), "NONE"
                )
                == {}
            )

    # Native punches are retained when their sequence conflicts with the imported day.
    native_id = imp.source_uuid(tid, "test-native", "collision")
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Punch(
                tenant_id=tid,
                id=native_id,
                employment_id=employees[0],
                work_date=date(2026, 10, 1),
                punch_type="IN",
                source="WEB",
                punched_at=datetime(2026, 10, 1, 4, 1, tzinfo=UTC),
            )
        )
    async with AsyncSession(engine) as session, session.begin():
        _, conflict = await imp.migrate(session, str(tid), tmp_path)
        assert len(conflict["days_needing_correction"]) == 1
        row = (
            await session.execute(
                text(
                    "SELECT effective_minutes,review_flags FROM attendance_days "
                    "WHERE tenant_id=:tid AND employment_id=:eid"
                ),
                {"tid": tid, "eid": employees[0]},
            )
        ).one()
        assert row.effective_minutes == 0 and row.review_flags == "LEGACY_CONFLICT"
        assert await session.get(Punch, (tid, native_id)) is not None

    # Locked periods refuse the entire rerun; source drift also fails closed.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE attendance_days SET is_locked=true WHERE tenant_id=:t"), {"t": tid}
        )
    with pytest.raises(HTTPException, match="locked"):
        async with AsyncSession(engine) as session, session.begin():
            await imp.migrate(session, str(tid), tmp_path)
    punches[1]["punch_time"] = stamp("2026-10-01T05:00:00Z")
    (tmp_path / "exim.attendancepunches.json").write_text(json.dumps(punches))
    with pytest.raises(ValueError, match="differs at punched_at"):
        async with AsyncSession(engine) as session, session.begin():
            await imp.migrate(session, str(tid), tmp_path)
    # A different tenant cannot see imported calendar rows through RLS.
    await tenant(client)
    assert await ok(client, "GET", "/v1/time/holidays?year=2026") == []
