"""Attendance, approved leave and ledger reporting without changing source records."""

import calendar
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from hrms.core.authz import Scope, read_scope
from hrms.core.datetime_utils import business_today, is_working_day
from hrms.core.ids import to_typed_id, to_uuid
from hrms.modules.policy.engine import PolicyResolver
from hrms.modules.reports.attendance_schemas import (
    AttendanceSummaryCompany,
    AttendanceSummaryDay,
    AttendanceSummaryEmployee,
    AttendanceSummaryMetrics,
    AttendanceSummaryReport,
    AttendanceSummaryTotals,
)
from hrms.modules.time.holidays import holiday_scope_sql
from hrms.modules.time.presence import classify

MAX_EMPLOYEES = 1000
MAX_RANGE_DAYS = 62
MAX_SOURCE_ROWS = 100_000


class ReportPolicyResolver(PolicyResolver):
    """Keep the resolved template's display name alongside the unchanged policy figures."""

    def __init__(self, session, tenant_id, work_date):
        super().__init__(session, tenant_id, work_date)
        self._shift_names: dict[int, str] = {}

    async def _load(self):
        await super()._load()
        for template in self._templates.values():
            if template.is_default and template.archived_at is None:
                self._shift_names[id(self._default)] = template.name

    def _resolved(self, assignment):
        policy = super()._resolved(assignment)
        if assignment and assignment.policy_template_id in self._templates:
            self._shift_names[id(policy)] = self._templates[assignment.policy_template_id].name
        return policy

    def shift_name(self, policy):
        return self._shift_names.get(id(policy))


_PEOPLE_SQL = """
    SELECT e.id, e.employee_number, e.legal_entity_id, le.name AS company,
           e.hire_date, e.separation_date,
           p.legal_first_name || ' ' || p.legal_last_name AS name,
           CASE WHEN ou.type = 'TEAM' THEN parent.id ELSE ou.id END AS department_id,
           CASE WHEN ou.type = 'TEAM' THEN parent.name ELSE ou.name END AS department
    FROM employments e
    JOIN persons p ON p.tenant_id=e.tenant_id AND p.id=e.person_id
    JOIN legal_entities le ON le.tenant_id=e.tenant_id AND le.id=e.legal_entity_id
    LEFT JOIN LATERAL (
        SELECT a.org_unit_id FROM assignments a
        WHERE a.tenant_id=e.tenant_id AND a.employment_id=e.id
          AND a.effective_from <= LEAST(:last, COALESCE(e.separation_date,:last))
          AND (a.effective_to IS NULL OR a.effective_to >
               LEAST(:last, COALESCE(e.separation_date,:last)))
        ORDER BY a.effective_from DESC, a.recorded_at DESC, a.id LIMIT 1
    ) a ON TRUE
    LEFT JOIN org_units ou ON ou.tenant_id=e.tenant_id AND ou.id=a.org_unit_id
    LEFT JOIN org_units parent ON parent.tenant_id=ou.tenant_id AND parent.id=ou.parent_id
    WHERE e.tenant_id=:tid AND e.archived_at IS NULL
      AND e.hire_date<=:last AND (e.separation_date IS NULL OR e.separation_date>=:first)
"""


def validate_period(first: date, last: date) -> None:
    if last < first or (last - first).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, f"Choose a range of 1 to {MAX_RANGE_DAYS} days")


def is_privilege_leave(code: str, name: str, is_paid: bool, is_comp_off: bool = False) -> bool:
    """PL is a named entitlement; casual/sick/comp-off are never relabelled PL."""
    if not is_paid or is_comp_off:
        return False
    code = code.upper()
    return (
        code in {"PL", "EXIMPL"}
        or re.fullmatch(r"EXPL[0-9A-F]{6}", code) is not None
        or "privilege leave" in name.casefold()
        or "privileged leave" in name.casefold()
    )


def _month_keys(first: date, last: date) -> list[tuple[int, int]]:
    keys = []
    month = first.replace(day=1)
    while month <= last:
        keys.append((month.year, month.month))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return keys


def _full_months(first: date, last: date) -> bool:
    return first.day == 1 and last.day == calendar.monthrange(last.year, last.month)[1]


