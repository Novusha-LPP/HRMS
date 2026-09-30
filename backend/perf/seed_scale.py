# ruff: noqa: E501 — long SQL literals read better unwrapped
"""
Seed a synthetic, realistically shaped tenant for performance measurement.

    uv run python perf/seed_scale.py --slug perf-2k --employees 2000 --months 6

Everything is generated — no real names, no real data. It builds:

  * 4 legal entities, each Company -> 6 departments -> 3 teams (100 org units)
  * N employees spread across the 72 teams, each with a person, employment, assignment and
    a login (EMPLOYEE, SELF scope)
  * a 3-level reporting line: team lead -> department head -> company head, with MANAGER
    roles (DIRECT_REPORTS for team leads, ALL_REPORTS for heads)
  * personas for every scope pattern the API resolves (see PERSONAS below)
  * `--months` of weekday attendance history: attendance_days + IN/OUT punches (~92% present)
  * holidays, leave types, monthly accruals and leave applications — the leave part goes
    through the real API (in-process) so the ledger is written by the real engine.

SAFETY: refuses to run if the target database contains any tenant whose slug does not start
with "perf-". Run it only against a throwaway database (see backend/perf/README.md) — never
against a database holding real employee data.
"""

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.authz import ROLE_DESCRIPTIONS
from hrms.core.config import settings
from hrms.core.ids import to_typed_id
from hrms.core.security import hash_password

PASSWORD = "PerfPassw0rd!"  # synthetic accounts in a throwaway database only
ENTITIES = ["ALPHA", "BETA", "GAMMA", "DELTA"]
DEPARTMENTS = ["Operations", "Production", "Quality", "Finance", "HR", "Sales"]
TEAMS_PER_DEPT = 3
JOBS = ["Executive", "Senior Executive", "Team Lead", "Manager", "Operator"]

# persona -> what it exercises
PERSONAS = {
    "employee": "EMPLOYEE / SELF — plain self-service",
    "team_lead": "MANAGER / DIRECT_REPORTS — one team",
    "dept_head": "MANAGER / ALL_REPORTS — recursive reporting chain",
    "hr_all": "HR_MANAGER / ALL — whole tenant",
    "hr_entity": "HR_MANAGER / LEGAL_ENTITY — two of four companies",
    "hr_dept": "HR_MANAGER / ORG_UNIT — one department subtree",
    "admin": "SUPER_ADMIN / ALL — tenant admin with no employee record",
}

FIRST = ["Aarav", "Diya", "Kabir", "Isha", "Vihaan", "Anaya", "Reyansh", "Myra", "Arjun", "Saanvi"]
LAST = ["Sample", "Tester", "Example", "Synthetic", "Placeholder", "Mock", "Dummy", "Fixture"]


def u() -> str:
    return str(uuid4())


async def guard(session) -> None:
    rows = (await session.execute(text("SELECT slug FROM tenants"))).scalars().all()
    foreign = [s for s in rows if not s.startswith("perf-")]
    if foreign:
        sys.exit(
            f"Refusing to run: this database has {len(foreign)} non-perf tenant(s). "
            "seed_scale.py only runs against a throwaway benchmark database."
        )


