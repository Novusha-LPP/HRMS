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
from pathlib import Path
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
        "employee_kyc_documents", "employee_kyc_records",
        "correction_approval_actions", "attendance_correction_requests",
        "leave_approval_actions", "leave_applications",
        "leave_encashments", "comp_off_grants", "leave_balances", "leave_types",
        "holidays",
        "employee_policy_assignments", "policy_templates",
        "report_definitions",
        "onboarding_items", "onboarding_cases", "onboarding_template_items", "onboarding_templates",
        "attendance_days", "punches",
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
        emp_rahul = await make_employment(p, "SFPL", "SFPL-0002", date(2019, 6, 15))
        emp = emp_rahul
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
        emp_arjun = None
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
                emp_arjun = emp
                await make_login(emp, "arjun.sharma@sfplgroup.in", "EMPLOYEE", "SELF", None)

        # Neha Patil — plain employee at SRCC (a sister company). Demonstrates
        # isolation: Priya/Arjun (SFPL-scoped) must never see her, and she must
        # never see SFPL. Meera (SRCC+Novusha scope) and Rahul/Kavita (ALL) can.
        p = await make_person("Neha", "Patil")
        emp_neha = await make_employment(p, "SRCC", "SRCC-0002", date(2022, 5, 20))
        await make_assignment(emp_neha, "SRCC", "Operations", "Executive")
        await make_login(emp_neha, "neha.patil@sfplgroup.in", "EMPLOYEE", "SELF", None)

        # A few more headcount-only records (no login) so dashboards/reports
        # have realistic numbers across all four companies.
        emp_vikram = None
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
            if i == 0:
                emp_vikram = emp
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

        # ── KYC Records & Documents ──────────────────────────────────────────
        storage_dir = Path("storage/kyc") / str(TENANT_ID)
        storage_dir.mkdir(parents=True, exist_ok=True)

        async def seed_kyc_doc(emp_id: UUID, doc_type: str, title: str, doc_num: str, fname: str, status: str, rej_reason: str = None):
            doc_id = uid()
            fpath = storage_dir / f"{doc_id}_{fname}"
            fpath.write_text(f"Mock Document Content for {title}\nDocument Type: {doc_type}\nDoc Number: {doc_num}\nTenant: {TENANT_ID}\nTimestamp: 2026-09-24\nStatus: {status}")
            await session.execute(
                text("""
                    INSERT INTO employee_kyc_documents (
                        tenant_id, id, employment_id, document_type, document_title, document_number,
                        file_name, file_size, mime_type, storage_path, status, rejection_reason
                    ) VALUES (
                        :tid, :id, :emp, :dtype, :title, :num,
                        :fname, :fsize, 'application/pdf', :fpath, :status, :rej
                    )
                """),
                {
                    "tid": str(TENANT_ID), "id": str(doc_id), "emp": str(emp_id),
                    "dtype": doc_type, "title": title, "num": doc_num,
                    "fname": fname, "fsize": 1024, "fpath": str(fpath),
                    "status": status, "rej": rej_reason,
                }
            )

        # 1. Rahul Iyer (HR Manager) — fully verified
        rec_id = uid()
        await session.execute(
            text("""
                INSERT INTO employee_kyc_records (
                    tenant_id, id, employment_id, pan_number, aadhaar_number, uan_number,
                    bank_name, account_holder_name, account_number, ifsc_code, branch_name,
                    father_or_spouse_name, marital_status, blood_group, emergency_contact_name,
                    emergency_contact_relation, emergency_contact_phone, current_address, permanent_address,
                    status, submitted_at, verified_at
                ) VALUES (
                    :tid, :id, :emp, 'ABCDE1234F', '987654321012', '100987654321',
                    'HDFC Bank', 'Rahul Iyer', '50100234567890', 'HDFC0001234', 'Bandra West, Mumbai',
                    'K. S. Iyer', 'MARRIED', 'O+', 'Pooja Iyer',
                    'Spouse', '+91 98201 12345', '402 Sea View Apts, Bandra, Mumbai 400050', '402 Sea View Apts, Bandra, Mumbai 400050',
                    'VERIFIED', NOW() - INTERVAL '30 days', NOW() - INTERVAL '28 days'
                )
            """),
            {"tid": str(TENANT_ID), "id": str(rec_id), "emp": str(emp_rahul)},
        )
        await seed_kyc_doc(emp_rahul, "PAN_CARD", "PAN Card Copy", "ABCDE1234F", "rahul_pan.pdf", "VERIFIED")
        await seed_kyc_doc(emp_rahul, "AADHAAR_FRONT", "Aadhaar Card Front", "987654321012", "rahul_aadhaar.pdf", "VERIFIED")
        await seed_kyc_doc(emp_rahul, "BANK_PROOF", "HDFC Cancelled Cheque", "50100234567890", "rahul_cheque.pdf", "VERIFIED")

        # 2. Priya Menon (Operations Manager) — fully verified
        rec_id = uid()
        await session.execute(
            text("""
                INSERT INTO employee_kyc_records (
                    tenant_id, id, employment_id, pan_number, aadhaar_number, uan_number,
                    bank_name, account_holder_name, account_number, ifsc_code, branch_name,
                    father_or_spouse_name, marital_status, blood_group, emergency_contact_name,
                    emergency_contact_relation, emergency_contact_phone, current_address, permanent_address,
                    status, submitted_at, verified_at
                ) VALUES (
                    :tid, :id, :emp, 'FGHIJ5678K', '876543210987', '100876543210',
                    'ICICI Bank', 'Priya Menon', '001105012345', 'ICIC0000011', 'Nariman Point, Mumbai',
                    'R. K. Menon', 'MARRIED', 'A+', 'Vikram Nair',
                    'Spouse', '+91 98202 23456', '12 Sunshine Enclave, Worli, Mumbai 400018', '12 Sunshine Enclave, Worli, Mumbai 400018',
                    'VERIFIED', NOW() - INTERVAL '20 days', NOW() - INTERVAL '18 days'
                )
            """),
            {"tid": str(TENANT_ID), "id": str(rec_id), "emp": str(mgr_emp)},
        )
        await seed_kyc_doc(mgr_emp, "PAN_CARD", "PAN Card Copy", "FGHIJ5678K", "priya_pan.pdf", "VERIFIED")
        await seed_kyc_doc(mgr_emp, "AADHAAR_FRONT", "Aadhaar Card Front", "876543210987", "priya_aadhaar.pdf", "VERIFIED")
        await seed_kyc_doc(mgr_emp, "BANK_PROOF", "ICICI Bank Passbook", "001105012345", "priya_bank.pdf", "VERIFIED")

        # 3. Arjun Sharma (Employee) — SUBMITTED (Pending HR Review)
        rec_id = uid()
        await session.execute(
            text("""
                INSERT INTO employee_kyc_records (
                    tenant_id, id, employment_id, pan_number, aadhaar_number, uan_number,
                    bank_name, account_holder_name, account_number, ifsc_code, branch_name,
                    father_or_spouse_name, marital_status, blood_group, emergency_contact_name,
                    emergency_contact_relation, emergency_contact_phone, current_address, permanent_address,
                    status, submitted_at
                ) VALUES (
                    :tid, :id, :emp, 'KLMNO9012P', '765432109876', '100765432109',
                    'State Bank of India', 'Arjun Sharma', '30245678901', 'SBIN0000300', 'Fort, Mumbai',
                    'Suresh Sharma', 'SINGLE', 'B+', 'Suresh Sharma',
                    'Father', '+91 98203 34567', 'Flat 304, Green Heights, Andheri East, Mumbai 400069', 'House 14, Civil Lines, Jaipur 302006',
                    'SUBMITTED', NOW() - INTERVAL '2 days'
                )
            """),
            {"tid": str(TENANT_ID), "id": str(rec_id), "emp": str(emp_arjun)},
        )
        await seed_kyc_doc(emp_arjun, "PAN_CARD", "PAN Card Copy", "KLMNO9012P", "arjun_pan.pdf", "PENDING")
        await seed_kyc_doc(emp_arjun, "AADHAAR_FRONT", "Aadhaar Card Front", "765432109876", "arjun_aadhaar_front.pdf", "PENDING")
        await seed_kyc_doc(emp_arjun, "BANK_PROOF", "SBI Cancelled Cheque", "30245678901", "arjun_cheque.pdf", "PENDING")

        # 4. Neha Patil (Employee) — DRAFT (Partially filled, 1 doc)
        rec_id = uid()
        await session.execute(
            text("""
                INSERT INTO employee_kyc_records (
                    tenant_id, id, employment_id, pan_number, aadhaar_number,
                    bank_name, account_holder_name, account_number, ifsc_code,
                    marital_status, blood_group, current_address,
                    status
                ) VALUES (
                    :tid, :id, :emp, 'PQRST3456M', '654321098765',
                    'Axis Bank', 'Neha Patil', '914010012345678', 'UTIB0000123',
                    'SINGLE', 'AB+', 'A-12 Pratham Apts, Kothrud, Pune 411038',
                    'DRAFT'
                )
            """),
            {"tid": str(TENANT_ID), "id": str(rec_id), "emp": str(emp_neha)},
        )
        await seed_kyc_doc(emp_neha, "PAN_CARD", "PAN Card", "PQRST3456M", "neha_pan.pdf", "PENDING")

        # 5. Vikram Rao (Novusha Operations) — ACTION REQUIRED / REJECTED with comments
        rec_id = uid()
        await session.execute(
            text("""
                INSERT INTO employee_kyc_records (
                    tenant_id, id, employment_id, pan_number, aadhaar_number,
                    bank_name, account_holder_name, account_number, ifsc_code,
                    status, rejection_reason
                ) VALUES (
                    :tid, :id, :emp, 'UVWXY7890Z', '543210987654',
                    'Bank of Baroda', 'Vikram Rao', '0123456789', 'BARB0AHMEDA',
                    'ACTION_REQUIRED', 'Aadhaar copy is blurry and address proof is older than 3 months. Please re-upload.'
                )
            """),
            {"tid": str(TENANT_ID), "id": str(rec_id), "emp": str(emp_vikram)},
        )
        await seed_kyc_doc(emp_vikram, "PAN_CARD", "PAN Card", "UVWXY7890Z", "vikram_pan.pdf", "VERIFIED")
        await seed_kyc_doc(emp_vikram, "AADHAAR_FRONT", "Aadhaar Card Front", "543210987654", "vikram_aadhaar.pdf", "REJECTED", "Document image is blurred and unreadable. Please upload clear scan.")

        # ── Daily Attendance & Punches (Today) ───────────────────────────────
        today = date.today()
        from datetime import datetime, timezone, time

        async def seed_attendance(emp_id: UUID, status: str, in_time: time, out_time: time, late_mins: int = 0):
            ad_id = uid()
            in_dt = datetime.combine(today, in_time).replace(tzinfo=timezone.utc)
            out_dt = datetime.combine(today, out_time).replace(tzinfo=timezone.utc)
            diff_mins = int((out_dt - in_dt).total_seconds() / 60)
            break_mins = 45
            eff_mins = max(0, diff_mins - break_mins)

            await session.execute(
                text("""
                    INSERT INTO attendance_days (
                        tenant_id, id, employment_id, work_date,
                        first_punch_in, last_punch_out,
                        gross_minutes, break_minutes, effective_minutes,
                        late_by_minutes, early_departure_minutes, status, is_locked
                    ) VALUES (
                        :tid, :id, :emp, :wdate,
                        :pin, :pout,
                        :gross, :brk, :eff,
                        :late, 0, :status, false
                    )
                """),
                {
                    "tid": str(TENANT_ID), "id": str(ad_id), "emp": str(emp_id), "wdate": today,
                    "pin": in_dt, "pout": out_dt,
                    "gross": diff_mins, "brk": break_mins, "eff": eff_mins,
                    "late": late_mins, "status": status,
                },
            )

            # Punch In
            await session.execute(
                text("""
                    INSERT INTO punches (tenant_id, id, employment_id, punch_type, punched_at, source)
                    VALUES (:tid, :id, :emp, 'IN', :ts, 'WEB')
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "emp": str(emp_id), "ts": in_dt},
            )
            # Punch Out
            await session.execute(
                text("""
                    INSERT INTO punches (tenant_id, id, employment_id, punch_type, punched_at, source)
                    VALUES (:tid, :id, :emp, 'OUT', :ts, 'WEB')
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "emp": str(emp_id), "ts": out_dt},
            )

        # Lookup all employment IDs by employee_number
        emp_lookup_res = await session.execute(
            text("SELECT id, employee_number FROM employments WHERE tenant_id = :tid"),
            {"tid": str(TENANT_ID)}
        )
        emp_by_num = {r._mapping["employee_number"]: r._mapping["id"] for r in emp_lookup_res}

        # Seed realistic attendees for today:
        if "SFPL-0005" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0005"], "PRESENT", time(9, 2), time(18, 15), 0)
        if "SFPL-0004" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0004"], "PRESENT", time(8, 55), time(18, 5), 0)
        if "SFPL-0006" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0006"], "LATE", time(9, 35), time(18, 45), 25)
        if "SFPL-0003" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0003"], "PRESENT", time(9, 8), time(18, 12), 0)
        if "SFPL-0002" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0002"], "PRESENT", time(8, 48), time(18, 20), 0)
        if "SFPL-0001" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-0001"], "PRESENT", time(8, 50), time(18, 10), 0)
        if "NOVUSHA-9001" in emp_by_num:
            await seed_attendance(emp_by_num["NOVUSHA-9001"], "LATE", time(9, 25), time(18, 20), 15)
        if "ALLUVIUM-9002" in emp_by_num:
            await seed_attendance(emp_by_num["ALLUVIUM-9002"], "PRESENT", time(9, 5), time(18, 35), 0)
        if "ALLUVIUM-9003" in emp_by_num:
            await seed_attendance(emp_by_num["ALLUVIUM-9003"], "PRESENT", time(9, 0), time(18, 0), 0)
        if "SFPL-9004" in emp_by_num:
            await seed_attendance(emp_by_num["SFPL-9004"], "LATE", time(9, 30), time(18, 40), 20)

        # Approved Leave for Neha (Casual Leave)
        cl_id = leave_type_ids.get("CL")
        if cl_id and "SRCC-0002" in emp_by_num:
            await session.execute(
                text("""
                    INSERT INTO leave_applications (
                        tenant_id, id, employment_id, leave_type_id,
                        from_date, to_date, days_requested, reason, status
                    ) VALUES (
                        :tid, :id, :emp, :lt,
                        :today, :today, 1.0, 'Personal work at bank', 'APPROVED'
                    )
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "emp": str(emp_by_num["SRCC-0002"]), "lt": str(cl_id), "today": today},
            )

        # Approved Leave for Meera (Sick Leave)
        sl_id = leave_type_ids.get("SL")
        if sl_id and "SRCC-0001" in emp_by_num:
            await session.execute(
                text("""
                    INSERT INTO leave_applications (
                        tenant_id, id, employment_id, leave_type_id,
                        from_date, to_date, days_requested, reason, status
                    ) VALUES (
                        :tid, :id, :emp, :lt,
                        :today, :today, 1.0, 'Viral fever recovery', 'APPROVED'
                    )
                """),
                {"tid": str(TENANT_ID), "id": str(uid()), "emp": str(emp_by_num["SRCC-0001"]), "lt": str(sl_id), "today": today},
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