def summarize_days(days: list[AttendanceSummaryDay]) -> AttendanceSummaryMetrics:
    m = AttendanceSummaryMetrics()
    for day in days:
        bucket = classify(day.status, day.first_punch_in, day.leave_type is not None)
        leave_days = day.paid_leave_days + day.lwp_days + day.other_leave_days
        present = 0.5 if day.status == "HALF_DAY" else 1.0
        if bucket == "present":
            present = min(present, max(0, 1 - leave_days))
            m.present_days += present
            m.worked_days += 1
        else:
            present = 0
        if (
            day.is_working_day
            and day.status != "UPCOMING"
            and day.work_date <= business_today(day.timezone)
            and (bucket in {"present", "absent"} or (bucket == "on_leave" and leave_days > 0))
        ):
            m.absent_days += max(0, 1 - present - leave_days)
        m.half_day_pl += day.half_day_pl
        m.full_day_pl += day.full_day_pl
        m.total_pl_taken += day.paid_leave_days
        m.lwp_taken += day.lwp_days
        m.other_leave_days += day.other_leave_days
        m.week_off_days += day.status == "WEEKEND" and bucket != "present" and not leave_days
        m.holiday_days += day.status == "HOLIDAY" and bucket != "present" and not leave_days
        m.total_work_minutes += day.effective_minutes
        m.late_days += day.late_by_minutes > 0 or day.status == "LATE"
        m.early_departure_days += day.early_departure_minutes > 0
    # The reference calls paid-equivalent days "Total Working Days": weekly off,
    # holiday and paid leave are included; absence and LWP are excluded.
    m.total_working_days = (
        m.present_days + m.total_pl_taken + m.other_leave_days + m.week_off_days + m.holiday_days
    )
    if m.worked_days:
        m.average_hours_per_day = round(m.total_work_minutes / m.worked_days / 60, 4)
    return m


def aggregate_metrics(employees: list[AttendanceSummaryEmployee]) -> AttendanceSummaryMetrics:
    m = AttendanceSummaryMetrics()
    additive = set(AttendanceSummaryMetrics.model_fields) - {
        "opening_balance",
        "pl_taken",
        "available_balance",
        "average_hours_per_day",
    }
    for field in additive:
        setattr(m, field, sum(getattr(e, field) for e in employees))
    # A partial balance total is misleading: all participating employees must have a source.
    for field in ("opening_balance", "pl_taken", "available_balance"):
        values = [getattr(e, field) for e in employees]
        if values and all(v is not None for v in values):
            setattr(m, field, round(sum(v for v in values if v is not None), 4))
    if m.worked_days:
        m.average_hours_per_day = round(m.total_work_minutes / m.worked_days / 60, 4)
    return m


def leave_covers_date(row, day, working, holiday):
    """Keep explicit calendar-day/sandwich allocations recorded on approved requests.

    Native requests normally exclude rest days. Imported or explicitly allocated requests
    whose stored monthly quantity covers every calendar date must keep those rest days.
    """
    if not row["from_date"] <= day <= row["to_date"]:
        return False
    allocation = row.get("days_by_month") or {}
    stored = allocation.get(f"{day.year:04d}-{day.month:02d}")
    month_first = max(row["from_date"], day.replace(day=1))
    month_last = min(row["to_date"], day.replace(day=calendar.monthrange(day.year, day.month)[1]))
    weight = 0.5 if row["half_day_option"] != "NONE" else 1
    calendar_quantity = ((month_last - month_first).days + 1) * weight
    if stored is not None and abs(float(stored) - calendar_quantity) < 0.0001:
        return True
    return working and not holiday


async def _rows(session, sql, params):
    rows = (await session.execute(text(sql), params)).mappings().all()
    if len(rows) > MAX_SOURCE_ROWS:
        raise HTTPException(
            422,
            "This report is too large. Narrow the dates, employee, department or location filters.",
        )
    return rows


