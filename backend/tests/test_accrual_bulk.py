"""
The set-based monthly accrual (engine.record_accruals + bulk policy resolution) must leave
exactly the ledger and journal the one-employee-at-a-time implementation did.

Two tenants are built identically. One is credited through POST /v1/leave/accrual/run (the
bulk path); the other by REFERENCE below — the previous per-employee loop, verbatim, over
the per-employee resolvers and record_transaction. Every ledger row and journal entry is
then compared exactly, floats included. The scenario covers each branch: all four policy
tiers (employee, nested department, legal entity, tenant default), an archived policy set,
probation and minimum-service gates, a January financial year, a pre-existing month row,
an employee whose later ledger rows need a forward cascade, and two leave types sharing
one bucket.
"""

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from hrms.core import database
from hrms.core.datetime_utils import tenure_months
from hrms.core.ids import to_uuid
from hrms.modules.leave.engine import monthly_credit, record_transaction
from hrms.modules.leave.models import LeaveTransactionType, LeaveType
from hrms.modules.leave.policy_resolver import (
    resolve_employee_fy_start_month,
    resolve_leave_policy_set,
    resolve_leave_policy_sets_bulk,
)
from hrms.modules.leave.router import _resolve_bucket_for_type, _resolve_entitlement
from tests.helpers import ok, person_and_employment, tenant

pytestmark = pytest.mark.database

AS_OF = date.today().replace(day=1)
NEXT_MONTH = (AS_OF + timedelta(days=32)).replace(day=1)
PREV_MONTH = (AS_OF - timedelta(days=1)).replace(day=1)


async def _tenant_session(tenant_id):
    session = database.AsyncSessionLocal()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    return session


