"""
Splitting an annual CTC into monthly pay components. Pure functions, no database.

How a breakup is worked out (all amounts monthly, in Decimal, never float):

1. FIXED and PERCENT lines in sequence order. A percentage is of the monthly CTC or of an
   earlier component, and can be clamped to a minimum and maximum.
2. The employer's statutory costs, from the statutory rule values in force:
   - PF employer: PF_EMPLOYER_RATE % of PF wages (the components marked "in PF wages"),
     limited to PF_WAGE_CEILING when PF_CAP_TO_CEILING is 1. Rounded to the nearest rupee.
   - ESIC employer: ESIC_EMPLOYER_RATE % of ESIC wages, only while ESIC wages are at or
     under ESIC_WAGE_CEILING. Rounded up to the next rupee.
3. The BALANCE line (e.g. special allowance) takes whatever is left, so earnings plus
   employer contributions plus reimbursements equal the CTC. Statutory costs depend on the
   balance when it is part of PF or ESIC wages, so it is found by iteration; it converges
   because each rupee of balance adds less than a rupee of cost.
4. ESIC: worked out as if it applies; if ESIC wages then exceed the ceiling, worked out
   again without it. (With ESIC the gross is lower, so if it is over the ceiling with ESIC
   it is also over without it; the two cases never contradict.)
5. Employee deductions: PF employee on the same base as the employer share, ESIC employee
   when ESIC applies, and any other deduction lines. Professional tax and TDS are not
   calculated yet and the result says so.

Every rule value used is reported with whether it has been verified, so a breakup built on
unverified values is visibly provisional (enterprise plan C-10, decision D-13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
PAISA = Decimal("0.01")
RUPEE = Decimal("1")
HUNDRED = Decimal("100")

# The rule codes the calculator reads, with what they mean (shown in the Settings screen).
RULES: dict[str, tuple[str, str]] = {
    "PF_WAGE_CEILING": ("AMOUNT", "PF wage ceiling (monthly)"),
    "PF_CAP_TO_CEILING": ("FLAG", "Limit PF contributions to the wage ceiling (1 = yes)"),
    "PF_EMPLOYEE_RATE": ("PERCENT", "PF employee contribution"),
    "PF_EMPLOYER_RATE": ("PERCENT", "PF employer contribution (EPF + EPS)"),
    "EPS_RATE": ("PERCENT", "Pension (EPS) part of the employer contribution"),
    "EPS_WAGE_CEILING": ("AMOUNT", "Pension (EPS) wage ceiling (monthly)"),
    "ESIC_WAGE_CEILING": ("AMOUNT", "ESIC wage ceiling (monthly)"),
    "ESIC_EMPLOYEE_RATE": ("PERCENT", "ESIC employee contribution"),
    "ESIC_EMPLOYER_RATE": ("PERCENT", "ESIC employer contribution"),
}


class BreakupError(ValueError):
    """The structure can't produce a valid breakup for this CTC; the message is for HR."""


@dataclass(frozen=True)
class RuleValue:
    value: Decimal
    verified: bool


@dataclass(frozen=True)
class Line:
    code: str
    name: str
    kind: str  # EARNING / DEDUCTION / EMPLOYER_CONTRIBUTION / REIMBURSEMENT / INFO
    calc_type: str  # FIXED / PERCENT / BALANCE / STATUTORY
    statutory_code: str | None = None
    in_pf_wages: bool = False
    in_esic_wages: bool = False
    taxable: bool = True
    amount: Decimal | None = None
    percent: Decimal | None = None
    base: str | None = None  # CTC / COMPONENT
    base_code: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


@dataclass
class BreakupLine:
    code: str
    name: str
    kind: str
    monthly: Decimal
    annual: Decimal


@dataclass
class Breakup:
    monthly_ctc: Decimal
    lines: list[BreakupLine]
    gross: Decimal
    employer_contributions: Decimal
    reimbursements: Decimal
    deductions: Decimal
    net_before_tax: Decimal
    pf_wages: Decimal
    esic_wages: Decimal
    esic_applies: bool
    rounding_adjustment: Decimal
    rules_used: dict[str, RuleValue] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


IN_CTC = {"EARNING", "EMPLOYER_CONTRIBUTION", "REIMBURSEMENT"}


