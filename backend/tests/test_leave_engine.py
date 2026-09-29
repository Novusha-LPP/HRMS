"""
Unit and database integration tests for the Leave Accounting Engine (Phase 1).

Verifies invariants from docs/leave-management-design.md:
1. Invariant 1: Ledger continuity (row[i+1].opening == row[i].closing)
2. Invariant 2: Ledger consistency (closing formula)
3. Invariant 3: Transaction immutability enforced by DB privileges
4. Invariant 4: Available balance = closing - held
5. Section 6.7 / 15.2: Dormant employee gap linking (prior row calendar search)
6. Section 6.7 / 15.3: Advance-dated row forward cascade when earlier month changes
7. Concurrency simulation: Advisory lock protects simultaneous transactions
"""

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hrms.core.datetime_utils import tenure_months
from hrms.modules.kernel.models import Tenant
from hrms.modules.leave.engine import (
    compute_fy_year,
    get_or_create_ledger_row,
    record_transaction,
)
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveTransactionType,
)
from hrms.modules.org.models import LegalEntity
from hrms.modules.people.models import Employment, Person

pytestmark = pytest.mark.database


def test_compute_fy_year():
    # April start (Indian standard)
    assert compute_fy_year(2026, 4, fy_start_month=4) == 2026
    assert compute_fy_year(2027, 3, fy_start_month=4) == 2026
    assert compute_fy_year(2027, 4, fy_start_month=4) == 2027

    # January start (Calendar year)
    assert compute_fy_year(2026, 1, fy_start_month=1) == 2026
    assert compute_fy_year(2026, 12, fy_start_month=1) == 2026

    # July start
    assert compute_fy_year(2026, 7, fy_start_month=7) == 2026
    assert compute_fy_year(2027, 6, fy_start_month=7) == 2026


def test_tenure_months():
    hire = date(2025, 1, 15)
    assert tenure_months(hire, as_of=date(2025, 1, 14)) == 0
    assert tenure_months(hire, as_of=date(2025, 1, 15)) == 0
    assert tenure_months(hire, as_of=date(2025, 2, 14)) == 0
    assert tenure_months(hire, as_of=date(2025, 2, 15)) == 1
    assert tenure_months(hire, as_of=date(2025, 4, 15)) == 3
    assert tenure_months(hire, as_of=date(2024, 12, 31)) == 0


@pytest.fixture
async def db_fixture(monkeypatch):
    """Provides admin engine and an async session factory connected to HRMS_TEST_DATABASE_URL."""
    import os

    test_url = os.environ.get(
        "HRMS_TEST_DATABASE_URL", "postgresql+asyncpg://hrms:hrms@localhost:5432/hrms_test"
    )
    url = make_url(test_url)
    assert url.database and url.database.endswith("_test"), (
        "Tests must run against an isolated *_test database"
    )

    admin_engine = create_async_engine(url, poolclass=NullPool)
    app_engine = create_async_engine(
        url.set(username="hrms_app", password="hrms_app_dev_password"), poolclass=NullPool
    )

    admin_session_factory = async_sessionmaker(
        admin_engine, expire_on_commit=False, autoflush=False
    )
    app_session_factory = async_sessionmaker(
        app_engine, expire_on_commit=False, autoflush=False
    )

    yield {
        "admin_engine": admin_engine,
        "app_engine": app_engine,
        "admin_session": admin_session_factory,
        "app_session": app_session_factory,
    }

    await app_engine.dispose()
    await admin_engine.dispose()


@pytest.fixture
async def seed_tenant_and_employment(db_fixture):
    """Seed tenant, legal entity, person, employment, bucket for engine tests."""
    tenant_id = uuid4()
    admin_session_factory = db_fixture["admin_session"]

    async with admin_session_factory() as session:
        tenant_obj = Tenant(
            id=tenant_id,
            slug=f"test-{tenant_id}",
            display_name="Test Tenant",
        )
        legal_entity = LegalEntity(
            tenant_id=tenant_id,
            id=uuid4(),
            name="Test Legal Entity",
            country_code="IN",
            financial_year_start_month=4,
        )
        person = Person(
            tenant_id=tenant_id,
            id=uuid4(),
            legal_first_name="John",
            legal_last_name="Doe",
        )
        employment = Employment(
            tenant_id=tenant_id,
            id=uuid4(),
            person_id=person.id,
            legal_entity_id=legal_entity.id,
            employee_number=f"EMP-{uuid4().hex[:6]}",
            hire_date=date(2025, 1, 1),
        )
        bucket = LeaveBalanceBucket(
            tenant_id=tenant_id,
            id=uuid4(),
            name="Paid Leave",
            code="PL_BAL",
            is_unlimited=False,
            is_active=True,
        )
        session.add_all([tenant_obj, legal_entity, person, employment, bucket])
        await session.commit()

    return {
        "tenant_id": tenant_id,
        "legal_entity_id": legal_entity.id,
        "employment_id": employment.id,
        "bucket_id": bucket.id,
    }


