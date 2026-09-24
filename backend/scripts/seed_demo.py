"""
Seed a realistic multi-company tenant: SFPL Group, HR at the group level,
three sister companies (SRCC, Novusha, Alluvium IoT Solutions), a manager
with direct reports, a plain employee, and a shared accountant who is
employed by one company but has visibility into two.

This is what every role_assignment.scope_type resolves against — run it,
then sign in as any of the printed accounts to see the scoping actually
enforced end to end (an SFPL-only user can never see SRCC's employees; the
shared accountant sees exactly SFPL + Novusha and nothing else).

Connects as the Postgres superuser (like Alembic) because seeding needs to
write across the whole tenant in one shot — the running app itself always
connects as the restricted hrms_app role (see core/database.py).

Usage:
    uv run python scripts/seed_demo.py
"""

import asyncio
import json
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

from hrms.core.authz import ROLE_DESCRIPTIONS
from hrms.core.config import settings
from hrms.core.ids import to_typed_id
from hrms.core.security import hash_password

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_PASSWORD = "Passw0rd!"

engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)


def uid() -> UUID:
    return uuid4()


async def wipe_tenant(session) -> None:
    """Delete-by-tenant in FK-safe order so this script is re-runnable."""
    tables = [
        "correction_approval_actions", "attendance_correction_requests",
        "leave_approval_actions", "leave_applications", "leave_balances", "leave_types",
        "employee_policy_assignments", "policy_templates",
        "report_definitions",
        "onboarding_items", "onboarding_cases", "onboarding_template_items", "onboarding_templates",
        "attendance_days", "punches", "shifts",
        "personnel_actions", "assignment_managers", "assignments",
        "employments", "persons",
        "positions", "cost_centres", "grades", "jobs", "org_units", "locations", "legal_entities",
        "role_assignments", "roles", "user_accounts",
    ]
    for t in tables:
        await session.execute(text(f"DELETE FROM {t} WHERE tenant_id = :tid"), {"tid": str(TENANT_ID)})
    await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": str(TENANT_ID)})