def validate_structure(lines: list[Line]) -> None:
    """Shape checks that don't need a CTC: run when a structure is saved."""
    if not lines:
        raise BreakupError("Add at least one component.")
    codes = [ln.code for ln in lines]
    if len(set(codes)) != len(codes):
        raise BreakupError("Each component can appear only once in a structure.")
    balances = [ln for ln in lines if ln.calc_type == "BALANCE"]
    if len(balances) != 1:
        raise BreakupError(
            "Exactly one component must take the balance (for example special allowance)."
        )
    if balances[0].kind != "EARNING":
        raise BreakupError("The balancing component must be an earning.")
    seen: set[str] = set()
    for ln in lines:
        if ln.calc_type == "FIXED" and ln.amount is None:
            raise BreakupError(f"{ln.name}: enter a monthly amount.")
        if ln.calc_type == "PERCENT":
            if ln.percent is None:
                raise BreakupError(f"{ln.name}: enter a percentage.")
            if ln.base == "COMPONENT":
                if not ln.base_code or ln.base_code not in seen:
                    raise BreakupError(
                        f"{ln.name}: a percentage can only be of a component listed above it."
                    )
            elif ln.base != "CTC":
                raise BreakupError(f"{ln.name}: choose what the percentage is of.")
        if ln.calc_type == "STATUTORY" and not ln.statutory_code:
            raise BreakupError(f"{ln.name}: only PF and ESIC components can be statutory.")
        if ln.statutory_code and ln.calc_type != "STATUTORY":
            raise BreakupError(f"{ln.name}: PF and ESIC components are always calculated by law.")
        if (
            ln.min_amount is not None
            and ln.max_amount is not None
            and ln.min_amount > ln.max_amount
        ):
            raise BreakupError(f"{ln.name}: the minimum is more than the maximum.")
        if ln.calc_type in ("FIXED", "PERCENT"):
            seen.add(ln.code)


def _rule(rules: dict[str, RuleValue], code: str, used: dict[str, RuleValue]) -> Decimal:
    rv = rules.get(code)
    if rv is None:
        raise BreakupError(
            f"The statutory value {code} isn't set up. Load the statutory rules in Payroll → "
            "Statutory rules first."
        )
    used[code] = rv
    return rv.value


def _clamp(value: Decimal, ln: Line) -> Decimal:
    if ln.min_amount is not None and value < ln.min_amount:
        value = ln.min_amount
    if ln.max_amount is not None and value > ln.max_amount:
        value = ln.max_amount
    return value


