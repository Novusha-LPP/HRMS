# 2 · Modules: from today's code to business-complete

Each module below follows the same template:

- **Today**: what the code has. Checked against the repository on 2026-10-09.
- **Build**: data and behaviour to add.
- **HR configures from the UI**: the settings that make it dynamic, using the foundations in [01](01-platform-foundations.md) (F1–F19).
- **Flows**: approvals (F6), obligations and reminders (F7), bypass under the entity's setting (F9) and letters (F11).

**"Exception" or "bypass" below always means F9**: allowed, allowed with a reason, or allowed with approval, as each entity sets per rule (D-16). Every rule in every module is set **per entity** (D-15/D-16).
- **Reports and dashboard**.
- **Access**.
- **Done when**: the acceptance tests from §42 of the requirements, plus the §43 release principle. HR must be able to demonstrate the normal, approval and exception paths, history, reports and access rules with real examples.

Section numbers (§) refer to the business requirements v2.0.

---

## M1 · Organisation (§2, §32)

**Today.**

- Legal entities, locations, org units (typed, nested, with head / lead / PM), jobs and employee-ID schemes, all with API and UI and effective change history.
- `grades`, `positions` and `cost_centres` exist as tables **with no API or UI**.
- Attendance rules live in attendance policies (there are no shifts by decision D-15).
- There is no org chart.
- There are no statutory registrations on legal entities or locations.
- Legal entities, locations, units, jobs and ID schemes can be updated (PATCH). The *tenant* display name can only be changed from the platform console.

**Build.**

- **Remaining masters:**
  - API and UI for grades (with sequence and band), positions (headcount, status, holder history) and cost centres
  - unit types and location types as lookups (F2)
- **Establishment registrations** per legal entity, with optional location sub-codes:
  - PF establishment code, ESIC code, PT registration (per state), LWF registration, TAN, PAN, GSTIN
  - Factory licence number and validity, Shops & Establishment registration, CLRA principal-employer registration
  - each with validity dates and documents (F10)
  - an `ESTABLISHMENT_LICENCE_RENEWAL` obligation (F7) for each registration that has a validity date
- **Letterhead and signatories** per entity (F11).
- **Org chart.** Interactive, by unit or by reporting line, with "as of date" (history), export to PDF/PNG and a vacancy overlay (positions without a holder).
- **Reorganisation tool.** Move units or re-parent them with an effective date. Affected employees' assignments are re-dated in bulk through personnel actions, with a preview.
- **Group level.** Tenant = Group. Add an optional **entity group** (for example "Logistics companies" and "Manufacturing companies") for consolidated dashboards and scopes.

**HR configures from the UI.** Every master above, unit and location types, terminology (F14), entity calendars, and the financial year start (exists).

**Flows.** Org changes are effective-dated and audited. A unit with active employees cannot be closed until they are moved, or until an exception is approved.

**Reports.** Org structure as of a date, positions and vacancy, and establishment registrations expiring.

**Access.** `org.read` / `org.write`, scoped by entity.

**Done when.**

- A second company with three plants and nested departments is created entirely from the UI.
- Its registrations remind before expiry.
- The org chart shows last month's structure correctly.

---

## M2 · Employee Master and Employee 360 (§7, §8, §28, §30)

**Today.**

- Person / Employment / Assignment, with effective-dated assignments and manager history.
- Personnel actions (hire, transfer, promotion, demotion, confirm, extend probation, place on notice, separation, rehire, change manager / grade / cost centre), with scheduling, a daily apply job and `FAILED` parking.
- **The UI exposes only hire and transfer.**
- **No action is approved by anyone.** Holding `people.write` is treated as the approval, so the "Personnel actions to approve" dashboard count is always zero. §27 requires approval for promotion, transfer, salary and exit.
- Contact, bank, emergency contact and address live in the KYC record; mobile and email live on the user account.
- There is no family or nominee, education or previous-employment record.
- There is no probation-end, confirmation, notice-period or contract-end date.
- `employment_state` mixes the employment state and the service stage (the architecture doc flagged this). A `service_stage` column exists but is unused.

**Build.**

- **Profile model.** Each item below is a proper section, so it can be versioned and reported:
  - personal email, official email, mobile (with verification)
  - photo
  - addresses (current and permanent, with state and pincode)
  - emergency contacts (many)
  - family and dependants
  - **nominees** (PF, ESIC, gratuity, insurance; percentage shares)
  - education
  - previous employment
  - languages and skills
  - bank accounts (Financial class; change only through the `BANK_CHANGE` flow)
- **Service fields:**
  - `probation_end_date` (derived from the lifecycle policy, can be overridden through an action)
  - `confirmation_date`
  - `notice_period_days` (from policy, as of the date)
  - `contract_end_date`
  - `employee_type` (F2 lookup, replacing the free-text `worker_type`)
  - `service_stage` (`PROBATION`, `CONFIRMED`, `TRAINEE`, `CONTRACT`), kept separate from `employment_state` (`ACTIVE`, `NOTICE`, `ON_HOLD`, `SEPARATED`)
  - a **Hold** definition per tenant: what Hold blocks (punching, payroll input, logins). This is configurable.
- **Personnel-action wizards** for every action type:
  - each wizard shows the current value next to the new value
  - effective date, reason (lookup), supporting documents
  - approval (F6), and a letter (F11) where configured
  - scheduling for future dates (exists)
  - mass actions through F13
- **Inter-company transfer** is modelled as a separation from entity A plus a hire into entity B, linked to each other:
  - service continuity flag
  - PF transfer obligation
  - leave balance carry rule (policy)
  - one person, two employment records
- **Concurrent employment (C-13, decision D-6).** One Person may hold **several active employments** in different group companies (shared-services staff).
  - Each employment has its own attendance, leave, policies and statutory profile.
  - One employment is marked *primary* for self-service, and the employee switches between them in the app.
  - Approvals and reports work per employment.
- **Employee number on rehire and transfer (C-27, decision D-7).** Rehire keeps the old number by default; an inter-company transfer takes a new number only if the receiving entity's numbering series requires it.
- **Rejoin.** Searching by PAN, mobile or name with date of birth finds the previous employment. Rehire reuses the person, creates a new employment, shows the rehire-eligibility flag from the earlier exit, and keeps the earlier history.
- **Self-service profile changes.**
  - Fields marked "employee can edit" (F3) are saved directly.
  - Fields marked "needs approval" create a `PROFILE_CHANGE` request with proof attachments.
  - Bank changes always go through `BANK_CHANGE`, with maker ≠ checker and step-up MFA.
- **Duplicate detection** on create and import:
  - exact match on PAN, Aadhaar (last 4 digits plus a hash), UAN, mobile and email
  - fuzzy match on name plus date of birth
  - HR can override with a reason
- **Employee 360 page** (F17), with tabs contributed by each module, and a **history timeline** that merges personnel actions, field change logs, documents, letters and approvals.

**HR configures from the UI.**

- Fields and form layouts (F3)
- Required-data rules by employee type (F3)
- Employee types and their attributes (F2)
- Personnel action reasons
- Which actions need approval and which letters they issue (F6, F11)
- Duplicate-match rules (exact keys on or off)
- Hold semantics

**Flows.**

