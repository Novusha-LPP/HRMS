"""Real import/applicability tests on synthetic data in the isolated test DB."""

import importlib.util
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
from hrms.modules.leave.models import LeaveType
from hrms.modules.leave.policy_resolver import resolve_employee_bucket_policy
from hrms.modules.leave.router import _validate_application
from hrms.modules.leave.schemas import LeaveApplyRequest
from tests.helpers import make_user, ok, person_and_employment, tenant

spec = importlib.util.spec_from_file_location(
    "legacy_leave", Path(__file__).resolve().parents[1] / "scripts/migrate_legacy_leave.py"
)
imp = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    spec.loader.exec_module(imp)
finally:
    sys.path.pop(0)


def source_policy(sid, company, kind):
    return {
        "_id": {"$oid": sid},
        "company_id": {"$oid": company},
        "policy_name": "Privilege Leave" if kind == "privilege" else "Leave Without Pay",
        "leave_type": kind,
        "leave_code": "PL" if kind == "privilege" else "LWP",
        "annual_quota": 25 if kind == "privilege" else 0,
        "eligibility": {"employment_types": [], "min_service_months": 0},
        "carry_forward": {
            "allowed": kind == "privilege",
            "max_days": 15,
            "encashment_allowed": False,
        },
        "rules": {
            "min_days_per_application": 1,
            "max_days_per_application": 30,
            "advance_notice_days": 1,
            "half_day_allowed": True,
            "can_apply_on_probation": True,
            "backdated_allowed": False,
            "sandwich_rule_enabled": False,
            "requires_document": False,
            "clubbing_allowed_with": [],
            "max_consecutive_days": 10,
        },
        "approval_workflow": {"levels": [], "auto_approve_if_balance": False},
        "deduction_rules": {
            k: kind == "lwp"
            for k in ["deduct_from_salary", "affects_attendance_percentage", "counted_as_absence"]
        },
        "status": "active",
        "createdAt": {"$date": "2026-01-01T00:00:00Z"},
    }


def test_unsupported_rules_and_ambiguous_payroll_are_rejected():
    p = source_policy("pl", "company", "privilege")
    p["rules"]["sandwich_rule_enabled"] = True
    with pytest.raises(ValueError, match="Unsupported Suraj application rules"):
        imp.validate_definition(p)
    p["rules"]["sandwich_rule_enabled"] = False
    p["deduction_rules"]["deduct_from_salary"] = True
    with pytest.raises(ValueError, match="Ambiguous deduction rules"):
        imp.validate_definition(p)


