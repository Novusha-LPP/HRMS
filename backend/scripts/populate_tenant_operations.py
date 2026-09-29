"""
Fill a DEMO tenant with sample leave and today's attendance, so the dashboards have
something to show.

THIS FABRICATES HR RECORDS. It is for demo / test tenants only, and it is built so it
cannot damage real data:

  * it refuses to run when HRMS_ENVIRONMENT=production;
  * it needs an explicit --tenant, and refuses a tenant that holds employees imported from
    an ERP (user_accounts.erp_system) unless you pass --allow-imported-tenant, which you
    should only do if you understand that it will invent leave and punches for real people;
  * it never deletes anything — an employee who already has an attendance row or any punch
    today is skipped, never overwritten;
  * every punch it writes says so (source MANUAL, correction_reason "DEMO DATA ...") rather
    than posing as a biometric or device reading;
  * times are built in the policy timezone and lateness is computed with the same function
    the app uses, so the numbers it shows agree with the rest of the system;
  * it does nothing on a non-working day.

Usage:
    uv run python scripts/populate_tenant_operations.py --tenant <slug-or-uuid>
    uv run python scripts/populate_tenant_operations.py --tenant <slug-or-uuid> --dry-run
"""

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.config import settings
from hrms.core.datetime_utils import calc_lateness, is_working_day
from hrms.modules.policy.engine import default_policy

DEMO_NOTE = "DEMO DATA (scripts/populate_tenant_operations.py)"

LEAVE_TYPES = [
    ("Casual Leave", "CL", 12, "#10b981"),
    ("Sick Leave", "SL", 10, "#f59e0b"),
    ("Earned Leave", "EL", 15, "#3b82f6"),
    ("Compensatory Off", "CO", 0, "#8b5cf6"),
]


async def resolve_tenant(session, ref: str) -> tuple[UUID, str]:
    try:
        clause, value = "id = CAST(:v AS uuid)", str(UUID(ref))
    except ValueError:
        clause, value = "slug = :v", ref
    row = (
        await session.execute(
            text(f"SELECT id, display_name FROM tenants WHERE {clause}"), {"v": value}
        )
    ).fetchone()
    if not row:
        raise SystemExit(f"No tenant matches {ref!r}.")
    return row[0], row[1]