- Every change in §27 goes through F6.
- "No manager" raises a data-quality obligation (M25).
- Joining date after exit date and similar §30 rules are hard validations, overridable only through F9 where the rule allows it.

**Reports.** Employee master (any field, including custom), changes register (who changed what, old → new, effective date), as-of headcount, duplicates.

**Access.**

- Directory fields are visible tenant-wide (narrowable).
- Personal, Identity and Financial fields are trimmed by data class (F1).
- Managers see their team's Directory fields plus limited Personal fields.

**Done when** the §42 tests pass for: create employee, change department (current changes, history remains), access (an unauthorised user cannot see bank or Aadhaar), and historical report.

---

## M3 · Onboarding (§9)

**Today.**

- Templates and cases with a default 10-item checklist.
- Item types: task, document, form, IT setup, policy acknowledgement, training.
- Assignee types: HR, employee, IT.
- Templates can be created **through the API only (no template editor UI)**.
- Items are ticked by hand. Nothing auto-completes from the real records.

**Build.**

- **Template editor UI.**
  - Templates by entity, location and employee type (F4).
  - Each item has: type, owner resolver (HR in scope, IT role, Admin role, manager, employee), due offset from the joining date, mandatory flag, and a linked source.
- **Auto-completion from source records.** The case progress is computed, not ticked by hand. Each source module registers a *completion signal* when it is built: documents, bank and emergency contact come with B5; policies, training, assets and PF/ESIC plug in when C5, D3, D4 and E2 land. Until then those items stay manual (review dependency fix V-6).

  | Checklist item | Completed when |
  |---|---|
  | Required documents | Verified (F10) |
  | Bank | `BANK_CHANGE` approved |
  | PF / ESIC | Applicability recorded (M14) |
  | Emergency contact | Recorded |
  | Policies | Acknowledged (M17) |
  | Assets | Issued, or marked not applicable (M12) |
  | Induction | Completed (M9) |
  | IT account | Created |

- **Pre-joining portal.**
  - When the offer is accepted, the candidate gets a secure link with an **email** OTP (candidate identity type). SMS OTP is added when SMS arrives (D-3, upcoming).
  - The candidate fills the joining form, uploads documents and acknowledges policies before day 1.
  - Data flows into the employee record at conversion (§11 rule: no re-entry).
- **Employee record creation timing** is a tenant setting: at offer acceptance (pre-hire state, recommended) or on the joining day.
- **Day-1 checklist** for the manager (seat, system, buddy). **Joining confirmation**, with a no-show path that reopens the opening (M5).

**HR configures from the UI.** Templates, items, owners, offsets, the required-documents matrix (F10), the joining form layout (F3), and the welcome email (F8).

**Flows.**

- Each item is an obligation (F7) with reminders to its owner.
- Completing onboarding with pending items is a bypass (F9, mode set by the entity) and creates a follow-up obligation.

**Reports.** Onboarding status, items overdue by owner, and time to complete.

**Done when** a candidate converts with no re-entry (§42 "Convert candidate"), the checklist completes by itself as the records arrive, and an incomplete onboarding stays visible until it is finished or excepted.

---

## M4 · Manpower planning (§10)

**Today.**

- Job openings have an approval flow (draft → pending approval → open).
- `positions.max_headcount` feeds a vacancies widget.
- There is no headcount plan, no sanctioned-strength record, and no replacement linkage.

**Build.**

- **Two modes, chosen per tenant or entity:**
  - **position-based**: a seat per approved position (large enterprises)
  - **budget-based**: N heads per unit, job and location per period (small and medium companies and factories)
- **Headcount plan:**
  - per entity, location, unit and job (or position) per period
  - sanctioned heads and FTE
  - approved by the management flow (`MANPOWER_PLAN`)
  - versioned
- **Requisition.** Extends today's opening:
  - new or replacement; the employee being replaced (auto-suggested when a resignation is accepted, M13)
  - priority (lookup), target joining date, justification
  - a budget check against the plan, with an over-plan exception (F9)
- **Live measures**, as of any date: sanctioned, current strength, vacancy, on notice, replacement need, new position need, future requirement. Each measure uses one definition, shared with the dashboard.
- **Rule (§10):** a requisition becomes a recruitable vacancy only after approval. This already holds for openings; keep it.

**HR configures from the UI.** Mode, which employee types count in strength (lookup attribute), the plan approval flow, and priorities.

**Reports and dashboard.** Sanctioned vs actual by entity, location and unit; vacancy ageing; replacement backlog.

**Done when** a resignation produces a replacement-need suggestion, HR raises a requisition from it, it is approved, it opens recruitment, and on joining the vacancy closes.

---

## M5 · Recruitment (§11)

**Today.**

- Openings with approval.
- Configurable pipeline stages (with categories).
- Candidates with resumes, applications that move between stages, notes, events.
- Hire → employee conversion.
- End-to-end specs exist.

**Build.**

- **Duplicate candidate check.** Matches mobile, email and PAN within the tenant, and shows prior applications and the rehire-ineligibility flag.
- **Interviews.**
  - Rounds (configurable per opening or job), schedule, panel, mode, location or link.
  - ICS invite, reschedule with reason, no-show.
  - **Feedback forms** configurable per round (F3-style form) with a rating scale.
  - Interviewers see only their assigned candidates.
- **Offers.**
  - Offer details (CTC, Financial class), joining date and expiry.
  - Offer letter (F11), approval (`OFFER`).
  - Accept or reject with a reason; expiry is automatic and creates an obligation.
  - Joining-date changes are logged.
- **Joining.** Expected vs actual date, no-show or withdrawal with a reason (lookup), and the vacancy reopens automatically.
- **Sources** as a lookup, with referral employee capture.
- **Bulk hiring mode** for blue-collar hiring:
  - walk-in drive event
  - quick-capture form on a tablet
  - bulk stage moves
  - bulk offer
- **Candidate privacy:**
  - consent notice
  - retention period for rejected candidates (setting), with an automatic purge job (DPDP)
  - candidate data access request
- **Later:** a career page and job-board connectors.

**HR configures from the UI.** Stages (exists), interview rounds and forms, sources, rejection and withdrawal reasons, offer templates and approval, retention period.

**Reports.** Pipeline by stage, time-to-fill, source effectiveness, offer acceptance rate, interviewer load.

**Done when** the §11 flow from manpower need to employee conversion runs with interview, offer approval, acceptance, and joining with no re-entry, and the duplicate check fires.

---

## M6 · Attendance: punch any time, count the total time (§12)

**Decision (D-15, 2026-10-09): there is no concept of a shift.** Employees punch in and out at any time. The system counts the **total time worked**, and every rule that turns that time into a status, overtime or pay is set **per company (legal entity)**. There is no shift master, no roster, no roster planner and no shift swap. Those were removed from v1.3.

**Today.** This is strong, and already mostly duration-based:

- punches and computed attendance days
- worked = first IN → last OUT minus the time actually checked out (user rule 2026-10-05; no automatic break deduction)
- the day belongs to the first IN; an OUT within 24 h closes it; after 24 h the day is `MISSED_PUNCH`
- long-day confirmation and review flags
- off-day work (as OT or comp-off)
- holiday calendars (library → calendars → company / entity / department)
- corrections with configurable approval
- overtime review
- day-wise register and direct edit
- daily analysis
- `is_locked` on attendance days

