"""
Payroll foundation — /v1/payroll.

Statutory rules   GET  /statutory-rules            POST /statutory-rules (a new value from a date)
                  POST /statutory-rules/india-defaults   POST /statutory-rules/{id}/verify
Components        GET/POST /components   PATCH /components/{id}   POST /components/standard
Structures        GET/POST /structures   PUT /structures/{id} (new version)
                  POST /structures/{id}/deactivate   POST /structures/standard
                  POST /structures/preview (breakup of an unsaved draft)
Salaries          GET  /salaries   GET/POST /employees/{employment_id}/compensation

Access: payroll.read to see, payroll.write to change, payroll.review to verify statutory
values. HR_MANAGER holds none of these; the Admin grants the PAYROLL_* roles, scoped to the
companies concerned. Salaries are scoped like the employee they belong to.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission
from hrms.core.change_audit import record_change
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.payroll import calculator
from hrms.modules.payroll.models import (
    EmployeeCompensation,
    PayComponent,
    SalaryStructure,
    SalaryStructureLine,
    StatutoryRule,
)
from hrms.modules.payroll.schemas import (
    BreakupLineResponse,
    BreakupRequest,
    BreakupResponse,
    CompensationCreate,
    CompensationResponse,
    EmployeeCompensationDetail,
    PayComponentCreate,
    PayComponentResponse,
    PayComponentUpdate,
    SalaryListItem,
    StatutoryRuleCreate,
    StatutoryRuleResponse,
    StructureCreate,
    StructureLineInput,
    StructureLineResponse,
    StructureResponse,
)

router = APIRouter(prefix="/v1/payroll", tags=["Payroll"])


async def _user_names(session, tenant_id: UUID, ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT ua.id,
                   CASE WHEN ua.status = 'SYSTEM' THEN 'System' ELSE
                   COALESCE(p.legal_first_name || ' ' || p.legal_last_name, ua.email,
                            ua.employee_code) END
            FROM user_accounts ua
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            WHERE ua.tenant_id = CAST(:tid AS uuid) AND ua.id = ANY(CAST(:ids AS uuid[]))
        """),
        {"tid": str(tenant_id), "ids": [str(i) for i in ids]},
    )
    return {r[0]: r[1] for r in rows}


# ─── Statutory rules ──────────────────────────────────────────────────────────

# India pack defaults. They load UNVERIFIED: the company's payroll reviewer checks each one
# against the current official notification before relying on it (decision D-13, plan C-10).
_PACK = "India pack default — verify against the current official EPFO / ESIC notification"
INDIA_DEFAULTS: list[tuple[str, str, date, str]] = [
    ("PF_WAGE_CEILING", "15000", date(2014, 9, 1), _PACK),
    (
        "PF_CAP_TO_CEILING",
        "1",
        date(2014, 9, 1),
        "Company choice (pack default: contributions limited to the ceiling; set 0 to "
        "contribute on actual PF wages)",
    ),
    ("PF_EMPLOYEE_RATE", "12", date(2014, 9, 1), _PACK),
    ("PF_EMPLOYER_RATE", "12", date(2014, 9, 1), _PACK),
    ("EPS_RATE", "8.33", date(2014, 9, 1), _PACK),
    ("EPS_WAGE_CEILING", "15000", date(2014, 9, 1), _PACK),
    ("ESIC_WAGE_CEILING", "21000", date(2017, 1, 1), _PACK),
    ("ESIC_EMPLOYEE_RATE", "0.75", date(2019, 7, 1), _PACK),
    ("ESIC_EMPLOYER_RATE", "3.25", date(2019, 7, 1), _PACK),
]


async def _rule_response(session, tenant_id: UUID, rules: list[StatutoryRule]):
    names = await _user_names(
        session, tenant_id, {r.verified_by for r in rules} | {r.recorded_by for r in rules}
    )
    out = []
    for r in rules:
        unit, label = calculator.RULES.get(r.rule_code, (r.unit, r.rule_code))
        out.append(
            StatutoryRuleResponse(
                id=to_typed_id("statutory_rule", r.id),
                rule_code=r.rule_code,
                label=label,
                unit=r.unit,
                state_code=r.state_code,
                value=r.value,
                effective_from=r.effective_from,
                effective_to=r.effective_to,
                source=r.source,
                verified=r.verified_by is not None,
                verified_by_name=names.get(r.verified_by) if r.verified_by else None,
                verified_at=r.verified_at,
                recorded_by_id=to_typed_id("user", r.recorded_by) if r.recorded_by else None,
                recorded_by_name=names.get(r.recorded_by) if r.recorded_by else None,
                status=r.status,
            )
        )
    return out