async def test_engine_ledger_lifecycle(db_fixture, seed_tenant_and_employment):
    """Test full balance transaction cycle: OPENING -> ACCRUAL -> HOLD -> LEAVE_TAKEN."""
    data = seed_tenant_and_employment
    tenant_id = data["tenant_id"]
    employment_id = data["employment_id"]
    bucket_id = data["bucket_id"]
    actor_id = uuid4()

    session_factory = db_fixture["admin_session"]
    async with session_factory() as session:
        # 1. Opening balance in April 2026
        tx1, row1 = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.OPENING,
            quantity=10.0,
            effective_date=date(2026, 4, 1),
            recorded_by=actor_id,
        )
        assert tx1.previous_balance == 0.0
        assert tx1.new_balance == 10.0
        assert row1.opening == 10.0
        assert row1.closing == 10.0
        assert row1.held == 0.0

        # 2. Accrual in May 2026 (+1.5 days)
        tx2, row2 = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.ACCRUAL,
            quantity=1.5,
            effective_date=date(2026, 5, 1),
            recorded_by=actor_id,
        )
        # May's opening should equal April's closing (10.0)
        assert row2.opening == 10.0
        assert row2.accrued == 1.5
        assert row2.closing == 11.5
        assert tx2.new_balance == 11.5

        # 3. Application submitted: HOLD 2.0 days in May 2026
        app_id = uuid4()
        tx3, row3 = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.HOLD,
            quantity=2.0,
            effective_date=date(2026, 5, 10),
            reference_id=app_id,
            reference_type="LEAVE_APPLICATION",
            recorded_by=actor_id,
        )
        assert row3.held == 2.0
        assert row3.closing == 11.5  # closing is unaffected by held!
        assert tx3.previous_balance == 11.5
        assert tx3.new_balance == 9.5  # available = closing - held = 9.5

        # 4. Final approval: LEAVE_TAKEN 2.0 days
        tx4, row4 = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.LEAVE_TAKEN,
            quantity=2.0,
            effective_date=date(2026, 5, 10),
            reference_id=app_id,
            reference_type="LEAVE_APPLICATION",
            recorded_by=actor_id,
            approved_by=actor_id,
        )
        assert row4.held == 0.0  # hold released
        assert row4.taken == 2.0  # taken posted
        assert row4.closing == 9.5  # closing deducted
        assert tx4.new_balance == 9.5

        await session.commit()


async def test_dormant_employee_gap_linking(db_fixture, seed_tenant_and_employment):
    """Test §6.7 / §15.2: An employee with zero activity for 10 months preserves balance."""
    data = seed_tenant_and_employment
    tenant_id = data["tenant_id"]
    employment_id = data["employment_id"]
    bucket_id = data["bucket_id"]
    actor_id = uuid4()

    session_factory = db_fixture["admin_session"]
    async with session_factory() as session:
        # Row created in May 2026 with closing 15.0
        await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.OPENING,
            quantity=15.0,
            effective_date=date(2026, 5, 1),
            recorded_by=actor_id,
        )

        # Nothing happens until March 2027 (FY year-end close month)
        row_march = await get_or_create_ledger_row(
            session,
            tenant_id,
            employment_id,
            bucket_id,
            calendar_year=2027,
            calendar_month=3,
        )

        # Invariant: March opening and closing equal May 2026 closing
        assert row_march.opening == 15.0
        assert row_march.closing == 15.0
        assert row_march.taken == 0.0
        await session.commit()


