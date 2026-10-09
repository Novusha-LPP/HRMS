# Payroll Module — Design & Scoping

> **Status update 2026-10-09:** decision D-2 puts final payroll **inside the HRMS**. The current scope, statutory approach and delivery plan are in [enterprise-plan/02-modules.md (M11)](enterprise-plan/02-modules.md) and the Payroll stream of [enterprise-plan/04-delivery-roadmap.md](enterprise-plan/04-delivery-roadmap.md). This document's open questions are answered there:
>
> 1. India first.
> 2. Bank details stay in the KYC record and change only through `BANK_CHANGE`.
> 3. Dedicated Payroll Administrator and Approver roles.
> 4. A named payroll / tax reviewer certifies the calculators (D-13).

**Status: scoping only, not implemented.** Written 2026-09-24 as part of a
gap-fill pass across Attendance/OT, Leave, and reporting (see `RUNBOOK.md`
for what that pass actually built). Payroll is a materially larger
subsystem — real money, statutory compliance, bank data — so per explicit
instruction this is a plan to build from later, not code to ship now.

## Why scope it separately

Everything else fixed this pass (overtime approval, holiday calendar,
comp-off, encashment, accrual, the Leave report) extended an existing,
working pipeline. Payroll has no existing pipeline to extend: there is no
salary data anywhere in this codebase today, on any model. Building it
without first deciding its boundaries would mean guessing at compliance
requirements (tax slabs, statutory filings) that have real legal
consequences if wrong. This document exists so that decision is made
deliberately, not implicitly by whichever fields got typed first.

## What already exists that Payroll would consume

Confirmed by reading the current models directly (not from memory):

| Source | Fields | Relevance |
|---|---|---|
| `time/models.py: AttendanceDay` | `effective_minutes`, `ot_minutes`, `ot_status` (NONE/PENDING/APPROVED/REJECTED), `is_locked` | Pay run needs effective worked time and — critically — only `ot_status=APPROVED` overtime, not raw `ot_minutes`. `is_locked` (period close) is the natural gate for "this period's attendance is final, safe to run payroll." |
| `leave/models.py: LeaveBalance` | `allocated_days`, `used_days`, `pending_days`, `last_accrued_period` | Paid-leave-taken feeds gross pay; `LeaveType.is_paid` distinguishes paid vs. unpaid leave types. |
| `leave/models.py: LeaveEncashment` (new this pass) | `employment_id`, `leave_type_id`, `days`, `effective_date` | Built specifically as *"the record for payroll to pick up externally; it does not itself move any money"* — already the designed handoff point. |
| `kyc/models.py: DocumentType.BANK_PROOF` | KYC doc type, verified/rejected workflow | Bank *proof document* exists (e.g. a cancelled cheque upload); there is no structured bank account number / IFSC / account holder name field anywhere — that's still a gap Payroll would need to fill. |
| `people/models.py: Employment`, `org/models.py: Grade`, `Assignment` | employee_number, hire_date, employment_state, `grade_id` (FK, no amount) | Grade is a pure label/rank table today — no pay range or band attached to it. |

**What does not exist at all, anywhere:** salary/CTC amount, currency,
salary components (basic/HRA/allowances), statutory config (PF/ESI/PT/TDS
rates), bank account number/IFSC, pay run records, payslips. This is a
from-scratch subsystem, not a gap-fill.

## Phase 1 scope (if greenlit)

**In:**
- Salary structure definition (a named template = ordered earning/deduction
  components, each fixed or percentage-of-basic)
- Per-employee CTC assignment, effective-dated the same way `Assignment` is
- Monthly pay run generation, reading attendance + approved OT + paid leave
  + encashments for the period
- India-specific statutory calc only (PF, ESI, Professional Tax, TDS slabs)
  — the seeded demo tenant (SFPL Group) is India-based; no reason to design
  multi-country on day one
- Payslip PDF generation
- Bank file export (a NEFT-format CSV/text file) for the finance team to
  upload to their bank portal manually

**Explicitly out of phase 1:**
- Any live bank transfer or payment API integration — this is a real money
  movement action. Even once built, an AI agent should not execute it
  unsupervised; per this session's own operating rules, financial transfers
  require explicit human action regardless of what's implemented.