async def main() -> None:
    async with Session() as session:
        await wipe_tenant(session)

        # ── Tenant ──────────────────────────────────────────────────────
        await session.execute(
            text("""
                INSERT INTO tenants (id, slug, display_name, industry, country_code, status, plan)
                VALUES (:id, 'sfpl-group', 'SFPL Group', 'Manufacturing & Trading', 'IN', 'ACTIVE', 'GROWTH')
            """),
            {"id": str(TENANT_ID)},
        )

        # ── Legal entities (the sister companies) ─────────────────────────
        entities = {
            "SFPL": "SFPL Pvt Ltd",
            "SRCC": "SRCC Enterprises",
            "NOVUSHA": "Novusha Industries",
            "ALLUVIUM": "Alluvium IoT Solutions",
        }
        entity_ids: dict[str, UUID] = {}
        for code, name in entities.items():
            eid = uid()
            entity_ids[code] = eid
            await session.execute(
                text("""
                    INSERT INTO legal_entities (tenant_id, id, name, short_name, country_code, status)
                    VALUES (:tid, :id, :name, :short, 'IN', 'ACTIVE')
                """),
                {"tid": str(TENANT_ID), "id": str(eid), "name": name, "short": code},
            )

        # ── One registered-office location per entity ──────────────────────
        location_ids: dict[str, UUID] = {}
        cities = {"SFPL": "Mumbai", "SRCC": "Pune", "NOVUSHA": "Ahmedabad", "ALLUVIUM": "Bengaluru"}
        for code, eid in entity_ids.items():
            lid = uid()
            location_ids[code] = lid
            await session.execute(
                text("""
                    INSERT INTO locations (tenant_id, id, name, type, city, country_code, timezone, legal_entity_id, status)
                    VALUES (:tid, :id, :name, 'OFFICE', :city, 'IN', 'Asia/Kolkata', :le, 'ACTIVE')
                """),
                {"tid": str(TENANT_ID), "id": str(lid), "name": f"{code} Head Office", "city": cities[code], "le": str(eid)},
            )

        # ── Org units: Company -> {Finance, HR, Operations} per entity ────
        org_unit_ids: dict[str, UUID] = {}          # "SFPL" -> company node
        dept_ids: dict[tuple[str, str], UUID] = {}  # ("SFPL", "Finance") -> dept node
        for code, eid in entity_ids.items():
            company_ou = uid()
            org_unit_ids[code] = company_ou
            await session.execute(
                text("""
                    INSERT INTO org_units (tenant_id, id, name, code, type, legal_entity_id, effective_from, status)
                    VALUES (:tid, :id, :name, :code, 'COMPANY', :le, :ef, 'ACTIVE')
                """),
                {"tid": str(TENANT_ID), "id": str(company_ou), "name": entities[code], "code": code,
                 "le": str(eid), "ef": date(2019, 1, 1)},
            )
            for dept in ("Finance", "HR", "Operations"):
                did = uid()
                dept_ids[(code, dept)] = did
                await session.execute(
                    text("""
                        INSERT INTO org_units (tenant_id, id, name, code, type, parent_id, legal_entity_id, effective_from, status)
                        VALUES (:tid, :id, :name, :code, 'DEPARTMENT', :parent, :le, :ef, 'ACTIVE')
                    """),
                    {"tid": str(TENANT_ID), "id": str(did), "name": dept, "code": f"{code}-{dept[:3].upper()}",
                     "parent": str(company_ou), "le": str(eid), "ef": date(2019, 1, 1)},
                )

        # ── Jobs (shared across entities) ───────────────────────────────
        job_ids: dict[str, UUID] = {}
        for title in ("HR Manager", "Accountant", "Operations Manager", "Software Engineer", "Executive"):
            jid = uid()
            job_ids[title] = jid
            await session.execute(
                text("INSERT INTO jobs (tenant_id, id, title, status) VALUES (:tid, :id, :title, 'ACTIVE')"),
                {"tid": str(TENANT_ID), "id": str(jid), "title": title},
            )

        # ── Roles ────────────────────────────────────────────────────────
        role_ids: dict[str, UUID] = {}
        for name, desc in ROLE_DESCRIPTIONS.items():
            rid = uid()
            role_ids[name] = rid
            await session.execute(
                text("""
                    INSERT INTO roles (tenant_id, id, name, description, is_system)
                    VALUES (:tid, :id, :name, :desc, true)
                """),
                {"tid": str(TENANT_ID), "id": str(rid), "name": name, "desc": desc},
            )

        pw_hash = hash_password(DEMO_PASSWORD)

        async def make_person(first: str, last: str) -> UUID:
            pid = uid()
            await session.execute(
                text("""
                    INSERT INTO persons (tenant_id, id, legal_first_name, legal_last_name)
                    VALUES (:tid, :id, :f, :l)
                """),
                {"tid": str(TENANT_ID), "id": str(pid), "f": first, "l": last},
            )
            return pid

        async def make_employment(person_id: UUID, entity_code: str, emp_no: str, hire: date, state: str = "ACTIVE") -> UUID:
            eid = uid()
            await session.execute(
                text("""
                    INSERT INTO employments (tenant_id, id, person_id, legal_entity_id, employee_number, hire_date, employment_state)
                    VALUES (:tid, :id, :pid, :le, :num, :hire, :state)
                """),
                {"tid": str(TENANT_ID), "id": str(eid), "pid": str(person_id), "le": str(entity_ids[entity_code]),
                 "num": emp_no, "hire": hire, "state": state},
            )
            return eid

        async def make_assignment(employment_id: UUID, entity_code: str, dept: str, job_title: str) -> UUID:
            aid = uid()
            await session.execute(
                text("""
                    INSERT INTO assignments (tenant_id, id, employment_id, effective_from, org_unit_id, location_id, job_id)
                    VALUES (:tid, :id, :eid, :ef, :ou, :loc, :job)
                """),
                {"tid": str(TENANT_ID), "id": str(aid), "eid": str(employment_id), "ef": date(2019, 1, 1),
                 "ou": str(dept_ids[(entity_code, dept)]), "loc": str(location_ids[entity_code]), "job": str(job_ids[job_title])},
            )
            return aid

        login_employments: list[UUID] = []

        async def make_login(
            employment_id: UUID | None, email: str, role: str, scope_type: str, scope_value: list[str] | None,
        ) -> None:
            if employment_id:
                login_employments.append(employment_id)
            account_id = uid()
            await session.execute(
                text("""
                    INSERT INTO user_accounts (tenant_id, id, email, password_hash, employment_id, status)
                    VALUES (:tid, :id, :email, :pw, :emp, 'ACTIVE')
                """),
                {"tid": str(TENANT_ID), "id": str(account_id), "email": email, "pw": pw_hash,
                 "emp": str(employment_id) if employment_id else None},
            )
            await session.execute(
                text("""
                    INSERT INTO role_assignments (tenant_id, id, user_account_id, role_id, scope_type, scope_value)
                    VALUES (:tid, :id, :uid, :rid, :st, :sv)
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "uid": str(account_id), "rid": str(role_ids[role]),
                 "st": scope_type, "sv": json.dumps(scope_value) if scope_value else None},
            )

        def le(*codes: str) -> list[str]:
            return [to_typed_id("legal_entity", entity_ids[c]) for c in codes]

        # ── People ───────────────────────────────────────────────────────

        # Kavita Singh — platform super admin, sees every company
        p = await make_person("Kavita", "Singh")
        emp = await make_employment(p, "SFPL", "SFPL-0001", date(2019, 3, 1))
        await make_assignment(emp, "SFPL", "HR", "HR Manager")
        await make_login(emp, "kavita.singh@sfplgroup.in", "SUPER_ADMIN", "ALL", None)

        # Rahul Iyer — group HR manager, sees every company (HR authority, not platform admin)
        p = await make_person("Rahul", "Iyer")
        emp = await make_employment(p, "SFPL", "SFPL-0002", date(2019, 6, 15))
        await make_assignment(emp, "SFPL", "HR", "HR Manager")
        await make_login(emp, "rahul.iyer@sfplgroup.in", "HR_MANAGER", "ALL", None)

        # Meera Joshi — regional HR manager for SRCC + Novusha only (NOT SFPL, NOT Alluvium)
        p = await make_person("Meera", "Joshi")
        emp = await make_employment(p, "SRCC", "SRCC-0001", date(2020, 2, 1))
        await make_assignment(emp, "SRCC", "HR", "HR Manager")
        await make_login(emp, "meera.joshi@sfplgroup.in", "HR_MANAGER", "LEGAL_ENTITY", le("SRCC", "NOVUSHA"))

        # Suresh Kumar — the shared accountant: employed by SFPL, books time at SFPL
        # and Novusha, sees only those two companies' people/reports/dashboard.
        p = await make_person("Suresh", "Kumar")
        emp = await make_employment(p, "SFPL", "SFPL-0003", date(2018, 4, 10))
        await make_assignment(emp, "SFPL", "Finance", "Accountant")
        await make_login(emp, "suresh.kumar@sfplgroup.in", "ACCOUNTANT", "LEGAL_ENTITY", le("SFPL", "NOVUSHA"))

        # Priya Menon — manager at SFPL Operations, sees herself + her direct reports
        p = await make_person("Priya", "Menon")
        mgr_emp = await make_employment(p, "SFPL", "SFPL-0004", date(2020, 8, 1))
        mgr_asgn = await make_assignment(mgr_emp, "SFPL", "Operations", "Operations Manager")
        await make_login(mgr_emp, "priya.menon@sfplgroup.in", "MANAGER", "DIRECT_REPORTS", None)

        # Arjun Sharma & Divya Nair — Priya's direct reports at SFPL
        for first, last, num in (("Arjun", "Sharma", "SFPL-0005"), ("Divya", "Nair", "SFPL-0006")):
            p = await make_person(first, last)
            emp = await make_employment(p, "SFPL", num, date(2021, 1, 10))
            asgn = await make_assignment(emp, "SFPL", "Operations", "Executive")
            await session.execute(
                text("""
                    INSERT INTO assignment_managers (tenant_id, id, assignment_id, manager_employment_id, manager_type, effective_from)
                    VALUES (:tid, :id, :asgn, :mgr, 'LINE', :ef)
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "asgn": str(asgn), "mgr": str(mgr_emp), "ef": date(2021, 1, 10)},
            )
            if first == "Arjun":
                await make_login(emp, "arjun.sharma@sfplgroup.in", "EMPLOYEE", "SELF", None)

        # Neha Patil — plain employee at SRCC (a sister company). Demonstrates
        # isolation: Priya/Arjun (SFPL-scoped) must never see her, and she must
        # never see SFPL. Meera (SRCC+Novusha scope) and Rahul/Kavita (ALL) can.
        p = await make_person("Neha", "Patil")
        emp = await make_employment(p, "SRCC", "SRCC-0002", date(2022, 5, 20))
        await make_assignment(emp, "SRCC", "Operations", "Executive")
        await make_login(emp, "neha.patil@sfplgroup.in", "EMPLOYEE", "SELF", None)

        # A few more headcount-only records (no login) so dashboards/reports
        # have realistic numbers across all four companies.
        filler = [
            ("Vikram", "Rao", "NOVUSHA", "Operations", "Executive", date(2021, 7, 1)),
            ("Anjali", "Deshmukh", "NOVUSHA", "Finance", "Accountant", date(2022, 3, 15)),
            ("Karan", "Mehta", "ALLUVIUM", "Operations", "Software Engineer", date(2023, 1, 5)),
            ("Sonal", "Gupta", "ALLUVIUM", "HR", "HR Manager", date(2023, 9, 1)),
            ("Imran", "Shaikh", "SFPL", "Operations", "Executive", date(2024, 2, 20)),
        ]
        for i, (first, last, entity, dept, job_title, hire) in enumerate(filler):
            p = await make_person(first, last)
            emp = await make_employment(p, entity, f"{entity}-{9000 + i}", hire)
            await make_assignment(emp, entity, dept, job_title)

        # ── Leave types (tenant-wide catalog) + balances for the logins ────
        leave_type_ids: dict[str, UUID] = {}
        for name, code, days, color in (
            ("Casual Leave", "CL", 12, "#14b8a6"),
            ("Sick Leave", "SL", 10, "#f59e0b"),
        ):
            ltid = uid()
            leave_type_ids[code] = ltid
            await session.execute(
                text("""
                    INSERT INTO leave_types (tenant_id, id, name, code, days_per_year, is_active, approval_levels, color)
                    VALUES (:tid, :id, :name, :code, :days, true, 1, :color)
                """),
                {"tid": str(TENANT_ID), "id": str(ltid), "name": name, "code": code, "days": days, "color": color},
            )
        for emp_id in login_employments:
            for code, ltid in leave_type_ids.items():
                await session.execute(
                    text("""
                        INSERT INTO leave_balances (tenant_id, id, employment_id, leave_type_id, year, allocated_days)
                        VALUES (:tid, :id, :emp, :lt, :yr, :days)
                    """),
                    {"tid": str(TENANT_ID), "id": str(uid()), "emp": str(emp_id), "lt": str(ltid),
                     "yr": date.today().year, "days": 12.0 if code == "CL" else 10.0},
                )

        await session.commit()

    print(f"\nSeeded tenant SFPL Group ({TENANT_ID}).\n")
    print(f"All demo accounts use the password: {DEMO_PASSWORD}\n")
    print(f"{'Email':<32} {'Role':<13} {'Scope':<28} What they should see")
    print("-" * 110)
    rows = [
        ("kavita.singh@sfplgroup.in", "SUPER_ADMIN", "ALL", "Every company (platform admin)"),
        ("rahul.iyer@sfplgroup.in", "HR_MANAGER", "ALL", "Every company (group HR)"),
        ("meera.joshi@sfplgroup.in", "HR_MANAGER", "SRCC + Novusha", "Only those two companies — not SFPL/Alluvium"),
        ("suresh.kumar@sfplgroup.in", "ACCOUNTANT", "SFPL + Novusha", "Shared accountant — read-only, those two companies"),
        ("priya.menon@sfplgroup.in", "MANAGER", "Direct reports", "Herself + Arjun + Divya, nothing else"),
        ("arjun.sharma@sfplgroup.in", "EMPLOYEE", "Self", "Only his own records"),
        ("neha.patil@sfplgroup.in", "EMPLOYEE", "Self (SRCC)", "Only her own records — proves SFPL managers can't see her"),
    ]
    for email, role, scope, desc in rows:
        print(f"{email:<32} {role:<13} {scope:<28} {desc}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
