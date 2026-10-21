"""Import the EXIM leave history (applications, approval trail, balances) through the HRMS engine.

Follows migrate_exim_punch_history.py: dry-run by default (every employee's transaction is
rolled back), one transaction per employee, deterministic ids and an "already imported" check
so a re-run changes nothing, exact EXIM employee links, RABS deferred.

What is imported (Suraj Group only):
  * every application as a leave application on the imported leave type (privilege ->
    EXIMPL, leave without pay -> EXIMLWP), with its status, levels and approval trail;
  * the ledger for the paid type, posted with the leave engine's own record_transaction:
      OPENING (opening + carried forward)  ->  HOLD / LEAVE_TAKEN for each approved application
      HOLD for each pending application (a pending leave holds balance until decided)
    Rejected and cancelled applications net to zero and post nothing;
  * one ADJUSTMENT ("Legacy import: reconciled to the old system's balance") when the history
    above does not reproduce the old system's closing balance, so people see the balance they had.
Leave without pay is unpaid and unlimited: it keeps its applications but has no balance.

Run from backend:
  .venv/bin/python scripts/migrate_exim_leave_history.py --tenant suraj-group
Add --apply to commit.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import exim_scope
from migrate_legacy_attendance import add_once, instant, source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import select

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core.config import settings
from hrms.core.locking import lock_resource
from hrms.modules.leave.engine import record_transaction
from hrms.modules.leave.models import (
    LeaveApplication,
    LeaveApprovalAction,
    LeaveBalanceTransaction,
    LeaveMonthlyLedger,
    LeaveTransactionType,
)
from hrms.modules.leave.policy_resolver import resolve_employee_fy_start_month

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = UUID(int=0)  # the tenant's system account
OPENING_DATE = date(2026, 1, 1)
RECONCILE_DATE = date(2026, 10, 1)
MARKER = "Legacy import:"  # the reason prefix on entries this import posts without an application
ALIAS = {"suraj forwarders": "suraj forwarders private limited"}


def num(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            if key.startswith("$number"):
                return float(inner)
        raise ValueError(f"Unsupported number: {value}")
    return float(value or 0)


def allocate(start, end, total):
    """Split the days charged across the calendar months touched (halves, remainder first)."""
    months = Counter()
    day = start
    while day <= end:
        months[f"{day.year:04d}-{day.month:02d}"] += 1
        day += timedelta(days=1)
    if len(months) == 1:
        return {next(iter(months)): total}
    span = sum(months.values())
    out = {k: round(total * v / span * 2) / 2 for k, v in months.items()}
    first = next(iter(out))
    out[first] = round((out[first] + total - sum(out.values())) * 2) / 2
    return {k: v for k, v in out.items() if v > 0}


async def prepare(session, tenant_ref, data_dir, company="suraj", decisions=None):
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
        "source_applications": 0,
        "skipped": Counter(),
        "other_company_applications": 0,
        "type_by_leave_type_fallback": 0,
        "created": Counter(),
        "existing": Counter(),
        "applications_by_status": Counter(),
        "cross_month_applications": 0,
        "half_day_session_defaulted": 0,
        "approver_unresolved": 0,
        "ledger_posted": Counter(),
        "ledger_already_imported_employees": 0,
        "paid_without_balance_record": 0,
        "balance_records_used": 0,
        "balance_records_skipped": Counter(),
        "reconciliation_adjustments": 0,
        "reconciliation_total": 0.0,
        "reconciliation_largest": 0.0,
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
    links = {k: v for k, v in accounts.items() if v["employment_id"] is not None}
    links.update(await exim_scope.decided_links(session, tid, decisions))
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
    policy_types = {}
    rows = (
        (
            await session.execute(
                text("""
        SELECT bp.source_policy->'_id'->>'$oid' AS pid,
               bp.source_policy->>'leave_type' AS source_type,
               bp.source_policy->>'status' AS source_status,
               lt.id, lt.code, lt.is_paid, m.bucket_id, b.is_unlimited
        FROM leave_bucket_policies bp
        JOIN leave_type_bucket_mapping m
          ON m.tenant_id = bp.tenant_id AND m.bucket_id = bp.bucket_id
        JOIN leave_types lt
          ON lt.tenant_id = m.tenant_id AND lt.id = m.leave_type_id AND lt.archived_at IS NULL
        JOIN leave_balance_buckets b ON b.tenant_id = m.tenant_id AND b.id = m.bucket_id
        WHERE bp.tenant_id = :tid AND bp.source_policy IS NOT NULL
    """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        policy_types.setdefault(row["pid"], dict(row))
    if not policy_types:
        raise ValueError("No imported leave policies found; import the leave policies first")
    types = {info["code"]: info for info in policy_types.values()}
    active_by_type = {}
    for info in policy_types.values():
        if info["source_status"] == "active":
            active_by_type.setdefault(info["source_type"], info)
    entity_for, other_company = exim_scope.build(company, entities, ALIAS)

    def actor(erp_id):
        row = accounts.get(erp_id)
        if row is None:
            stats["approver_unresolved"] += 1
            return None, None
        return row["employment_id"], row["account_id"]

    per_employee = {}
    for a in json.loads((data_dir / "exim.leaveapplications.json").read_text()):
        stats["source_applications"] += 1
        sid, uid = unwrap(a["_id"]), unwrap(a["employee_id"])
        user = users.get(uid)
        if user is None:
            stats["skipped"]["source user missing"] += 1
            continue
        if other_company(user):
            stats["other_company_applications"] += 1
            continue
        if uid not in links:
            stats["skipped"]["no HRMS employee link"] += 1
            continue
        if entity_for(user) != links[uid]["legal_entity_id"]:
            stats["skipped"]["company differs from the linked employee"] += 1
            continue
        info = policy_types.get(unwrap(a.get("leave_policy_id")))
        if info is None:
            # The application's own policy was not imported: use the active policy of the same
            # old leave type, so the application still lands on the right leave type.
            info = active_by_type.get(a["leave_type"])
            if info is not None:
                stats["type_by_leave_type_fallback"] += 1
        if info is None:
            stats["skipped"]["leave policy not imported"] += 1
            continue
        code = info["code"]
        start = instant(a["from_date"]).astimezone(UTC).date()
        end = instant(a["to_date"]).astimezone(UTC).date()
        start = date.fromisoformat(a["from_date_str"]) if a.get("from_date_str") else start
        end = date.fromisoformat(a["to_date_str"]) if a.get("to_date_str") else end
        total = num(a["total_days"])
        chain = a.get("approval_chain") or []
        levels = min(3, max(1, len(chain)))
        approved = [c for c in chain if c.get("action") == "approved"]
        status = a["approval_status"]
        if status == "approved":
            new_status, level = "APPROVED", levels
        elif status == "rejected":
            rejected = next((c for c in chain if c.get("action") == "rejected"), None)
            new_status, level = "REJECTED", int(rejected["level"]) if rejected else 1
        elif status == "pending":
            level = min(levels, len(approved) + 1)
            new_status = f"PENDING_L{level}"
        elif status == "cancelled":
            new_status, level = "CANCELLED", max(1, min(levels, len(approved)))
        else:
            stats["skipped"][f"unsupported status {status}"] += 1
            continue
        half = "NONE"
        if start == end and a.get("is_half_day"):
            session_name = (a.get("half_day_session") or "").lower().replace(" ", "_")
            half = {"first_half": "FIRST_HALF", "second_half": "SECOND_HALF"}.get(session_name)
            if half is None:
                half = "FIRST_HALF"
                stats["half_day_session_defaulted"] += 1
        by_month = allocate(start, end, total)
        if len(by_month) > 1:
            stats["cross_month_applications"] += 1
        actions = []
        for index, c in enumerate(chain, start=1):
            if c.get("action") not in {"approved", "rejected"}:
                continue
            emp, acct = actor(unwrap(c.get("approver_id")))
            lvl = int(c.get("level") or index)
            comment = None
            if c["action"] == "rejected":
                comment = a.get("rejection_reason")
            elif lvl == 1:
                comment = a.get("hod_review_comment")
            elif lvl == levels:
                comment = a.get("final_review_comment")
            actions.append(
                {
                    "id": source_uuid(tid, "leave-action", f"{sid}:{lvl}:{c['action']}"),
                    "type": "APPROVE" if c["action"] == "approved" else "REJECT",
                    "level": lvl,
                    "emp": emp,
                    "acct": acct if emp is None else None,
                    "comment": (comment or None) and comment[:1000],
                    "at": instant(c["action_date"])
                    if c.get("action_date")
                    else instant(a["updatedAt"]),
                }
            )
        if status == "cancelled" and a.get("cancelled_at"):
            emp, acct = actor(unwrap(a.get("cancelled_by")))
            actions.append(
                {
                    "id": source_uuid(tid, "leave-action", f"{sid}:cancel"),
                    "type": "CANCEL_APPROVE",
                    "level": 1,
                    "emp": emp,
                    "acct": acct if emp is None else None,
                    "comment": (a.get("cancellation_reason") or None)
                    and a["cancellation_reason"][:1000],
                    "at": instant(a["cancelled_at"]),
                }
            )
        eid = links[uid]["employment_id"]
        per_employee.setdefault(eid, {"apps": [], "balances": {}, "uid": uid})["apps"].append(
            {
                "sid": sid,
                "code": code,
                "from": start,
                "to": end,
                "total": total,
                "by_month": by_month,
                "half": half,
                "reason": (a.get("reason") or None) and a["reason"][:1000],
                "status": new_status,
                "source_status": status,
                "level": level,
                "levels": levels,
                "applied_at": instant(a["applied_on"]),
                "created": instant(a["createdAt"]),
                "cancel_reason": (a.get("cancellation_reason") or None)
                and a["cancellation_reason"][:1000],
                "actions": actions,
                "final_approver": next((x["acct"] for x in reversed(actions) if x["acct"]), None),
            }
        )
        stats["applications_by_status"][new_status.split("_L")[0]] += 1

    for b in json.loads((data_dir / "exim.leavebalances.json").read_text()):
        uid = unwrap(b["employee_id"])
        user = users.get(uid)
        if user is None or other_company(user) or uid not in links or b["year"] != 2026:
            stats["balance_records_skipped"]["not in scope / not linked / not 2026"] += 1
            continue
        info = policy_types.get(unwrap(b.get("leave_policy_id"))) or active_by_type.get(
            b["leave_type"]
        )
        if info is None:
            stats["balance_records_skipped"]["leave policy not imported"] += 1
            continue
        if info["is_unlimited"] or not info["is_paid"]:
            stats["balance_records_skipped"][f"{b['leave_type']} (no balance kept)"] += 1
            continue
        eid = links[uid]["employment_id"]
        entry = per_employee.setdefault(eid, {"apps": [], "balances": {}, "uid": uid})
        # Two old records for the same bucket: keep the one under an active policy, then the
        # most recently updated, so the choice does not depend on file order.
        rank = (info["source_status"] == "active", str(instant(b["updatedAt"])))
        kept = entry["balances"].get(info["bucket_id"])
        if kept is not None:
            stats["balance_records_skipped"]["duplicate balance for the same bucket"] += 1
            if rank <= kept["rank"]:
                continue
        else:
            stats["balance_records_used"] += 1
        entry["balances"][info["bucket_id"]] = {
            "opening": num(b["opening_balance"]) + num(b["carried_forward"]),
            "closing": num(b["closing_balance"]),
            "code": info["code"],
            "rank": rank,
        }
    for name in ("exim.leaveapplications.json", "exim.leavebalances.json"):
        stats.setdefault("source_fingerprints", {})[name] = hashlib.sha256(
            (data_dir / name).read_bytes()
        ).hexdigest()
    return tid, per_employee, types, stats


async def post(
    session, tid, eid, bucket_id, lt_id, fy, kind, qty, when, *, ref=None, by=None, why=None
):
    await record_transaction(
        session,
        tid,
        employment_id=eid,
        bucket_id=bucket_id,
        leave_type_id=lt_id,
        transaction_type=kind,
        quantity=qty,
        effective_date=when,
        reason=why,
        reference_id=ref,
        reference_type="LEAVE_APPLICATION" if ref else "MANUAL",
        recorded_by=SYSTEM,
        approved_by=by,
        fy_start_month=fy,
    )


async def import_employee(session, tid, eid, entry, types, stats):
    await lock_resource(session, tid, "EXIM-leave-history-import")
    for app in entry["apps"]:
        lt = types[app["code"]]
        sid = app["sid"]
        row = LeaveApplication(
            tenant_id=tid,
            id=source_uuid(tid, "leaveapplications", sid),
            employment_id=eid,
            leave_type_id=lt["id"],
            from_date=app["from"],
            to_date=app["to"],
            days_by_month=app["by_month"],
            days_requested=app["total"],
            half_day_option=app["half"],
            reason=app["reason"],
            status=app["status"],
            current_level=app["level"],
            total_levels=app["levels"],
            applied_at=app["applied_at"],
            cancel_reason=app["cancel_reason"],
            recorded_at=app["created"],
        )
        await add_once(session, LeaveApplication, row, stats)
        for act in app["actions"]:
            await add_once(
                session,
                LeaveApprovalAction,
                LeaveApprovalAction(
                    tenant_id=tid,
                    id=act["id"],
                    application_id=row.id,
                    action_type=act["type"],
                    level=act["level"],
                    approver_employment_id=act["emp"],
                    approver_user_account_id=act["acct"],
                    comments=act["comment"],
                    actioned_at=act["at"],
                    recorded_at=act["at"],
                ),
                stats,
            )

    # Ledger: one pass per paid, tracked bucket the employee has applications or a balance in.
    fy = None
    buckets = {}
    for app in entry["apps"]:
        buckets.setdefault(types[app["code"]]["bucket_id"], types[app["code"]])
    for bucket_id, balance in entry["balances"].items():
        buckets.setdefault(bucket_id, types[balance["code"]])
    for bucket, paid in buckets.items():
        if not (paid["is_paid"] and bucket) or paid["is_unlimited"]:
            continue
        done = (
            await session.execute(
                select(LeaveBalanceTransaction.id)
                .where(LeaveBalanceTransaction.tenant_id == tid)
                .where(LeaveBalanceTransaction.employment_id == eid)
                .where(LeaveBalanceTransaction.bucket_id == bucket)
                .where(LeaveBalanceTransaction.reference_type == "MANUAL")
                .where(LeaveBalanceTransaction.reason.like(f"{MARKER}%"))
                .limit(1)
            )
        ).first()
        if done:
            stats["ledger_already_imported_employees"] += 1
            continue
        fy = fy or await resolve_employee_fy_start_month(session, tid, eid)
        paid_apps = sorted(
            (a for a in entry["apps"] if types[a["code"]]["bucket_id"] == bucket),
            key=lambda a: (a["from"], a["sid"]),
        )
        balance = entry["balances"].get(bucket)
        if balance is None and not paid_apps:
            continue
        if balance is None:
            stats["paid_without_balance_record"] += 1
        else:
            await post(
                session,
                tid,
                eid,
                bucket,
                paid["id"],
                fy,
                LeaveTransactionType.OPENING,
                balance["opening"],
                OPENING_DATE,
                why=f"{MARKER} opening balance carried over",
            )
            stats["ledger_posted"]["OPENING"] += 1
        for app in paid_apps:
            if app["source_status"] not in {"approved", "pending"}:
                continue  # rejected and cancelled leave nets to zero
            ref = source_uuid(tid, "leaveapplications", app["sid"])
            for period, days in sorted(app["by_month"].items()):
                when = date(int(period[:4]), int(period[5:7]), 1)
                await post(
                    session,
                    tid,
                    eid,
                    bucket,
                    paid["id"],
                    fy,
                    LeaveTransactionType.HOLD,
                    days,
                    when,
                    ref=ref,
                )
                stats["ledger_posted"]["HOLD"] += 1
                if app["source_status"] == "approved":
                    await post(
                        session,
                        tid,
                        eid,
                        bucket,
                        paid["id"],
                        fy,
                        LeaveTransactionType.LEAVE_TAKEN,
                        days,
                        when,
                        ref=ref,
                        by=app["final_approver"],
                    )
                    stats["ledger_posted"]["LEAVE_TAKEN"] += 1
        if balance is None:
            continue
        latest = (
            (
                await session.execute(
                    select(LeaveMonthlyLedger)
                    .where(LeaveMonthlyLedger.tenant_id == tid)
                    .where(LeaveMonthlyLedger.employment_id == eid)
                    .where(LeaveMonthlyLedger.bucket_id == bucket)
                    .order_by(
                        LeaveMonthlyLedger.calendar_year.desc(),
                        LeaveMonthlyLedger.calendar_month.desc(),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        available = (latest.closing - latest.held) if latest else 0.0
        diff = round(balance["closing"] - available, 4)
        if abs(diff) > 0.001:
            await post(
                session,
                tid,
                eid,
                bucket,
                paid["id"],
                fy,
                LeaveTransactionType.ADJUSTMENT,
                diff,
                RECONCILE_DATE,
                why=f"{MARKER} reconciled to the old system's balance",
            )
            stats["ledger_posted"]["ADJUSTMENT"] += 1
            stats["reconciliation_adjustments"] += 1
            stats["reconciliation_total"] = round(stats["reconciliation_total"] + diff, 4)
            stats["reconciliation_largest"] = max(stats["reconciliation_largest"], abs(diff))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--company", choices=["suraj", "rabs"], default="suraj")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-leave-history.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, per_employee, types, stats = await prepare(
                    session, args.tenant, args.data_dir, args.company, args.decisions
                )
            stats["employees"] = len(per_employee)
            for eid, entry in sorted(per_employee.items(), key=lambda kv: str(kv[0])):
                async with session.begin():
                    await import_employee(session, tid, eid, entry, types, stats)
                    if not args.apply:
                        await session.rollback()
            stats["mode"] = "APPLIED" if args.apply else "DRY_RUN_ROLLED_BACK"
            if args.apply:
                async with session.begin():
                    await session.execute(
                        text("""
                        INSERT INTO import_batches
                          (tenant_id,id,source_system,imported_at,total_records,
                            created_records,updated_records,is_dry_run,details)
                        VALUES (:tid,:id,'EXIM_LEAVE_HISTORY',now(),:total,:created,0,
                                false,CAST(:details AS jsonb))
                    """),
                        {
                            "tid": tid,
                            "id": source_uuid(
                                tid, "leave-history-batch", datetime.now(UTC).isoformat()
                            ),
                            "total": stats["source_applications"],
                            "created": sum(stats["created"].values()),
                            "details": json.dumps(stats, default=str),
                        },
                    )
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            print(json.dumps(stats, indent=2, default=str))
            print(f"Report: {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
