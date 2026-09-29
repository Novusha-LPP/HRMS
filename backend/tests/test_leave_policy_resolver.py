"""
Tests for Phase 2: Leave Policy Resolver and Leave Configuration CRUD API.

Covers:
1. CRUD operations for buckets, mappings, policy sets, bucket policies, and assignments.
2. Target validation on policy assignments (num_nonnulls == 1).
3. Policy resolution cascade (Tier 1: Employee -> Tier 2: Org Unit CTE ->
   Tier 3: Legal Entity -> Tier 4: Tenant Default).
4. Org unit CTE ancestor walk (child overrides parent, grandchild inherits from parent).
5. Effective date windowing (effective_from / effective_to).
6. Financial year start month resolution (Legal Entity vs Default).
7. Read endpoints for ledger and transactions history.
"""

from datetime import date

import pytest
from sqlalchemy import text

from hrms.core import database
from hrms.core.ids import to_uuid
from hrms.modules.leave.policy_resolver import (
    resolve_employee_bucket_policy,
    resolve_employee_fy_start_month,
    resolve_leave_policy_set,
)
from hrms.modules.org.models import LegalEntity
from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

AS_OF = date(2026, 4, 15)


# ─── API CRUD Tests ──────────────────────────────────────────────────────────


async def test_leave_bucket_crud(api):
    client, _ = api
    await tenant(client)

    # 1. Create bucket
    created = await ok(
        client,
        "POST",
        "/v1/leave/buckets",
        json={"name": "Paid Leave", "code": "PL", "is_unlimited": False, "is_active": True},
    )
    assert created["id"].startswith("lmb_")
    assert created["name"] == "Paid Leave"
    assert created["code"] == "PL"
    assert created["is_unlimited"] is False

    # 2. List buckets
    buckets = await ok(client, "GET", "/v1/leave/buckets")
    assert any(b["code"] == "PL" for b in buckets)

    # 3. Patch bucket
    bucket_id = created["id"]
    updated = await ok(
        client,
        "PATCH",
        f"/v1/leave/buckets/{bucket_id}",
        json={"name": "Annual / Paid Leave", "is_active": False},
    )
    assert updated["name"] == "Annual / Paid Leave"
    assert updated["is_active"] is False

    # 4. Soft-delete bucket
    await ok(client, "DELETE", f"/v1/leave/buckets/{bucket_id}")
    buckets_after = await ok(client, "GET", "/v1/leave/buckets")
    assert not any(b["id"] == bucket_id for b in buckets_after)


async def test_leave_type_bucket_mapping_crud(api):
    client, _ = api
    await tenant(client)

    # Create bucket
    bucket = await ok(
        client,
        "POST",
        "/v1/leave/buckets",
        json={"name": "Paid Leave", "code": "PL", "is_unlimited": False, "is_active": True},
    )

    # Create leave type
    ltype = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={
            "name": "Casual Leave",
            "code": "CL",
            "category": "PAID",
            "days_per_year": 12.0,
            "requires_document": False,
        },
    )

    # 1. Create mapping
    mapping = await ok(
        client,
        "POST",
        "/v1/leave/bucket-mappings",
        json={"leave_type_id": ltype["id"], "bucket_id": bucket["id"]},
    )
    assert mapping["id"].startswith("lmap_")
    assert mapping["leave_type_id"] == ltype["id"]
    assert mapping["bucket_id"] == bucket["id"]

    # 2. List mappings
    mappings = await ok(client, "GET", "/v1/leave/bucket-mappings")
    assert len(mappings) >= 1
    assert any(m["id"] == mapping["id"] for m in mappings)

    # 3. Delete mapping
    await ok(client, "DELETE", f"/v1/leave/bucket-mappings/{mapping['id']}")
    mappings_after = await ok(client, "GET", "/v1/leave/bucket-mappings")
    assert not any(m["id"] == mapping["id"] for m in mappings_after)


