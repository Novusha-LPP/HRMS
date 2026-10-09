"""Materialize one scoped calculation in bounded batches; page/export stored rows."""

import csv
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from hrms.core import database
from hrms.core.config import settings
from hrms.modules.policy.engine import PolicyResolver
from hrms.modules.time.presence import classify, is_late
from hrms.modules.time.schemas import DailyAnalysisResponse, DailyEmployeeRecord, DailyMetrics


def scope_key(scope) -> str:
    clause, params = scope.employment_filter_sql("e")
    params = {
        k: sorted(map(str, v)) if isinstance(v, (list, set, frozenset)) else v
        for k, v in params.items()
    }
    return hashlib.sha256(
        json.dumps([clause, params], default=str, sort_keys=True).encode()
    ).hexdigest()


class Summary:
    def __init__(self):
        self.metrics = DailyMetrics()
        self.work_minutes = 0
        self.departments: dict[str, dict] = {}
        self.hours = {f"{h:02d}:00": 0 for h in range(7, 20)}

    def add(self, record):
        m = self.metrics
        m.total_headcount += 1
        bucket = classify(
            record.status, record.first_punch_in, on_leave=record.leave_type is not None
        )
        late = bucket == "present" and is_late(record.status, record.late_by_minutes)
        m.present_count += bucket == "present"
        m.late_count += late
        m.absent_count += bucket == "absent"
        m.on_leave_count += bucket == "on_leave"
        m.half_day_count += record.status == "HALF_DAY"
        m.total_overtime_minutes += record.overtime_minutes
        if bucket == "present":
            self.work_minutes += record.effective_minutes
        dept = self.departments.setdefault(
            record.department or "General", dict(total=0, present=0, late=0, absent=0, on_leave=0)
        )
        dept["total"] += 1
        if bucket in {"present", "absent", "on_leave"}:
            dept[bucket] += 1
        dept["late"] += late
        payload = DailyEmployeeRecord(
            **{
                f: getattr(record, f)
                for f in DailyEmployeeRecord.model_fields
                if f != "employment_id"
            },
            employment_id=str(record.employment_id),
        ).model_dump(mode="json")
        # Public typed ids must retain the API contract.
        from hrms.core.ids import to_typed_id

        payload["employment_id"] = to_typed_id("employment", record.employment_id)
        payload["presence_bucket"] = bucket
        payload["is_late"] = bool(late)
        return payload

    def finish(self):
        m = self.metrics
        m.on_time_count = m.present_count - m.late_count
        m.presence_rate = (
            round(m.present_count / m.total_headcount * 100, 1) if m.total_headcount else 0
        )
        m.average_work_minutes = (
            round(self.work_minutes / m.present_count) if m.present_count else 0
        )
        return {
            "metrics": m.model_dump(),
            "department_stats": [
                {
                    "department": name,
                    **values,
                    "presence_rate": round(values["present"] / values["total"] * 100, 1),
                }
                for name, values in sorted(self.departments.items())
            ],
            "hourly_arrivals": [{"hour": h, "count": n} for h, n in self.hours.items()],
        }


async def build_snapshot(tenant_id, user_id, scope, work_date, batch_fn):
    snapshot_id = uuid4()
    generated = datetime.now(UTC)
    summary = Summary()
    deadline = time.monotonic() + settings.daily_report_timeout_seconds
    # A consistent source view across batches; this session uses the same restricted role
    # as the application, including in tests. No source writes occur here.
    async with database.AsyncSessionLocal() as session:
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await session.execute(
            text("SELECT set_config('app.tenant_id',:tid,true)"), {"tid": str(tenant_id)}
        )
        await session.execute(text("SET LOCAL statement_timeout='30s'"))
        await session.execute(
            text(
                "INSERT INTO daily_report_snapshots "
                "VALUES (:tid,:sid,:uid,:key,:day,:now,:expiry,'{}'::jsonb)"
            ),
            dict(
                tid=tenant_id,
                sid=snapshot_id,
                uid=user_id,
                key=scope_key(scope),
                day=work_date,
                now=generated,
                expiry=generated + timedelta(minutes=5),
            ),
        )
        policies = PolicyResolver(session, tenant_id, work_date)
        batch_offset = 0
        while True:
            if time.monotonic() > deadline:
                raise HTTPException(
                    503, "Report generation exceeded capacity; retry with a narrower scope"
                )
            records, hours, count = await batch_fn(
                session, tenant_id, scope, work_date, batch_offset, policies
            )
            if batch_offset + count > settings.daily_report_max_employees:
                raise HTTPException(
                    413, "Report scope exceeds configured capacity; narrow access scope"
                )
            values = [
                dict(
                    tid=tenant_id,
                    sid=snapshot_id,
                    pos=batch_offset + i,
                    data=json.dumps(summary.add(record)),
                )
                for i, record in enumerate(records)
            ]
            if values:
                await session.execute(
                    text(
                        "INSERT INTO daily_report_rows VALUES (:tid,:sid,:pos,CAST(:data AS jsonb))"
                    ),
                    values,
                )
            for hour, n in hours.items():
                summary.hours[hour] += n
            batch_offset += count
            if count < 250:
                break
        await session.execute(
            text(
                "UPDATE daily_report_snapshots SET summary=CAST(:summary AS jsonb) "
                "WHERE tenant_id=:tid AND id=:sid"
            ),
            dict(tid=tenant_id, sid=snapshot_id, summary=json.dumps(summary.finish())),
        )
        await session.commit()
    return snapshot_id


