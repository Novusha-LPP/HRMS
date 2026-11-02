"""
The fixed SAMPLE payslip the setup preview prints, so HR can design the layout without seeing
anyone's pay. Every figure is made up, and the PDF is watermarked SAMPLE.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal

from hrms.modules.payroll.payslip.document import LeaveRow, Line, PayslipData
from hrms.modules.payroll.payslip.formatting import to_paise

# Full-month earnings of the sample employee.
_RATES = (
    ("Basic", Decimal("25000")),
    ("House rent allowance", Decimal("10000")),
    ("Special allowance", Decimal("9500")),
    ("Conveyance allowance", Decimal("1600")),
)
_PF_WAGE_CAP = Decimal("15000")


def sample_payslip(today: date, now: datetime, reference_prefix: str = "SAMPLE") -> PayslipData:
    """Last month's payslip for a made-up employee with one day of loss of pay."""
    first = today.replace(day=1)
    year, month = (first.year - 1, 12) if first.month == 1 else (first.year, first.month - 1)
    days = calendar.monthrange(year, month)[1]
    paid = days - 1
    # Months already paid in the financial year (April to March), for the YTD column.
    earlier = (month - 4) % 12

    def earned(rate: Decimal) -> Decimal:
        return to_paise(rate * paid / days)

    earnings = tuple(
        Line(label, earned(rate), rate=rate, ytd=earned(rate) + rate * earlier)
        for label, rate in _RATES
    )
    pf = to_paise(min(earnings[0].amount, _PF_WAGE_CAP) * Decimal("0.12"))
    deductions = (
        Line("Provident fund", pf, ytd=pf * (earlier + 1)),
        Line("ESIC", Decimal(0)),  # not applicable above the wage ceiling: hidden as zero
        Line("Professional tax", Decimal(200), ytd=Decimal(200) * (earlier + 1)),
        Line("Income tax (TDS)", Decimal(1250), ytd=Decimal(1250) * (earlier + 1)),
    )
    weekly_offs = sum(1 for d in range(1, days + 1) if date(year, month, d).weekday() == 6)
    return PayslipData(
        reference=f"{reference_prefix}/{year}-{month:02d}/E1042",
        period_label=f"{calendar.month_name[month]} {year}",
        pay_date=date(year, month, days),
        days_in_period=Decimal(days),
        paid_days=Decimal(paid),
        lop_days=Decimal(1),
        employee_name="Aarav Mehta",
        employee={
            "employee_number": "E1042",
            "designation": "Senior Executive",
            "department": "Operations",
            "location": "Head office",
            "grade": "G4",
            "date_of_joining": "04 Jan 2021",
            "pan": "XXXXXX234F",
            "uan": "XXXXXXXX5521",
            "pf_number": "XXXXXXXXXXXXXXX0042",
            "esic_number": "Not applicable",
            "bank_account": "HDFC Bank XXXXXXXXXX4821",
            "tax_regime": "New regime",
        },
        earnings=earnings,
        deductions=deductions,
        employer_contributions=(
            Line("PF employer share", pf),
            Line("Gratuity provision", to_paise(earnings[0].amount * Decimal("0.0481"))),
        ),
        attendance=(
            ("Days in month", str(days)),
            ("Weekly offs", str(weekly_offs)),
            ("Holidays", "1"),
            ("Leave taken", "1"),
            ("Loss of pay", "1"),
            ("Overtime", "4 h"),
        ),
        leave_balances=(
            LeaveRow("Casual leave", Decimal(8), Decimal(1), Decimal(7)),
            LeaveRow("Sick leave", Decimal(6), Decimal(0), Decimal(6)),
            LeaveRow("Earned leave", Decimal(15), Decimal(0), Decimal(15)),
        ),
        generated_at=now,
    )