async def _build(client, engine):
    """One tenant with the full scenario. Returns (tenant_id, admin account id, labels)."""
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    le_a = admin["user"]["legal_entities"][0]["id"]
    le_b = (
        await ok(
            client,
            "POST",
            "/v1/org/legal-entities",
            json={"name": "Jan FY Co", "country_code": "IN", "financial_year_start_month": 1},
        )
    )["id"]
    labels: dict[UUID, str] = {}
    emps: dict[str, UUID] = {}
    for label, entity in [
        ("dept_nested", le_a),
        ("direct", le_a),
        ("entity_b", le_b),
        ("default", le_a),
        ("probation", le_a),
        ("new_joiner", le_a),
        ("backdated", le_a),
        ("existing_row", le_a),
        ("archived_set", le_a),
    ]:
        emp = await person_and_employment(client, entity)
        emps[label] = to_uuid(emp["id"])
        labels[emps[label]] = label

    cl = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Casual", "code": "CL", "days_per_year": 12, "accrual_enabled": True},
    )
    cl2 = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Casual 2", "code": "CL2", "days_per_year": 6, "accrual_enabled": True},
    )
    await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Earned", "code": "EL", "days_per_year": 15, "accrual_enabled": True},
    )
    await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Flat", "code": "FL", "days_per_year": 10, "accrual_enabled": False},
    )

    ids = {k: uuid4() for k in ["loc", "job", "d1", "d2", "cl_bucket", "ps_dept", "ps_emp"]}
    ids |= {k: uuid4() for k in ["ps_ent", "ps_default", "ps_archived"]}
    async with engine.begin() as conn:
        q = conn.execute
        p = {"t": tid, **ids, "a": to_uuid(le_a)}
        await q(
            text("""INSERT INTO locations (tenant_id,id,name,type,legal_entity_id)
                    VALUES (:t,:loc,'HQ','OFFICE',:a)"""),
            p,
        )
        await q(text("INSERT INTO jobs (tenant_id,id,title) VALUES (:t,:job,'Exec')"), p)
        await q(
            text("""INSERT INTO org_units (tenant_id,id,name,type,legal_entity_id,effective_from)
                    VALUES (:t,:d1,'Ops','DEPARTMENT',:a,'2019-01-01')"""),
            p,
        )
        await q(
            text("""INSERT INTO org_units (tenant_id,id,name,type,parent_id,legal_entity_id,
                        effective_from)
                    VALUES (:t,:d2,'Ops team','TEAM',:d1,:a,'2019-01-01')"""),
            p,
        )
        for label in ["dept_nested", "direct", "probation", "backdated"]:
            await q(
                text("""INSERT INTO assignments (tenant_id,id,employment_id,effective_from,
                            org_unit_id,location_id,job_id)
                        VALUES (:t,:id,:e,'2019-01-01',:d2,:loc,:job)"""),
                {**p, "id": uuid4(), "e": emps[label]},
            )
        # New employments start in PROBATION; only the "probation" case should stay there.
        await q(
            text("""UPDATE employments SET employment_state =
                        CASE WHEN id = :e THEN 'PROBATION' ELSE 'ACTIVE' END
                    WHERE tenant_id = :t"""),
            {"e": emps["probation"], "t": tid},
        )
        await q(
            text("UPDATE employments SET hire_date=:h, continuity_start_date=:h WHERE id=:e"),
            {"e": emps["new_joiner"], "h": AS_OF - timedelta(days=20)},
        )
        # CL and CL2 share one bucket: an employee is credited for it once per period.
        await q(
            text("""INSERT INTO leave_balance_buckets (tenant_id,id,name,code,is_unlimited)
                    VALUES (:t,:cl_bucket,'Casual','CL',false)"""),
            p,
        )
        for lt in (cl, cl2):
            await q(
                text("""INSERT INTO leave_type_bucket_mapping (tenant_id,id,leave_type_id,
                            bucket_id) VALUES (:t,:id,:lt,:cl_bucket)"""),
                {**p, "id": uuid4(), "lt": to_uuid(lt["id"])},
            )
        for key, name, default in [
            ("ps_dept", "Dept", False),
            ("ps_emp", "Emp", False),
            ("ps_ent", "Ent", False),
            ("ps_default", "Default", True),
            ("ps_archived", "Archived", False),
        ]:
            await q(
                text("""INSERT INTO leave_policy_sets (tenant_id,id,name,is_default)
                        VALUES (:t,:id,:n,:d)"""),
                {"t": tid, "id": ids[key], "n": name, "d": default},
            )
        await q(
            text("UPDATE leave_policy_sets SET archived_at=now() WHERE id=:id"),
            {"id": ids["ps_archived"]},
        )
        # Bucket policies on the shared CL bucket, one per set, all different.
        for key, days, probation_ok, min_service in [
            ("ps_dept", 18, False, 0),
            ("ps_emp", 24, True, 0),
            ("ps_ent", 9, True, 0),
            ("ps_default", 14, True, 3),
        ]:
            await q(
                text("""INSERT INTO leave_bucket_policies (tenant_id,id,policy_set_id,bucket_id,
                            accrual_type,days_per_year,probation_eligible,min_service_months)
                        VALUES (:t,:id,:ps,:cl_bucket,'MONTHLY_PRORATE',:days,:pe,:ms)"""),
                {
                    **p,
                    "id": uuid4(),
                    "ps": ids[key],
                    "days": days,
                    "pe": probation_ok,
                    "ms": min_service,
                },
            )
        for target, key in [
            ({"org_unit_id": ids["d1"]}, "ps_dept"),  # ancestor of d2: the nested walk
            ({"employment_id": emps["direct"]}, "ps_emp"),
            ({"legal_entity_id": to_uuid(le_b)}, "ps_ent"),
            ({"employment_id": emps["archived_set"]}, "ps_archived"),  # -> tenant default
        ]:
            cols = ", ".join(target)
            vals = ", ".join(f":{c}" for c in target)
            await q(
                text(f"""INSERT INTO leave_policy_assignments (tenant_id,id,{cols},
                            leave_policy_set_id,effective_from)
                        VALUES (:t,:id,{vals},:ps,'2019-01-01')"""),
                {"t": tid, "id": uuid4(), "ps": ids[key], **target},
            )

    # Ledger rows before, at and after the accrual month.
    session = await _tenant_session(tid)
    async with session:
        for label, when in [
            ("backdated", NEXT_MONTH),  # a later row: the cascading fallback
            ("existing_row", AS_OF),  # this month's row already exists
            ("dept_nested", PREV_MONTH),  # new row must open at last month's closing
            ("entity_b", PREV_MONTH),
        ]:
            await record_transaction(
                session,
                tid,
                employment_id=emps[label],
                bucket_id=ids["cl_bucket"],
                leave_type_id=to_uuid(cl["id"]),
                transaction_type=LeaveTransactionType.GRANT,
                quantity=2.5,
                effective_date=when,
                reference_type="MANUAL",
                recorded_by=to_uuid(admin["user"]["id"]),
            )
        # Leave on hold this month: available balance = closing - held.
        await record_transaction(
            session,
            tid,
            employment_id=emps["existing_row"],
            bucket_id=ids["cl_bucket"],
            leave_type_id=to_uuid(cl["id"]),
            transaction_type=LeaveTransactionType.HOLD,
            quantity=1.0,
            effective_date=AS_OF,
            reference_type="MANUAL",
            recorded_by=to_uuid(admin["user"]["id"]),
        )
        await session.commit()
    return tid, to_uuid(admin["user"]["id"]), labels