**One difference from the decision.** Attendance policies still carry an expected start and end (for example 09:30–18:30) with grace. The code uses them for late and early marks, and measures OT against that span. **Wrap, do not migrate** (O-1):

- these become *optional reference times*
- an entity that leaves them empty gets pure duration rules (below)
- existing Suraj and RABS policies keep working unchanged until their HR switches them off

**Decided (D-17): late and early marks are optional, and each company decides.**

Missing:

- per-entity duration thresholds as the primary rule
- punch import screen (devices are deferred, D-12)
- geo / selfie / kiosk capture
- WFH and on-duty
- hours permission
- period close process
- pay periods
- payroll input

**Build.**

- **Duration rules per entity** (the attendance policy, scoped to the legal entity by default; finer overrides are optional, F5):
  - **full-day hours** (for example 8 h), **half-day hours** (for example 4 h); below that = absent
  - **minimum session** to ignore accidental taps
  - **maximum day** before the long-day confirmation (exists: 16 h)
  - **open-session window** before `MISSED_PUNCH` (exists: 24 h)
  - **OT** = worked beyond the entity's OT threshold hours (by default the full-day hours plus a qualifying margin), with rounding, a daily cap, a weekly cap and a period cap, a rate multiplier, and pre-approval yes/no
  - **off-day work**: OT, comp-off, or ignore (exists)
  - **weekly offs** as a work-days pattern per entity (exists, with Saturday patterns). A per-employee weekly-off day is available for companies that stagger days off. This is not a shift; it only says which weekday counts as off.
  - **optional reference times** (in / out time and grace, D-17). Each company decides whether it wants late and early marks. If set: late and early marks, late minutes, and late penalties (C2). If not set: none of these appear anywhere (status, dashboard, reports, payroll). Off by default for new companies; Suraj and RABS keep their current times until their HR changes them.
  - **hours permission** (the replacement for a "gate pass"): up to N hours a month that an employee can ask to count as worked (`HOURS_PERMISSION` request, entity limit)
  - **night hours** (optional, later): minutes worked inside a time band the entity defines (for example 22:00–06:00). This is for a night allowance in payroll or for legal alerts. It is a time band, not a shift.
  - **working-hours alerts** (optional, per entity, review E-3): maximum hours a day, maximum hours a week, maximum continuous hours without a check-out, minimum rest between days. Factories and shops laws set such limits by state. They raise alerts and bypassable warnings, and never block a punch.