def local(day: date, hh: int, mm: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(UTC)


async def populate(session, tenant_id: UUID, name: str, today: date) -> None:
    policy = default_policy()
    tz = ZoneInfo(policy.timezone)
    if not is_working_day(today, policy.work_days, policy.saturday_pattern):
        print(f"{today} is not a working day under the default policy — nothing to do.")
        return
    tid = str(tenant_id)
    print(f"Populating DEMO operational data for {name} ({tid}) for {today}...")

    lt_ids: dict[str, UUID] = {}
    for lname, code, days, color in LEAVE_TYPES:
        row = (
            await session.execute(
                text("SELECT id FROM leave_types WHERE tenant_id = :tid AND code = :code"),
                {"tid": tid, "code": code},
            )
        ).fetchone()
        if row:
            lt_ids[code] = row[0]
            continue
        lt_ids[code] = uuid4()
        await session.execute(
            text("""
                INSERT INTO leave_types
                    (tenant_id, id, name, code, days_per_year, is_active, approval_levels, color)
                VALUES (:tid, :id, :name, :code, :days, true, 1, :color)
            """),
            {
                "tid": tid,
                "id": str(lt_ids[code]),
                "name": lname,
                "code": code,
                "days": days,
                "color": color,
            },
        )
    print(f"  Leave types ready: {', '.join(lt_ids)}")

    employees = [
        r[0]
        for r in await session.execute(
            text("""
                SELECT id FROM employments
                WHERE tenant_id = :tid AND employment_state != 'SEPARATED' AND archived_at IS NULL
                ORDER BY id
            """),
            {"tid": tid},
        )
    ]
    print(f"  Found {len(employees)} current employees.")
    if len(employees) < 8:
        print("  Fewer than 8 employees — too few for a useful demo; stopping.")
        return

    allocation = {"CL": 12.0, "SL": 10.0, "EL": 15.0, "CO": 0.0}
    for emp in employees:
        for code, lt_id in lt_ids.items():
            await session.execute(
                text("""
                    INSERT INTO leave_balances
                        (tenant_id, id, employment_id, leave_type_id, year, allocated_days)
                    SELECT :tid, :id, :emp, :lt, :yr, :alloc
                    WHERE NOT EXISTS (
                        SELECT 1 FROM leave_balances
                        WHERE tenant_id = :tid AND employment_id = :emp
                          AND leave_type_id = :lt AND year = :yr)
                """),
                {
                    "tid": tid,
                    "id": str(uuid4()),
                    "emp": str(emp),
                    "lt": str(lt_id),
                    "yr": today.year,
                    "alloc": allocation[code],
                },
            )

    has_leave = (
        await session.execute(
            text("SELECT count(*) FROM leave_applications WHERE tenant_id = :tid"), {"tid": tid}
        )
    ).scalar()
    if not has_leave:
        samples = [
            (employees[0], "CL", "APPROVED", 1.0, "Personal work (demo)"),
            (employees[1], "SL", "APPROVED", 1.0, "Unwell (demo)"),
            (employees[2], "EL", "PENDING_APPROVAL", 2.0, "Family function (demo)"),
            (employees[3], "CL", "REJECTED", 1.0, "Urgent leave request (demo)"),
        ]
        for emp, code, status, days, reason in samples:
            await session.execute(
                text("""
                    INSERT INTO leave_applications
                        (tenant_id, id, employment_id, leave_type_id, from_date, to_date,
                         days_requested, reason, status)
                    VALUES (:tid, :id, :emp, :lt, :d, :d, :days, :reason, :status)
                """),
                {
                    "tid": tid,
                    "id": str(uuid4()),
                    "emp": str(emp),
                    "lt": str(lt_ids[code]),
                    "d": today,
                    "days": days,
                    "reason": reason,
                    "status": status,
                },
            )
        print("  Created 4 sample leave applications.")

    on_leave, absent = set(employees[0:2]), set(employees[2:4])
    late_group = set(employees[4:8])
    written = skipped = 0
    for i, emp in enumerate(employees):
        already = (
            await session.execute(
                text("""
                    SELECT 1 FROM attendance_days
                    WHERE tenant_id = :tid AND employment_id = :emp AND work_date = :d
                    UNION ALL
                    SELECT 1 FROM punches
                    WHERE tenant_id = :tid AND employment_id = :emp AND work_date = :d
                    LIMIT 1
                """),
                {"tid": tid, "emp": str(emp), "d": today},
            )
        ).fetchone()
        if already:
            skipped += 1  # real data (or an earlier run) — never overwritten
            continue
        base = {"tid": tid, "id": str(uuid4()), "emp": str(emp), "d": today}
        if emp in on_leave or emp in absent:
            await session.execute(
                text("""
                    INSERT INTO attendance_days
                        (tenant_id, id, employment_id, work_date, gross_minutes, break_minutes,
                         effective_minutes, late_by_minutes, status, is_locked)
                    VALUES (:tid, :id, :emp, :d, 0, 0, 0, 0, :status, false)
                """),
                {**base, "status": "ON_LEAVE" if emp in on_leave else "ABSENT"},
            )
            written += 1
            continue

        start = policy.expected_start_time
        if emp in late_group:
            arrive = datetime.combine(today, start) + timedelta(
                minutes=policy.grace_late_minutes + 10 + 5 * i
            )
        else:
            arrive = datetime.combine(today, start) - timedelta(minutes=(i % 12) + 1)
        depart = datetime.combine(today, policy.expected_end_time) + timedelta(minutes=i % 20)
        first_in = local(today, arrive.hour, arrive.minute, tz)
        last_out = local(today, depart.hour, depart.minute, tz)
        late = calc_lateness(first_in, start, policy.grace_late_minutes, policy.timezone)
        gross = int((last_out - first_in).total_seconds() / 60)
        brk = policy.break_minutes
        await session.execute(
            text("""
                INSERT INTO attendance_days
                    (tenant_id, id, employment_id, work_date, first_punch_in, last_punch_out,
                     gross_minutes, break_minutes, effective_minutes, late_by_minutes, status,
                     is_locked)
                VALUES (:tid, :id, :emp, :d, :fin, :lout, :gross, :brk, :eff, :late, :status, false)
            """),
            {
                **base,
                "fin": first_in,
                "lout": last_out,
                "gross": gross,
                "brk": brk,
                "eff": max(gross - brk, 0),
                "late": late.late_by_minutes,
                "status": "LATE" if late.is_late else "PRESENT",
            },
        )
        for kind, stamp in (("IN", first_in), ("OUT", last_out)):
            await session.execute(
                text("""
                    INSERT INTO punches
                        (tenant_id, id, employment_id, work_date, punch_type, punched_at, source,
                         is_corrected, correction_reason)
                    VALUES (:tid, :id, :emp, :d, :kind, :ts, 'MANUAL', false, :note)
                """),
                {
                    "tid": tid,
                    "id": str(uuid4()),
                    "emp": str(emp),
                    "d": today,
                    "kind": kind,
                    "ts": stamp,
                    "note": DEMO_NOTE,
                },
            )
        written += 1
    print(f"  Wrote attendance for {written} employees; left {skipped} existing day(s) untouched.")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Populate a DEMO tenant with sample operations")
    parser.add_argument("--tenant", required=True, help="Tenant slug or UUID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen; roll back")
    parser.add_argument(
        "--allow-imported-tenant",
        action="store_true",
        help="Proceed even though this tenant holds employees imported from an ERP",
    )
    args = parser.parse_args()

    if settings.environment == "production":
        print("Refusing to fabricate HR data in production.")
        return 2

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session, session.begin():
        tenant_id, name = await resolve_tenant(session, args.tenant)
        imported = (
            await session.execute(
                text("""
                    SELECT count(*) FROM user_accounts
                    WHERE tenant_id = :tid AND erp_system IS NOT NULL
                """),
                {"tid": str(tenant_id)},
            )
        ).scalar()
        if imported and not args.allow_imported_tenant:
            print(
                f"{name} holds {imported} employees imported from an ERP — real people. This "
                "script would invent leave and punches for them, so it refuses. Use a demo "
                "tenant, or pass --allow-imported-tenant if you really mean it."
            )
            return 2
        await populate(session, tenant_id, name, date.today())
        if args.dry_run:
            await session.rollback()
            print("DRY RUN — rolled back, nothing was saved.")
        else:
            print("\nDEMO DATA COMMITTED.")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
