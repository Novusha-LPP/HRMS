"""Confirmed mapping, tenant scope and atomic/idempotent RABS punch imports."""

import csv
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from hrms.core.ids import to_uuid
from tests.helpers import ok, person_and_employment, tenant

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import import_rabs_october as imp
finally:
    sys.path.pop(0)


def write_map(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "legacy_user_id",
                "confirmed_hrms_employment_id",
                "candidate_hrms_employment_id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_candidate_is_not_a_confirmed_mapping(tmp_path):
    path = tmp_path / "map.csv"
    write_map(
        path,
        [
            {
                "legacy_user_id": "candidate",
                "confirmed_hrms_employment_id": "",
                "candidate_hrms_employment_id": str(uuid4()),
            }
        ],
    )
    assert imp.confirmed_links(path) == {}
    write_map(path, [{"legacy_user_id": "duplicate", "confirmed_hrms_employment_id": ""}] * 2)
    with pytest.raises(ValueError, match="duplicate source employee"):
        imp.confirmed_links(path)


@pytest.mark.database
async def test_confirmed_partial_import_is_atomic_scoped_and_rerunnable(api, tmp_path, monkeypatch):
    client, engine = api
    company = await tenant(client)
    tid = to_uuid(company["user"]["tenant_id"])
    async with engine.connect() as conn:
        slug = (
            await conn.execute(text("select slug from tenants where id=:tid"), {"tid": tid})
        ).scalar_one()
    monkeypatch.setattr(imp, "TARGET_SLUG", slug)
    entity = await ok(
        client,
        "POST",
        "/v1/org/legal-entities",
        json={"name": "RABS Industries India Private Limited"},
    )
    emp = await person_and_employment(client, entity["id"])
    eid = to_uuid(emp["id"])
    await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json={
            "name": "Test current shift",
            "is_default": True,
            "timezone": "Asia/Kolkata",
            "expected_start_time": "09:30:00",
            "expected_end_time": "18:30:00",
            "ot_enabled": False,
        },
    )
    users = [
        {"_id": {"$oid": sid}, "company_id": {"$oid": imp.RABS}} for sid in ["known", "unmapped"]
    ]

    def punch(sid, owner, stamp, day="2026-10-05", kind="IN"):
        return {
            "_id": {"$oid": sid},
            "employee_id": {"$oid": owner},
            "company_id": {"$oid": imp.RABS},
            "punch_time": {"$date": stamp},
            "punch_date_str": day,
            "punch_type": kind,
            "punch_method": "mobile",
            "is_valid": True,
            "is_regularized": False,
            "createdAt": {"$date": stamp},
        }

    punches = [
        punch("in", "known", "2026-10-05T04:00:00Z"),
        punch("out", "known", "2026-10-05T13:00:00Z", kind="OUT"),
        punch("other", "unmapped", "2026-10-05T04:00:00Z"),
    ]
    (tmp_path / "exim.users.json").write_text(json.dumps(users))
    source = tmp_path / "exim.attendancepunches.json"
    source.write_text(json.dumps(punches))
    mapping = tmp_path / "map.csv"
    write_map(mapping, [{"legacy_user_id": "known", "confirmed_hrms_employment_id": str(eid)}])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        with pytest.raises(ValueError, match="Missing 1 confirmed"):
            await imp.migrate(session, tmp_path, mapping)
        await session.rollback()
        _, dry = await imp.migrate(session, tmp_path, mapping, True)
        assert dry["imported_punches"] == 2 and dry["deferred_punches"] == 1
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("select count(*) from punches where tenant_id=:tid"), {"tid": tid}
            )
        ).scalar() == 0
    async with AsyncSession(engine, expire_on_commit=False) as session:
        _, applied = await imp.migrate(session, tmp_path, mapping, True)
        assert applied["recomputed_days"] == 1
        await session.commit()
        _, repeated = await imp.migrate(session, tmp_path, mapping, True)
        assert sum(repeated["created"].values()) == 0 and repeated["recomputed_days"] == 0
        await session.rollback()
    other_entity = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Other Entity"})
    other_emp = await person_and_employment(client, other_entity["id"])
    write_map(
        mapping, [{"legacy_user_id": "known", "confirmed_hrms_employment_id": other_emp["id"]}]
    )
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="outside the RABS entity"):
            await imp.migrate(session, tmp_path, mapping, True)
        await session.rollback()
    write_map(mapping, [{"legacy_user_id": "known", "confirmed_hrms_employment_id": emp["id"]}])
    punches[0]["punch_time"]["$date"] = "2026-10-05T04:01:00Z"
    source.write_text(json.dumps(punches))
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="differs at punched_at"):
            await imp.migrate(session, tmp_path, mapping, True)
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("select count(*) from punches where tenant_id=:tid"), {"tid": tid}
            )
        ).scalar() == 2
        for table in ["leave_policy_assignments", "employee_policy_assignments"]:
            assert (
                await conn.execute(
                    text(f"select count(*) from {table} where tenant_id=:tid"), {"tid": tid}
                )
            ).scalar() == 0