- **Capture methods**, enabled per entity or location (F18):
  - devices (F19): **deferred until the device list (D-12)**, as WP C7. Until then, device punches come in through the **punch import screen** (CSV / Excel, built in C1, replacing today's one-off import scripts).
  - web punch
  - mobile punch with a **geo-fence** (multiple sites per location)
  - **selfie** (a restricted document; face-match later)
  - **kiosk mode** (shared tablet, employee number + PIN or QR)
  - IP allow-list for web punch
  - anomaly flags: punch outside the fence, new device, one kiosk punching many people within seconds
  - **privacy of capture (C-12):**
    - selfies kept 90 days by default (entity setting)
    - face-match is opt-in with consent
    - kiosk sessions end after each punch
    - PIN attempts are throttled
  - **offline and late punches (C-18):**
    - the PWA queues punches offline with device time, checked for plausibility
    - imported or late punches recompute the day until the period close, and become post-close adjustments after it
- **Statuses (§12)**, mapped to the decision:

  | §12 status | How it works |
  |---|---|
  | Present / Half day / Absent | From worked hours vs the entity's thresholds |
  | On leave / Holiday / Weekly off | Exist |
  | Missing punch | Exists |
  | Overtime | From worked hours beyond the threshold, with approval if the entity wants it |
  | **WFH** | `WFH_REQUEST`, eligibility per entity |
  | **Official duty** | `OD_REQUEST`; the approved hours count as worked |
  | **Late / Early leaving** | **Optional per company (D-17)**: only companies that set reference times get them; otherwise they are not shown |

- **Pay groups and pay calendars (C-06).**
  - Each entity (or a group inside it) has a pay calendar with a **cut-off day**, for example 26th → 25th.
  - The attendance period = the pay period.
  - A day belongs to the date of its first IN, and therefore to that date's period.
- **Period close** per pay group:
  - **pre-close checks**: open corrections, missed punches, pending OT, pending leave, unreviewed long days
  - lock (sets `is_locked`)
  - **payroll input snapshot** (M11)
  - reopen through `PERIOD_REOPEN`
  - after close, corrections become **post-close adjustments** in the next period's input (§12 rule)
- **Correction limits** (entity policy): N per month, maximum back-days, evidence above a threshold.
- **Every rule can be bypassed if the entity allows it** (D-16, F9). For example: a correction beyond the monthly limit, a correction after close, OT beyond a cap. Each rule's bypass setting decides whether the bypass is allowed directly, needs a reason, or needs approval.

**HR configures from the UI.**

- duration thresholds, OT rules, off-day rules, weekly-off patterns and optional reference times, per entity
- capture methods and geo-fences (map picker) per entity or location
- correction limits and hours-permission limits
- pay calendars and cut-offs
- WFH and OD eligibility
- bypass settings for each rule

**Flows.**

- Corrections, OT, OD, WFH, hours permission and period reopen go through F6, but only where the entity wants approval.
- Obligations: missed punches pending, unreviewed long days, period close due.

**Reports.**

- daily and monthly muster with **worked hours**
- absent, half day, missing punch, OT
- late and early (entities with reference times only)
- corrections and bypass log
- punch-import log
- statutory registers through the factory pack (form formats per state, see [03](03-industry-coverage.md))

**Done when.**

- §42 "Correct attendance" passes.
- An employee punching 22:10 → 06:40 gets one day, dated to the first IN, with 8 h 30 m worked and the entity's OT rule applied.
- Two entities in the same tenant with different full-day hours compute differently for the same punches.
- A month is closed with a payroll input produced, and a post-close correction lands in the next period.

---

## M7 · Leave (§13)

**Today.** This is strong:

- leave types, buckets, mappings
- policy sets with bucket policies (upfront or monthly pro-rata accrual, carry forward, lapse, encashment, probation eligibility, minimum service)
- assignments by employee, unit or entity
- an immutable transaction ledger and monthly ledger
- comp-off, encashment, accrual and year-end jobs
- application → approval → cancellation with configurable flows

Partly there:

- **Optional holidays** exist on holiday calendars (`is_optional`), but employees cannot pick them and there is no yearly limit.
- **Some application rules** (back-dating allowed, half day allowed, maximum consecutive days, document required) exist only for policies imported from the old ERP (`leave/legacy.py`, migration 0046). **Generalise these into the policy-set editor rather than writing them again** (review O-3).

Missing:

- **attendance-based accrual** (for example 1 day per 20 days worked, as under the Factories Act)
- explicit sandwich-rule settings
- notice-period rules
- a negative-balance limit
- a team leave calendar

**Build.**

- **Accrual basis** options:
  - upfront
  - monthly
  - **per N days worked or present** (with a qualifying-days threshold)
  - per completed month of service
  - none

  **Days-worked accrual runs after the attendance period close (C-05)**, because it needs final days worked. It is re-run when a post-close adjustment changes days worked. The statutory numbers (days per leave day, eligibility threshold) are **verified pack data (C-10)**. The Factories Act values differ from the OSH Code values, so the tenant confirms which apply.
- **Leave on a closed date (C-19).** A leave approved or cancelled after the period close, for a date inside the closed period, never edits locked attendance. It becomes a **post-close adjustment**: an LOP reversal or recovery line in the next period's payroll input (M11).
- **Application rules** in the policy:
  - sandwich (holidays and weekly offs inside or adjacent to a span)
  - minimum and maximum per application
  - notice days before applying
  - maximum back-days
  - document required above N days (for example a medical certificate for sick leave over 2 days)
  - half-day and quarter-day allowed
  - clubbing restrictions
  - leave during notice period (allowed / blocked / counted against notice)
  - leave during probation
  - **negative balance** allowed up to N, with a bypass beyond it (F9, entity mode)
  - long-leave condition routing to the HR stage
- **Statutory leave templates** in the country pack, as verified data with a source and verification date (C-10):
  - maternity (with the statutory weeks as data, not code)
  - paternity, bereavement, election, marriage, etc.
  - the tenant enables or edits them
- **Optional holidays chosen by the employee** (the holidays already exist on calendars; add the choice, a limit of N per year, and approval if configured).
- **Team leave calendar** for managers and **leave planning**.
- **Loss of pay** handling into the payroll input (M11).

**HR configures from the UI.** All of the above through policy sets (exists) and the new rule fields, with **simulation**: balance impact for a sample before publishing (F5).

**Flows.**

- Approval (exists). Exceptions for insufficient balance where the policy permits.
- Reminders on pending approvals (F7).
- An unapproved absence becomes an obligation for the manager to regularise.

**Reports.** Balances, utilisation, pending, department usage, encashment, liability (days × rate when compensation is enabled).

**Done when** §42 "Apply leave" passes. In addition, a factory-pack tenant accrues earned leave from days worked, and the sandwich rule computes as configured.

---

## M8 · Employee lifecycle (§14)

**Today.**

- Personnel action types exist in the backend.
- There are no lifecycle dates, no due reminders, no review forms and no letters.
- The UI has transfer only.

**Build.**

- **Lifecycle policy** (F5), **set per entity** (optionally varied by employee type, grade or group inside it):
  - probation length (months or days)
  - maximum extensions and maximum total length
  - review required, and its form
  - auto-confirm if no action by the due date (yes/no — most tenants: no)
  - confirmation letter template
  - increment cycle (fixed annual date, work anniversary, or none)
  - contract renewal alert offsets
- **Obligations (F7):**
  - `PROBATION_REVIEW_DUE` (with the review form to the manager)
  - `CONFIRMATION_DUE`
  - `INCREMENT_DUE`
  - `CONTRACT_END`

  Defaults: 30/15/7 days and overdue (§26). Overdue stays visible until done or excepted.
- **Probation review form** (configurable questions, recommendation: confirm / extend / terminate). It creates the matching personnel action draft for HR, and approval runs through F6.
- **Wizards** for confirmation, extension, promotion, **designation change** (a new job without promotion, §7), transfer (intra- and inter-company), manager change, location change, grade change, contract renewal and rejoin:
  - each with an effective date, reason, approval, letter, and history
  - **salary impact** captured when compensation is enabled (M11)
- **Increment** records the old and new compensation, percentage, effective date, approval and letter. Bulk increment via upload with approval (F13).

**HR configures from the UI.** Lifecycle policies, review forms, reminder offsets and recipients, letters per action, and the approval flow per action.

**Reports.** Probation due and overdue, confirmations, increments due, promotions and transfers register, contract expiries.

**Done when** the §42 tests "Probation due" (reminder appears) and "Confirmation" (status changes, letter issued, history kept) pass, and "Change salary" passes once M11 is enabled.

---

## M9 · Training and development (§15)

**Today.** Nothing.

**Build.**

- **Catalogue.** Programmes with type (lookup), objective, mode, duration, internal or external trainer and vendor, cost, mandatory flag, and **validity (months) for recertification**.
- **Sessions.** Date and time, location or link, trainer, capacity, waitlist, materials. Statuses from §4: Planned, Open (nominations), Completed, Cancelled.
- **Nominations** by HR, by a manager, or requested by the employee (`TRAINING_NOMINATION` flow). Bulk nominate by group.
- **Attendance** marking (bulk, or by QR at the venue), completion, assessment score (optional), certificates (F10 document, with expiry for recertification).
- **Feedback forms** (configurable) and **effectiveness review** by the manager after N days (obligation).
- **Requirements matrix.** Required programmes by job, location or group (F4). Examples: safety induction for every plant employee, POSH for all, forklift for operators. This feeds a compliance percentage and `RECERTIFICATION_DUE` obligations.
- **Calendar** view and an **employee training history** (360 tab).

**HR configures from the UI.** Programmes, types, forms, requirements matrix, recertification periods, reminders.

**Reports.** Plan vs actual, attendance, completion, feedback, overdue mandatory training by department, training hours per employee.

**Done when** the §42 "Training" test passes (attendance, completion and feedback recorded), and a mandatory-training gap appears for a new plant joiner automatically.

---

## M10 · Performance / KPI (§16): deferred by decision

You excluded KPI on 2026-09-21. The requirements document still contains it, so this is recorded as a **deferred module** with hooks kept open:

- the "Performance" data class is reserved
- promotion and increment actions may reference an external rating field (F3 custom field)
- the module contract allows adding review cycles, goal sheets and configurable scoring later without platform changes

If it is brought back in, it becomes a Phase D item (see [04](04-delivery-roadmap.md)).

---

## M11 · Payroll inside the HRMS (§17): decided 2026-10-09 (D-2)

**Decision.** Final payroll runs **inside the HRMS**. This replaces the "inputs only" scope of v1.2, and `docs/payroll-design.md` (scoping only) is superseded by this section.

**Today.**

- No payroll code (`modules/payroll/` is an empty package).
- What payroll will consume already exists:
  - locked attendance days (`is_locked`), approved overtime (`ot_status`)
  - the leave ledger and `leave_encashments`
  - bank fields in the KYC record (encrypted)
  - UAN, PF and ESI numbers
  - legal-entity financial year start
  - the jobs runner with checkpoints
  - document storage and encryption

**Principles specific to payroll.**

1. **Payroll is where silent bugs become legal and financial harm.** Every statutory value is verified data (C-10), every calculator is checked by the Payroll Reviewer the Admin assigns (D-13), and nothing goes live before two clean month-ends (PY-1, D-14).
2. **The HRMS never moves money.** It produces a bank advice file that Accounts uploads to the bank. No bank API, no automatic transfer.
3. **Locked means locked.** A locked pay run is never edited. Corrections flow into the next run as arrears or recoveries, or into an off-cycle run.
4. **Money controls start as `BLOCK`** (payroll lock, bank-change cooling-off, maker ≠ checker on bank and salary). Like every rule, an entity can change its bypass mode (D-16, review E-5), and every bypass is recorded.

### Compensation (the structure HR and Accounts maintain)

- **Pay components master** (F2-backed):
  - kind: earning, deduction, employer contribution, reimbursement, or information-only (for example a perquisite value)
  - taxable treatment
  - **membership of statutory wage bases** (PF wages, ESIC wages, bonus, gratuity, the Labour Codes "wages" test), as **effective-dated attributes**
  - proration by paid days (yes/no)
  - payslip label and order
  - GL account and cost-centre allocation (for the accounting export)
- **Calculation types** (PY-5), chosen per component in a structured builder:
  - fixed amount
  - percentage of one or more components, with a floor and a cap
  - slab table (by amount, location or grade)
  - **balancing component** ("special allowance = CTC − everything else")
  - attendance-driven (per present day, per worked hour, per OT hour × rate, per night-band hour)
  - input-driven (one-time lines)
  - **formula**: an Excel-like expression with a whitelisted function library, **only for users holding `payroll.structure.formula`**, type-checked, with test cases and a preview on sample employees, versioned
- **Salary structures.** Templates per grade, employee type or group (F4), with a **CTC breakup calculator** and a "show me this structure for CTC X in city Y" preview.
- **Employee compensation:**
  - effective-dated and **bitemporal** (correct a past record without losing what was known when payroll ran)
  - revision through `SALARY_REVISION` (maker ≠ checker, step-up MFA)
  - bulk revision by upload, as a batch request (F6)
  - increment letters (F11)
- **Bank details for pay.** The KYC record holds them today. Changes go only through `BANK_CHANGE`. A **cooling-off rule** (PY-6): a change within N days before the pay date is flagged and needs an extra approval, otherwise it applies to the next run.
- **Minimum wages** (PY-8):
  - a rule table by state × skill category × zone with effective dates (pack data, verified; revised several times a year in many states)
  - an employee **skill category** field
  - a pre-lock check that blocks, or warns per tenant setting, when wages fall below the minimum

### Pay run (the monthly process Accounts runs)

1. **Pay group and calendar** (from C1): period, cut-off, pay date, the entity, the employees in it.
2. **Input snapshot** at the attendance period close (C3), versioned:
   - paid days, worked hours, LOP, OT hours by rate, night-band hours (if used)
   - leave encashment
   - joiners and exits with dates
   - one-time earnings and deductions (incentives, bonuses, allowances), entered or uploaded per period and approved
   - loan EMIs (M23)
   - salary holds
   - post-close adjustments
   - statutory applicability per employee
3. **Compute.**
   - Components, then statutory: PF (employee and employer split), ESIC (including the contribution-period rule), PT by state, LWF by state, TDS (below).
   - Calculators are **country-pack plugins** reading verified rule tables (PY-2).
   - Each payslip line stores *how* it was calculated: formula, inputs, rule version.
4. **Review:**
   - a **variance report** against the last run (per employee and component, threshold-highlighted)
   - an exceptions list: negative net, below minimum wage, missing bank, missing UAN for PF-applicable staff, new joiners, exits, holds, bank changed recently
   - recompute of single employees after a fix
   - inputs changed after the snapshot are flagged "changed since compute" (PY-10)
5. **Approve and lock** (`PAYROLL_APPROVAL`, maker ≠ checker, step-up MFA). Locking freezes the run and every payslip.
6. **Outputs**, generated only from a locked run:
   - **payslips** (F11 template, published on a release date, in-app and PWA, email link)
   - **bank advice file** in a bank-specific format (format = pack or tenant data), with a control sheet (count, total, hash)
   - **statutory files**: PF ECR, ESIC monthly contribution upload, PT and LWF challan data. File formats are versioned pack data with a validator (PY-9), and are uploaded to the portals by people (A10).
   - **accounting journal** by GL account and cost centre: CSV, then Tally and other formats (PY-12)
   - **payroll register** and the statutory wage registers (state forms through the pack)
7. **After lock:**
   - corrections become arrears or recoveries in the next run, or an **off-cycle run**
   - **arrears engine** (PY-4): a back-dated revision, a late attendance correction or leave after the close re-computes the affected past periods in shadow, and pays or recovers the difference, including statutory contributions on arrears

**Off-cycle runs** handle F&F (with M13), bonus, arrears-only runs and salary-hold releases.

### Daily calculation (D-14, decided 2026-10-09)

**Payroll is calculated every day**, not only at month end.

- **Every night**, and on demand for one employee, the engine recalculates the **open pay period** for every employee whose inputs changed (incremental, through the jobs runner with checkpoints). It uses attendance up to yesterday, approved leave, OT, revisions and one-time lines.
- **What it shows**, per employee and per entity:
  - earned to date
  - deductions to date (PF, ESIC, PT, LWF, loans)
  - LOP and OT so far
  - **projected month-end gross and net**: the remaining days are assumed worked unless leave is planned; the method is an entity setting
  - TDS projection
- **Live payroll dashboard** for Payroll and Accounts: cost to date and projected cost by entity and department, plus the exceptions *as they arise* (missing bank details, below minimum wage, negative net forecast, large variance, missing UAN). Problems are fixed during the month, so month end becomes a formality.
- **Provisional, never final (review DC-1).** Daily figures are labelled *Provisional*. They never produce payslips, bank files or statutory files; only a locked month-end run does. The final run uses the same engine on the closed snapshot, so it holds no surprises.
- **Monthly statutory rules stay monthly (DC-2).** PT slabs, ESIC eligibility for the contribution period, and TDS are applied on the projected month, and the screen says so.
- **Employees can see "earned so far this month"** in self-service, if the entity switches it on (off by default, DC-4).
- **Pay frequency** per pay group: monthly by default. Weekly or daily payouts for daily-wage or contract staff are an entity option (Should). They are paid through off-cycle runs from the same daily figures.
- **It makes go-live a fact, not a guess.** From the day the engine runs (release R4), the daily calculation runs in shadow next to the current payroll. Each month end is compared to the rupee (P7). **Payroll goes live on the first month after two consecutive clean month-ends**, signed off by the Payroll Reviewer.

### Payroll Reviewer (D-13, decided 2026-10-09)

**The Admin assigns the Payroll Reviewer** in the app. It is a role (F1), typically given to a chartered accountant, payroll specialist or senior Accounts person, and can be one person per entity. The Reviewer:

- verifies statutory rule values and their sources (C-10) before they are activated
- checks the golden test cases when calculators change
- signs off each month-end comparison during the parallel run (P7)
- optionally reviews each pay run before it is locked, if the entity adds a review step to the payroll approval flow

Each sign-off is stored with the version. The Admin can reassign the role at any time; the history keeps who signed what.

### Income tax (TDS)

**Needed from the first live run.**

- **Regime per employee** (old / new) per financial year, with the default set by the tenant.
- **Declarations** (the Form 12BB style categories as pack data), and **proof upload and verification windows** set by Accounts.
- **Monthly projection.** Projected annual income, exemptions, deductions and tax; monthly TDS = remaining tax ÷ remaining months. Every value is pack data (slabs, rebates, cess, standard deduction, surcharge), verified each budget year.
- **Previous-employer income and TDS** for mid-year joiners.
- **YTD opening balances.** Per employee, component and month, imported when payroll goes live mid-year (PY-3, D-14).
- **Year end** (PY-15): Form 16 Part B data (Part A comes from the government portal), quarterly 24Q return data, and perquisite valuation inputs. Statutory dates are pack data.
- **Employee tax worksheet** in self-service: how the TDS was computed this month.

### F&F (with M13)

The F&F worksheet becomes **calculated**. The off-cycle run computes:

- salary to LWD
- leave encashment
- notice pay or recovery
- gratuity (verified eligibility rule, C-10)
- bonus
- asset and loan recoveries
- tax

Accounts reviews and approves it (`FNF_APPROVAL`), and it pays through the bank file. The **statutory payment deadline after separation is a verified rule** (the Code on Wages sets a short one; confirm it), and F&F due dates come from it (PY-13).

### Access

- **Payroll Administrator**, **Payroll Approver** and **Payroll Reviewer** role templates (F1); the Admin assigns them. Payroll is *not* folded into HR Manager.
- The Financial class is restricted.
- **Restricted pay groups** (PY-7): a "management payroll" group visible only to named users, even inside the payroll team.
- Payslip and salary views are logged.
- Managers see no salary by default.

### HR, Accounts and payroll admins configure from the UI

- components, calculation types and formulas (formula permission only)
- structures
- pay groups, pay calendars and pay dates
- statutory rule values (verified, with source)
- minimum wage tables
- bank file formats
- GL mapping
- payslip template
- declaration windows
- variance thresholds
- approval flow
- cooling-off days

### Reports

- payroll register
- bank statement
- component summary
- CTC report
- variance
- arrears register
- PF / ESIC / PT / LWF registers
- TDS register and projections
- cost-centre cost
- salary on hold
- minimum-wage exceptions
- headcount cost trend

### Done when

- the §42 "Change salary" test passes (approval, effective date, history)
- the daily calculation runs every night within its budget, and its month-end figure equals the locked run
- **two consecutive month-ends reconcile with the current payroll to the rupee for every employee and component**, with every difference explained and signed off by Accounts and the Admin-assigned Payroll Reviewer (D-13)
- the bank file is accepted by the bank in a test upload
- the statutory files pass their validators

---

## M12 · Assets (§18)

**Today.** Nothing (an onboarding item "Asset issuance" only).

**Build.**

- **Asset types** (lookup with **per-type custom fields**). Examples:
  - laptop: serial, OS
  - vehicle: registration, insurance expiry
  - SIM: number
  - **consumables / PPE**: size, issued without return
- **Asset register:**
  - asset ID (F12), type, serial, purchase date, cost, vendor, location
  - status: in stock / issued / in repair / lost / retired
  - document attachments
  - full assignment history
- **Issue and return:**
  - condition at issue and at return (lookup plus photos)
  - expected return date
  - employee acknowledgement (in-app)
  - damage, loss or recovery amount → payroll / F&F input line (M11 / M13)
- **Employee requests** for an asset (through HR requests, M16), approved and then issued.
- **Exit clearance** pulls every asset assigned to the employee automatically (§18 rule).
- **Bulk import** of the existing register.

**HR / Admin configure from the UI.** Asset types and fields, categories, return rules, the write-off approval flow.

**Reports.** Issued, returned, pending clearance, assets by location, consumable issue register (PPE).

**Done when** the §42 "Issue asset" test passes (linked to the employee and shown in 360 and clearance).

---

## M13 · Exit management (§19)

**Today.** `PLACE_ON_NOTICE` and `SEPARATION` personnel actions exist (backend only). Exit KPIs and widgets exist. There is no exit case, clearance, F&F, letters or interview.

**Build.**

- **Exit case**, with its own number (F12) and status machine: Submitted → Notice → Clearance → F&F pending → Completed (§4), plus withdrawn, rejected and on hold.
- **Separation types** (lookup with category): resignation, termination, retirement, death, absconding, end of contract, VRS, transfer-out (inter-company). **Each type has its own flow and checklist.**
- **Resignation by the employee** (self-service), with a reason, proposed LWD and attachments. Manager and HR approve through `RESIGNATION`. Retention discussion notes are Case class.
- **Absconding (C-41).** The data-quality rule "absent N consecutive days without leave" (M25) opens an obligation for HR. The absconding flow then issues the configured notices (F11 letters, with dates tracked) before any separation. N, the notices and the waiting periods are tenant settings.
- **Notice:**
  - **the notice period is set by each entity** (D-16). It can optionally vary by employee type, grade or service stage within the entity, and is taken as of the resignation date.
  - shortfall shown in days
  - **if the entity wants to release someone early, it bypasses** (F9). The entity's mode decides direct release, release with a reason, or release with approval. Buy-out or recovery of the shortfall is an optional entity setting that feeds an F&F line.
  - **LWD change** through `LWD_CHANGE` recomputes clearance due dates and obligations (§29)
- **Handover plan** (items, receiver, status), owned by the manager.
- **Clearance:**
  - templates per entity, location and separation type
  - owners: department, IT, Admin, Accounts, HR, plus custom
  - items auto-include assets (M12), loans and advances (M23), and IT accounts
  - **parallel sign-offs** (F6 parallel stage) with SLA and escalation
  - **bypass** to clear without an item (F9, entity mode)
- **Exit interview.** Configurable form, Case data class, may be anonymous in reports.
- **F&F worksheet.** Lines are pulled automatically where the data exists:
  - salary to LWD
  - leave encashment
  - notice recovery or pay
  - asset recovery
  - loans and advances
  - gratuity eligibility (service-years rule from the pack; **verified data, C-10**, because the Labour Codes changed eligibility for some employee types such as fixed-term employees, so confirm before use)
  - bonus

  With payroll inside the HRMS (D-2), these lines are **calculated by an off-cycle payroll run** (M11 "F&F"). Accounts reviews them, adds manual lines with a reason where needed, and approves (`FNF_APPROVAL`). Payment goes through the bank advice file. The F&F due date comes from the verified statutory payment deadline.
- **Letters:** relieving and experience (F11), issued only after clearance or an approved exception.
- **Statutory exit:**
  - PF date of exit
  - ESIC update
  - obligations for HR or the compliance owner (M14)
- **Final separation** applies the `SEPARATION` action. It schedules **account deactivation at the end of LWD**, closes open obligations, and sets the **rehire eligibility** (plus reason), which recruitment reads (M5).

**HR configures from the UI.** Separation types and reasons, notice policies, clearance templates and owners, the interview form, F&F line types, letter templates, approval flows.

**Reports.** Resignations, notice, clearance pending by owner, F&F pending and ageing, exit reasons, attrition (voluntary vs involuntary, by tenure).

**Done when** the §42 tests "Resignation", "Clearance" and "F&F" pass, and the employee cannot be fully exited until clearance is complete or an exception is approved (§19 rule).

---

## M14 · Statutory compliance: PF and ESIC first (§20, §44)

**Today.**

- UAN, PF and ESI numbers are stored (encrypted) in KYC.
- A "Statutory IDs not on file" count exists.
- No applicability, establishment, monthly checklist, evidence, rules, links or exceptions.

**Build.**

- **Compliance control centre** (its own module route), with the §20 cards: PF compliant employees, ESIC compliant employees, upcoming returns, pending actions, overdue, exceptions.
- **Employee statutory profile:**
  - PF: applicable (yes/no + reason + effective date), UAN, PF join date, previous membership, KYC status, nomination status, exit date
  - ESIC: applicable, IP number, registration date, dispensary, exit / update status

  Applicability is suggested from the rule table (wage ceiling as of the date) and confirmed by HR. **Applicability is always recorded explicitly** (§30).
- **Establishments** from M1 (codes per entity and location).
- **Obligation calendar (country pack):**
  - obligation types: PF ECR monthly, ESIC monthly contribution, PT (state), LWF (state, periodic), CLRA returns, Factories Act annual and half-yearly returns, Bonus, S&E renewal
  - due-date rules are pack data, editable by the tenant
  - generated per establishment and period
- **Monthly checklist** per obligation (steps from §20, editable): employee data checked → wage data checked → applicability checked → return prepared → submitted → paid → proof uploaded → HR verified. Each step has an owner, a date and a status.
- **Evidence** per period:
  - reference number (for example the TRRN)
  - submission and payment dates
  - amount
  - proof documents
  - responsible person, verifier, remarks
- **Statuses (§4):** every obligation and checklist step uses Not Applicable, Pending, In Progress, Completed, Overdue and Exception.
- **Official notices register** (§20, employer PF and ESIC). Each notice records:
  - received date and authority (EPFO / ESIC office)
  - subject
  - response due date (obligation)
  - owner, response and documents
  - closure
- **Per-employee contribution status** (§20, employee side). Optional upload of the period's ECR or contribution file, matched by UAN or IP number. It marks each employee's contribution for the month as filed / missing, and lists mismatches against the active headcount.
- **Exceptions** (§20 table): not applicable, registration pending, KYC pending, payment delayed, portal issue, each through F9 with the required fields.
- **Statutory rule table:** rates, ceilings, due days and applicability thresholds, each with an effective date, **source reference, verified by and verified on**. Pack updates arrive as proposed changes (F16). An expired verification flags in setup health.
- **Official links** (§44 list) as pack data, **separated into Employee and Employer/HR groups**, with a "last verified" date. They show:
  - on the compliance centre (employer group)
  - in employee self-service "My PF/ESIC" (employee group only)
  - **No portal credentials are stored**; "Employer login" is a link.

**HR / Accounts configure from the UI.** Establishments, rule values (with source), obligation calendar, checklist steps, owners, links.

**Reports.** PF and ESIC status by employee, monthly compliance status by establishment, overdue, exceptions, evidence register.

**Done when** the §42 tests for the PF and ESIC employee and employer links and "Compliance evidence" pass, and one month's PF and ESIC checklist is completed with evidence for one establishment.

---

## M15 · Documents (§21)

**Today.** The KYC document upload and verification flow, encrypted storage.

**Build.** The full F10 rollout:

- document types and categories
- required-documents matrix
- verification queue
- versioning and replace history
- expiry reminders
- retention and legal hold
- company documents (establishment licences, policies)
- the employee **My Documents** page
- HR document requests ("please upload X by date"), which create an obligation for the employee

**Done when** the §42 test "Document expiry" passes (the reminder appears), and replacing a document keeps the old version.

---

## M16 · HR requests and helpdesk (§22)

**Today.** Nothing (corrections and leave are separate flows).

**Build.**

- **Request categories** (two levels, F2), each with:
  - a form (F3-style custom fields)
  - SLA hours, measured against a **business-hours calendar** (per location, using holiday calendars)
  - assignment rule: queue, round-robin within a role in scope, or a named person
  - confidentiality (normal / Case class for grievances)
  - an optional **linked action** — for example "Address change" opens a `PROFILE_CHANGE`, "Salary certificate" generates a letter (F11), "Missing punch" opens a correction
- **Ticket:**
  - reference number (F12)
  - statuses from §4: New, In Progress, Waiting for Employee (pauses the SLA), Resolved, Closed
  - priority
  - assignee
  - due date
  - age
  - SLA status
  - escalation (F7)
  - internal notes vs public replies
  - attachments
  - canned responses
  - reopen within N days
  - a satisfaction rating
- **Employee view:** My Requests with status and history (§22: the employee sees the result).

**HR configures from the UI.** Categories, forms, SLAs, calendars, assignment, escalation, canned responses, confidentiality.

**Reports.** Open, overdue, ageing, by category, by assignee, SLA attainment, closure time.

**Done when** the §42 "HR request" test passes (the employee sees the status, HR resolves), and an SLA breach escalates.

---

## M17 · Policy documents and acknowledgement (§23)

**Today.** Nothing. The "Policies" page holds attendance and leave *rules*. Onboarding has a `POLICY_ACK` item type with nothing to acknowledge.

**Build.**

- **Rename to avoid confusion:** the Settings page for rules becomes "Attendance and leave rules"; this module is **"Company policies"**.
- **Policy library:**
  - category (lookup: Leave, Attendance, Code of Conduct, POSH, Asset, IT, Travel, Exit, Handbook, custom)
  - versions (file, or rich text)
  - effective date
  - language variants
  - audience (F4 group, or entity / location)
  - acknowledgement required (yes/no)
  - re-acknowledge on new version (yes/no)
  - status: draft / published / withdrawn
- **Publish** (`POLICY_PUBLISH` flow optional) notifies the audience (F8) and creates `POLICY_ACKNOWLEDGEMENT` obligations (F7) with reminders.
- **Acknowledgement record:** employee, version, timestamp, channel (web, mobile, kiosk), IP / device.
- **Tracking:** acknowledged percentage by unit, and the list of pending employees.
- The onboarding policy items complete automatically from acknowledgements.

**Done when** the §42 "Policy acknowledgement" test passes.

---

## M18 · Reports (§24)

**Today.**

- A report builder with saved definitions for 5 modules: attendance, employee, onboarding, leave, headcount.
- Column and filter metadata per module.
- Scope-aware.
- Daily report snapshots.

**Build.**

- **New datasets:** lifecycle, recruitment, training, exit, compliance, documents, requests, assets, payroll inputs, exceptions, audit and changes. Each module registers a dataset with its columns, filters, data classes and **as-of support**.
- **Universal filters (§24):** company, branch / location, department, designation, employee type, manager, date range, status, plus employee groups (F4) and custom fields.
- **As-of-date reporting** for history: headcount as at 31 March, the structure as it was.
- **Standard report pack:** every report named in the §24 table ships as a system report, so a tenant has them on day one without building.
- **Scheduled delivery** (email a report link, never the restricted data itself), and export audit with masking by class.
- **Consistent definitions (§30, §39):** Active Employee, New Joiner, Vacancy, Overdue and similar terms are defined once in a metric layer that the dashboards also use.
- **A Definitions page (C-48)** is generated from that layer. It says, for example, whether headcount includes trainees, contract workers or people on hold (from the employee-type attributes). Every dashboard number links to its definition.

**Done when** each §24 report exists, respects access, and dashboard numbers equal report numbers for the same scope and date.

---

## M19 · Dashboards and Action Centre (§6)

**Today.**

- Per-role dashboards with per-user widget layouts and a widget catalogue.
- Action Centre counts for approvals, corrections, OT, personnel actions, KYC, onboarding, statutory IDs and passports.

**Build.**

- **Action Centre v2** from F7: every §6 item (probation due, confirmation overdue, increment due, leave approval, attendance correction, document expiry, PF/ESIC pending, notice ending soon, clearance pending, F&F pending, recruitment action, training feedback).
- **New widgets** per module (training, compliance, documents, requests, exits, manpower, recruitment).
- **Quick actions** (§6 list), configurable per role.
- **Management dashboard:** group and company view with aggregates only (no Personal or Financial detail).
- All counts come from the metric layer (M18).

---

## M20 · Employee self-service and mobile (§25, §35)

**Today.**

- Employee home with month stats, week strip, leave balance, my requests, upcoming holidays and KYC to-do.
- Profile and KYC.
- Punch clock, leave, corrections.
- Manager "My team".
- Responsive web, no installable app.
- Login with **email, employee number or mobile** plus password (`login_lookup`, migration 0033), optional MFA, and forced password change after an admin reset.

**Build.**

- **"My" pages:** My Profile (with change requests), My Attendance, My Leave, My Training, My Documents, My Requests, **My PF/ESIC** (own statutory info + employee links only), My Policies, My Assets, My Letters/Payslips, Notifications.
- **Employee home additions (§25):** upcoming training, important notices (announcements), statutory quick links, documents needing action.
- **Mobile:**
  - an installable PWA with mobile-first layouts for the §35 tasks
  - an offline-tolerant punch queue with server-side time validation
  - push notifications later
- **Login for staff without email:** employee code + mobile OTP (rate-limited, device-bound). **Upcoming: deferred by decision D-3 (2026-10-09).** It needs an SMS provider with DLT registration. Settings → Notifications lists SMS and WhatsApp as **Upcoming**, and the roadmap holds it in Phase G. The user model already has `employee_code` and `mobile`.
- **No-SMS fallback that already exists (C-09, review O-2).** Employee number + an HR-issued initial password, with forced change on first login, works today. Quick win Q6 only adds:
  - bulk credential issue for a group
  - a printable credential slip
  - a numeric short-password option for shop-floor users (minimum length and throttling unchanged)

  Kiosk mode follows in C1. Factory workers can use the system before SMS registration completes.
- **Kiosk mode** for the shop floor (M6).
- **Regional languages** for self-service (F14).

**Done when** an employee completes each §35 task on a phone in three taps or fewer from home, and a worker without email can log in with an OTP, or with a PIN where SMS is not yet available.

---

## M21 · Contract labour and contractors (new: not in the requirements, needed for factories and logistics)

The requirements do not cover contract labour. Factories and logistics depots in India rely on it heavily, and the principal employer carries legal liability (see [03](03-industry-coverage.md)).

**Build.**

- **Contractor (vendor) master:**
  - legal details
  - CLRA licence number and validity (obligation)
  - PF and ESIC codes of the contractor
  - work order / contract period
  - headcount allowed per location
- **Contract workers.** Employment records with the employee type `CONTRACT_WORKER` and a contractor link. They use attendance and punches (same devices), gate access and training (safety), **without** leave policies or payroll unless configured.
- **Data boundary (C-11).** Contract workers are not the principal employer's employees.
  - The employee type sets `counts_in_headcount = false`, `self_service_enabled` (default off) and `payroll_by = CONTRACTOR`.
  - A **minimal default field set** applies: identity, contractor, location, attendance, training and safety documents. Bank and salary fields are hidden.
  - A consent notice is shown at enrolment.
  - The contractor's wage data stays in the contractor's monthly evidence, not on worker records.
- **Monthly contractor compliance.** The contractor uploads wage register proof, PF/ESIC challans and the ECR for its workers. HR verifies them against the attendance headcount (evidence + exceptions, M14).
- **Reports:** contract headcount vs licence limit, attendance by contractor, compliance status by contractor.
- **Contractor portal** later (contractor user type, limited to their workers).

---

## M22 · Employee relations cases (new: grievance, disciplinary, POSH)

The requirements do not cover grievances, discipline or POSH cases. Factories under standing orders and every company with an Internal Committee need case handling with the **Case data class** (named access only, never inherited by the manager hierarchy).

**Build.**

- **Case types** (lookup): grievance, disciplinary (show-cause → enquiry → order), POSH complaint (Internal Committee members only), whistle-blower.
- **Case record:** parties, confidentiality, timeline, hearings, documents, outcome, appeal, linked letter (warning or show-cause, F11), and retention.
- **Intake** through HR requests (a confidential category) or HR directly. An anonymous option is available for whistle-blowing.
- **Access:** the named case team per case only. Cases are excluded from search, reports and exports by default.

---

## M23 · Loans and advances (new, small)

These are referenced by Accounts clearance and F&F but owned by no module.

**Build.** Loan and advance types (lookup), a request (`LOAN_REQUEST` flow), approval, a schedule of recoveries (EMI) as payroll input lines (M11), outstanding balance, and an automatic F&F line and clearance item at exit.

---

## M24 · Privacy operations (§33; DPDP Act)

**Build.**

- a privacy notice acknowledgement (M17) for employees and a candidate consent (M5)
- purpose tags on data categories
- **data-principal requests** (access, correction, erasure where lawful, grievance) as an HR request category with statutory timelines (M16)
- **retention schedules** per data class and record type with purge jobs and legal hold (F10)
- breach register
- sensitive-read log for all restricted classes, extending the existing KYC access log
- processing records export

The tenant is the Data Fiduciary and the platform is the Processor; the obligations need confirming with counsel.

---

## M25 · Data quality (§30)

**Build.**

- **A rules catalogue** (each rule on/off and severity set by the tenant):
  - no line manager
  - no attendance policy, holiday calendar or leave policy
  - joining after exit
  - LWD before resignation without an exception
  - duplicate PAN, mobile or UAN
  - missing required documents by employee type
  - PF/ESIC applicability not recorded
  - inactive approver still in a flow
  - contract end passed while active
  - bank account missing for an active employee
  - **absent N consecutive days without leave or OD** (absconding detection, C-41)
- **Nightly evaluation** plus on-save checks. Results become `DATA_QUALITY` obligations owned by HR in scope, with a fix link each.
- **Data-quality dashboard** with a trend.

---

## Cross-cutting sections of the requirements and where they are handled

| Section | Handled by |
|---|---|
| §5 Common business rules | F6 (reject reason), F7 (pending in action list), F1 (role visibility), F15 / F17 (history), F10 (proof), F5 (HR-changeable rules) |
| §26 Notifications, reminders and escalation | F7 + F8, with the §26 table as the base-pack default |
| §27 Approval framework | F6 (every listed process is a request type) |
| §28 History and change tracking | M2 history timeline, F15 config audit, personnel actions, document versions (F10) |
| §29 Exception handling | F9 + module rules (no manager → M25 / F6 fallback, no-show → M5, LWD change → M13, …) |
| §31 Search and navigation | F17 |
| §33 Privacy and confidentiality | F1 data classes, M24 |
| §34 Integrations | F19 |
| §36 Complete employee journey | Every step owned by a module above; the end-to-end journey test in [04](04-delivery-roadmap.md) |
| §38 UI/UX | F17 navigation, design system rules (docs/ui), §38 checklist in the definition of done |
| §41 Decisions before development | [05-critique.md](05-critique.md), "Decisions needed" |
