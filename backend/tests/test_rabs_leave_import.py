"""RABS definitions retain their own rules and never grant employee access."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from hrms.core.ids import to_typed_id, to_uuid
from hrms.modules.kernel.models import ImportBatch
from hrms.modules.leave.models import LeaveBucketPolicy, LeaveType
from hrms.modules.leave.router import _validate_application
from hrms.modules.leave.schemas import LeaveApplyRequest
from tests.helpers import ok, person_and_employment, tenant
from tests.test_legacy_leave_import import source_policy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import migrate_rabs_leave as imp
finally:
    sys.path.pop(0)


@pytest.mark.database
async def test_rabs_definitions_are_distinct_unassigned_and_idempotent(api, tmp_path, monkeypatch):
    client, engine = api
    auth = await tenant(client)
    tid = to_uuid(auth["user"]["tenant_id"])
    async with engine.connect() as conn:
        slug = (
            await conn.execute(text("select slug from tenants where id=:tid"), {"tid": tid})
        ).scalar_one()
    monkeypatch.setattr(imp, "TARGET_SLUG", slug)
    entity = auth["user"]["legal_entities"][0]["id"]
    employee = await person_and_employment(client, entity)
    native = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={
            "name": "Native Paid Leave",
            "code": "PL",
            "days_per_year": 20,
        },
    )
    policies = [
        source_policy("privilege", imp.RABS, "privilege"),
        source_policy("paid", imp.RABS, "casual"),
        source_policy("unpaid", imp.RABS, "lwp"),
        source_policy("old-paid", imp.RABS, "casual"),
        source_policy("old-lwp", imp.RABS, "lwp"),
    ]
    for p in policies:
        p["updatedAt"] = p["createdAt"]
        if p["leave_type"] == "casual":
            p.update(policy_name="Paid Leave", leave_code="PL", annual_quota=12)
            p["eligibility"] = {"employment_types": ["permanent"], "min_service_months": 6}
            p["rules"]["can_apply_on_probation"] = False
        if p["_id"]["$oid"].startswith("old-"):
            p["status"] = "inactive"
        if p["_id"]["$oid"] == "unpaid":
            p["policy_name"] = "Unpaid Leave"
            p["annual_quota"] = 12
            p["deduction_rules"]["deduct_from_salary"] = False
            p["deduction_rules"]["counted_as_absence"] = False
            p["rules"]["sandwich_rule_enabled"] = True
    foreign = source_policy("suraj", "suraj-company", "privilege")
    export = tmp_path / "exim.leavepolicies.json"
    export.write_text(json.dumps(policies + [foreign]))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        _, _, dry = await imp.migrate(session, str(tid), tmp_path)
        assert dry["source_policy_count"] == 5
        assert dry["active_source_policies"] == 3 and dry["inactive_source_policies"] == 2
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("select count(*) from leave_types where tenant_id=:tid"), {"tid": tid}
            )
        ).scalar() == 1
    async with AsyncSession(engine, expire_on_commit=False) as session:
        _, bid, report = await imp.migrate(session, str(tid), tmp_path)
        session.add(
            ImportBatch(tenant_id=tid, id=bid, source_system="EXIM_RABS_LEAVE", details=report)
        )
        await session.commit()
        _, _, again = await imp.migrate(session, str(tid), tmp_path)
        assert sum(again["created"].values()) == 0
        assert len({m["type_id"] for m in report["mappings"]}) == 5
        assert len({m["bucket_id"] for m in report["mappings"]}) == 5
        for p in policies:
            sid = p["_id"]["$oid"]
            lt = await session.get(LeaveType, (tid, imp.uid(tid, "rabs-type", sid)))
            bp = await session.get(
                LeaveBucketPolicy, (tid, imp.uid(tid, "rabs-definition-bucket", sid))
            )
            assert bp.source_policy == p
            assert lt.is_active == (p["status"] == "active")
            assert bool(lt.archived_at) == (p["status"] == "inactive")
            assert lt.days_per_year == p["annual_quota"]
            assert lt.is_paid == (not p["deduction_rules"]["deduct_from_salary"])
            assert lt.accrual_enabled is False
            if p["status"] == "active":
                body = LeaveApplyRequest(
                    leave_type_id=to_typed_id("leave_type", lt.id),
                    from_date=date(2026, 11, 2),
                    to_date=date(2026, 11, 2),
                )
                with pytest.raises(HTTPException, match="not assigned"):
                    await _validate_application(session, tid, to_uuid(employee["id"]), lt, body, 1)
        retained = await session.get(LeaveType, (tid, to_uuid(native["id"])))
        assert retained.days_per_year == 20 and retained.legacy_managed is False
        await session.rollback()
    async with engine.connect() as conn:
        for table in [
            "leave_policy_assignments",
            "leave_monthly_ledger",
            "leave_balance_transactions",
        ]:
            assert (
                await conn.execute(
                    text(f"select count(*) from {table} where tenant_id=:tid"), {"tid": tid}
                )
            ).scalar() == 0
    policies[0]["annual_quota"] = 26
    export.write_text(json.dumps(policies + [foreign]))
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="Source export changed"):
            await imp.migrate(session, str(tid), tmp_path)
        await session.rollback()
        monkeypatch.setattr(imp, "TARGET_SLUG", "unapproved")
        with pytest.raises(ValueError, match="restricted to the approved RABS"):
            await imp.migrate(session, str(tid), tmp_path)
