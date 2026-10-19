"""Import the EXIM regularization (attendance correction) history as finished requests.

Same rules as the other EXIM imports: dry-run by default (rolled back), exact EXIM employee
links, deterministic ids so a re-run changes nothing, RABS deferred.

Each old request becomes an APPROVED or REJECTED HRMS correction request with its single
approval step, so people and HR can see what was asked and decided. Punches are NOT changed:
the old system mostly fixed such days by setting the status, which the punch-history import
already carries onto the day (status_override); inventing punch times here would contradict it.

Run from backend:
  .venv/bin/python scripts/migrate_exim_regularizations.py --tenant suraj-group
Add --apply to commit.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import exim_scope
from migrate_legacy_attendance import add_once, instant, source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.modules.corrections.models import AttendanceCorrectionRequest, CorrectionApprovalAction

ROOT = Path(__file__).resolve().parents[2]
ALIAS = {"suraj forwarders": "suraj forwarders private limited"}
TYPE = {
    "missing_punch": "MISSED_PUNCH",
    "half_day": "REGULARIZE",
    "absent": "MARK_PRESENT",
    "early_out": "EARLY_DEPARTURE_REASON",
    "late_in": "LATE_REASON",
}
MANUAL_NOTE = {
    "admin_manual_correction": "Corrected directly by an administrator in the old system",
    "hod_manual_correction": "Corrected directly by the head of department in the old system",
}


def day_of(value):
    raw = unwrap(value)
    if isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-":
        return date.fromisoformat(raw[:10])
    return instant(value).date()


def optional_instant(value):
    return instant(value) if value else None


async def migrate(session, tenant_ref, data_dir, company="suraj", decisions=None):
    tenant = (
        (
            await session.execute(
                text("SELECT id,slug FROM tenants WHERE slug = :ref OR id::text = :ref"),
                {"ref": tenant_ref},
            )
        )
        .mappings()
        .one()
    )
    tid = tenant["id"]
    stats = {
        "tenant": tenant["slug"],
        "source_requests": 0,
        "created": Counter(),
        "existing": Counter(),
        "skipped": Counter(),
        "other_company_requests": 0,
        "by_status": Counter(),
        "by_type": Counter(),
        "approver_not_recorded": 0,
    }
    users = {
        unwrap(r["_id"]): r for r in json.loads((data_dir / "exim.users copy.json").read_text())
    }
    rows = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_user_id, ua.id AS account_id, ua.employment_id, e.legal_entity_id
        FROM user_accounts ua LEFT JOIN employments e
          ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        WHERE ua.tenant_id = :tid AND ua.erp_system = 'EXIM'
    """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    accounts = {r["erp_user_id"]: r for r in rows}
    accounts.update(await exim_scope.decided_links(session, tid, decisions))
    entities = {
        r["name"].casefold(): r["id"]
        for r in (
            await session.execute(
                text(
                    "SELECT id,name FROM legal_entities "
                    "WHERE tenant_id=:tid AND archived_at IS NULL"
                ),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    }

    entity_for, other_company = exim_scope.build(company, entities, ALIAS)

    source = data_dir / "exim.regularizationrequests.json"
    for r in json.loads(source.read_text()):
        stats["source_requests"] += 1
        sid, uid = unwrap(r["_id"]), unwrap(r["employee_id"])
        user = users.get(uid)
        link = accounts.get(uid)
        if user is None:
            stats["skipped"]["source user missing"] += 1
            continue
        if other_company(user):
            stats["other_company_requests"] += 1
            continue
        if link is None or link["employment_id"] is None:
            stats["skipped"]["no HRMS employee link"] += 1
            continue
        if entity_for(user) != link["legal_entity_id"]:
            stats["skipped"]["company differs from the linked employee"] += 1
            continue
        kind = TYPE.get(r["regularization_type"])
        status = {"approved": "APPROVED", "rejected": "REJECTED"}.get(r["status"])
        if kind is None or status is None:
            stats["skipped"]["unsupported type or status"] += 1
            continue
        request_id = source_uuid(tid, "regularizationrequests", sid)
        stamp = instant(r["createdAt"])
        await add_once(
            session,
            AttendanceCorrectionRequest,
            AttendanceCorrectionRequest(
                tenant_id=tid,
                id=request_id,
                employment_id=link["employment_id"],
                work_date=day_of(r["attendance_date"]),
                correction_type=kind,
                requested_punch_in=optional_instant(r.get("requested_in_time")),
                requested_punch_out=optional_instant(r.get("requested_out_time")),
                reason=(r.get("reason") or "No reason given")[:1000],
                status=status,
                current_level=1,
                total_levels=1,
                submitted_at=stamp,
                recorded_at=stamp,
            ),
            stats,
        )
        decided = optional_instant(r.get("resolved_at")) or instant(r["updatedAt"])
        approver = accounts.get(unwrap(r.get("resolved_by"))) if r.get("resolved_by") else None
        if approver is None:
            stats["approver_not_recorded"] += 1
        employment = approver["employment_id"] if approver else None
        await add_once(
            session,
            CorrectionApprovalAction,
            CorrectionApprovalAction(
                tenant_id=tid,
                id=source_uuid(tid, "correction-action", sid),
                correction_id=request_id,
                action="APPROVE" if status == "APPROVED" else "REJECT",
                level=1,
                approver_employment_id=employment,
                approver_user_account_id=(
                    approver["account_id"] if approver and not employment else None
                ),
                comments=MANUAL_NOTE.get(r.get("resolution_source")),
                actioned_at=decided,
                recorded_at=decided,
            ),
            stats,
        )
        stats["by_status"][status] += 1
        stats["by_type"][kind] += 1
    stats["source_fingerprint"] = hashlib.sha256(source.read_bytes()).hexdigest()
    return tid, stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--company", choices=["suraj", "rabs"], default="suraj")
    parser.add_argument(
        "--decisions", type=Path, help="JSON with {'same': {exim id: employee code}}"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-regularizations.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, stats = await migrate(
                    session, args.tenant, args.data_dir, args.company, args.decisions
                )
                stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
                if args.apply:
                    await session.execute(
                        text("""
                        INSERT INTO import_batches
                          (tenant_id,id,source_system,imported_at,total_records,
                            created_records,updated_records,is_dry_run,details)
                        VALUES (:tid,:id,'EXIM_REGULARIZATIONS',now(),:total,:created,0,
                                false,CAST(:details AS jsonb))
                    """),
                        {
                            "tid": tid,
                            "id": source_uuid(
                                tid, "regularization-batch", datetime.now(UTC).isoformat()
                            ),
                            "total": stats["source_requests"],
                            "created": sum(stats["created"].values()),
                            "details": json.dumps(stats, default=str),
                        },
                    )
                else:
                    await session.rollback()
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(json.dumps(stats, indent=2, default=str))
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