async def seed_structure(session, slug: str, n: int, months: int) -> dict:
    t0 = time.perf_counter()
    tid = u()
    await session.execute(
        text("""INSERT INTO tenants (id, slug, display_name, country_code, status, plan)
                VALUES (:id, :slug, :name, 'IN', 'ACTIVE', 'GROWTH')"""),
        {"id": tid, "slug": slug, "name": f"Perf {slug}"},
    )
    base = {"tid": tid}

    entity_ids, loc_ids, company_ou = {}, {}, {}
    dept_ou: dict[tuple[str, str], str] = {}
    teams: list[dict] = []
    for code in ENTITIES:
        entity_ids[code] = u()
        await session.execute(
            text("""INSERT INTO legal_entities (tenant_id, id, name, short_name, country_code, status)
                    VALUES (:tid, :id, :name, :short, 'IN', 'ACTIVE')"""),
            {**base, "id": entity_ids[code], "name": f"{code} Industries", "short": code},
        )
        loc_ids[code] = u()
        await session.execute(
            text("""INSERT INTO locations (tenant_id, id, name, type, city, country_code, timezone,
                        legal_entity_id, status)
                    VALUES (:tid, :id, :name, 'OFFICE', 'Pune', 'IN', 'Asia/Kolkata', :le, 'ACTIVE')"""),
            {**base, "id": loc_ids[code], "name": f"{code} Plant", "le": entity_ids[code]},
        )
        company_ou[code] = u()
        await session.execute(
            text("""INSERT INTO org_units (tenant_id, id, name, code, type, legal_entity_id,
                        effective_from, status)
                    VALUES (:tid, :id, :name, :code, 'COMPANY', :le, '2019-01-01', 'ACTIVE')"""),
            {
                **base,
                "id": company_ou[code],
                "name": f"{code} Industries",
                "code": code,
                "le": entity_ids[code],
            },
        )
        for d in DEPARTMENTS:
            did = u()
            dept_ou[(code, d)] = did
            await session.execute(
                text("""INSERT INTO org_units (tenant_id, id, name, code, type, parent_id,
                            legal_entity_id, effective_from, status)
                        VALUES (:tid, :id, :name, :code, 'DEPARTMENT', :p, :le, '2019-01-01', 'ACTIVE')"""),
                {
                    **base,
                    "id": did,
                    "name": d,
                    "code": f"{code}-{d[:3].upper()}",
                    "p": company_ou[code],
                    "le": entity_ids[code],
                },
            )
            for t in range(TEAMS_PER_DEPT):
                team_id = u()
                await session.execute(
                    text("""INSERT INTO org_units (tenant_id, id, name, code, type, parent_id,
                                legal_entity_id, effective_from, status)
                            VALUES (:tid, :id, :name, :code, 'TEAM', :p, :le, '2019-01-01', 'ACTIVE')"""),
                    {
                        **base,
                        "id": team_id,
                        "name": f"{d} Team {t + 1}",
                        "code": f"{code}-{d[:3].upper()}-T{t + 1}",
                        "p": did,
                        "le": entity_ids[code],
                    },
                )
                teams.append({"entity": code, "dept": d, "team": t, "ou": team_id, "members": []})

    job_ids = {}
    for title in JOBS:
        job_ids[title] = u()
        await session.execute(
            text(
                "INSERT INTO jobs (tenant_id, id, title, status) VALUES (:tid, :id, :t, 'ACTIVE')"
            ),
            {**base, "id": job_ids[title], "t": title},
        )
    role_ids = {}
    for name, desc in ROLE_DESCRIPTIONS.items():
        role_ids[name] = u()
        await session.execute(
            text("""INSERT INTO roles (tenant_id, id, name, description, is_system)
                    VALUES (:tid, :id, :name, :d, true)"""),
            {**base, "id": role_ids[name], "name": name, "d": desc},
        )

    # ── Employees ──────────────────────────────────────────────────────────
    rng = random.Random(slug)
    pw_hash = hash_password(PASSWORD)
    persons, employments, assignments, accounts, grants = [], [], [], [], []
    emps = []
    for i in range(n):
        team = teams[i % len(teams)]
        code = team["entity"]
        e = {"n": i, "pid": u(), "eid": u(), "aid": u(), "uid": u(), "team": team}
        emps.append(e)
        team["members"].append(e)
        persons.append({**base, "id": e["pid"], "f": rng.choice(FIRST), "l": rng.choice(LAST)})
        hire = date(2018, 1, 1) + timedelta(days=rng.randrange(0, 2400))
        employments.append(
            {
                **base,
                "id": e["eid"],
                "pid": e["pid"],
                "le": entity_ids[code],
                "num": f"{code[:2]}{i + 1:06d}",
                "hire": hire,
            }
        )
        assignments.append(
            {
                **base,
                "id": e["aid"],
                "eid": e["eid"],
                "ou": team["ou"],
                "loc": loc_ids[code],
                "job": job_ids[rng.choice(JOBS)],
            }
        )
        accounts.append(
            {
                **base,
                "id": e["uid"],
                "email": f"e{i + 1:06d}@{slug}.perf.invalid",
                "pw": pw_hash,
                "emp": e["eid"],
            }
        )
        grants.append(
            {
                **base,
                "id": u(),
                "uid": e["uid"],
                "rid": role_ids["EMPLOYEE"],
                "st": "SELF",
                "sv": None,
            }
        )

    await session.execute(
        text("""INSERT INTO persons (tenant_id, id, legal_first_name, legal_last_name)
                VALUES (:tid, :id, :f, :l)"""),
        persons,
    )
    await session.execute(
        text("""INSERT INTO employments (tenant_id, id, person_id, legal_entity_id, employee_number,
                    hire_date, employment_state)
                VALUES (:tid, :id, :pid, :le, :num, :hire, 'ACTIVE')"""),
        employments,
    )
    await session.execute(
        text("""INSERT INTO assignments (tenant_id, id, employment_id, effective_from, org_unit_id,
                    location_id, job_id)
                VALUES (:tid, :id, :eid, '2019-01-01', :ou, :loc, :job)"""),
        assignments,
    )
    await session.execute(
        text("""INSERT INTO user_accounts (tenant_id, id, email, password_hash, employment_id, status)
                VALUES (:tid, :id, :email, :pw, :emp, 'ACTIVE')"""),
        accounts,
    )

    # ── Reporting lines: team lead <- members; dept head <- team leads; company head <- dept heads
    managers = []

    def manage(mgr, report):
        managers.append({**base, "id": u(), "a": report["aid"], "m": mgr["eid"]})
        report["manager"] = mgr

    lead_of = {}
    for team in teams:
        if team["members"]:
            lead = team["members"][0]
            lead_of[team["ou"]] = lead
            for m in team["members"][1:]:
                manage(lead, m)
            grants.append(
                {
                    **base,
                    "id": u(),
                    "uid": lead["uid"],
                    "rid": role_ids["MANAGER"],
                    "st": "DIRECT_REPORTS",
                    "sv": None,
                }
            )
    heads = {}
    for code in ENTITIES:
        for d in DEPARTMENTS:
            leads = [
                lead_of[t["ou"]]
                for t in teams
                if t["entity"] == code and t["dept"] == d and t["ou"] in lead_of
            ]
            if not leads:
                continue
            heads[(code, d)] = leads[0]
            for lead in leads[1:]:
                manage(leads[0], lead)
            grants.append(
                {
                    **base,
                    "id": u(),
                    "uid": leads[0]["uid"],
                    "rid": role_ids["MANAGER"],
                    "st": "ALL_REPORTS",
                    "sv": None,
                }
            )
        dept_heads = [heads[(code, d)] for d in DEPARTMENTS if (code, d) in heads]
        for h in dept_heads[1:]:
            manage(dept_heads[0], h)
    if managers:
        await session.execute(
            text("""INSERT INTO assignment_managers (tenant_id, id, assignment_id,
                        manager_employment_id, manager_type, effective_from)
                    VALUES (:tid, :id, :a, :m, 'LINE', '2019-01-01')"""),
            managers,
        )

    # ── Personas ───────────────────────────────────────────────────────────
    def le(*codes):
        return json.dumps([to_typed_id("legal_entity", UUID(entity_ids[c])) for c in codes])

    plain = next(e for e in emps if e not in lead_of.values() and e not in heads.values())
    persona_accounts = {
        "employee": plain,
        "team_lead": lead_of[teams[1]["ou"]],
        "dept_head": heads[(ENTITIES[0], DEPARTMENTS[0])],
    }
    hr_all, hr_entity, hr_dept = emps[-1], emps[-2], emps[-3]
    extra = [
        (hr_all, "HR_MANAGER", "ALL", None),
        (hr_entity, "HR_MANAGER", "LEGAL_ENTITY", le(ENTITIES[0], ENTITIES[1])),
        (
            hr_dept,
            "HR_MANAGER",
            "ORG_UNIT",
            json.dumps([to_typed_id("org_unit", UUID(dept_ou[(ENTITIES[0], DEPARTMENTS[0])]))]),
        ),
    ]
    persona_accounts.update(hr_all=hr_all, hr_entity=hr_entity, hr_dept=hr_dept)
    for emp, role, st, sv in extra:
        grants.append(
            {**base, "id": u(), "uid": emp["uid"], "rid": role_ids[role], "st": st, "sv": sv}
        )
    admin_uid = u()
    await session.execute(
        text("""INSERT INTO user_accounts (tenant_id, id, email, password_hash, status)
                VALUES (:tid, :id, :email, :pw, 'ACTIVE')"""),
        {**base, "id": admin_uid, "email": f"admin@{slug}.perf.invalid", "pw": pw_hash},
    )
    grants.append(
        {
            **base,
            "id": u(),
            "uid": admin_uid,
            "rid": role_ids["SUPER_ADMIN"],
            "st": "ALL",
            "sv": None,
        }
    )
    await session.execute(
        text("""INSERT INTO role_assignments (tenant_id, id, user_account_id, role_id, scope_type,
                    scope_value)
                VALUES (:tid, :id, :uid, :rid, :st, :sv)"""),
        grants,
    )

    # ── Holidays + attendance history (set-based) ─────────────────────────
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=31 * months)).replace(day=1)
    holidays = [start + timedelta(days=d) for d in range(17, (today - start).days, 29)]
    await session.execute(
        text("""INSERT INTO holidays (tenant_id, id, holiday_date, name)
                VALUES (:tid, :id, :d, :name)"""),
        [{**base, "id": u(), "d": h, "name": f"Holiday {i + 1}"} for i, h in enumerate(holidays)],
    )
    await session.execute(
        text("""
        CREATE TEMP TABLE perf_days ON COMMIT DROP AS
        SELECT e.id AS employment_id, d::date AS work_date,
               (d::date + time '09:00' + (random() * interval '55 minutes'))
                   AT TIME ZONE 'Asia/Kolkata' AS in_at,
               (d::date + time '18:00' + (random() * interval '90 minutes'))
                   AT TIME ZONE 'Asia/Kolkata' AS out_at
        FROM employments e
        CROSS JOIN generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
        WHERE e.tenant_id = :tid
          AND extract(isodow FROM d) < 6
          AND d::date <> ALL(CAST(:hol AS date[]))
          AND random() < 0.92
        """),
        {**base, "start": start, "end": today - timedelta(days=1), "hol": holidays},
    )
    await session.execute(
        text("""
        INSERT INTO attendance_days (tenant_id, id, employment_id, work_date, first_punch_in,
            last_punch_out, gross_minutes, effective_minutes, late_by_minutes, status)
        SELECT CAST(:tid AS uuid), gen_random_uuid(), employment_id, work_date, in_at, out_at,
               extract(epoch FROM out_at - in_at)::int / 60,
               extract(epoch FROM out_at - in_at)::int / 60 - 30,
               greatest(0, extract(epoch FROM in_at - ((work_date + time '09:30')
                   AT TIME ZONE 'Asia/Kolkata'))::int / 60),
               CASE WHEN in_at > (work_date + time '09:45') AT TIME ZONE 'Asia/Kolkata'
                    THEN 'LATE' ELSE 'PRESENT' END
        FROM perf_days
        """),
        base,
    )
    await session.execute(
        text("""
        INSERT INTO punches (tenant_id, id, employment_id, punch_type, punched_at, work_date, source)
        SELECT CAST(:tid AS uuid), gen_random_uuid(), employment_id, 'IN', in_at, work_date, 'DEVICE' FROM perf_days
        UNION ALL
        SELECT CAST(:tid AS uuid), gen_random_uuid(), employment_id, 'OUT', out_at, work_date, 'DEVICE' FROM perf_days
        """),
        base,
    )
    days = (await session.execute(text("SELECT count(*) FROM perf_days"))).scalar()
    await session.commit()

    personas = {k: f"e{v['n'] + 1:06d}@{slug}.perf.invalid" for k, v in persona_accounts.items()}
    personas["admin"] = f"admin@{slug}.perf.invalid"
    print(
        f"  structure: {n} employees, {len(managers)} reporting lines, {days} attendance days "
        f"({2 * days} punches) in {time.perf_counter() - t0:.1f}s"
    )
    return {
        "tenant_id": tid,
        "slug": slug,
        "employees": n,
        "personas": personas,
        "start": start.isoformat(),
        # employment -> its line manager's login (None for a company head)
        "employment_ids": {
            to_typed_id(
                "employment", UUID(e["eid"])
            ): f"e{e['manager']['n'] + 1:06d}@{slug}.perf.invalid" if "manager" in e else None
            for e in emps
        },
    }