async def test_leave_policy_set_and_bucket_policies_crud(api):
    client, _ = api
    await tenant(client)

    # Create bucket
    bucket = await ok(
        client,
        "POST",
        "/v1/leave/buckets",
        json={"name": "Earned Leave", "code": "EL", "is_unlimited": False, "is_active": True},
    )

    # 1. Create policy set
    pset = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={
            "name": "Corporate Standard",
            "description": "Default tech policy",
            "is_default": True,
        },
    )
    assert pset["id"].startswith("lps_")
    assert pset["name"] == "Corporate Standard"
    assert pset["is_default"] is True

    # 2. Update policy set
    pset_updated = await ok(
        client,
        "PATCH",
        f"/v1/leave/policy-sets/{pset['id']}",
        json={"description": "Updated tech policy"},
    )
    assert pset_updated["description"] == "Updated tech policy"

    # 3. Add bucket policy to policy set
    bp = await ok(
        client,
        "POST",
        f"/v1/leave/policy-sets/{pset['id']}/bucket-policies",
        json={
            "bucket_id": bucket["id"],
            "accrual_type": "MONTHLY_PRORATE",
            "days_per_year": 18.0,
            "carry_forward_enabled": True,
            "max_carry_forward_days": 10.0,
            "lapse_enabled": True,
            "encashment_enabled": True,
            "max_encashment_days": 5.0,
            "probation_eligible": False,
            "min_service_months": 3,
            "pro_rate_first_year": True,
        },
    )
    assert bp["id"].startswith("lbp_")
    assert bp["days_per_year"] == 18.0
    assert bp["accrual_type"] == "MONTHLY_PRORATE"

    # 4. List bucket policies for set
    bps = await ok(client, "GET", f"/v1/leave/policy-sets/{pset['id']}/bucket-policies")
    assert len(bps) == 1
    assert bps[0]["id"] == bp["id"]

    # 5. Patch bucket policy
    bp_patched = await ok(
        client,
        "PATCH",
        f"/v1/leave/bucket-policies/{bp['id']}",
        json={"days_per_year": 21.0, "max_carry_forward_days": 12.0},
    )
    assert bp_patched["days_per_year"] == 21.0
    assert bp_patched["max_carry_forward_days"] == 12.0

    # 6. Delete bucket policy
    await ok(client, "DELETE", f"/v1/leave/bucket-policies/{bp['id']}")
    bps_after = await ok(client, "GET", f"/v1/leave/policy-sets/{pset['id']}/bucket-policies")
    assert len(bps_after) == 0


async def test_leave_policy_assignment_validation_and_crud(api):
    client, _ = api
    admin = await tenant(client)
    company_id = admin["user"]["legal_entities"][0]["id"]
    base = await org_basics(client, company_id)
    emp = await person_and_employment(client, company_id)

    # Create policy set
    pset = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Factory Policy", "is_default": False},
    )

    # Validation failure: zero targets
    res_zero = await client.post(
        "/v1/leave/policy-assignments",
        json={"leave_policy_set_id": pset["id"], "effective_from": "2026-01-01"},
    )
    assert res_zero.status_code == 422

    # Validation failure: multiple targets (both org_unit and employment)
    res_multi = await client.post(
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": pset["id"],
            "effective_from": "2026-01-01",
            "org_unit_id": base["org_unit_id"],
            "employment_id": emp["id"],
        },
    )
    assert res_multi.status_code == 422

    # Validation failure: effective_to < effective_from
    res_dates = await client.post(
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": pset["id"],
            "effective_from": "2026-06-01",
            "effective_to": "2026-01-01",
            "legal_entity_id": company_id,
        },
    )
    assert res_dates.status_code == 422

    # Success: single target (Legal Entity)
    asgn = await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": pset["id"],
            "effective_from": "2026-01-01",
            "legal_entity_id": company_id,
        },
    )
    assert asgn["id"].startswith("lpa_")
    assert asgn["legal_entity_id"] == company_id

    # List assignments
    asgns = await ok(client, "GET", "/v1/leave/policy-assignments")
    assert any(a["id"] == asgn["id"] for a in asgns)

    # Delete assignment
    await ok(client, "DELETE", f"/v1/leave/policy-assignments/{asgn['id']}")
    asgns_after = await ok(client, "GET", "/v1/leave/policy-assignments")
    assert not any(a["id"] == asgn["id"] for a in asgns_after)


async def test_leave_ledger_and_transactions_get_endpoints(api):
    client, _ = api
    admin = await tenant(client)
    company_id = admin["user"]["legal_entities"][0]["id"]
    emp = await person_and_employment(client, company_id)

    # Query ledger for employee
    ledger_rows = await ok(client, "GET", f"/v1/leave/ledger?employment_id={emp['id']}")
    assert isinstance(ledger_rows, list)

    # Query transactions for employee
    tx_rows = await ok(client, "GET", f"/v1/leave/transactions?employment_id={emp['id']}")
    assert isinstance(tx_rows, list)


# ─── 4-Tier Policy Resolution Cascade Tests ─────────────────────────────────