- Multi-country statutory variants
- Loans, advances, reimbursements/expense claims
- General ledger / accounting system export
- Multi-level pay-run approval chains (defer to phase 2 — the
  leave/corrections approval-chain pattern already in this codebase is the
  template to reuse when it's needed)

## Proposed data model

Following the `models.py` / `router.py` / `schemas.py` convention every
other module in `backend/src/hrms/modules/` already uses. The `payroll/`
directory already exists in the tree as an empty `__init__.py` stub —
scaffolded, never filled in.

- **`SalaryComponent`** — tenant-wide catalog. `name`, `code`, `kind`
  (EARNING/DEDUCTION), `calc_type` (FIXED/PERCENT_OF_BASIC/FORMULA),
  `is_statutory` (bool — PF/ESI/PT/TDS rows are system-managed, not
  HR-editable).
- **`SalaryStructure`** — named template, `components: list[{component_id,
  value_or_pct}]`.
- **`EmployeeCompensation`** — `employment_id`, `structure_id`,
  `ctc_annual`, `effective_from`/`effective_to` (nullable, open-ended —
  mirrors `Assignment`'s effective-dating exactly, including how a new row
  should close out the previous one on a raise/promotion).
- **`BankAccountDetail`** — `employment_id`, `account_number`, `ifsc`,
  `account_holder_name`. Sensitive financial PII: keep it in its own table
  (not inlined on `EmployeeCompensation`) so it can carry stricter RLS
  and, if the platform ever needs it, column-level encryption, without
  touching the compensation-amount table. Whether this reuses/extends the
  `kyc/` module's document-verification workflow (since `BANK_PROOF` KYC
  documents already exist) or lives standalone is an open call — see below.
- **`StatutoryConfig`** — tenant/legal-entity-scoped PF/ESI/PT/TDS rates
  and thresholds. Legal-entity-scoped because a group tenant (like SFPL
  Group) can have companies registered in different states with different
  Professional Tax rules.
- **`PayRun`** — `tenant_id`, `period` ("YYYY-MM"), `status`
  (DRAFT/PROCESSING/APPROVED/PAID), `locked` (bool, same pattern as
  `AttendanceDay.is_locked`), `generated_at`, `approved_by`.
- **`Payslip`** — one row per employment per `PayRun`: computed line-item
  breakdown (JSON, same pattern as `ReportDefinition.columns`/`filters`
  storing JSON-as-text), `net_pay`, `pdf_key` (S3, same pattern as
  `Punch.selfie_key`/KYC document storage).

Migrations would start at **`0012`** (last one shipped this pass is
`0011_drop_shifts.py`). Every new table gets `tenant_id` in its composite
primary key and a `tenant_isolation` RLS policy, exactly like every table
added this session (`holidays`, `comp_off_grants`, `leave_encashments`).

## Permissions

Add to `core/authz.py`'s `ROLE_PERMISSIONS`: `payroll.read`,
`payroll.write` (define/adjust comp structures and CTC), `payroll.process`
(trigger pay run generation — kept distinct from `payroll.write` since
generating a run touches every employee's numbers in one action, not just
one record), `payroll.approve` (mark a run APPROVED/PAID).

Open question worth deciding before building: should `payroll.*` fold into
`HR_MANAGER`'s existing permission set like everything else has so far, or
does compensation data warrant a narrower dedicated role (e.g.
`PAYROLL_ADMIN`) so that a regional HR manager scoped to two companies
doesn't automatically see salary data for those same two companies just
because they already see everything else? Every other module built this
session reused an existing permission deliberately to avoid inventing
plumbing — payroll may be the first case where that default is wrong,
given the sensitivity gap between "who can approve a leave request" and
"who can see what someone is paid."

## Integration points to get right

- Pay run generation must read `ot_status == 'APPROVED'` specifically —
  never raw `ot_minutes` — otherwise unreviewed or rejected overtime would
  leak into pay.
- Should only run against `AttendanceDay` rows with `is_locked = true`
  (i.e. after period close), so payroll never runs against attendance that
  could still be corrected out from under it.
- `LeaveEncashment` rows for the period are the existing, already-built
  handoff — payroll reads them, not the other way around.
- A mid-period `CHANGE_GRADE`/promotion `PersonnelAction` raises a
  proration question (does pay split across the old/new `Assignment`
  within one month?) that needs a product decision, not just an
  engineering one.

## Open questions for the user

1. India-only for phase 1, or does the platform's business model (per the
   existing system-design doc's B2B SaaS-across-companies premise) require
   multi-country payroll sooner than "later"?
2. Does `BankAccountDetail` belong in a new table, or should it extend the
   `kyc/` module's existing `BANK_PROOF` document-verification flow so
   bank details go through the same verify/reject workflow as PAN/Aadhaar?
3. Dedicated `PAYROLL_ADMIN` role, or fold into `HR_MANAGER`?
4. Who signs off on statutory-calc correctness before this goes anywhere
   near a real payslip — this is the one area in the whole system where a
   silent bug has legal/financial consequences, not just a UI bug.
