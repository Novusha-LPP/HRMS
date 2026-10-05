# ruff: noqa: E501
"""
Sample recruitment data for one tenant, so the Recruitment screens can be reviewed.

Everything it creates is fake and marked:
  - every opening title starts with "DEMO · ";
  - every candidate email ends in ".demo@example.com" (example.com never delivers mail);
  - every event carries {"demo": true}.

It uses the tenant's real companies, departments, designations and locations, and an
existing admin account as the requester and approver. It doesn't touch employees, and
no candidate is converted into an employee.

    cd backend
    .venv/bin/python scripts/seed_recruitment_demo.py --tenant suraj-group --yes
    .venv/bin/python scripts/seed_recruitment_demo.py --tenant suraj-group --remove --yes

Run it from backend/ so that resumes land in the same document store as the API's.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core import document_store
from hrms.core.config import settings
from hrms.modules.recruitment.service import DEFAULT_STAGES

PREFIX = "DEMO · "
SAVED_REFS: list[str] = []  # resumes written this run, removed again if the transaction fails
EMAIL_SUFFIX = ".demo@example.com"
NOW = datetime.now(UTC)

# (title, department, company keyword, designation keyword, status, positions, priority,
#  employment type, work mode, reason, experience, salary, skills, description,
#  responsibilities, requirements, hold/close reason)
OPENINGS = [
    dict(
        title="Senior Export Documentation Executive",
        dept="Export",
        company="Suraj Forwarders Private",
        job="Executive",
        status="OPEN",
        positions=2,
        priority="HIGH",
        etype="FULL_TIME",
        mode="ONSITE",
        reason="EXPANSION",
        exp=(3, 6),
        salary=(420000, 650000),
        skills=["Shipping bills", "ICEGATE", "Letters of credit", "Incoterms"],
        description="Prepare and file export documentation for FCL and LCL shipments, coordinate with "
        "shipping lines and CHAs, and keep every shipment compliant with customs and DGFT rules.",
        responsibilities="File shipping bills on ICEGATE\nCoordinate BL drafts with shipping lines\n"
        "Track LC terms and flag discrepancies before submission\nMaintain the shipment document register",
        requirements="3+ years in export documentation\nWorking knowledge of Incoterms and LCs\n"
        "Comfortable with ICEGATE and DGFT portals",
        days_ago=21,
    ),
    dict(
        title="Logistics Coordinator",
        dept="Operations",
        company="SR Container",
        job="Executive",
        status="OPEN",
        positions=1,
        priority="MEDIUM",
        etype="FULL_TIME",
        mode="ONSITE",
        reason="REPLACEMENT",
        replacement="Outgoing coordinator (demo)",
        exp=(1, 4),
        salary=(300000, 420000),
        skills=["Container tracking", "Excel", "Vendor coordination"],
        description="Plan container movements between port, CFS and customer sites and keep customers "
        "updated on every milestone.",
        responsibilities="Book trailers and track container movements\nShare daily status reports\n"
        "Resolve detention and demurrage queries",
        requirements="1+ years in container logistics\nGood spoken English and Hindi",
        days_ago=14,
    ),
    dict(
        title="Full Stack Developer (React / Python)",
        dept="Software Development",
        company="Novusha",
        job="Developer",
        status="OPEN",
        positions=2,
        priority="CRITICAL",
        etype="FULL_TIME",
        mode="HYBRID",
        reason="NEW_ROLE",
        exp=(2, 5),
        salary=(800000, 1400000),
        skills=["React", "TypeScript", "Python", "FastAPI", "PostgreSQL"],
        description="Build features across the HRMS web app and API, from database migrations to the "
        "React screens HR teams use every day.",
        responsibilities="Ship features end to end with tests\nReview pull requests\n"
        "Improve performance and reliability of the API",
        requirements="2+ years building web apps with React\nProduction experience with Python\n"
        "Solid SQL and PostgreSQL",
        days_ago=10,
    ),
    dict(
        title="Accounts Executive (GST)",
        dept="Finance & Accounts",
        company="Suraj Forwarders Private",
        job="Account",
        status="PENDING_APPROVAL",
        positions=1,
        priority="MEDIUM",
        etype="FULL_TIME",
        mode="ONSITE",
        reason="EXPANSION",
        exp=(2, 4),
        salary=(350000, 500000),
        skills=["GST returns", "Tally", "Reconciliation"],
        description="Handle GST filings, vendor reconciliation and month-end closing for the forwarding "
        "business.",
        responsibilities="File GSTR-1 and GSTR-3B\nReconcile vendor ledgers\nSupport the statutory audit",
        requirements="B.Com or equivalent\n2+ years with GST compliance",
        days_ago=3,
    ),
    dict(
        title="Customs Compliance Manager",
        dept="Import",
        company="Suraj Forwarders Private",
        job="Manager",
        status="DRAFT",
        positions=1,
        priority="HIGH",
        etype="FULL_TIME",
        mode="ONSITE",
        reason="NEW_ROLE",
        exp=(8, 12),
        salary=(1200000, 1800000),
        skills=["Customs Act", "AEO", "Audit"],
        description="Own customs compliance across import operations, including AEO certification and "
        "internal audits.",
        responsibilities="Run quarterly compliance audits\nLead AEO renewal\nTrain the import team",
        requirements="8+ years in customs brokerage\nLicensed customs broker preferred",
        days_ago=1,
    ),
    dict(
        title="Warehouse Supervisor",
        dept="Operations",
        company="Suraj Forwarders & Shipping",
        job="Supervisor",
        status="ON_HOLD",
        positions=1,
        priority="LOW",
        etype="CONTRACT",
        mode="ONSITE",
        reason="NEW_ROLE",
        exp=(4, 8),
        salary=(360000, 480000),
        skills=["Warehouse management", "Inventory", "Team handling"],
        description="Supervise day-to-day warehouse operations and a team of loaders at the CFS.",
        responsibilities="Plan daily stuffing and de-stuffing\nMaintain stock accuracy\nEnsure safety compliance",
        requirements="4+ years supervising warehouse teams",
        hold="Waiting for the new CFS lease to be signed (demo)",
        days_ago=30,
    ),
]

# Candidates per opening index: (first, last, title, company, years, current, expected, notice,
#  source, stage, rating, note, outcome reason)
CANDIDATES = {
    0: [
        (
            "Aarti",
            "Kulkarni",
            "Documentation Executive",
            "Blue Ocean Logistics",
            4,
            420000,
            540000,
            30,
            "LINKEDIN",
            "Interview",
            4,
            "Strong on LC discrepancies; second round with the export head.",
            None,
        ),
        (
            "Rohan",
            "Mehta",
            "Export Executive",
            "Westline Shipping",
            3.5,
            380000,
            500000,
            45,
            "JOB_PORTAL",
            "Shortlisted",
            3,
            None,
            None,
        ),
        (
            "Sneha",
            "Patil",
            "Senior Documentation Executive",
            "Coastal Freight",
            6,
            560000,
            680000,
            60,
            "REFERRAL",
            "Offer released",
            5,
            "Offer at ₹6.5 L shared; joining by mid-November.",
            None,
        ),
        (
            "Imran",
            "Shaikh",
            "CHA Executive",
            "Harbour Clearing Agency",
            2,
            300000,
            420000,
            15,
            "WALK_IN",
            "Screening",
            None,
            None,
            None,
        ),
        (
            "Pooja",
            "Iyer",
            "Shipping Coordinator",
            "Atlas Lines",
            3,
            360000,
            480000,
            30,
            "LINKEDIN",
            "Rejected",
            2,
            None,
            "Limited hands-on experience with ICEGATE filings",
        ),
        (
            "Vikas",
            "Rao",
            "Export Documentation Assistant",
            "Trans Global Cargo",
            1.5,
            240000,
            360000,
            0,
            "CAREERS_SITE",
            "Applied",
            None,
            None,
            None,
        ),
    ],
    1: [
        (
            "Neha",
            "Joshi",
            "Logistics Executive",
            "Swift Movers",
            2.5,
            320000,
            400000,
            30,
            "JOB_PORTAL",
            "Selected",
            4,
            "Good fit; reference check done.",
            None,
        ),
        (
            "Karan",
            "Singh",
            "Transport Coordinator",
            "Roadlink Carriers",
            3,
            340000,
            420000,
            30,
            "REFERRAL",
            "Interview",
            3,
            None,
            None,
        ),
        (
            "Divya",
            "Menon",
            "Operations Trainee",
            "Port Connect",
            1,
            240000,
            320000,
            0,
            "CAMPUS",
            "Applied",
            None,
            None,
            None,
        ),
        (
            "Arjun",
            "Pillai",
            "Fleet Coordinator",
            "CityHaul",
            4,
            380000,
            460000,
            60,
            "AGENCY",
            "Withdrawn",
            None,
            None,
            "Accepted a counter-offer from current employer",
        ),
    ],
    2: [
        (
            "Ananya",
            "Deshpande",
            "Software Engineer",
            "Brightcode Labs",
            3,
            900000,
            1250000,
            30,
            "LINKEDIN",
            "Interview",
            4,
            "Excellent take-home; system design round next.",
            None,
        ),
        (
            "Siddharth",
            "Nair",
            "Full Stack Developer",
            "Cloudnest",
            4,
            1100000,
            1400000,
            60,
            "REFERRAL",
            "Onboarding",
            5,
            "Offer accepted. Joining 3 Nov.",
            None,
        ),
        (
            "Meera",
            "Krishnan",
            "Frontend Developer",
            "Pixelworks",
            2,
            700000,
            950000,
            30,
            "CAREERS_SITE",
            "Shortlisted",
            3,
            None,
            None,
        ),
        (
            "Rahul",
            "Verma",
            "Backend Developer",
            "Dataforge",
            2.5,
            800000,
            1100000,
            45,
            "JOB_PORTAL",
            "Screening",
            None,
            None,
            None,
        ),
        (
            "Fatima",
            "Khan",
            "Junior Developer",
            "Startup Studio",
            1,
            450000,
            700000,
            15,
            "LINKEDIN",
            "Rejected",
            2,
            None,
            "Needs more production experience with Python",
        ),
    ],
    5: [
        (
            "Prakash",
            "Yadav",
            "Warehouse In-charge",
            "Metro Storage",
            6,
            380000,
            450000,
            30,
            "WALK_IN",
            "Interview",
            3,
            None,
            None,
        ),
        (
            "Sunil",
            "Gaikwad",
            "Shift Supervisor",
            "Prime CFS",
            5,
            340000,
            420000,
            30,
            "REFERRAL",
            "Screening",
            None,
            None,
            None,
        ),
    ],
}

TECH_SKILLS = {2: ["React", "TypeScript", "Python", "FastAPI"]}


def _pdf(lines: list[str]) -> bytes:
    """A small, valid one-page PDF with the given lines of text."""

    def esc(s: str) -> str:
        return (
            s.encode("latin-1", "replace")
            .decode("latin-1")
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )

    body = ["BT", "/F1 20 Tf", "60 780 Td", f"({esc(lines[0])}) Tj", "/F1 11 Tf"]
    for line in lines[1:]:
        body += ["0 -22 Td", f"({esc(line)}) Tj"]
    body.append("ET")
    stream = "\n".join(body).encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


async def _one(conn, sql, **params):
    return (await conn.execute(text(sql), params)).first()


async def _event(conn, tid, opening_id, actor, action, details, when, application_id=None):
    await conn.execute(
        text("""INSERT INTO recruitment_events
                (tenant_id, id, opening_id, application_id, actor_user_id, action, details, created_at)
                VALUES (:tid, :id, :oid, :aid, :actor, :action, CAST(:details AS jsonb), :at)"""),
        dict(
            tid=tid,
            id=uuid4(),
            oid=opening_id,
            aid=application_id,
            actor=actor,
            action=action,
            details=json.dumps({**details, "demo": True}),
            at=when,
        ),
    )


async def remove(conn, tid) -> None:
    refs = [
        r[0]
        for r in await conn.execute(
            text(f"""SELECT resume_ref FROM candidates WHERE tenant_id = :tid
                 AND email LIKE '%{EMAIL_SUFFIX}' AND resume_ref IS NOT NULL"""),
            {"tid": tid},
        )
    ]
    openings = await conn.execute(
        text("DELETE FROM job_openings WHERE tenant_id = :tid AND title LIKE :p"),
        {"tid": tid, "p": PREFIX + "%"},
    )
    candidates = await conn.execute(
        text(f"""DELETE FROM candidates c WHERE c.tenant_id = :tid AND c.email LIKE '%{EMAIL_SUFFIX}'
                 AND NOT EXISTS (SELECT 1 FROM job_applications a
                                 WHERE a.tenant_id = c.tenant_id AND a.candidate_id = c.id)"""),
        {"tid": tid},
    )
    await conn.execute(
        text(
            "DELETE FROM approval_instances WHERE tenant_id = :tid AND request_type = 'JOB_REQUISITION' "
            "AND request_id NOT IN (SELECT id FROM job_openings WHERE tenant_id = :tid)"
        ),
        {"tid": tid},
    )
    for ref in refs:
        try:
            document_store.remove(ref)
        except Exception as exc:  # a missing file is fine
            print(f"  (couldn't remove {ref}: {exc})")
    print(f"Removed {openings.rowcount} demo openings and {candidates.rowcount} demo candidates.")


async def seed(conn, tid) -> None:
    existing = await _one(
        conn,
        "SELECT count(*) FROM job_openings WHERE tenant_id = :tid AND title LIKE :p",
        tid=tid,
        p=PREFIX + "%",
    )
    if existing[0]:
        sys.exit("Demo openings already exist for this tenant — run with --remove first.")

    admins = [
        r[0]
        for r in await conn.execute(
            text("""
        SELECT ua.id FROM user_accounts ua
        JOIN role_assignments ra ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
        JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
        WHERE ua.tenant_id = :tid AND r.name IN ('SUPER_ADMIN', 'HR_MANAGER') AND ua.status = 'ACTIVE'
        ORDER BY (r.name = 'HR_MANAGER') DESC, ua.created_at
    """),
            {"tid": tid},
        )
    ]
    if not admins:
        sys.exit("This tenant has no active SUPER_ADMIN or HR_MANAGER account to act as requester.")
    hr = admins[0]
    requester = admins[1] if len(admins) > 1 else admins[0]

    stage_rows = (
        await conn.execute(
            text(
                "SELECT id, name, category FROM recruitment_stages WHERE tenant_id = :tid AND is_active"
            ),
            {"tid": tid},
        )
    ).all()
    if not stage_rows:
        for i, (name, category, color) in enumerate(DEFAULT_STAGES):
            await conn.execute(
                text("""INSERT INTO recruitment_stages
                (tenant_id, id, name, category, color, sequence) VALUES (:tid, :id, :n, :c, :col, :s)"""),
                dict(tid=tid, id=uuid4(), n=name, c=category.value, col=color, s=i),
            )
        stage_rows = (
            await conn.execute(
                text(
                    "SELECT id, name, category FROM recruitment_stages WHERE tenant_id = :tid AND is_active"
                ),
                {"tid": tid},
            )
        ).all()
    stages = {r.name.lower(): r for r in stage_rows}

    def stage(name):
        found = stages.get(name.lower())
        if found:
            return found
        # Tenants that renamed stages: fall back to the first stage of the right kind.
        kind = {"rejected": "REJECTED", "withdrawn": "WITHDRAWN", "onboarding": "HIRED"}.get(
            name.lower(), "ACTIVE"
        )
        return next(r for r in stage_rows if r.category == kind)

    code = (
        await _one(
            conn,
            """SELECT COALESCE(MAX(CAST(substring(code FROM 5) AS integer)), 0)
                                FROM job_openings WHERE tenant_id = :tid AND code ~ '^REQ-[0-9]{1,9}$'""",
            tid=tid,
        )
    )[0]
    created_openings = created_candidates = 0
    phone = 90000_10000

    for index, spec in enumerate(OPENINGS):
        unit = await _one(
            conn,
            """
            SELECT ou.id, ou.legal_entity_id FROM org_units ou
            JOIN legal_entities le ON le.tenant_id = ou.tenant_id AND le.id = ou.legal_entity_id
            WHERE ou.tenant_id = :tid AND ou.type = 'DEPARTMENT' AND ou.status = 'ACTIVE'
              AND ou.archived_at IS NULL AND ou.name = :dept AND le.name ILIKE :company
            ORDER BY ou.name LIMIT 1""",
            tid=tid,
            dept=spec["dept"],
            company=f"%{spec['company']}%",
        )
        if unit is None:
            unit = await _one(
                conn,
                """SELECT id, legal_entity_id FROM org_units WHERE tenant_id = :tid
                AND type = 'DEPARTMENT' AND status = 'ACTIVE' AND archived_at IS NULL
                AND legal_entity_id IS NOT NULL ORDER BY name LIMIT 1""",
                tid=tid,
            )
        job = await _one(
            conn,
            "SELECT id FROM jobs WHERE tenant_id = :tid AND title ILIKE :t ORDER BY title LIMIT 1",
            tid=tid,
            t=f"%{spec['job']}%",
        )
        location = await _one(
            conn,
            """SELECT id FROM locations WHERE tenant_id = :tid
            AND (legal_entity_id = :le OR legal_entity_id IS NULL) ORDER BY legal_entity_id NULLS LAST LIMIT 1""",
            tid=tid,
            le=unit.legal_entity_id,
        )
        code += 1
        oid = uuid4()
        created = NOW - timedelta(days=spec["days_ago"])
        submitted = created + timedelta(hours=2) if spec["status"] != "DRAFT" else None
        approved = created + timedelta(days=1) if spec["status"] in ("OPEN", "ON_HOLD") else None
        await conn.execute(
            text("""
            INSERT INTO job_openings (tenant_id, id, code, title, legal_entity_id, org_unit_id, job_id,
              location_id, requested_by, employment_type, work_mode, positions, priority, reason,
              replacement_for, min_experience_years, max_experience_years, salary_min, salary_max,
              currency, target_start_date, description, responsibilities, requirements, skills, status,
              approval_mode, submitted_at, approved_at, approved_by, decision_comment, close_reason,
              created_at, updated_at)
            VALUES (:tid, :id, :code, :title, :le, :ou, :job, :loc, :req, :etype, :mode, :pos, :prio,
              :reason, :repl, :emin, :emax, :smin, :smax, 'INR', :target, :descr, :resp, :reqs,
              CAST(:skills AS jsonb), :status, :amode, :sub, :appr, :apprby, :comment, :hold, :created, :updated)
        """),
            dict(
                tid=tid,
                id=oid,
                code=f"REQ-{code:04d}",
                title=PREFIX + spec["title"],
                le=unit.legal_entity_id,
                ou=unit.id,
                job=job.id if job else None,
                loc=location.id if location else None,
                req=requester,
                etype=spec["etype"],
                mode=spec["mode"],
                pos=spec["positions"],
                prio=spec["priority"],
                reason=spec["reason"],
                repl=spec.get("replacement"),
                emin=spec["exp"][0],
                emax=spec["exp"][1],
                smin=spec["salary"][0],
                smax=spec["salary"][1],
                target=date.today() + timedelta(days=30 + 7 * index),
                descr=spec["description"],
                resp=spec["responsibilities"],
                reqs=spec["requirements"],
                skills=json.dumps(spec["skills"]),
                status=spec["status"],
                amode=None if spec["status"] == "DRAFT" else "HR",
                sub=submitted,
                appr=approved,
                apprby=hr if approved else None,
                comment="Budget approved (demo)" if approved else None,
                hold=spec.get("hold"),
                created=created,
                updated=NOW - timedelta(hours=index),
            ),
        )
        created_openings += 1
        await _event(conn, tid, oid, requester, "CREATED", {"code": f"REQ-{code:04d}"}, created)
        if submitted:
            await _event(conn, tid, oid, requester, "SUBMITTED", {"mode": "HR"}, submitted)
        if approved:
            await _event(
                conn,
                tid,
                oid,
                hr,
                "APPROVED",
                {"mode": "HR", "comments": "Budget approved (demo)"},
                approved,
            )
        if spec["status"] == "ON_HOLD":
            await _event(
                conn,
                tid,
                oid,
                hr,
                "STATUS_CHANGED",
                {"from": "OPEN", "to": "ON_HOLD", "reason": spec["hold"]},
                approved + timedelta(days=5),
            )

        for n, (
            first,
            last,
            title,
            company,
            years,
            cur,
            exp,
            notice,
            source,
            stage_name,
            rating,
            note,
            outcome,
        ) in enumerate(CANDIDATES.get(index, [])):
            cid = uuid4()
            slug = f"{first}.{last}".lower()
            email = f"{slug}{EMAIL_SUFFIX}"
            links = [
                {
                    "type": "LINKEDIN",
                    "label": None,
                    "url": f"https://www.linkedin.com/in/{slug.replace('.', '-')}-demo",
                }
            ]
            if index in TECH_SKILLS:
                links.append(
                    {
                        "type": "GITHUB",
                        "label": None,
                        "url": f"https://github.com/{slug.replace('.', '-')}-demo",
                    }
                )
                if n % 2 == 0:
                    links.append(
                        {
                            "type": "PORTFOLIO",
                            "label": None,
                            "url": f"https://{slug.replace('.', '')}-demo.dev",
                        }
                    )
            skills = (TECH_SKILLS.get(index) or spec["skills"])[: 3 + n % 2]
            applied = approved + timedelta(days=1 + n) if approved else NOW
            summary = f"{years} years as {title} at {company}. Sample candidate created for the recruitment demo."
            phone += 1
            existing_candidate = await _one(
                conn,
                "SELECT id FROM candidates WHERE tenant_id = :tid AND lower(email) = :e",
                tid=tid,
                e=email,
            )
            if existing_candidate:
                cid = existing_candidate.id
            else:
                pdf = _pdf(
                    [
                        f"{first} {last}",
                        f"{title}, {company}",
                        f"Experience: {years} years",
                        f"Skills: {', '.join(skills)}",
                        f"Email: {email}",
                        "Sample resume generated for the HRMS recruitment demo.",
                    ]
                )
                file_name = f"{first}_{last}_Resume.pdf"
                ref = document_store.save(f"recruitment/{tid}/{cid}/{uuid4()}_{file_name}", pdf)
                SAVED_REFS.append(ref)
                await conn.execute(
                    text("""
                    INSERT INTO candidates (tenant_id, id, first_name, last_name, email, phone, location,
                      current_company, current_title, total_experience_years, current_ctc, expected_ctc,
                      notice_period_days, source, source_detail, links, skills, summary, resume_ref,
                      resume_file_name, resume_mime_type, resume_size, resume_uploaded_at, created_by,
                      created_at, updated_at)
                    VALUES (:tid, :id, :fn, :ln, :email, :phone, :loc, :co, :title, :yrs, :cur, :exp, :notice,
                      :src, :srcd, CAST(:links AS jsonb), CAST(:skills AS jsonb), :summary, :ref, :fname,
                      'application/pdf', :size, :at, :by, :at, :at)
                """),
                    dict(
                        tid=tid,
                        id=cid,
                        fn=first,
                        ln=last,
                        email=email,
                        phone=f"+91 {str(phone)[:5]} {str(phone)[5:]}",
                        loc=["Mumbai", "Navi Mumbai", "Pune", "Ahmedabad"][n % 4],
                        co=company,
                        title=title,
                        yrs=years,
                        cur=cur,
                        exp=exp,
                        notice=notice,
                        src=source,
                        srcd="Referred by a current employee (demo)"
                        if source == "REFERRAL"
                        else None,
                        links=json.dumps(links),
                        skills=json.dumps(skills),
                        summary=summary,
                        ref=ref,
                        fname=file_name,
                        size=len(pdf),
                        at=applied,
                        by=hr,
                    ),
                )
                created_candidates += 1
            aid = uuid4()
            target = stage(stage_name)
            moved = applied + timedelta(days=2 + n)
            await conn.execute(
                text("""
                INSERT INTO job_applications (tenant_id, id, opening_id, candidate_id, stage_id, rating,
                  owner_user_id, outcome_reason, applied_at, stage_changed_at, created_by, created_at, updated_at)
                VALUES (:tid, :id, :oid, :cid, :sid, :rating, :hr, :outcome, :applied, :moved, :hr, :applied, :moved)
            """),
                dict(
                    tid=tid,
                    id=aid,
                    oid=oid,
                    cid=cid,
                    sid=target.id,
                    rating=rating,
                    hr=hr,
                    outcome=outcome,
                    applied=applied,
                    moved=moved,
                ),
            )
            entry = stage("Applied")
            await _event(
                conn, tid, oid, hr, "APPLICATION_ADDED", {"stage": entry.name}, applied, aid
            )
            await _event(
                conn,
                tid,
                oid,
                hr,
                "RESUME_UPLOADED",
                {"file_name": f"{first}_{last}_Resume.pdf"},
                applied + timedelta(minutes=2),
                aid,
            )
            if target.id != entry.id:
                await _event(
                    conn,
                    tid,
                    oid,
                    hr,
                    "STAGE_CHANGED",
                    {
                        "from": entry.name,
                        "to": target.name,
                        "category": target.category,
                        "reason": outcome,
                    },
                    moved,
                    aid,
                )
            if rating:
                await _event(
                    conn,
                    tid,
                    oid,
                    hr,
                    "RATED",
                    {"rating": rating},
                    moved + timedelta(minutes=5),
                    aid,
                )
            if note:
                await _event(
                    conn,
                    tid,
                    oid,
                    requester,
                    "NOTE",
                    {"body": note},
                    moved + timedelta(hours=1),
                    aid,
                )

        # Keep FILLED in step with the hires, as the API does.
        hired = await _one(
            conn,
            """SELECT count(*) FROM job_applications a JOIN recruitment_stages s
            ON s.tenant_id = a.tenant_id AND s.id = a.stage_id
            WHERE a.tenant_id = :tid AND a.opening_id = :oid AND s.category = 'HIRED'""",
            tid=tid,
            oid=oid,
        )
        if spec["status"] == "OPEN" and hired[0] >= spec["positions"]:
            await conn.execute(
                text(
                    "UPDATE job_openings SET status = 'FILLED' WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": oid},
            )

    print(
        f"Seeded {created_openings} demo openings and {created_candidates} demo candidates "
        f"(requester and approver: existing admin accounts)."
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tenant", required=True, help="Tenant slug, e.g. suraj-group")
    parser.add_argument("--remove", action="store_true", help="Delete the demo data instead")
    parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation")
    args = parser.parse_args()

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            row = await _one(
                conn, "SELECT id, display_name FROM tenants WHERE slug = :s", s=args.tenant
            )
            if row is None:
                sys.exit(f"No tenant with slug {args.tenant!r}")
            tid: UUID = row.id
            action = (
                "REMOVE demo recruitment data from"
                if args.remove
                else "Add demo recruitment data to"
            )
            if not args.yes and input(f"{action} {row.display_name}? [y/N] ").lower() != "y":
                sys.exit("Aborted — nothing was changed.")
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)}
            )
            await (remove(conn, tid) if args.remove else seed(conn, tid))
    except BaseException:
        for ref in SAVED_REFS:
            document_store.remove(ref)
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