async def checked_snapshot(session, tenant_id, user_id, scope, day, snapshot_id):
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM daily_report_snapshots WHERE tenant_id=:tid "
                    "AND id=:sid AND user_id=:uid AND scope_key=:key AND work_date=:day "
                    "AND expires_at > now()"
                ),
                dict(tid=tenant_id, sid=snapshot_id, uid=user_id, key=scope_key(scope), day=day),
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(409, "Report expired or access changed; refresh the first page")
    return row


def filters(department, status, search):
    clauses = []
    params = {}
    if department:
        clauses.append("lower(payload->>'department')=:department")
        params["department"] = department.lower()
    if search and search.strip():
        clauses.append(
            "(strpos(lower(payload->>'name'),:search)>0 OR "
            "strpos(lower(payload->>'employee_number'),:search)>0)"
        )
        params["search"] = search.strip().lower()
    if status:
        if status.upper() == "PRESENT":
            clauses.append("payload->>'presence_bucket'='present'")
        elif status.upper() == "NEEDS_REVIEW":
            clauses.append("payload->>'needs_review'='true'")
        elif status.upper() == "LATE":
            clauses.append("payload->>'is_late'='true'")
        else:
            clauses.append("upper(payload->>'status')=:status")
            params["status"] = status.upper()
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


async def read_snapshot(
    session,
    tenant_id,
    user_id,
    scope,
    day,
    department,
    status,
    search,
    limit,
    offset,
    snapshot_id,
    batch_fn,
):
    if snapshot_id is None:
        # Avoid duplicate heavy calculations for one account; fail fast instead of queuing.
        lock_key = f"daily-report:{tenant_id}:{user_id}"
        locked = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": lock_key},
            )
        ).scalar()
        if not locked:
            raise HTTPException(429, "Another report is being generated; retry shortly")
        if offset:
            snapshot_id = (
                await session.execute(
                    text(
                        "SELECT id FROM daily_report_snapshots "
                        "WHERE tenant_id=:tid AND user_id=:uid "
                        "AND scope_key=:key AND work_date=:day "
                        "AND expires_at>now() ORDER BY generated_at DESC LIMIT 1"
                    ),
                    dict(tid=tenant_id, uid=user_id, key=scope_key(scope), day=day),
                )
            ).scalar()
        if snapshot_id is None:
            snapshot_id = await build_snapshot(tenant_id, user_id, scope, day, batch_fn)
        # At most two retained snapshots per user, and no expired rows for this user.
        await session.execute(
            text(
                "DELETE FROM daily_report_snapshots WHERE tenant_id=:tid AND user_id=:uid "
                "AND (expires_at<=now() OR id NOT IN (SELECT id FROM daily_report_snapshots "
                "WHERE tenant_id=:tid AND user_id=:uid ORDER BY generated_at DESC LIMIT 2))"
            ),
            dict(tid=tenant_id, uid=user_id),
        )
    row = await checked_snapshot(session, tenant_id, user_id, scope, day, snapshot_id)
    clause, params = filters(department, status, search)
    params.update(tid=tenant_id, sid=snapshot_id)
    base = " FROM daily_report_rows WHERE tenant_id=:tid AND snapshot_id=:sid" + clause
    total = (await session.execute(text("SELECT count(*)" + base), params)).scalar_one()
    records = (
        (
            await session.execute(
                text("SELECT payload" + base + " ORDER BY position LIMIT :lim OFFSET :off"),
                {**params, "lim": limit, "off": offset},
            )
        )
        .scalars()
        .all()
    )
    return DailyAnalysisResponse(
        snapshot_id=snapshot_id,
        generated_at=row["generated_at"],
        total_filtered=total,
        work_date=day,
        **row["summary"],
        employees=records,
    )


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value  # Prevent employee-controlled spreadsheet formulas.
    return value


async def export_snapshot(
    session, tenant_id, user_id, scope, day, department, status, search, snapshot_id
):
    await checked_snapshot(session, tenant_id, user_id, scope, day, snapshot_id)
    clause, params = filters(department, status, search)
    params.update(tid=tenant_id, sid=snapshot_id)
    fd, name = tempfile.mkstemp(prefix="hrms-report-", suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            fields = [
                "employee_number",
                "name",
                "email",
                "department",
                "designation",
                "status",
                "first_punch_in",
                "last_punch_out",
                "effective_minutes",
                "gross_minutes",
                "break_minutes",
                "late_by_minutes",
                "early_departure_minutes",
                "overtime_minutes",
                "comp_off_days",
                "needs_review",
                "leave_type",
                "punches_count",
            ]
            writer.writerow(["Work Date", *fields])
            result = await session.stream(
                text(
                    "SELECT payload FROM daily_report_rows "
                    "WHERE tenant_id=:tid AND snapshot_id=:sid" + clause + " ORDER BY position"
                ),
                params,
                execution_options={"yield_per": 250},
            )
            async for payload in result.scalars():
                writer.writerow([str(day), *(csv_cell(payload.get(f)) for f in fields)])
            await result.close()
        return FileResponse(
            name,
            media_type="text/csv",
            filename=f"daily-analysis-{day}.csv",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(Path(name).unlink, missing_ok=True),
        )
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
