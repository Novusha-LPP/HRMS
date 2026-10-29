"""
The payslip as data: what it holds (PayslipData), how it is set up (TemplateSettings), who
issues it (Issuer), and the finished view the HTML template prints (build_view).

build_view is pure: the same inputs always give the same view, so it is tested with golden
values, and a stored payslip can be rendered again exactly as it was issued.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal

from hrms.modules.branding.resolve import WHITE, mix, readable_on_white, text_on
from hrms.modules.payroll.payslip.formatting import amount_in_words, format_inr

# Employee details a payslip can print, in the order HR picks them. Identifiers arrive masked.
EMPLOYEE_FIELDS: dict[str, str] = {
    "employee_number": "Employee number",
    "designation": "Designation",
    "department": "Department",
    "location": "Location",
    "grade": "Grade",
    "date_of_joining": "Date of joining",
    "pan": "PAN",
    "uan": "UAN",
    "pf_number": "PF number",
    "esic_number": "ESIC IP number",
    "bank_account": "Bank account",
    "tax_regime": "Tax regime",
}
DEFAULT_EMPLOYEE_FIELDS = (
    "employee_number",
    "designation",
    "department",
    "location",
    "date_of_joining",
    "pan",
    "uan",
    "bank_account",
)
LAYOUTS = ("MODERN", "CLASSIC", "COMPACT")
NO_SIGNATURE_TEXT = "This is a computer-generated payslip and needs no signature."


@dataclass(frozen=True)
class Line:
    label: str
    amount: Decimal
    rate: Decimal | None = None  # the full-month amount, for earnings
    ytd: Decimal | None = None


@dataclass(frozen=True)
class LeaveRow:
    leave_type: str
    opening: Decimal
    availed: Decimal
    closing: Decimal


@dataclass(frozen=True)
class PayslipData:
    reference: str
    period_label: str
    pay_date: date
    days_in_period: Decimal
    paid_days: Decimal
    lop_days: Decimal
    employee_name: str
    employee: dict[str, str]
    earnings: tuple[Line, ...]
    deductions: tuple[Line, ...]
    generated_at: datetime
    employer_contributions: tuple[Line, ...] = ()
    reimbursements: tuple[Line, ...] = ()
    attendance: tuple[tuple[str, str], ...] = ()
    leave_balances: tuple[LeaveRow, ...] = ()


@dataclass(frozen=True)
class TemplateSettings:
    layout: str = "MODERN"
    title: str = "Payslip"
    employee_fields: tuple[str, ...] = DEFAULT_EMPLOYEE_FIELDS
    show_attendance: bool = True
    show_leave_balances: bool = False
    show_employer_contributions: bool = False
    show_ytd: bool = False
    hide_zero_lines: bool = True
    signature_mode: str = "COMPUTER_GENERATED"
    note_text: str | None = None


@dataclass(frozen=True)
class Signer:
    name: str
    designation: str | None = None
    signature_png: bytes | None = None


@dataclass(frozen=True)
class Issuer:
    """The employer as printed: resolved branding plus company details."""

    name: str
    address: str | None = None
    registrations: tuple[tuple[str, str], ...] = ()
    logo_png: bytes | None = None
    primary_color: str = "#0F766E"
    accent_color: str = "#134E4A"
    footer_text: str | None = None
    contact: tuple[str, ...] = ()
    signer: Signer | None = None


@dataclass(frozen=True)
class ViewLine:
    label: str
    amount: str
    rate: str | None
    ytd: str | None


@dataclass(frozen=True)
class PayslipView:
    layout: str
    title: str
    sample: bool
    issuer: Issuer
    logo_uri: str | None
    signature_uri: str | None
    colors: dict[str, str]
    data: PayslipData
    employee_fields: tuple[tuple[str, str], ...]
    earnings: tuple[ViewLine, ...]
    deductions: tuple[ViewLine, ...]
    employer_contributions: tuple[ViewLine, ...]
    reimbursements: tuple[ViewLine, ...]
    totals: dict[str, str]
    net_pay: str
    net_pay_words: str
    show_attendance: bool
    show_leave_balances: bool
    show_ytd: bool
    signature_mode: str
    no_signature_text: str
    note_text: str | None
    generated_at: str
    days: dict[str, str] = field(default_factory=dict)


def _png_uri(png: bytes | None) -> str | None:
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


def _days(value: Decimal) -> str:
    return f"{value.normalize():f}" if value == value.to_integral() else f"{value:.1f}"


def _lines(lines: tuple[Line, ...], settings: TemplateSettings) -> tuple[ViewLine, ...]:
    kept = [ln for ln in lines if not (settings.hide_zero_lines and ln.amount == 0)]
    return tuple(
        ViewLine(
            label=ln.label,
            amount=format_inr(ln.amount),
            rate=format_inr(ln.rate) if ln.rate is not None else None,
            ytd=format_inr(ln.ytd) if ln.ytd is not None else None,
        )
        for ln in kept
    )


def _sum(lines: tuple[Line, ...], attr: str = "amount") -> Decimal:
    return sum((getattr(ln, attr) or Decimal(0) for ln in lines), Decimal(0))


def build_view(
    data: PayslipData, issuer: Issuer, settings: TemplateSettings, *, sample: bool = False
) -> PayslipView:
    gross = _sum(data.earnings)
    deductions = _sum(data.deductions)
    reimbursements = _sum(data.reimbursements)
    net = gross - deductions + reimbursements
    primary = issuer.primary_color.upper()
    compact = settings.layout == "COMPACT"
    signer = issuer.signer if settings.signature_mode == "SIGNATORY" else None
    return PayslipView(
        layout=settings.layout,
        title=settings.title,
        sample=sample,
        issuer=issuer if signer else _without_signer(issuer),
        logo_uri=_png_uri(issuer.logo_png),
        signature_uri=_png_uri(signer.signature_png) if signer else None,
        colors={
            "primary": primary,
            "on_primary": text_on(primary),
            "primary_text": readable_on_white(primary),
            "accent_text": readable_on_white(issuer.accent_color.upper()),
            "tint": mix(primary, WHITE, 0.92),
            "tint_border": mix(primary, WHITE, 0.7),
        },
        data=data,
        employee_fields=tuple(
            (EMPLOYEE_FIELDS[key], data.employee[key])
            for key in settings.employee_fields
            if key in EMPLOYEE_FIELDS and data.employee.get(key)
        ),
        earnings=_lines(data.earnings, settings),
        deductions=_lines(data.deductions, settings),
        employer_contributions=_lines(data.employer_contributions, settings)
        if settings.show_employer_contributions
        else (),
        reimbursements=_lines(data.reimbursements, settings),
        totals={
            "gross": format_inr(gross),
            "gross_rate": format_inr(_sum(data.earnings, "rate")),
            "gross_ytd": format_inr(_sum(data.earnings, "ytd")),
            "deductions": format_inr(deductions),
            "deductions_ytd": format_inr(_sum(data.deductions, "ytd")),
            "reimbursements": format_inr(reimbursements),
        },
        net_pay=format_inr(net),
        net_pay_words=amount_in_words(net),
        # Compact is half a page: it keeps the essentials and leaves these two out.
        show_attendance=settings.show_attendance and bool(data.attendance) and not compact,
        show_leave_balances=settings.show_leave_balances
        and bool(data.leave_balances)
        and not compact,
        show_ytd=settings.show_ytd,
        signature_mode="SIGNATORY" if signer else "COMPUTER_GENERATED",
        no_signature_text=NO_SIGNATURE_TEXT,
        note_text=settings.note_text,
        generated_at=data.generated_at.strftime("%d %b %Y, %H:%M"),
        days={
            "in_period": _days(data.days_in_period),
            "paid": _days(data.paid_days),
            "lop": _days(data.lop_days),
        },
    )


def _without_signer(issuer: Issuer) -> Issuer:
    return replace(issuer, signer=None)