@pytest.mark.database
async def test_suraj_import_rollback_rerun_rules_and_existing_entitlements(
    api, tmp_path, monkeypatch
):
    client, engine = api
    auth = await tenant(client)
    tid = to_uuid(auth["user"]["tenant_id"])
    async with engine.connect() as conn:
        slug = (
            await conn.execute(text("select slug from tenants where id=:tid"), {"tid": tid})
        ).scalar_one()
    monkeypatch.setattr(imp, "TARGET_SLUG", slug)
    from hrms.modules.leave import legacy

    monkeypatch.setattr(legacy, "business_today", lambda: date(2026, 10, 6))
    entity = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Synthetic Suraj"})
    employees = []
    users = []
    for label, refs in [("assigned", ["pl"]), ("lwp-only", []), ("cross", ["foreign-pl"])]:
        emp = await person_and_employment(client, entity["id"])
        _, _, account = await make_user(client, emp["id"])
        employees.append(to_uuid(emp["id"]))
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE user_accounts SET erp_system='EXIM',erp_user_id=:sid "
                    "WHERE tenant_id=:tid AND id=:id"
                ),
                {"sid": label, "tid": tid, "id": to_uuid(account["id"])},
            )
        users.append(
            {
                "_id": {"$oid": label},
                "company": "Synthetic Suraj",
                "company_id": {"$oid": "company"},
                "leave_settings": {"special_leave_policies": [{"$oid": r} for r in refs]},
            }
        )
    users.append(
        {
            "_id": {"$oid": "foreign"},
            "company": "Other company",
            "company_id": {"$oid": "foreign-company"},
        }
    )
    users.append(
        {
            "_id": {"$oid": "rabs"},
            "company": "RABS Industries India Private Limited",
            "company_id": {"$oid": imp.RABS},
        }
    )
    policies = [
        source_policy("pl", "company", "privilege"),
        source_policy("lwp", "company", "lwp"),
        source_policy("foreign-pl", "foreign-company", "privilege"),
        source_policy("foreign-lwp", "foreign-company", "lwp"),
        source_policy("rabs-policy", imp.RABS, "privilege"),
    ]
    for name, data in [
        ("users", users),
        ("leavepolicies", policies),
        ("leavequotas", [{"driver_id": "d"}]),
    ]:
        (tmp_path / f"exim.{name}.json").write_text(json.dumps(data))
    bucket = await ok(
        client, "POST", "/v1/leave/buckets", json={"name": "Native", "code": "NATIVE"}
    )
    pset = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Native entitlements", "is_default": True},
    )
    await ok(
        client,
        "POST",
        f"/v1/leave/policy-sets/{pset['id']}/bucket-policies",
        json={
            "bucket_id": bucket["id"],
            "accrual_type": "MONTHLY_PRORATE",
            "days_per_year": 18,
            "carry_forward_enabled": True,
            "max_carry_forward_days": 10,
        },
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        _, _, dry = await imp.migrate(session, str(tid), tmp_path)
        assert dry["source_policy_count"] == 4
        assert dry["assigned_employees"] == 3
        assert dry["employees_with_privilege_leave"] == 1
        assert dry["deferred_policy_ids"] == ["rabs-policy"]
        await session.rollback()
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text(
                    "select count(*) from leave_types where tenant_id=:tid and legacy_managed=true"
                ),
                {"tid": tid},
            )
        ).scalar() == 0
    async with AsyncSession(engine, expire_on_commit=False) as session:
        _, bid, report = await imp.migrate(session, str(tid), tmp_path)
        session.add(ImportBatch(tenant_id=tid, id=bid, source_system="EXIM_LEAVE", details=report))
        await session.commit()
        _, _, rerun = await imp.migrate(session, str(tid), tmp_path)
        assert sum(rerun["created"].values()) == 0
        assert len(rerun["ignored_cross_company_references"]) == 1
        pl = await session.get(LeaveType, (tid, imp.uid(tid, "type", "privilege")))
        lwp = await session.get(LeaveType, (tid, imp.uid(tid, "type", "lwp")))

        def request(start="2026-11-02", end="2026-11-02", half="NONE"):
            return LeaveApplyRequest(
                leave_type_id=to_typed_id("leave_type", lwp.id),
                from_date=start,
                to_date=end,
                half_day_option=half,
            )

        await _validate_application(session, tid, employees[0], pl, request(), 1)
        await _validate_application(
            session, tid, employees[1], lwp, request(half="FIRST_HALF"), 0.5
        )
        for employee in employees[1:]:
            with pytest.raises(HTTPException, match="not assigned"):
                await _validate_application(session, tid, employee, pl, request(), 1)
        with pytest.raises(HTTPException, match="consecutive-day"):
            await _validate_application(
                session, tid, employees[1], lwp, request(end="2026-11-12"), 9
            )
        with pytest.raises(HTTPException, match="backdated"):
            await _validate_application(
                session, tid, employees[1], lwp, request(start="2026-10-05", end="2026-10-05"), 1
            )
        for employee in employees:
            native = await resolve_employee_bucket_policy(
                session, tid, employee, to_uuid(bucket["id"]), date(2026, 11, 2)
            )
            assert native.days_per_year == 18 and native.accrual_type == "MONTHLY_PRORATE"
            assert native.max_carry_forward_days == 10 and native.source_policy is None
        await session.rollback()
    # A real HTTP submission of unpaid leave must work without inventing a balance.
    application = await ok(
        client,
        "POST",
        "/v1/leave/applications",
        params={"employment_id": to_typed_id("employment", employees[1])},
        json={
            "leave_type_id": to_typed_id("leave_type", imp.uid(tid, "type", "lwp")),
            "from_date": "2026-11-02",
            "to_date": "2026-11-02",
            "reason": "Synthetic",
        },
    )
    submitted = await ok(client, "POST", f"/v1/leave/applications/{application['id']}/submit")
    assert submitted["status"] == "PENDING_L1" and submitted["total_levels"] == 3
    async with engine.connect() as conn:
        for table in ["leave_monthly_ledger", "leave_balance_transactions", "leave_balances"]:
            assert (
                await conn.execute(
                    text(f"select count(*) from {table} where tenant_id=:tid"), {"tid": tid}
                )
            ).scalar() == 0
    changed = policies.copy()
    changed[0]["annual_quota"] = 26
    (tmp_path / "exim.leavepolicies.json").write_text(json.dumps(changed))
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="Source exports changed"):
            await imp.migrate(session, str(tid), tmp_path)
        await session.rollback()
        monkeypatch.setattr(imp, "TARGET_SLUG", "unapproved")
        with pytest.raises(ValueError, match="Only the approved"):
            await imp.migrate(session, str(tid), tmp_path)