async def report_people(
    session,
    tenant_id,
    scope,
    first,
    last,
    entity=None,
    department=None,
    search="",
    limit=MAX_EMPLOYEES,
    population_filters=None,
):
    clause, params = scope.for_permission("reports.read").employment_filter_sql("e")
    selection, selection_params = population_filter_sql(population_filters or [])
    clause = f"{clause} {selection}"
    params.update(selection_params)
    conditions = ""
    if entity:
        conditions += " AND legal_entity_id=:entity"
        params["entity"] = to_uuid(entity)
    if department:
        conditions += " AND department_id=:department"
        params["department"] = to_uuid(department)
    rows = await _rows(
        session,
        f"""
        SELECT * FROM ({_PEOPLE_SQL} {clause}) people
        WHERE (:search='' OR strpos(lower(name),:search)>0
            OR strpos(lower(employee_number),:search)>0) {conditions}
        ORDER BY company,name,id LIMIT :limit
    """,
        dict(
            tid=tenant_id,
            first=first,
            last=last,
            search=search.strip().lower(),
            limit=limit + 1,
            **params,
        ),
    )
    if len(rows) > limit:
        raise HTTPException(
            422,
            f"More than {limit} employees match. "
            "Narrow the employee, department or location filters.",
        )
    return rows


def population_filter_sql(filters: list[dict]) -> tuple[str, dict]:
    """Select people using every constraint on the same effective assignment slice.

    Department/location select employees assigned there during the period. The calendar
    subsequently retains only dates matching the same assignment constraints.
    The report router validates operators and value types before calling this helper.
    """
    direct, assignment = [], []
    params = {}
    for index, spec in enumerate(filters):
        field, value = spec["field"], spec["value"]
        if field == "employment_id":
            key = f"export_employee_{index}"
            direct.append(f"AND e.id=CAST(:{key} AS uuid)")
            params[key] = str(to_uuid(value))
        elif field in {"department", "location"}:
            values = value if isinstance(value, list) else [value]
            keys = [f"export_{field}_{index}_{i}" for i in range(len(values))]
            column = "filter_unit.name" if field == "department" else "filter_location.name"
            assignment.append(f"{column} IN ({', '.join(':' + key for key in keys)})")
            params.update(zip(keys, values, strict=True))
        else:
            raise HTTPException(422, "Remove unsupported filters before exporting the register")
    if assignment:
        direct.append(
            """AND EXISTS (
            SELECT 1 FROM assignments filter_assignment
            LEFT JOIN org_units filter_unit ON filter_unit.tenant_id=filter_assignment.tenant_id
              AND filter_unit.id=filter_assignment.org_unit_id
            LEFT JOIN locations filter_location
              ON filter_location.tenant_id=filter_assignment.tenant_id
              AND filter_location.id=filter_assignment.location_id
            WHERE filter_assignment.tenant_id=e.tenant_id AND filter_assignment.employment_id=e.id
              AND filter_assignment.effective_from<=LEAST(:last,COALESCE(e.separation_date,:last))
              AND (filter_assignment.effective_to IS NULL
                   OR filter_assignment.effective_to>GREATEST(:first,e.hire_date))
              AND """
            + " AND ".join(assignment)
            + ")"
        )
    return " ".join(direct), params


def day_matches_population_filters(filters, assignment) -> bool:
    for spec in filters:
        if spec["field"] not in {"department", "location"}:
            continue
        values = spec["value"] if isinstance(spec["value"], list) else [spec["value"]]
        key = "assignment_unit_name" if spec["field"] == "department" else "location_name"
        if assignment is None or assignment[key] not in values:
            return False
    return True