async def test_advance_dated_row_forward_cascade(db_fixture, seed_tenant_and_employment):
    """
    Test §6.7 / §15.3:
    Advance-dated hold creates a future row (month 6).
    Later, an intervening accrual is posted into month 5.
    The forward cascade must correct month 6's opening and closing automatically.
    """
    data = seed_tenant_and_employment
    tenant_id = data["tenant_id"]
    employment_id = data["employment_id"]
    bucket_id = data["bucket_id"]
    actor_id = uuid4()

    session_factory = db_fixture["admin_session"]
    async with session_factory() as session:
        # Month 4 (April): Opening = 10.0
        await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.OPENING,
            quantity=10.0,
            effective_date=date(2026, 4, 1),
            recorded_by=actor_id,
        )

        # Advance application for June 2026 (Month 6): Hold 3.0 days
        # Month 6 is created with opening = 10.0 (from April closing)
        tx_june, row_june = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.HOLD,
            quantity=3.0,
            effective_date=date(2026, 6, 15),
            recorded_by=actor_id,
        )
        assert row_june.calendar_month == 6
        assert row_june.opening == 10.0
        assert row_june.closing == 10.0
        assert row_june.held == 3.0
        assert row_june.closing - row_june.held == 7.0

        # Now, May 2026 (Month 5) accrual of +2.0 days is processed!
        tx_may, row_may = await record_transaction(
            session,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.ACCRUAL,
            quantity=2.0,
            effective_date=date(2026, 5, 1),
            recorded_by=actor_id,
        )
        assert row_may.calendar_month == 5
        assert row_may.opening == 10.0
        assert row_may.accrued == 2.0
        assert row_may.closing == 12.0

        # Verify that the forward cascade updated Month 6 automatically!
        refreshed_june = await get_or_create_ledger_row(
            session,
            tenant_id,
            employment_id,
            bucket_id,
            calendar_year=2026,
            calendar_month=6,
        )
        assert refreshed_june.opening == 12.0  # updated from May's closing!
        assert refreshed_june.closing == 12.0  # recomputed
        assert refreshed_june.held == 3.0
        assert refreshed_june.closing - refreshed_june.held == 9.0  # 12 - 3 = 9!

        await session.commit()


async def test_privilege_enforced_transaction_immutability(db_fixture, seed_tenant_and_employment):
    """
    Test Invariant 3 (§8):
    The app role (hrms_app) cannot UPDATE or DELETE leave_balance_transactions rows.
    """
    data = seed_tenant_and_employment
    tenant_id = data["tenant_id"]
    employment_id = data["employment_id"]
    bucket_id = data["bucket_id"]
    actor_id = uuid4()

    admin_session_factory = db_fixture["admin_session"]
    app_session_factory = db_fixture["app_session"]

    # Insert a transaction using admin session
    async with admin_session_factory() as admin_sess:
        tx, _ = await record_transaction(
            admin_sess,
            tenant_id,
            employment_id=employment_id,
            bucket_id=bucket_id,
            transaction_type=LeaveTransactionType.OPENING,
            quantity=10.0,
            effective_date=date(2026, 4, 1),
            recorded_by=actor_id,
        )
        await admin_sess.commit()
        tx_id = tx.id

    # Now attempt UPDATE as the restricted hrms_app role
    async with app_session_factory() as app_sess:
        await app_sess.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        with pytest.raises(Exception) as exc_info:
            await app_sess.execute(
                text("UPDATE leave_balance_transactions SET quantity = 999 WHERE id = :id"),
                {"id": str(tx_id)},
            )
            await app_sess.flush()
        # Verify permission denied error from Postgres
        assert "permission denied" in str(exc_info.value).lower()

    # Attempt DELETE as hrms_app in a fresh session
    async with app_session_factory() as app_sess:
        await app_sess.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        with pytest.raises(Exception) as exc_info_del:
            await app_sess.execute(
                text("DELETE FROM leave_balance_transactions WHERE id = :id"),
                {"id": str(tx_id)},
            )
            await app_sess.flush()
        assert "permission denied" in str(exc_info_del.value).lower()


async def test_concurrency_locking(db_fixture, seed_tenant_and_employment):
    """
    Simulate concurrent transactions against the same (employment_id, bucket_id).
    The advisory lock should prevent race conditions.
    """
    data = seed_tenant_and_employment
    tenant_id = data["tenant_id"]
    employment_id = data["employment_id"]
    bucket_id = data["bucket_id"]
    actor_id = uuid4()

    admin_session_factory = db_fixture["admin_session"]

    async def worker_add_credit(credit_amount: float):
        async with admin_session_factory() as session:
            await record_transaction(
                session,
                tenant_id,
                employment_id=employment_id,
                bucket_id=bucket_id,
                transaction_type=LeaveTransactionType.GRANT,
                quantity=credit_amount,
                effective_date=date(2026, 4, 1),
                recorded_by=actor_id,
            )
            await session.commit()

    # Launch 5 concurrent workers each adding 1.0 day
    workers = [worker_add_credit(1.0) for _ in range(5)]
    await asyncio.gather(*workers)

    # Read final ledger row
    async with admin_session_factory() as session:
        row = await get_or_create_ledger_row(
            session,
            tenant_id,
            employment_id,
            bucket_id,
            calendar_year=2026,
            calendar_month=4,
        )
        # All 5 transactions must be cleanly serialized and summed
        assert row.granted == 5.0
        assert row.closing == 5.0