async def seed_leave(meta: dict, months: int, apps_per_employee: float) -> None:
    """Leave setup through the real API (in-process), so the engine writes its own ledger."""
    import httpx

    from hrms.main import app

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://perf") as c:
        r = await c.post(
            "/v1/auth/login", json={"identifier": meta["personas"]["admin"], "password": PASSWORD}
        )
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        types = []
        for name, code, days, accrue in (
            ("Casual Leave", "CL", 12, True),
            ("Sick Leave", "SL", 10, True),
            ("Earned Leave", "EL", 15, True),
        ):
            r = await c.post(
                "/v1/leave/types",
                headers=h,
                json={
                    "name": name,
                    "code": code,
                    "days_per_year": days,
                    "accrual_enabled": accrue,
                    "carry_forward": code == "EL",
                    "max_carry_forward_days": 30,
                },
            )
            r.raise_for_status()
            types.append(r.json()["id"])

        today = date.today()
        t0 = time.perf_counter()
        month = date.fromisoformat(meta["start"])
        timings = []
        while month <= today:
            s = time.perf_counter()
            r = await c.post(f"/v1/leave/accrual/run?period={month:%Y-%m}", headers=h)
            timings.append((f"{month:%Y-%m}", time.perf_counter() - s, r.status_code))
            month = (month + timedelta(days=32)).replace(day=1)
        print(
            f"  accrual: {len(timings)} monthly runs in {time.perf_counter() - t0:.1f}s "
            f"(slowest {max(t for _, t, _ in timings):.1f}s; "
            f"statuses {sorted({s for *_, s in timings})})"
        )
        meta["accrual_seconds"] = timings

        rng = random.Random(meta["slug"])
        emp_ids = [e for e, m in meta["employment_ids"].items() if m]
        tokens: dict[str, dict] = {}
        token_lock = asyncio.Lock()

        async def manager_headers(email):
            async with token_lock:
                if email not in tokens:
                    r = await c.post(
                        "/v1/auth/login", json={"identifier": email, "password": PASSWORD}
                    )
                    r.raise_for_status()
                    tokens[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}
                return tokens[email]

        n_apps = int(len(emp_ids) * apps_per_employee)
        start = date.fromisoformat(meta["start"])
        span = (today - start).days
        sem = asyncio.Semaphore(16)
        stats = {"created": 0, "approved": 0, "errors": {}}

        async def one(i):
            emp = rng.choice(emp_ids)
            d0 = start + timedelta(days=rng.randrange(0, span + 20))
            while d0.isoweekday() > 5:
                d0 += timedelta(days=1)
            d1 = d0 + timedelta(days=rng.choice([0, 0, 0, 1, 2]))
            async with sem:
                r = await c.post(
                    f"/v1/leave/applications?employment_id={emp}",
                    headers=h,
                    json={
                        "leave_type_id": rng.choice(types),
                        "from_date": d0.isoformat(),
                        "to_date": d1.isoformat(),
                        "reason": "perf seed",
                    },
                )
                if r.status_code != 201:
                    key = f"create {r.status_code}: {str(r.json().get('detail'))[:60]}"
                    stats["errors"][key] = stats["errors"].get(key, 0) + 1
                    return
                stats["created"] += 1
                app_id = r.json()["id"]
                r = await c.post(f"/v1/leave/applications/{app_id}/submit", headers=h)
                if r.status_code != 200 or rng.random() < 0.25:
                    return  # leave ~25% pending
                mh = await manager_headers(meta["employment_ids"][emp])
                r = await c.post(
                    f"/v1/leave/applications/{app_id}/approve",
                    headers=mh,
                    json={"action": "APPROVE", "comments": "ok"},
                )
                if r.status_code == 200:
                    stats["approved"] += 1
                else:
                    key = f"approve {r.status_code}: {str(r.json().get('detail'))[:60]}"
                    stats["errors"][key] = stats["errors"].get(key, 0) + 1

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(n_apps)))
        print(
            f"  leave: {stats['created']} applications, {stats['approved']} approved in "
            f"{time.perf_counter() - t0:.1f}s; errors: {stats['errors'] or 'none'}"
        )


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--slug", required=True, help='tenant slug; must start with "perf-"')
    p.add_argument("--employees", type=int, default=2000)
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--apps-per-employee", type=float, default=1.5)
    p.add_argument("--out", default="perf/out", help="where the personas file is written")
    args = p.parse_args()
    if not args.slug.startswith("perf-"):
        sys.exit('--slug must start with "perf-"')

    engine = create_async_engine(settings.database_url)  # owner role: bulk writes across RLS
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await guard(session)
        print(f"Seeding {args.slug}")
        meta = await seed_structure(session, args.slug, args.employees, args.months)
    await engine.dispose()
    await seed_leave(meta, args.months, args.apps_per_employee)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta.pop("employment_ids")
    (out / f"{args.slug}.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"  personas -> {out / (args.slug + '.json')} (password: see perf/README.md)")


if __name__ == "__main__":
    asyncio.run(main())