async def build_attendance_summary(
    session,
    tenant_id: UUID,
    scope: Scope,
    first: date,
    last: date,
    legal_entity_id: str | None = None,
    department_id: str | None = None,
    search: str = "",
    population_filters: list[dict] | None = None,
) -> AttendanceSummaryReport:
    validate_period(first, last)
    people = await report_people(
        session,
        tenant_id,
        scope,
        first,
        last,
        legal_entity_id,
        department_id,
        search,
        population_filters=population_filters,
    )
    params = dict(
        tid=tenant_id,
        first=first,
        last=last,
        ids=[str(p["id"]) for p in people],
        cap=MAX_SOURCE_ROWS + 1,
    )
    notes = [
        "Source attendance and leave records are read without changing them.",
        "Present is a day quantity: recorded half days count 0.5. Approved leave quantities "
        "are retained separately, and half-day PL shows occurrences.",
        "Total Working Days follows the reference's paid-day convention: present + paid leave "
        "+ weekly off + holiday. Absence and LWP are excluded.",
        "Daily work schedules follow each dated policy and applicable holiday calendar. "
        "Average hours/day is recorded work time divided by dates with recorded presence, "
        "including half days as one worked date.",
        "PL means an explicit Privilege Leave entitlement. "
        "Other paid leave is retained separately.",
        "Recorded leave without a matching dated approved application retains its recorded "
        "status; a PL/LWP quantity or absence is not inferred from that status alone.",
        "Approved monthly allocations covering every calendar date retain weekly off/holiday "
        "leave deductions (including sandwich leave). Other leave follows the dated work schedule.",
        "Opening, ledger PL taken and available balances are shown for complete calendar months "
        "where a PL ledger exists and leave access is granted. Missing values are not zero.",
        "Department and location filters include only dates with a matching effective assignment. "
        "Attendance and leave totals summarize those included dates. PL ledger balances cover "
        "the complete calendar month, including any dates outside those assignment filters.",
        "With department or location filters, the employee summary department follows the last "
        "included date rather than an assignment outside those filtered dates.",
    ]
    if not people:
        return AttendanceSummaryReport(
            from_date=first,
            to_date=last,
            generated_at=datetime.now(UTC),
            employees=[],
            companies=[],
            totals=AttendanceSummaryTotals(),
            notes=notes,
        )
    attendance = await _rows(
        session,
        """
        SELECT * FROM attendance_days WHERE tenant_id=:tid
          AND employment_id=ANY(CAST(:ids AS uuid[]))
          AND work_date BETWEEN :first AND :last LIMIT :cap
    """,
        params,
    )
    assignments = await _rows(
        session,
        """
        SELECT a.employment_id,a.org_unit_id,a.effective_from,a.effective_to,
          ou.name AS assignment_unit_name, location.name AS location_name,
          CASE WHEN ou.type='TEAM' THEN parent.id ELSE ou.id END AS department_id,
          CASE WHEN ou.type='TEAM' THEN parent.name ELSE ou.name END AS department
        FROM assignments a
        LEFT JOIN org_units ou ON ou.tenant_id=a.tenant_id AND ou.id=a.org_unit_id
        LEFT JOIN org_units parent ON parent.tenant_id=ou.tenant_id AND parent.id=ou.parent_id
        LEFT JOIN locations location ON location.tenant_id=a.tenant_id AND location.id=a.location_id
        WHERE a.tenant_id=:tid AND a.employment_id=ANY(CAST(:ids AS uuid[]))
          AND a.effective_from<=:last AND (a.effective_to IS NULL OR a.effective_to>:first)
        ORDER BY a.effective_from DESC,a.recorded_at DESC,a.id LIMIT :cap
    """,
        params,
    )
    holidays = await _rows(
        session,
        f"""
        SELECT e.id AS employment_id,h.holiday_date,h.name
        FROM employments e JOIN holidays h ON h.tenant_id=e.tenant_id
        WHERE e.tenant_id=:tid AND e.id=ANY(CAST(:ids AS uuid[]))
          AND h.holiday_date BETWEEN :first AND :last
          AND h.archived_at IS NULL AND NOT h.is_optional
          AND {holiday_scope_sql(employee="e.id")} LIMIT :cap
    """,
        params,
    )
    leaves = await _rows(
        session,
        """
        SELECT la.employment_id,la.from_date,la.to_date,la.half_day_option,la.days_by_month,
               lt.name,lt.code,lt.is_paid,lt.is_comp_off
        FROM leave_applications la JOIN leave_types lt
          ON lt.tenant_id=la.tenant_id AND lt.id=la.leave_type_id
        WHERE la.tenant_id=:tid AND la.employment_id=ANY(CAST(:ids AS uuid[]))
          AND la.status='APPROVED' AND la.archived_at IS NULL
          AND la.from_date<=:last AND la.to_date>=:first LIMIT :cap
    """,
        params,
    )
    ledger_scope = read_scope(scope, "leave.read")
    ledger_clause, ledger_params = ledger_scope.employment_filter_sql("e")
    ledgers = await _rows(
        session,
        f"""
        SELECT l.*,b.name AS bucket_name,b.code AS bucket_code,
          lt.name AS type_name,lt.code AS type_code,lt.is_paid,lt.is_comp_off
        FROM leave_monthly_ledger l
        JOIN employments e ON e.tenant_id=l.tenant_id AND e.id=l.employment_id
        JOIN leave_balance_buckets b ON b.tenant_id=l.tenant_id AND b.id=l.bucket_id
        LEFT JOIN leave_type_bucket_mapping bm ON bm.tenant_id=b.tenant_id AND bm.bucket_id=b.id
        LEFT JOIN leave_types lt ON lt.tenant_id=bm.tenant_id AND lt.id=bm.leave_type_id
        WHERE l.tenant_id=:tid AND l.employment_id=ANY(CAST(:ids AS uuid[]))
          AND (l.calendar_year*12+l.calendar_month) BETWEEN :month_first AND :month_last
          {ledger_clause} LIMIT :cap
    """,
        dict(
            params,
            month_first=first.year * 12 + first.month,
            month_last=last.year * 12 + last.month,
            **ledger_params,
        ),
    )
    ad_map = {(r["employment_id"], r["work_date"]): r for r in attendance}
    holiday_map = defaultdict(list)
    for row in holidays:
        holiday_map[(row["employment_id"], row["holiday_date"])].append(row["name"])
    assignment_map, leave_map, ledger_map = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in assignments:
        assignment_map[row["employment_id"]].append(row)
    for row in leaves:
        leave_map[row["employment_id"]].append(row)
    for row in ledgers:
        ledger_map[row["employment_id"]].append(row)
    policies = {
        day: ReportPolicyResolver(session, tenant_id, day)
        for day in (first + timedelta(days=i) for i in range((last - first).days + 1))
    }
    employees = []
    for person in people:
        eid = person["id"]
        days = []
        day = max(first, person["hire_date"])
        end = min(last, person["separation_date"] or last)
        while day <= end:
            assignment = next(
                (
                    a
                    for a in assignment_map[eid]
                    if a["effective_from"] <= day
                    and (a["effective_to"] is None or a["effective_to"] > day)
                ),
                None,
            )
            if not day_matches_population_filters(population_filters or [], assignment):
                day += timedelta(days=1)
                continue
            policy = await policies[day].resolve(
                eid,
                org_unit_id=assignment["org_unit_id"] if assignment else None,
                legal_entity_id=person["legal_entity_id"],
            )
            working = is_working_day(day, policy.work_days, policy.saturday_pattern)
            holiday = "; ".join(sorted(set(holiday_map[(eid, day)]))) or None
            eligible_leave = [
                r for r in leave_map[eid] if leave_covers_date(r, day, working, holiday)
            ]
            pl = [
                r
                for r in eligible_leave
                if is_privilege_leave(r["code"], r["name"], r["is_paid"], r["is_comp_off"])
            ]
            unpaid = [r for r in eligible_leave if not r["is_paid"]]
            other = [r for r in eligible_leave if r not in pl and r not in unpaid]

            def quantity(rows):
                return sum(0.5 if r["half_day_option"] != "NONE" else 1 for r in rows)

            ad = ad_map.get((eid, day))
            if ad and ad["first_punch_in"]:
                state = ad["status"]
            elif eligible_leave:
                state = "ON_LEAVE"
            elif holiday:
                state = "HOLIDAY"
            elif not working:
                state = "WEEKEND"
            elif day > business_today(policy.timezone):
                state = "UPCOMING"
            else:
                state = ad["status"] if ad and ad["status"] != "PENDING" else "ABSENT"
            display_status = state.replace("_", " ").title()
            if pl:
                display_status = "Half Day (PL)" if quantity(pl) == 0.5 else "PL"
            elif unpaid:
                display_status = "Half Day (LWP)" if quantity(unpaid) == 0.5 else "LWP"
            days.append(
                AttendanceSummaryDay(
                    work_date=day,
                    day_name=day.strftime("%A"),
                    shift_start=policy.expected_start_time.strftime("%H:%M"),
                    shift_end=policy.expected_end_time.strftime("%H:%M"),
                    timezone=policy.timezone,
                    status=state,
                    display_status=display_status,
                    shift_name=policies[day].shift_name(policy),
                    is_off_day=not working or bool(holiday),
                    first_punch_in=ad["first_punch_in"] if ad else None,
                    last_punch_out=ad["last_punch_out"] if ad else None,
                    effective_minutes=ad["effective_minutes"] if ad else 0,
                    late_by_minutes=ad["late_by_minutes"] if ad else 0,
                    early_departure_minutes=ad["early_departure_minutes"] if ad else 0,
                    leave_type="; ".join(sorted({r["name"] for r in eligible_leave})) or None,
                    paid_leave_days=quantity(pl),
                    lwp_days=quantity(unpaid),
                    other_leave_days=quantity(other),
                    half_day_pl=sum(r["half_day_option"] != "NONE" for r in pl),
                    full_day_pl=sum(r["half_day_option"] == "NONE" for r in pl),
                    is_working_day=working and not holiday,
                    holiday_name=holiday,
                    department_id=to_typed_id("org_unit", assignment["department_id"])
                    if assignment and assignment["department_id"]
                    else None,
                    department=assignment["department"] if assignment else None,
                )
            )
            day += timedelta(days=1)
        metrics = summarize_days(days)
        if _full_months(first, last):
            apply_ledger_balances(metrics, ledger_map[eid], first, last)
        filtered_assignment = bool(days) and any(
            spec["field"] in {"department", "location"} for spec in population_filters or []
        )
        summary_department_id = (
            days[-1].department_id
            if filtered_assignment
            else (
                to_typed_id("org_unit", person["department_id"])
                if person["department_id"]
                else None
            )
        )
        employees.append(
            AttendanceSummaryEmployee(
                **metrics.model_dump(),
                employment_id=to_typed_id("employment", eid),
                employee_number=person["employee_number"],
                name=person["name"],
                legal_entity_id=to_typed_id("legal_entity", person["legal_entity_id"]),
                company=person["company"],
                department_id=summary_department_id,
                department=days[-1].department if filtered_assignment else person["department"],
                days=days,
            )
        )
    grouped = defaultdict(list)
    for employee in employees:
        grouped[(employee.legal_entity_id, employee.company)].append(employee)
    companies = [
        AttendanceSummaryCompany(
            **aggregate_metrics(group).model_dump(),
            legal_entity_id=key[0],
            company=key[1],
            employee_count=len(group),
        )
        for key, group in grouped.items()
    ]
    return AttendanceSummaryReport(
        from_date=first,
        to_date=last,
        generated_at=datetime.now(UTC),
        employees=employees,
        companies=companies,
        totals=AttendanceSummaryTotals(
            **aggregate_metrics(employees).model_dump(), employee_count=len(employees)
        ),
        notes=notes,
    )


def apply_ledger_balances(metrics, rows, first, last):
    """Read only explicit PL buckets, and never combine mixed leave entitlements."""
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["bucket_id"]].append(row)
    selected = []
    for bucket_rows in buckets.values():
        kinds = [
            is_privilege_leave(
                r["type_code"] or r["bucket_code"],
                r["type_name"] or r["bucket_name"],
                r["is_paid"] is not False,
                r["is_comp_off"] is True,
            )
            for r in bucket_rows
        ]
        if any(kinds) and not all(kinds):
            return
        if not any(kinds):
            continue
        unique = {(r["calendar_year"], r["calendar_month"]): r for r in bucket_rows}
        if set(unique) != set(_month_keys(first, last)):
            return
        selected.append(unique)
    if not selected:
        return
    metrics.opening_balance = round(
        float(sum(rows[(first.year, first.month)]["opening"] for rows in selected)), 4
    )
    metrics.pl_taken = round(
        float(sum(row["taken"] for rows in selected for row in rows.values())), 4
    )
    metrics.available_balance = round(
        float(
            sum(
                rows[(last.year, last.month)]["closing"] - rows[(last.year, last.month)]["held"]
                for rows in selected
            )
        ),
        4,
    )