async def REFERENCE(session, tenant_id, recorded_by):
    """The previous run_accrual loop for tenant-wide scope (verbatim but for the ORDER BY)."""
    rows = await session.execute(
        text("""SELECT e.id, COALESCE(e.continuity_start_date, e.hire_date), e.employment_state
                FROM employments e
                WHERE e.tenant_id = CAST(:tid AS uuid)
                  AND e.employment_state NOT IN ('SEPARATED')"""),
        {"tid": str(tenant_id)},
    )
    employees = sorted(((r[0], r[1], r[2]) for r in rows), key=lambda e: str(e[0]))
    from sqlmodel import col, func, select

    from hrms.modules.leave.models import LeaveBalanceTransaction

    leave_types = (
        await session.execute(
            select(LeaveType)
            .where(LeaveType.tenant_id == tenant_id)
            .where(LeaveType.archived_at == None)  # noqa: E711
            .where(col(LeaveType.is_paid) | col(LeaveType.is_comp_off))
            # The one change from the old loop: it had no ORDER BY, so which of two types
            # sharing a bucket got the accrual depended on physical row order.
            .order_by(col(LeaveType.recorded_at), col(LeaveType.id))
        )
    ).scalars()
    credited, total = 0, 0.0
    for lt in list(leave_types):
        resolved = await _resolve_bucket_for_type(session, tenant_id, lt)
        if resolved is None:
            continue
        bucket_id, _ = resolved
        for emp_id, hire_date, emp_state in employees:
            fy = await resolve_employee_fy_start_month(session, tenant_id, emp_id)
            ent = await _resolve_entitlement(session, tenant_id, emp_id, bucket_id, lt, AS_OF)
            if ent.accrual_type != "MONTHLY_PRORATE":
                continue
            if ent.days_per_year <= 0:
                continue
            if not (
                (ent.probation_eligible or emp_state != "PROBATION")
                and tenure_months(hire_date, AS_OF) >= ent.min_service_months
            ):
                continue
            already = await session.execute(
                select(LeaveBalanceTransaction.id)
                .where(LeaveBalanceTransaction.tenant_id == tenant_id)
                .where(LeaveBalanceTransaction.employment_id == emp_id)
                .where(LeaveBalanceTransaction.bucket_id == bucket_id)
                .where(LeaveBalanceTransaction.transaction_type == "ACCRUAL")
                .where(LeaveBalanceTransaction.effective_date == AS_OF)
            )
            if already.scalar():
                continue
            # Half-day rule (DB-D2): this month's credit depends on how many monthly accruals
            # the employee already has in this financial year — counted here independently.
            fy_start = date(AS_OF.year if AS_OF.month >= fy else AS_OF.year - 1, fy, 1)
            months_before = (
                await session.execute(
                    select(func.count())
                    .select_from(LeaveBalanceTransaction)
                    .where(LeaveBalanceTransaction.tenant_id == tenant_id)
                    .where(LeaveBalanceTransaction.employment_id == emp_id)
                    .where(LeaveBalanceTransaction.bucket_id == bucket_id)
                    .where(LeaveBalanceTransaction.transaction_type == "ACCRUAL")
                    .where(LeaveBalanceTransaction.effective_date >= fy_start)
                    .where(LeaveBalanceTransaction.effective_date < AS_OF)
                )
            ).scalar()
            monthly = monthly_credit(ent.days_per_year, months_before)
            await record_transaction(
                session,
                tenant_id,
                employment_id=emp_id,
                bucket_id=bucket_id,
                leave_type_id=lt.id,
                transaction_type=LeaveTransactionType.ACCRUAL,
                quantity=monthly,
                effective_date=AS_OF,
                reference_type="ACCRUAL_RUN",
                recorded_by=recorded_by,
                fy_start_month=fy,
            )
            credited += 1
            total += monthly
    return credited, round(total, 2)