@router.get(
    "/statutory-rules",
    response_model=list[StatutoryRuleResponse],
    summary="List statutory rule values",
    dependencies=[require_permission("payroll.read")],
)
async def list_statutory_rules(
    tenant_id: TenantDep, session: SessionDep, include_retired: bool = False
) -> list[StatutoryRuleResponse]:
    q = select(StatutoryRule).where(StatutoryRule.tenant_id == tenant_id)
    if not include_retired:
        q = q.where(StatutoryRule.status == "ACTIVE")
    rows = (
        (
            await session.execute(
                q.order_by(col(StatutoryRule.rule_code), col(StatutoryRule.effective_from).desc())
            )
        )
        .scalars()
        .all()
    )
    return await _rule_response(session, tenant_id, list(rows))


@router.post(
    "/statutory-rules/india-defaults",
    response_model=list[StatutoryRuleResponse],
    summary="Load the India statutory defaults, unverified",
    dependencies=[require_permission("payroll.write")],
)
async def load_india_statutory_defaults(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> list[StatutoryRuleResponse]:
    await lock_resource(session, tenant_id, "payroll:statutory-rules")
    existing = set(
        (
            await session.execute(
                select(StatutoryRule.rule_code)
                .where(StatutoryRule.tenant_id == tenant_id)
                .where(StatutoryRule.status == "ACTIVE")
            )
        )
        .scalars()
        .all()
    )
    for code, value, start, source in INDIA_DEFAULTS:
        if code in existing:
            continue  # never overwrite a value the company already maintains
        rule = StatutoryRule(
            tenant_id=tenant_id,
            id=uuid4(),
            rule_code=code,
            value=Decimal(value),
            unit=calculator.RULES[code][0],
            effective_from=start,
            source=source,
            recorded_by=principal.user_account_id,
        )
        session.add(rule)
        await session.flush()
        await record_change(
            session,
            tenant_id,
            "statutory_rule",
            rule.id,
            "CREATE",
            changed_by=principal.user_account_id,
            before=None,
            after={"rule_code": code, "value": rule.value, "effective_from": start},
        )
    return await list_statutory_rules(tenant_id, session)


@router.post(
    "/statutory-rules",
    response_model=StatutoryRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new statutory value from a date",
    dependencies=[require_permission("payroll.write")],
)
async def create_statutory_rule(
    body: StatutoryRuleCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> StatutoryRuleResponse:
    if body.rule_code not in calculator.RULES:
        raise HTTPException(422, f"Unknown rule {body.rule_code!r}")
    unit = calculator.RULES[body.rule_code][0]
    if unit == "PERCENT" and body.value > 100:
        raise HTTPException(422, "A percentage can't be more than 100")
    await lock_resource(session, tenant_id, "payroll:statutory-rules")
    current = (
        (
            await session.execute(
                select(StatutoryRule)
                .where(StatutoryRule.tenant_id == tenant_id)
                .where(StatutoryRule.rule_code == body.rule_code)
                .where(StatutoryRule.status == "ACTIVE")
                .where(col(StatutoryRule.effective_to).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if current is not None:
        if body.effective_from <= current.effective_from:
            raise HTTPException(
                409,
                f"The current value applies from {current.effective_from}; a new value must start "
                "after that.",
            )
        current.effective_to = body.effective_from
        session.add(current)
        await session.flush()
    rule = StatutoryRule(
        tenant_id=tenant_id,
        id=uuid4(),
        rule_code=body.rule_code,
        state_code=body.state_code,
        value=body.value,
        unit=unit,
        effective_from=body.effective_from,
        source=body.source.strip(),
        recorded_by=principal.user_account_id,
    )
    session.add(rule)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "statutory_rule",
        rule.id,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={
            "rule_code": rule.rule_code,
            "value": rule.value,
            "effective_from": rule.effective_from,
        },
    )
    return (await _rule_response(session, tenant_id, [rule]))[0]


@router.post(
    "/statutory-rules/{rule_id}/verify",
    response_model=StatutoryRuleResponse,
    summary="Verify a statutory value against the official source",
    dependencies=[require_permission("payroll.review")],
)
async def verify_statutory_rule(
    rule_id: str, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> StatutoryRuleResponse:
    rule = (
        (
            await session.execute(
                select(StatutoryRule)
                .where(StatutoryRule.tenant_id == tenant_id)
                .where(StatutoryRule.id == to_uuid(rule_id))
            )
        )
        .scalars()
        .first()
    )
    if not rule:
        raise HTTPException(404, "Statutory value not found")
    if rule.recorded_by == principal.user_account_id:
        raise HTTPException(
            403, "Someone other than the person who entered this value must verify it."
        )
    if rule.verified_by is None:
        rule.verified_by = principal.user_account_id
        rule.verified_at = datetime.now(UTC)
        session.add(rule)
        await session.flush()
        await record_change(
            session,
            tenant_id,
            "statutory_rule",
            rule.id,
            "UPDATE",
            changed_by=principal.user_account_id,
            before={"verified": False},
            after={"verified": True},
        )
    return (await _rule_response(session, tenant_id, [rule]))[0]


async def rules_at(session, tenant_id: UUID, on: date) -> dict[str, calculator.RuleValue]:
    rows = (
        await session.execute(
            select(StatutoryRule)
            .where(StatutoryRule.tenant_id == tenant_id)
            .where(StatutoryRule.status == "ACTIVE")
            .where(col(StatutoryRule.state_code).is_(None))
            .where(StatutoryRule.effective_from <= on)
            .where(
                (col(StatutoryRule.effective_to).is_(None)) | (col(StatutoryRule.effective_to) > on)
            )
        )
    ).scalars()
    return {
        r.rule_code: calculator.RuleValue(Decimal(r.value), r.verified_by is not None) for r in rows
    }


# ─── Components ───────────────────────────────────────────────────────────────


def _component_response(c: PayComponent) -> PayComponentResponse:
    return PayComponentResponse(
        id=to_typed_id("pay_component", c.id),
        code=c.code,
        name=c.name,
        kind=c.kind,
        statutory_code=c.statutory_code,
        taxable=c.taxable,
        in_pf_wages=c.in_pf_wages,
        in_esic_wages=c.in_esic_wages,
        prorate=c.prorate,
        payslip_order=c.payslip_order,
        status=c.status,
        version=c.version,
    )


async def _components(session, tenant_id: UUID) -> list[PayComponent]:
    return list(
        (
            await session.execute(
                select(PayComponent)
                .where(PayComponent.tenant_id == tenant_id)
                .where(col(PayComponent.archived_at).is_(None))
                .order_by(col(PayComponent.payslip_order), col(PayComponent.code))
            )
        )
        .scalars()
        .all()
    )


@router.get(
    "/components",
    response_model=list[PayComponentResponse],
    summary="List pay components",
    dependencies=[require_permission("payroll.read")],
)
async def list_pay_components(
    tenant_id: TenantDep, session: SessionDep
) -> list[PayComponentResponse]:
    return [_component_response(c) for c in await _components(session, tenant_id)]


def _check_component_shape(kind: str, statutory_code: str | None) -> None:
    if statutory_code is None:
        return
    expected = "DEDUCTION" if statutory_code.endswith("EMPLOYEE") else "EMPLOYER_CONTRIBUTION"
    if kind != expected:
        raise HTTPException(
            422,
            f"{statutory_code} must be a "
            f"{'deduction' if expected == 'DEDUCTION' else 'employer contribution'}.",
        )


async def _insert_component(session, tenant_id: UUID, body: PayComponentCreate, by: UUID):
    _check_component_shape(body.kind, body.statutory_code)
    clash = (
        await session.execute(
            text(
                "SELECT 1 FROM pay_components WHERE tenant_id = CAST(:tid AS uuid) "
                "AND lower(code) = lower(:code) AND archived_at IS NULL"
            ),
            {"tid": str(tenant_id), "code": body.code},
        )
    ).first()
    if clash:
        raise HTTPException(409, f"A component with code {body.code!r} already exists")
    if body.statutory_code:
        taken = (
            await session.execute(
                select(PayComponent.code)
                .where(PayComponent.tenant_id == tenant_id)
                .where(PayComponent.statutory_code == body.statutory_code)
                .where(col(PayComponent.archived_at).is_(None))
            )
        ).scalar()
        if taken:
            raise HTTPException(409, f"{taken} is already the {body.statutory_code} component")
    component = PayComponent(
        tenant_id=tenant_id, id=uuid4(), recorded_by=by, **body.model_dump(exclude={"code"})
    )
    component.code = body.code.upper()
    component.name = body.name.strip()
    session.add(component)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "pay_component",
        component.id,
        "CREATE",
        changed_by=by,
        before=None,
        after=body.model_dump() | {"code": component.code},
    )
    return component


@router.post(
    "/components",
    response_model=PayComponentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pay component",
    dependencies=[require_permission("payroll.write")],
)
async def create_pay_component(
    body: PayComponentCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> PayComponentResponse:
    return _component_response(
        await _insert_component(session, tenant_id, body, principal.user_account_id)
    )


STANDARD_COMPONENTS = [
    PayComponentCreate(
        code="BASIC", name="Basic", kind="EARNING", in_pf_wages=True, payslip_order=10
    ),
    PayComponentCreate(code="HRA", name="House rent allowance", kind="EARNING", payslip_order=20),
    PayComponentCreate(code="SPECIAL", name="Special allowance", kind="EARNING", payslip_order=90),
    PayComponentCreate(
        code="PF_ER",
        name="PF (employer share)",
        kind="EMPLOYER_CONTRIBUTION",
        statutory_code="PF_EMPLOYER",
        taxable=False,
        in_esic_wages=False,
        payslip_order=110,
    ),
    PayComponentCreate(
        code="ESIC_ER",
        name="ESIC (employer share)",
        kind="EMPLOYER_CONTRIBUTION",
        statutory_code="ESIC_EMPLOYER",
        taxable=False,
        in_esic_wages=False,
        payslip_order=120,
    ),
    PayComponentCreate(
        code="PF_EE",
        name="PF (employee)",
        kind="DEDUCTION",
        statutory_code="PF_EMPLOYEE",
        in_esic_wages=False,
        payslip_order=210,
    ),
    PayComponentCreate(
        code="ESIC_EE",
        name="ESIC (employee)",
        kind="DEDUCTION",
        statutory_code="ESIC_EMPLOYEE",
        in_esic_wages=False,
        payslip_order=220,
    ),
]


@router.post(
    "/components/standard",
    response_model=list[PayComponentResponse],
    summary="Add the standard India pay components",
    dependencies=[require_permission("payroll.write")],
)
async def create_standard_pay_components(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> list[PayComponentResponse]:
    await lock_resource(session, tenant_id, "payroll:components")
    have = await _components(session, tenant_id)
    codes = {c.code.upper() for c in have}
    statutory = {c.statutory_code for c in have if c.statutory_code}
    for body in STANDARD_COMPONENTS:
        if body.code in codes or (body.statutory_code and body.statutory_code in statutory):
            continue
        await _insert_component(session, tenant_id, body, principal.user_account_id)
    return [_component_response(c) for c in await _components(session, tenant_id)]


async def _get_component(session, tenant_id: UUID, component_id: str) -> PayComponent:
    c = (
        (
            await session.execute(
                select(PayComponent)
                .where(PayComponent.tenant_id == tenant_id)
                .where(PayComponent.id == to_uuid(component_id))
                .where(col(PayComponent.archived_at).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if not c:
        raise HTTPException(404, "Pay component not found")
    return c


@router.patch(
    "/components/{component_id}",
    response_model=PayComponentResponse,
    summary="Update a pay component",
    dependencies=[require_permission("payroll.write")],
)
async def update_pay_component(
    component_id: str,
    body: PayComponentUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PayComponentResponse:
    component = await _get_component(session, tenant_id, component_id)
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    before = {k: getattr(component, k) for k in fields}
    for k, v in fields.items():
        setattr(component, k, v)
    session.add(component)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "pay_component",
        component.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _component_response(component)


# ─── Structures ───────────────────────────────────────────────────────────────


async def _lines_from_input(
    session, tenant_id: UUID, inputs: list[StructureLineInput]
) -> tuple[list[calculator.Line], list[tuple[StructureLineInput, PayComponent]]]:
    """Resolve the components behind a structure's lines and build calculator lines."""
    by_id = {c.id: c for c in await _components(session, tenant_id)}
    resolved: list[tuple[StructureLineInput, PayComponent]] = []
    for line in inputs:
        component = by_id.get(to_uuid(line.component_id))
        if component is None:
            raise HTTPException(422, "One of the components no longer exists")
        resolved.append((line, component))
    calc_lines = []
    for line, component in resolved:
        base_code = None
        if line.base == "COMPONENT":
            base = by_id.get(to_uuid(line.base_component_id)) if line.base_component_id else None
            if base is None:
                raise HTTPException(422, f"{component.name}: choose which component it is a % of")
            base_code = base.code
        calc_lines.append(
            calculator.Line(
                code=component.code,
                name=component.name,
                kind=component.kind,
                calc_type=line.calc_type,
                statutory_code=component.statutory_code,
                in_pf_wages=component.in_pf_wages,
                in_esic_wages=component.in_esic_wages,
                taxable=component.taxable,
                amount=line.amount,
                percent=line.percent,
                base=line.base,
                base_code=base_code,
                min_amount=line.min_amount,
                max_amount=line.max_amount,
            )
        )
    return calc_lines, resolved


def _breakup_response(annual_ctc: Decimal, b: calculator.Breakup) -> BreakupResponse:
    return BreakupResponse(
        annual_ctc=annual_ctc,
        monthly_ctc=b.monthly_ctc,
        lines=[BreakupLineResponse(**vars(bl)) for bl in b.lines],
        gross=b.gross,
        employer_contributions=b.employer_contributions,
        reimbursements=b.reimbursements,
        deductions=b.deductions,
        net_before_tax=b.net_before_tax,
        pf_wages=b.pf_wages,
        esic_wages=b.esic_wages,
        esic_applies=b.esic_applies,
        provisional=any(not rv.verified for rv in b.rules_used.values()),
        warnings=b.warnings,
    )


@router.post(
    "/structures/preview",
    response_model=BreakupResponse,
    summary="Break a CTC down with a draft structure",
    dependencies=[require_permission("payroll.read")],
)
async def preview_salary_breakup(
    body: BreakupRequest, tenant_id: TenantDep, session: SessionDep
) -> BreakupResponse:
    lines, _ = await _lines_from_input(session, tenant_id, body.lines)
    rules = await rules_at(session, tenant_id, body.on or business_today())
    try:
        return _breakup_response(
            body.annual_ctc, calculator.calculate(body.annual_ctc, lines, rules)
        )
    except calculator.BreakupError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _structure_lines(session, tenant_id: UUID, structure_ids: list[UUID]):
    if not structure_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(SalaryStructureLine)
                .where(SalaryStructureLine.tenant_id == tenant_id)
                .where(col(SalaryStructureLine.structure_id).in_(structure_ids))
                .order_by(col(SalaryStructureLine.sequence))
            )
        )
        .scalars()
        .all()
    )
    out: dict[UUID, list[SalaryStructureLine]] = {}
    for r in rows:
        out.setdefault(r.structure_id, []).append(r)
    return out


def _line_input(ln: SalaryStructureLine) -> StructureLineInput:
    return StructureLineInput(
        component_id=to_typed_id("pay_component", ln.component_id),
        calc_type=ln.calc_type,
        amount=ln.amount,
        percent=ln.percent,
        base=ln.base,
        base_component_id=to_typed_id("pay_component", ln.base_component_id)
        if ln.base_component_id
        else None,
        min_amount=ln.min_amount,
        max_amount=ln.max_amount,
    )


async def _structure_responses(session, tenant_id: UUID, structures: list[SalaryStructure]):
    lines = await _structure_lines(session, tenant_id, [s.id for s in structures])
    components = {c.id: c for c in await _components(session, tenant_id)}
    counts = dict(
        (
            await session.execute(
                text("""
                    SELECT structure_id, count(*) FROM employee_compensations
                    WHERE tenant_id = CAST(:tid AS uuid) AND effective_from <= :today
                      AND (effective_to IS NULL OR effective_to > :today)
                    GROUP BY structure_id
                """),
                {"tid": str(tenant_id), "today": business_today()},
            )
        ).all()
    )
    out = []
    for s in structures:
        out.append(
            StructureResponse(
                id=to_typed_id("salary_structure", s.id),
                name=s.name,
                description=s.description,
                legal_entity_id=to_typed_id("legal_entity", s.legal_entity_id)
                if s.legal_entity_id
                else None,
                status=s.status,
                supersedes_id=to_typed_id("salary_structure", s.supersedes_id)
                if s.supersedes_id
                else None,
                employees=counts.get(s.id, 0),
                lines=[
                    StructureLineResponse(
                        **_line_input(ln).model_dump(),
                        id=to_typed_id("salary_structure_line", ln.id),
                        component_code=components[ln.component_id].code,
                        component_name=components[ln.component_id].name,
                        component_kind=components[ln.component_id].kind,
                        sequence=ln.sequence,
                    )
                    for ln in lines.get(s.id, [])
                    if ln.component_id in components
                ],
            )
        )
    return out


@router.get(
    "/structures",
    response_model=list[StructureResponse],
    summary="List salary structures",
    dependencies=[require_permission("payroll.read")],
)
async def list_salary_structures(
    tenant_id: TenantDep, session: SessionDep
) -> list[StructureResponse]:
    rows = (
        (
            await session.execute(
                select(SalaryStructure)
                .where(SalaryStructure.tenant_id == tenant_id)
                .where(SalaryStructure.status == "ACTIVE")
                .order_by(col(SalaryStructure.name))
            )
        )
        .scalars()
        .all()
    )
    return await _structure_responses(session, tenant_id, list(rows))


async def _insert_structure(
    session, tenant_id: UUID, body: StructureCreate, by: UUID, supersedes: UUID | None = None
) -> SalaryStructure:
    calc_lines, resolved = await _lines_from_input(session, tenant_id, body.lines)
    try:
        calculator.validate_structure(calc_lines)
    except calculator.BreakupError as exc:
        raise HTTPException(422, str(exc)) from exc
    for _, component in resolved:
        if component.status != "ACTIVE":
            raise HTTPException(422, f"{component.name} is inactive")
    structure = SalaryStructure(
        tenant_id=tenant_id,
        id=uuid4(),
        name=body.name.strip(),
        description=body.description,
        legal_entity_id=to_uuid(body.legal_entity_id) if body.legal_entity_id else None,
        supersedes_id=supersedes,
        recorded_by=by,
    )
    session.add(structure)
    await session.flush()
    for i, (line, component) in enumerate(resolved):
        session.add(
            SalaryStructureLine(
                tenant_id=tenant_id,
                id=uuid4(),
                structure_id=structure.id,
                component_id=component.id,
                sequence=i,
                calc_type=line.calc_type,
                amount=line.amount,
                percent=line.percent,
                base=line.base,
                base_component_id=to_uuid(line.base_component_id)
                if line.base == "COMPONENT" and line.base_component_id
                else None,
                min_amount=line.min_amount,
                max_amount=line.max_amount,
            )
        )
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "salary_structure",
        structure.id,
        "CREATE",
        changed_by=by,
        before=None,
        after={
            "name": structure.name,
            "lines": ", ".join(c.code for _, c in resolved),
            "replaces": to_typed_id("salary_structure", supersedes) if supersedes else None,
        },
    )
    return structure


@router.post(
    "/structures",
    response_model=StructureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a salary structure",
    dependencies=[require_permission("payroll.write")],
)
async def create_salary_structure(
    body: StructureCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> StructureResponse:
    structure = await _insert_structure(session, tenant_id, body, principal.user_account_id)
    return (await _structure_responses(session, tenant_id, [structure]))[0]


async def _get_active_structure(session, tenant_id: UUID, structure_id: str) -> SalaryStructure:
    s = (
        (
            await session.execute(
                select(SalaryStructure)
                .where(SalaryStructure.tenant_id == tenant_id)
                .where(SalaryStructure.id == to_uuid(structure_id))
                .where(SalaryStructure.status == "ACTIVE")
            )
        )
        .scalars()
        .first()
    )
    if not s:
        raise HTTPException(404, "Salary structure not found")
    return s


@router.put(
    "/structures/{structure_id}",
    response_model=StructureResponse,
    summary="Save a new version of a salary structure",
    dependencies=[require_permission("payroll.write")],
)
async def replace_salary_structure(
    structure_id: str,
    body: StructureCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> StructureResponse:
    """
    The old version is retired; salaries assigned with it keep it (and their breakup) until
    they are revised. New assignments and revisions use the new version.
    """
    old = await _get_active_structure(session, tenant_id, structure_id)
    await lock_resource(session, tenant_id, f"payroll:structure:{old.id}")
    old.status = "RETIRED"
    session.add(old)
    await session.flush()
    structure = await _insert_structure(
        session, tenant_id, body, principal.user_account_id, supersedes=old.id
    )
    return (await _structure_responses(session, tenant_id, [structure]))[0]


@router.post(
    "/structures/{structure_id}/deactivate",
    response_model=StructureResponse,
    summary="Stop offering a salary structure",
    dependencies=[require_permission("payroll.write")],
)
async def deactivate_salary_structure(
    structure_id: str, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> StructureResponse:
    structure = await _get_active_structure(session, tenant_id, structure_id)
    structure.status = "INACTIVE"
    session.add(structure)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "salary_structure",
        structure.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before={"status": "ACTIVE"},
        after={"status": "INACTIVE"},
    )
    return (await _structure_responses(session, tenant_id, [structure]))[0]


@router.post(
    "/structures/standard",
    response_model=StructureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add the standard India salary structure",
    dependencies=[require_permission("payroll.write")],
)
async def create_standard_salary_structure(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> StructureResponse:
    """Basic 50% of CTC, HRA 40% of basic, special allowance as the balance, PF and ESIC."""
    await create_standard_pay_components(principal, tenant_id, session)
    by_code = {c.code: c for c in await _components(session, tenant_id)}

    def ref(code: str) -> str:
        if code not in by_code:
            raise HTTPException(409, f"Component {code} is missing; add it first")
        return to_typed_id("pay_component", by_code[code].id)

    body = StructureCreate(
        name="Standard (India)",
        description="Basic 50% of CTC, HRA 40% of basic, special allowance as the balance, "
        "with PF and ESIC as the law requires.",
        lines=[
            StructureLineInput(
                component_id=ref("BASIC"), calc_type="PERCENT", percent=Decimal("50"), base="CTC"
            ),
            StructureLineInput(
                component_id=ref("HRA"),
                calc_type="PERCENT",
                percent=Decimal("40"),
                base="COMPONENT",
                base_component_id=ref("BASIC"),
            ),
            StructureLineInput(component_id=ref("SPECIAL"), calc_type="BALANCE"),
            StructureLineInput(component_id=ref("PF_ER"), calc_type="STATUTORY"),
            StructureLineInput(component_id=ref("ESIC_ER"), calc_type="STATUTORY"),
            StructureLineInput(component_id=ref("PF_EE"), calc_type="STATUTORY"),
            StructureLineInput(component_id=ref("ESIC_EE"), calc_type="STATUTORY"),
        ],
    )
    structure = await _insert_structure(session, tenant_id, body, principal.user_account_id)
    return (await _structure_responses(session, tenant_id, [structure]))[0]


# ─── Employee compensation ────────────────────────────────────────────────────


async def _compensation_responses(session, tenant_id: UUID, rows: list[EmployeeCompensation]):
    names = await _user_names(session, tenant_id, {r.recorded_by for r in rows})
    structure_names = dict(
        (
            await session.execute(
                select(SalaryStructure.id, SalaryStructure.name)
                .where(SalaryStructure.tenant_id == tenant_id)
                .where(col(SalaryStructure.id).in_([r.structure_id for r in rows] or [uuid4()]))
            )
        ).all()
    )
    return [
        CompensationResponse(
            id=to_typed_id("employee_compensation", r.id),
            employment_id=to_typed_id("employment", r.employment_id),
            structure_id=to_typed_id("salary_structure", r.structure_id),
            structure_name=structure_names.get(r.structure_id, ""),
            annual_ctc=r.annual_ctc,
            currency=r.currency,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            reason=r.reason,
            note=r.note,
            recorded_by_name=names.get(r.recorded_by) if r.recorded_by else None,
            recorded_at=r.recorded_at,
        )
        for r in rows
    ]


async def _breakup_for(session, tenant_id: UUID, comp: EmployeeCompensation, on: date):
    lines = (await _structure_lines(session, tenant_id, [comp.structure_id])).get(
        comp.structure_id, []
    )
    calc_lines, _ = await _lines_from_input(session, tenant_id, [_line_input(ln) for ln in lines])
    rules = await rules_at(session, tenant_id, on)
    return calculator.calculate(Decimal(comp.annual_ctc), calc_lines, rules)


@router.get(
    "/employees/{employment_id}/compensation",
    response_model=EmployeeCompensationDetail,
    summary="An employee's salary, breakup and history",
    dependencies=[require_permission("payroll.read")],
)
async def get_employee_compensation(
    employment_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> EmployeeCompensationDetail:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope.for_permission("payroll.read"), emp_uuid)
    rows = list(
        (
            await session.execute(
                select(EmployeeCompensation)
                .where(EmployeeCompensation.tenant_id == tenant_id)
                .where(EmployeeCompensation.employment_id == emp_uuid)
                .order_by(col(EmployeeCompensation.effective_from).desc())
            )
        )
        .scalars()
        .all()
    )
    today = business_today()
    current = next(
        (
            r
            for r in rows
            if r.effective_from <= today and (r.effective_to is None or r.effective_to > today)
        ),
        None,
    ) or next((r for r in reversed(rows) if r.effective_from > today), None)
    history = await _compensation_responses(session, tenant_id, rows)
    breakup = breakup_error = None
    if current is not None:
        try:
            on = max(current.effective_from, today) if current.effective_to is None else today
            breakup = _breakup_response(
                Decimal(current.annual_ctc), await _breakup_for(session, tenant_id, current, on)
            )
        except calculator.BreakupError as exc:
            breakup_error = str(exc)
    return EmployeeCompensationDetail(
        employment_id=employment_id,
        current=next((h for h in history if current and to_uuid(h.id) == current.id), None),
        breakup=breakup,
        breakup_error=breakup_error,
        history=history,
    )


@router.post(
    "/employees/{employment_id}/compensation",
    response_model=CompensationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign or revise an employee's salary",
    dependencies=[require_permission("payroll.write")],
)
async def set_employee_compensation(
    employment_id: str,
    body: CompensationCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> CompensationResponse:
    """
    The first salary, or a revision from a date. A revision ends the current salary the day
    before it starts; history is never overwritten. The structure must be able to pay the CTC
    (a CTC too low for its fixed parts is refused).
    """
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope.for_permission("payroll.write"), emp_uuid)
    if principal.employment_id == emp_uuid:
        raise HTTPException(403, "Your own salary is set by someone else.")
    await lock_resource(session, tenant_id, f"payroll:compensation:{emp_uuid}")
    emp = (
        (
            await session.execute(
                text("""
                    SELECT hire_date, employment_state, legal_entity_id FROM employments
                    WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
                """),
                {"tid": str(tenant_id), "eid": str(emp_uuid)},
            )
        )
        .mappings()
        .first()
    )
    if not emp:
        raise HTTPException(404, "Employee not found")
    if emp["employment_state"] == "SEPARATED":
        raise HTTPException(409, "This employee has left.")
    if body.effective_from < emp["hire_date"]:
        raise HTTPException(422, f"The salary can't start before they joined ({emp['hire_date']}).")
    structure = await _get_active_structure(session, tenant_id, body.structure_id)
    if structure.legal_entity_id and structure.legal_entity_id != emp["legal_entity_id"]:
        raise HTTPException(422, "This structure belongs to a different company.")

    rows = list(
        (
            await session.execute(
                select(EmployeeCompensation)
                .where(EmployeeCompensation.tenant_id == tenant_id)
                .where(EmployeeCompensation.employment_id == emp_uuid)
                .order_by(col(EmployeeCompensation.effective_from))
            )
        )
        .scalars()
        .all()
    )
    open_row = next((r for r in rows if r.effective_to is None), None)
    if open_row is not None and body.effective_from <= open_row.effective_from:
        raise HTTPException(
            409,
            f"The current salary applies from {open_row.effective_from}; a revision must start "
            "after that.",
        )

    draft = EmployeeCompensation(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp_uuid,
        structure_id=structure.id,
        annual_ctc=body.annual_ctc,
        effective_from=body.effective_from,
        reason=body.reason,
        note=body.note,
        recorded_by=principal.user_account_id,
    )
    try:
        await _breakup_for(session, tenant_id, draft, body.effective_from)
    except calculator.BreakupError as exc:
        raise HTTPException(422, str(exc)) from exc

    if open_row is not None:
        before_ctc = open_row.annual_ctc
        open_row.effective_to = body.effective_from
        session.add(open_row)
        await session.flush()
    else:
        before_ctc = None
    session.add(draft)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "employee_compensation",
        draft.id,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={
            "employment_id": emp_uuid,
            "annual_ctc": draft.annual_ctc,
            "previous_annual_ctc": before_ctc,
            "structure": structure.name,
            "effective_from": draft.effective_from,
            "reason": draft.reason,
        },
    )
    return (await _compensation_responses(session, tenant_id, [draft]))[0]


@router.get(
    "/salaries",
    response_model=list[SalaryListItem],
    summary="Current salary of every employee you can see",
    dependencies=[require_permission("payroll.read")],
)
async def list_salaries(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    legal_entity_id: str | None = Query(default=None),
) -> list[SalaryListItem]:
    scope = scope.for_permission("payroll.read")
    emp_clause, params = scope.employment_filter_sql("e")
    if legal_entity_id:
        emp_clause += " AND e.legal_entity_id = CAST(:focus_le AS uuid)"
        params["focus_le"] = str(to_uuid(legal_entity_id))
    rows = (
        (
            await session.execute(
                text(f"""
                    SELECT e.id, e.employee_number, e.employment_state, e.legal_entity_id,
                           le.name AS company,
                           COALESCE(NULLIF(p.preferred_name, ''), p.legal_first_name)
                               || ' ' || p.legal_last_name AS name,
                           ou.name AS department, j.title AS designation,
                           c.annual_ctc, c.effective_from, s.name AS structure_name
                    FROM employments e
                    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                    JOIN legal_entities le ON le.tenant_id = e.tenant_id
                        AND le.id = e.legal_entity_id
                    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id
                        AND a.employment_id = e.id AND a.effective_from <= :today
                        AND (a.effective_to IS NULL OR a.effective_to > :today)
                    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
                    LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
                    -- The salary in force today or, failing that, the next one to start.
                    LEFT JOIN LATERAL (
                        SELECT * FROM employee_compensations ec
                        WHERE ec.tenant_id = e.tenant_id AND ec.employment_id = e.id
                          AND (ec.effective_to IS NULL OR ec.effective_to > :today)
                        ORDER BY ec.effective_from LIMIT 1
                    ) c ON true
                    LEFT JOIN salary_structures s ON s.tenant_id = c.tenant_id
                        AND s.id = c.structure_id
                    WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
                      AND e.employment_state <> 'SEPARATED' {emp_clause}
                    ORDER BY name
                """),
                {"tid": str(tenant_id), "today": business_today(), **params},
            )
        )
        .mappings()
        .all()
    )
    return [
        SalaryListItem(
            employment_id=to_typed_id("employment", r["id"]),
            employee_number=r["employee_number"],
            name=r["name"],
            legal_entity_id=to_typed_id("legal_entity", r["legal_entity_id"]),
            company=r["company"],
            department=r["department"],
            designation=r["designation"],
            employment_state=r["employment_state"],
            annual_ctc=r["annual_ctc"],
            structure_name=r["structure_name"],
            effective_from=r["effective_from"],
        )
        for r in rows
    ]
