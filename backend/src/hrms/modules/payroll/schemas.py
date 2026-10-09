from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ComponentKindLiteral = Literal[
    "EARNING", "DEDUCTION", "EMPLOYER_CONTRIBUTION", "REIMBURSEMENT", "INFO"
]
StatutoryCodeLiteral = Literal["PF_EMPLOYEE", "PF_EMPLOYER", "ESIC_EMPLOYEE", "ESIC_EMPLOYER"]
CalcTypeLiteral = Literal["FIXED", "PERCENT", "BALANCE", "STATUTORY"]


# ─── Statutory rules ──────────────────────────────────────────────────────────


class StatutoryRuleCreate(BaseModel):
    """A new value for a rule from a date. The value in force before it ends that day."""

    rule_code: str = Field(min_length=1, max_length=60)
    state_code: str | None = Field(default=None, max_length=10)
    value: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    effective_from: date
    source: str = Field(min_length=3, max_length=1000)


class StatutoryRuleResponse(BaseModel):
    id: str
    rule_code: str
    label: str
    unit: str
    state_code: str | None
    value: Decimal
    effective_from: date
    effective_to: date | None
    source: str
    verified: bool
    verified_by_name: str | None
    verified_at: datetime | None
    recorded_by_id: str | None  # the verifier must be someone else
    recorded_by_name: str | None
    status: str


# ─── Components ───────────────────────────────────────────────────────────────


class PayComponentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=100)
    kind: ComponentKindLiteral
    statutory_code: StatutoryCodeLiteral | None = None
    taxable: bool = True
    in_pf_wages: bool = False
    in_esic_wages: bool = True
    prorate: bool = True
    payslip_order: int = Field(default=0, ge=0, le=10000)


class PayComponentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    taxable: bool | None = None
    in_pf_wages: bool | None = None
    in_esic_wages: bool | None = None
    prorate: bool | None = None
    payslip_order: int | None = Field(default=None, ge=0, le=10000)
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class PayComponentResponse(BaseModel):
    id: str
    code: str
    name: str
    kind: str
    statutory_code: str | None
    taxable: bool
    in_pf_wages: bool
    in_esic_wages: bool
    prorate: bool
    payslip_order: int
    status: str
    version: int


# ─── Structures ───────────────────────────────────────────────────────────────


class StructureLineInput(BaseModel):
    component_id: str
    calc_type: CalcTypeLiteral
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=4)
    base: Literal["CTC", "COMPONENT"] | None = None
    base_component_id: str | None = None
    min_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class StructureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    legal_entity_id: str | None = None
    lines: list[StructureLineInput] = Field(min_length=1, max_length=60)


class StructureLineResponse(StructureLineInput):
    id: str
    component_code: str
    component_name: str
    component_kind: str
    sequence: int


class StructureResponse(BaseModel):
    id: str
    name: str
    description: str | None
    legal_entity_id: str | None
    status: str
    supersedes_id: str | None
    lines: list[StructureLineResponse]
    employees: int  # people whose current salary uses this version


class BreakupRequest(BaseModel):
    annual_ctc: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    lines: list[StructureLineInput] = Field(min_length=1, max_length=60)
    on: date | None = None  # which statutory values to use; today by default


class BreakupLineResponse(BaseModel):
    code: str
    name: str
    kind: str
    monthly: Decimal
    annual: Decimal


class BreakupResponse(BaseModel):
    annual_ctc: Decimal
    monthly_ctc: Decimal
    lines: list[BreakupLineResponse]
    gross: Decimal
    employer_contributions: Decimal
    reimbursements: Decimal
    deductions: Decimal
    net_before_tax: Decimal
    pf_wages: Decimal
    esic_wages: Decimal
    esic_applies: bool
    provisional: bool  # built on statutory values nobody has verified yet
    warnings: list[str]


# ─── Employee compensation ────────────────────────────────────────────────────


class CompensationCreate(BaseModel):
    structure_id: str
    annual_ctc: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    effective_from: date
    reason: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class CompensationResponse(BaseModel):
    id: str
    employment_id: str
    structure_id: str
    structure_name: str
    annual_ctc: Decimal
    currency: str
    effective_from: date
    effective_to: date | None
    reason: str | None
    note: str | None
    recorded_by_name: str | None
    recorded_at: datetime


class EmployeeCompensationDetail(BaseModel):
    employment_id: str
    current: CompensationResponse | None
    breakup: BreakupResponse | None
    breakup_error: str | None = None
    history: list[CompensationResponse]


class SalaryListItem(BaseModel):
    employment_id: str
    employee_number: str
    name: str
    legal_entity_id: str
    company: str | None
    department: str | None
    designation: str | None
    employment_state: str
    annual_ctc: Decimal | None
    structure_name: str | None
    effective_from: date | None
