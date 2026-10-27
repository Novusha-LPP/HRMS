"""Set each active EXIM team member's line manager to the team's HOD; dry-run by default.

Source: exim.teams.json (+ exim.users.json). HRMS keeps one LINE manager per assignment, so a
team becomes "everyone in it reports to its HOD". Rules:

  * only active teams; the HOD must be an active, linked employee of the same company group;
  * a member's line is added only when they have none: an existing line is never changed;
  * a person in two active teams keeps the first team in the file (the others are reported);
  * inactive members, unlinked members and the HOD themselves are skipped;
  * a line that would make two people each other's manager (a loop) is skipped and reported;
  * no org units are created: HRMS has no team membership, only reporting lines.

Run from backend (same scope switches as the other EXIM importers):
  python scripts/migrate_exim_teams.py --tenant suraj-group
  python scripts/migrate_exim_teams.py --tenant rabs-industries-india-private-limited \
      --company rabs --decisions rabs_decisions.json
Add --apply to commit.
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import exim_scope
from migrate_legacy_attendance import source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.core.datetime_utils import business_today
from hrms.core.locking import lock_resource

ROOT = Path(__file__).resolve().parents[2]
ALIAS = {"suraj forwarders": "suraj forwarders private limited"}


def would_loop(manager_of, member, manager):
    """True if making `manager` the line manager of `member` closes a reporting loop."""
    seen = set()
    node = manager
    while node is not None and node not in seen:
        if node == member:
            return True
        seen.add(node)
        node = manager_of.get(node)
    return False


async def prepare(session, tenant_ref, data_dir, company, decisions):
    tid = (
        await session.execute(
            text("SELECT id FROM tenants WHERE slug = :r OR CAST(id AS text) = :r"),
            {"r": tenant_ref},
        )
    ).scalar_one()
    users = {unwrap(r["_id"]): r for r in json.loads((data_dir / "exim.users.json").read_text())}
    teams = json.loads((data_dir / "exim.teams.json").read_text())
    rows = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_user_id, ua.employment_id, ua.employee_code, e.legal_entity_id,
               (ua.status = 'ACTIVE' AND e.archived_at IS NULL
                AND e.employment_state <> 'SEPARATED'
                AND (e.separation_date IS NULL OR e.separation_date > :today)) AS active
        FROM user_accounts ua JOIN employments e
          ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        WHERE ua.tenant_id = :tid AND ua.erp_system = 'EXIM'
    """),
                {"tid": tid, "today": business_today()},
            )
        )
        .mappings()
        .all()
    )
    links = {r["erp_user_id"]: dict(r) for r in rows}
    for key, link in (await exim_scope.decided_links(session, tid, decisions)).items():
        code_active = (
            await session.execute(
                text("""SELECT (ua.status = 'ACTIVE' AND e.archived_at IS NULL
                        AND e.employment_state <> 'SEPARATED') FROM user_accounts ua
                        JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                        WHERE ua.tenant_id = :tid AND ua.id = :a"""),
                {"tid": tid, "a": link["account_id"]},
            )
        ).scalar()
        links[key] = {**link, "active": bool(code_active), "employee_code": link.get("code")}
    entities = {
        r["name"].casefold(): r["id"]
        for r in (
            await session.execute(
                text(
                    "SELECT id,name FROM legal_entities WHERE tenant_id=:t AND archived_at IS NULL"
                ),
                {"t": tid},
            )
        )
        .mappings()
        .all()
    }
    entity_for, other_company = exim_scope.build(company, entities, ALIAS)
    return tid, users, teams, links, entity_for, other_company


async def current_assignments(session, tid):
    rows = await session.execute(
        text("""
        SELECT a.employment_id, a.id, a.effective_from FROM assignments a
        WHERE a.tenant_id = :tid AND a.effective_from <= :today
          AND (a.effective_to IS NULL OR a.effective_to > :today)
    """),
        {"tid": tid, "today": business_today()},
    )
    return {r.employment_id: (r.id, r.effective_from) for r in rows}


async def current_lines(session, tid):
    rows = (
        await session.execute(
            text("""
        SELECT am.assignment_id, am.manager_employment_id, a.employment_id
        FROM assignment_managers am JOIN assignments a
          ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
        WHERE am.tenant_id = :tid AND am.manager_type = 'LINE' AND am.effective_from <= :today
          AND (am.effective_to IS NULL OR am.effective_to > :today)
    """),
            {"tid": tid, "today": business_today()},
        )
    ).all()
    return {r.assignment_id: r.manager_employment_id for r in rows}, {
        r.employment_id: r.manager_employment_id for r in rows
    }


