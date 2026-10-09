"""
Payroll foundation tables (migration 0050).

- StatutoryRule: one statutory value (a PF rate, the ESIC wage ceiling, ...) with the date
  it applies from, where it came from, and who verified it. Values are data, never code
  (enterprise plan C-10); calculations flag any value nobody has verified yet.
- PayComponent: an item that can appear on a payslip (Basic, HRA, PF employer share, ...)
  and how it behaves: kind, taxable, part of PF / ESIC wages, prorated by paid days.
- SalaryStructure + SalaryStructureLine: how a CTC is split into components. Editing a
  structure saves a new version, so the salaries already assigned with the old version keep
  the breakup they were given.
- EmployeeCompensation: an employee's annual CTC on a structure version, effective-dated with
  no overlaps; a revision closes the current row and opens a new one.
"""

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Column, Numeric
from sqlmodel import Field, SQLModel


class ComponentKind(enum.StrEnum):
    EARNING = "EARNING"
    DEDUCTION = "DEDUCTION"
    EMPLOYER_CONTRIBUTION = "EMPLOYER_CONTRIBUTION"
    REIMBURSEMENT = "REIMBURSEMENT"
    INFO = "INFO"


class StatutoryCode(enum.StrEnum):
    PF_EMPLOYEE = "PF_EMPLOYEE"
    PF_EMPLOYER = "PF_EMPLOYER"
    ESIC_EMPLOYEE = "ESIC_EMPLOYEE"
    ESIC_EMPLOYER = "ESIC_EMPLOYER"


class CalcType(enum.StrEnum):
    FIXED = "FIXED"  # a monthly amount
    PERCENT = "PERCENT"  # a percentage of the CTC or of an earlier component
    BALANCE = "BALANCE"  # whatever is left of the CTC (e.g. special allowance)
    STATUTORY = "STATUTORY"  # computed from the statutory rules (PF, ESIC)


def _money(name: str, nullable: bool = True) -> Column:
    return Column(name, Numeric(14, 2), nullable=nullable)


class StatutoryRule(SQLModel, table=True):
    __tablename__ = "statutory_rules"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    country_code: str = Field(default="IN", max_length=2)
    rule_code: str = Field(max_length=60)
    state_code: str | None = Field(default=None, max_length=10)
    value: Decimal = Field(sa_column=Column("value", Numeric(14, 4), nullable=False))
    unit: str = Field(max_length=10)
    effective_from: date
    effective_to: date | None = Field(default=None)
    source: str
    verified_by: UUID | None = Field(default=None)
    verified_at: datetime | None = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=20)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)


class PayComponent(SQLModel, table=True):
    __tablename__ = "pay_components"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=30)
    name: str = Field(max_length=100)
    kind: str = Field(max_length=30)
    statutory_code: str | None = Field(default=None, max_length=30)
    taxable: bool = Field(default=True)
    in_pf_wages: bool = Field(default=False)
    in_esic_wages: bool = Field(default=True)
    prorate: bool = Field(default=True)
    payslip_order: int = Field(default=0)
    status: str = Field(default="ACTIVE", max_length=20)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class SalaryStructure(SQLModel, table=True):
    __tablename__ = "salary_structures"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=500)
    # None = available to every company.
    legal_entity_id: UUID | None = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=20)
    supersedes_id: UUID | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)


class SalaryStructureLine(SQLModel, table=True):
    __tablename__ = "salary_structure_lines"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    structure_id: UUID = Field(index=True)
    component_id: UUID
    sequence: int = Field(default=0)
    calc_type: str = Field(max_length=20)
    amount: Decimal | None = Field(default=None, sa_column=_money("amount"))
    percent: Decimal | None = Field(
        default=None, sa_column=Column("percent", Numeric(7, 4), nullable=True)
    )
    base: str | None = Field(default=None, max_length=20)
    base_component_id: UUID | None = Field(default=None)
    min_amount: Decimal | None = Field(default=None, sa_column=_money("min_amount"))
    max_amount: Decimal | None = Field(default=None, sa_column=_money("max_amount"))


class EmployeeCompensation(SQLModel, table=True):
    __tablename__ = "employee_compensations"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    structure_id: UUID
    annual_ctc: Decimal = Field(sa_column=_money("annual_ctc", nullable=False))
    currency: str = Field(default="INR", max_length=3)
    effective_from: date
    effective_to: date | None = Field(default=None)
    reason: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