def calculate(annual_ctc: Decimal, lines: list[Line], rules: dict[str, RuleValue]) -> Breakup:
    validate_structure(lines)
    if annual_ctc <= ZERO:
        raise BreakupError("The CTC must be more than zero.")
    monthly_ctc = (annual_ctc / 12).quantize(PAISA, ROUND_HALF_UP)
    used: dict[str, RuleValue] = {}

    # 1. Fixed and percentage lines, in order.
    amounts: dict[str, Decimal] = {}
    for ln in lines:
        # validate_structure() guarantees the fields each calc_type needs.
        if ln.calc_type == "FIXED":
            assert ln.amount is not None
            amounts[ln.code] = _clamp(Decimal(ln.amount), ln).quantize(PAISA, ROUND_HALF_UP)
        elif ln.calc_type == "PERCENT":
            assert ln.percent is not None
            if ln.base == "CTC":
                base = monthly_ctc
            else:
                assert ln.base_code is not None
                base = amounts[ln.base_code]
            amounts[ln.code] = _clamp(base * Decimal(ln.percent) / HUNDRED, ln).quantize(
                PAISA, ROUND_HALF_UP
            )

    balance_line = next(ln for ln in lines if ln.calc_type == "BALANCE")
    stat = {ln.statutory_code: ln for ln in lines if ln.calc_type == "STATUTORY"}
    has_pf = "PF_EMPLOYER" in stat or "PF_EMPLOYEE" in stat
    has_esic = "ESIC_EMPLOYER" in stat or "ESIC_EMPLOYEE" in stat

    def wages(balance: Decimal) -> tuple[Decimal, Decimal]:
        pf = esic = ZERO
        for ln in lines:
            if ln.kind != "EARNING":
                continue
            value = balance if ln.calc_type == "BALANCE" else amounts.get(ln.code, ZERO)
            if ln.in_pf_wages:
                pf += value
            if ln.in_esic_wages:
                esic += value
        return pf, esic

    def pf_base(pf_wages: Decimal) -> Decimal:
        if not has_pf:
            return ZERO
        cap = _rule(rules, "PF_CAP_TO_CEILING", used)
        ceiling = _rule(rules, "PF_WAGE_CEILING", used)
        return min(pf_wages, ceiling) if cap >= 1 else pf_wages

    def employer_statutory(balance: Decimal, esic_on: bool) -> dict[str, Decimal]:
        pf_wages, esic_wages = wages(balance)
        out: dict[str, Decimal] = {}
        if "PF_EMPLOYER" in stat:
            rate = _rule(rules, "PF_EMPLOYER_RATE", used)
            out["PF_EMPLOYER"] = (pf_base(pf_wages) * rate / HUNDRED).quantize(RUPEE, ROUND_HALF_UP)
        if "ESIC_EMPLOYER" in stat:
            if esic_on:
                rate = _rule(rules, "ESIC_EMPLOYER_RATE", used)
                out["ESIC_EMPLOYER"] = (esic_wages * rate / HUNDRED).quantize(RUPEE, ROUND_CEILING)
            else:
                out["ESIC_EMPLOYER"] = ZERO
        return out

    fixed_ctc_cost = sum(
        (amounts[ln.code] for ln in lines if ln.kind in IN_CTC and ln.code in amounts),
        ZERO,
    )

    def solve(esic_on: bool) -> tuple[Decimal, dict[str, Decimal], Decimal]:
        balance = monthly_ctc - fixed_ctc_cost
        statutory: dict[str, Decimal] = {}
        for _ in range(60):
            statutory = employer_statutory(balance, esic_on)
            nxt = monthly_ctc - fixed_ctc_cost - sum(statutory.values(), ZERO)
            if abs(nxt - balance) < PAISA:
                balance = nxt
                break
            balance = nxt
        # Rupee rounding in the statutory shares can leave a few paise: the balance absorbs it.
        statutory = employer_statutory(balance, esic_on)
        residue = monthly_ctc - fixed_ctc_cost - sum(statutory.values(), ZERO) - balance
        return balance + residue, statutory, residue

    esic_ceiling = _rule(rules, "ESIC_WAGE_CEILING", used) if has_esic else ZERO
    esic_applies = has_esic
    balance, statutory, residue = solve(esic_on=has_esic)
    if has_esic and wages(balance)[1] > esic_ceiling:
        esic_applies = False
        balance, statutory, residue = solve(esic_on=False)

    if balance < ZERO:
        raise BreakupError(
            f"This CTC is too low for the structure: the fixed parts and statutory costs come to "
            f"more than ₹{monthly_ctc:,.2f} a month. Lower the fixed amounts or raise the CTC."
        )
    amounts[balance_line.code] = balance.quantize(PAISA, ROUND_HALF_UP)
    pf_wages, esic_wages = wages(balance)

    # 5. Employee deductions.
    deductions: dict[str, Decimal] = {}
    if "PF_EMPLOYEE" in stat:
        rate = _rule(rules, "PF_EMPLOYEE_RATE", used)
        deductions["PF_EMPLOYEE"] = (pf_base(pf_wages) * rate / HUNDRED).quantize(
            RUPEE, ROUND_HALF_UP
        )
    if "ESIC_EMPLOYEE" in stat:
        if esic_applies:
            rate = _rule(rules, "ESIC_EMPLOYEE_RATE", used)
            deductions["ESIC_EMPLOYEE"] = (esic_wages * rate / HUNDRED).quantize(
                RUPEE, ROUND_CEILING
            )
        else:
            deductions["ESIC_EMPLOYEE"] = ZERO

    result_lines: list[BreakupLine] = []
    for ln in lines:
        if ln.calc_type == "STATUTORY":
            assert ln.statutory_code is not None
            value = statutory.get(ln.statutory_code, deductions.get(ln.statutory_code, ZERO))
        else:
            value = amounts.get(ln.code, ZERO)
        result_lines.append(BreakupLine(ln.code, ln.name, ln.kind, value, value * 12))

    def total(kind: str) -> Decimal:
        return sum((bl.monthly for bl in result_lines if bl.kind == kind), ZERO)

    gross = total("EARNING")
    deduction_total = total("DEDUCTION")
    warnings = [
        "Professional tax and income tax (TDS) are not included yet; net pay is before them."
    ]
    unverified = sorted(code for code, rv in used.items() if not rv.verified)
    if unverified:
        warnings.insert(
            0,
            "Provisional: these statutory values haven't been verified by the payroll reviewer: "
            + ", ".join(unverified)
            + ".",
        )
    if has_esic and not esic_applies:
        warnings.append(
            f"ESIC doesn't apply: ESIC wages of ₹{esic_wages:,.2f} are over the "
            f"₹{esic_ceiling:,.2f} ceiling."
        )

    return Breakup(
        monthly_ctc=monthly_ctc,
        lines=result_lines,
        gross=gross,
        employer_contributions=total("EMPLOYER_CONTRIBUTION"),
        reimbursements=total("REIMBURSEMENT"),
        deductions=deduction_total,
        net_before_tax=gross - deduction_total,
        pf_wages=pf_wages,
        esic_wages=esic_wages,
        esic_applies=esic_applies,
        rounding_adjustment=residue,
        rules_used=used,
        warnings=warnings,
    )