async def plan_and_apply(session, tid, users, teams, links, entity_for, other_company, apply):
    stats = {
        "teams_in_file": len(teams),
        "teams_inactive": 0,
        "teams_out_of_scope": 0,
        "teams_applied": 0,
        "members_seen": 0,
        "created": Counter(),
        "existing": Counter(),
        "skipped": Counter(),
        "by_team": [],
    }
    assignment_of = await current_assignments(session, tid)
    line_by_assignment, manager_of = await current_lines(session, tid)
    claimed = {}
    for team in teams:
        name = team.get("name")
        if not team.get("isActive"):
            stats["teams_inactive"] += 1
            continue
        hod_id = unwrap(team["hodId"])
        hod_user, hod = users.get(hod_id), links.get(hod_id)
        if hod_user is None or other_company(hod_user) or entity_for(hod_user) is None:
            stats["teams_out_of_scope"] += 1
            stats["by_team"].append(
                {
                    "team": name,
                    "hod": hod_user["username"] if hod_user else hod_id,
                    "skipped": "HOD not in this tenant's company group or legal entity",
                    "members": len(team.get("members") or []),
                }
            )
            continue
        row = {"team": name, "hod": (hod or {}).get("employee_code") or hod_user["username"]}
        counts = Counter()
        if hod is None or not hod["active"] or not hod_user.get("isActive"):
            row["skipped"] = "HOD not an active linked employee"
            counts["members_skipped_no_active_hod"] = len(team.get("members") or [])
            stats["skipped"]["team HOD not an active linked employee"] += len(
                team.get("members") or []
            )
            row["counts"] = dict(counts)
            stats["by_team"].append(row)
            continue
        stats["teams_applied"] += 1
        hod_emp = hod["employment_id"]
        for member in team.get("members") or []:
            uid = unwrap(member["userId"])
            stats["members_seen"] += 1
            user, link = users.get(uid), links.get(uid)
            if uid == hod_id:
                counts["hod_itself"] += 1
                continue
            if user is None or other_company(user):
                stats["skipped"]["member not in this company group"] += 1
                counts["not_in_group"] += 1
                continue
            if link is None:
                stats["skipped"]["no HRMS employee link"] += 1
                counts["no_link"] += 1
                continue
            if not link["active"] or not user.get("isActive"):
                stats["skipped"]["member not active"] += 1
                counts["inactive"] += 1
                continue
            emp = link["employment_id"]
            if emp in claimed:
                stats["skipped"]["already placed under the first of their teams"] += 1
                counts["second_team_ignored"] += 1
                continue
            claimed[emp] = name
            slot = assignment_of.get(emp)
            if slot is None:
                stats["skipped"]["no current assignment"] += 1
                counts["no_assignment"] += 1
                continue
            assignment_id, effective_from = slot
            existing = line_by_assignment.get(assignment_id)
            if existing == hod_emp:
                stats["existing"]["same line already set"] += 1
                counts["already_same"] += 1
                continue
            if existing is not None:
                stats["existing"]["different line kept"] += 1
                counts["different_kept"] += 1
                continue
            if would_loop(manager_of, emp, hod_emp):
                stats["skipped"]["would make a reporting loop"] += 1
                counts["loop"] += 1
                continue
            await session.execute(
                text("""
                INSERT INTO assignment_managers
                  (tenant_id,id,assignment_id,manager_employment_id,manager_type,effective_from)
                VALUES (:tid,:id,:a,:m,'LINE',:f)
            """),
                {
                    "tid": tid,
                    "id": source_uuid(tid, "team-line", f"{assignment_id}:{hod_emp}"),
                    "a": assignment_id,
                    "m": hod_emp,
                    "f": effective_from,
                },
            )
            manager_of[emp] = hod_emp
            line_by_assignment[assignment_id] = hod_emp
            stats["created"]["lines"] += 1
            counts["created"] += 1
        row["counts"] = dict(counts)
        stats["by_team"].append(row)
    return stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--company", choices=["suraj", "rabs"], default="suraj")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-team-lines.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            tid, users, teams, links, entity_for, other_company = await prepare(
                session, args.tenant, args.data_dir, args.company, args.decisions
            )
            await lock_resource(session, tid, "exim-team-lines")
            stats = await plan_and_apply(
                session, tid, users, teams, links, entity_for, other_company, args.apply
            )
            stats["tenant"] = args.tenant
            stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
            if args.apply:
                await session.execute(
                    text("""
                    INSERT INTO import_batches
                      (tenant_id,id,source_system,imported_at,total_records,
                       created_records,updated_records,is_dry_run,details)
                    VALUES (:tid,:id,'EXIM_TEAM_LINES',now(),:total,:created,0,false,
                            CAST(:details AS jsonb))
                """),
                    {
                        "tid": tid,
                        "id": source_uuid(tid, "team-lines-batch", datetime.now(UTC).isoformat()),
                        "total": stats["members_seen"],
                        "created": stats["created"]["lines"],
                        "details": json.dumps(stats, default=str),
                    },
                )
            else:
                await session.rollback()
        args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
        args.report.chmod(0o600)
        print(json.dumps({k: v for k, v in stats.items() if k != "by_team"}, indent=2, default=str))
        print(f"Per-team detail: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