async def _snapshot(engine, tenant_id, labels):
    """Ledger and journal with ids replaced by labels / codes, sorted."""
    async with engine.connect() as conn:
        ledger = await conn.execute(
            text("""SELECT l.employment_id, b.code, l.calendar_year, l.calendar_month, l.fy_year,
                           l.opening, l.accrued, l.granted, l.held, l.adjustment, l.taken,
                           l.lapsed, l.encashed, l.closing
                    FROM leave_monthly_ledger l
                    JOIN leave_balance_buckets b ON b.tenant_id = l.tenant_id AND b.id = l.bucket_id
                    WHERE l.tenant_id = :t"""),
            {"t": tenant_id},
        )
        journal = await conn.execute(
            text("""SELECT j.employment_id, b.code, lt.code, j.transaction_type, j.quantity,
                           j.previous_balance, j.new_balance, j.effective_date, j.reference_type
                    FROM leave_balance_transactions j
                    JOIN leave_balance_buckets b ON b.tenant_id = j.tenant_id AND b.id = j.bucket_id
                    LEFT JOIN leave_types lt
                      ON lt.tenant_id = j.tenant_id AND lt.id = j.leave_type_id
                    WHERE j.tenant_id = :t"""),
            {"t": tenant_id},
        )

        def norm(rows):
            return sorted((labels[UUID(str(r[0]))], *r[1:]) for r in rows)

        return norm(ledger.all()), norm(journal.all())


async def test_bulk_accrual_matches_the_per_employee_reference(api):
    client, engine = api
    bulk_tid, _, bulk_labels = await _build(client, engine)
    bulk_admin = {"Authorization": client.headers["Authorization"]}
    run = f"/v1/leave/accrual/run?period={AS_OF:%Y-%m}"
    result = await ok(client, "POST", run, headers=bulk_admin)

    ref_tid, ref_admin, ref_labels = await _build(client, engine)
    session = await _tenant_session(ref_tid)
    async with session:
        ref_credited, ref_total = await REFERENCE(session, ref_tid, ref_admin)
        await session.commit()

    assert (result["balances_credited"], result["days_credited_total"]) == (
        ref_credited,
        ref_total,
    )
    bulk = await _snapshot(engine, bulk_tid, bulk_labels)
    ref = await _snapshot(engine, ref_tid, ref_labels)
    assert bulk[0] == ref[0]  # ledger
    assert bulk[1] == ref[1]  # journal
    # The scenario really exercised both paths and the gates.
    credited = {row[0] for row in bulk[1] if row[3] == "ACCRUAL"}
    assert {"backdated", "existing_row", "direct", "entity_b"} <= credited
    cl_credited = {row[0] for row in bulk[1] if row[1] == "CL" and row[3] == "ACCRUAL"}
    assert {"backdated", "existing_row", "dept_nested", "entity_b", "direct"} <= cl_credited
    assert "probation" not in cl_credited  # dept set: probation not eligible
    assert "new_joiner" not in cl_credited  # default set: 3 months' service first

    # Idempotent: a second run credits nothing and changes nothing.
    again = await ok(client, "POST", run, headers=bulk_admin)
    assert again["balances_credited"] == 0
    assert await _snapshot(engine, bulk_tid, bulk_labels) == bulk


async def test_bulk_policy_resolution_matches_per_employee(api):
    client, engine = api
    tid, _, labels = await _build(client, engine)
    session = await _tenant_session(tid)
    async with session:
        emp_ids = list(labels)
        bulk = await resolve_leave_policy_sets_bulk(session, tid, emp_ids, AS_OF)
        for emp in emp_ids:
            one = await resolve_leave_policy_set(session, tid, emp, AS_OF)
            got = bulk[emp]
            assert (got.id if got else None) == (one.id if one else None), labels[emp]
        names = {labels[e]: (p.name if p else None) for e, p in bulk.items()}
    assert names["dept_nested"] == "Dept"
    assert names["direct"] == "Emp"
    assert names["entity_b"] == "Ent"
    assert names["archived_set"] == "Default"
    assert names["default"] == "Default"