async def test_policy_resolution_cascade(api):
    """
    Test 4-tier resolution hierarchy:
    Tier 1: Employee-level assignment
    Tier 2: Department-level (org unit CTE ancestor chain)
    Tier 3: Legal-entity-level (company-wide)
    Tier 4: Tenant default policy set
    """
    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_id = admin["user"]["legal_entities"][0]["id"]
    base = await org_basics(client, company_id)

    # Create 3-level org hierarchy: Parent -> Child -> Grandchild
    parent_unit = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Engineering",
            "type": "DEPARTMENT",
            "legal_entity_id": company_id,
            "effective_from": "2020-01-01",
        },
    )
    child_unit = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Core Platform",
            "type": "DEPARTMENT",
            "legal_entity_id": company_id,
            "parent_id": parent_unit["id"],
            "effective_from": "2020-01-01",
        },
    )
    grandchild_unit = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Infrastructure",
            "type": "DEPARTMENT",
            "legal_entity_id": company_id,
            "parent_id": child_unit["id"],
            "effective_from": "2020-01-01",
        },
    )

    # Create employee placed in grandchild_unit
    emp = await person_and_employment(client, company_id)
    await hire(
        client,
        emp["id"],
        {
            "location_id": base["location_id"],
            "org_unit_id": grandchild_unit["id"],
            "job_id": base["job_id"],
        },
        when=date(2025, 1, 1),
    )
    emp_uuid = to_uuid(emp["id"])

    # Create policy sets for each tier
    set_default = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Tenant Default Policy", "is_default": True},
    )
    set_company = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Company Wide Policy", "is_default": False},
    )
    set_parent = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Parent Eng Policy", "is_default": False},
    )
    set_child = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Child Core Policy", "is_default": False},
    )
    set_employee = await ok(
        client,
        "POST",
        "/v1/leave/policy-sets",
        json={"name": "Special Employee Policy", "is_default": False},
    )

    # Also create a bucket and bucket policies under set_employee and set_default
    bucket = await ok(
        client,
        "POST",
        "/v1/leave/buckets",
        json={"name": "Privilege Leave", "code": "PL", "is_unlimited": False, "is_active": True},
    )
    bucket_uuid = to_uuid(bucket["id"])

    await ok(
        client,
        "POST",
        f"/v1/leave/policy-sets/{set_employee['id']}/bucket-policies",
        json={
            "bucket_id": bucket["id"],
            "accrual_type": "ANNUAL_UPFRONT",
            "days_per_year": 25.0,
            "carry_forward_enabled": True,
        },
    )
    await ok(
        client,
        "POST",
        f"/v1/leave/policy-sets/{set_default['id']}/bucket-policies",
        json={
            "bucket_id": bucket["id"],
            "accrual_type": "ANNUAL_UPFRONT",
            "days_per_year": 15.0,
            "carry_forward_enabled": False,
        },
    )

    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        # Step A: Only Tenant Default exists (no assignments yet)
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Tenant Default Policy"

        # Bucket policy resolution walks down to default
        resolved_bp = await resolve_employee_bucket_policy(
            session, tid, emp_uuid, bucket_uuid, AS_OF
        )
        assert resolved_bp is not None
        assert resolved_bp.days_per_year == 15.0

    # Step B: Assign to Legal Entity (Tier 3)
    await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": set_company["id"],
            "effective_from": "2025-01-01",
            "legal_entity_id": company_id,
        },
    )
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Company Wide Policy"

    # Step C: Assign to Parent Org Unit (Tier 2 - ancestor walk: grandchild inherits parent)
    await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": set_parent["id"],
            "effective_from": "2025-01-01",
            "org_unit_id": parent_unit["id"],
        },
    )
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Parent Eng Policy"

    # Step D: Assign to Child Org Unit (Tier 2 - closer ancestor overrides parent)
    await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": set_child["id"],
            "effective_from": "2025-01-01",
            "org_unit_id": child_unit["id"],
        },
    )
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Child Core Policy"

    # Step E: Assign directly to Employee (Tier 1 - employee overrides all)
    await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": set_employee["id"],
            "effective_from": "2025-01-01",
            "employment_id": emp["id"],
        },
    )
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Special Employee Policy"

        resolved_bp = await resolve_employee_bucket_policy(
            session, tid, emp_uuid, bucket_uuid, AS_OF
        )
        assert resolved_bp is not None
        assert resolved_bp.days_per_year == 25.0

    # Step F: Verify effective date windowing (assignment in the future should NOT match)
    future_date = date(2027, 1, 1)
    await ok(
        client,
        "POST",
        "/v1/leave/policy-assignments",
        json={
            "leave_policy_set_id": set_company["id"],
            "effective_from": str(future_date),
            "employment_id": emp["id"],
        },
    )
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        # As of today (2026-04-15), asgn_future is not active yet, so set_employee is still resolved
        resolved = await resolve_leave_policy_set(session, tid, emp_uuid, AS_OF)
        assert resolved is not None
        assert resolved.name == "Special Employee Policy"

        # As of 2027-01-01, asgn_future is active and more recent
        resolved_2027 = await resolve_leave_policy_set(session, tid, emp_uuid, future_date)
        assert resolved_2027 is not None
        assert resolved_2027.name == "Company Wide Policy"


async def test_resolve_fy_start_month(api):
    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company_id = admin["user"]["legal_entities"][0]["id"]
    emp = await person_and_employment(client, company_id)
    emp_uuid = to_uuid(emp["id"])

    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        # Default start month is 4 (April)
        month = await resolve_employee_fy_start_month(session, tid, emp_uuid)
        assert month == 4

        # Configure legal entity financial_year_start_month = 1 (Calendar Year FY)
        le = await session.get(LegalEntity, (tid, to_uuid(company_id)))
        assert le is not None
        le.financial_year_start_month = 1
        session.add(le)
        await session.flush()

        month_configured = await resolve_employee_fy_start_month(session, tid, emp_uuid)
        assert month_configured == 1
