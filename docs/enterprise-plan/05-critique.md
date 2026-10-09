# 5 · Critique of the plan, and what was changed

This file records five reviews:

- **v1.1:** the critique below, through nine lenses
- **v1.2:** a second review that verified every claim against the code, traced every section of the requirements, and optimised the schedule (see "Second review")
- **v1.3:** a third review of the payroll scope after decision D-2 (see "Third review")
- **v1.4:** a fourth review after the no-shift and per-entity bypass decisions (see "Fourth review")
- **v1.5:** a fifth review after the single-developer, daily-payroll and reviewer decisions (see "Fifth review")

After the first draft of files 01–04, the plan was reviewed through **nine lenses**. For each lens the question was: "which organisation, factory, industry or user would this plan fail, and how?"

1. Industry (factory, logistics, healthcare, retail, construction, IT, small company, large group)
2. User role (tenant admin, HR head, HR executive, manager, shop-floor worker, accounts, admin/IT, management, auditor)
3. Configurability: what goes wrong when HR can change everything
4. Time and data: effective dating, period close, night shifts, recomputation
5. Scale and performance
6. Security, privacy and statutory law
7. Migration and operations on a system that already holds real data
8. Delivery: scope, sequencing, team capacity
9. Fit with the requirements and with the existing code

**Severity:**

- **Critical:** would cause wrong pay or attendance, a data leak, a legal breach, or a stalled programme.
- **High:** a real organisation type could not use the module as specified.
- **Medium:** friction or rework.

**Every finding below changed the plan.** The right-hand column names where. Findings that could not be designed away are listed under residual risks at the end.

---

## 1 · Industry lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-05 | Critical | **Factories accrue earned leave by days worked**, with an eligibility threshold. The leave engine today supports only upfront and monthly accrual (`accrual_type`: `ANNUAL_UPFRONT`, `MONTHLY_PRORATE`, `NONE`). Days-worked accrual also depends on *final* attendance, so running it before the attendance close gives wrong balances. | M7: days-worked accrual runs **after the attendance period close**, and is re-run when a post-close correction changes days worked. The threshold is pack data (the Factories Act number differs from the OSH Code number; verify). |
| C-06 | High | **Pay periods are not always calendar months.** Many factories and logistics firms cut attendance on the 25th or 20th. Night shifts on the last day straddle two periods. | M6/M11: a **pay group** owns a pay calendar with a cut-off day. Attendance period = pay period. The night-shift day belongs to the shift-start date, and the period follows that date. |
| C-11 | High | **Contract workers are not the principal employer's employees.** They must not count in headcount, must not get leave or payroll unless configured, and the principal employer should hold only the data it needs. | M21: employee-type attributes `counts_in_headcount`, `self_service_enabled`, `payroll_by = CONTRACTOR`; a minimal default field set for contract workers; consent notice; contractor-owned data stays in contractor evidence, not employee records. |
| C-18 | High | **Factories and depots lose network.** Devices buffer punches; mobile punches happen offline; punches arrive days late. | F19/M6: adapters accept late punches (idempotent, by device ID + timestamp). Recompute happens until the period close. After the close, a late punch becomes a post-close adjustment. The PWA queues offline punches with device time plus a server-side plausibility check. |
| C-41 | High | **Absconding** (absent without leave for N consecutive days) is routine in factories and has a legal procedure: notices, then termination. The draft had a separation type but no detection. | M25: a data-quality rule "absent N consecutive days without leave" (N set by the tenant). M13: the absconding flow (notice letters through F11, then separation). |
| C-13 | High | **Concurrent employment.** In groups with shared services, one person can be on two companies' rolls at once. The draft handled only sequential inter-company transfer. | M2: one Person may hold **several active employments**. Each has its own attendance and leave; one is marked *primary* for self-service, with an employment switcher. Listed as decision D-6 (allow or not). |
| C-43 | High | **Biometric templates** (fingerprints, face data) are sensitive personal data. Device integrations must not copy them into the HRMS. | F19: the HRMS stores punches only, never biometric templates. Selfie punches are restricted documents with a short default retention (C-12). |

## 2 · User-role lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-35 | Critical | **HR users acting on their own record.** An HR manager with `people.write` could change their own bank account, grade or salary. Self-approval rules cover approvals, not direct edits. | F1: HR and admin permissions **never apply to the user's own employment** for Personal, Identity and Financial changes. Those go through self-service plus another approver. |
| C-49 | High | **Configuration needs scopes too.** A location HR person should edit their plant's shifts and rosters, but not the tenant-wide leave policy or another company's flows. The draft scoped *data*, not *settings*. | F1/F15: settings permissions are **scope-aware**. A configuration object (policy assignment, roster, flow route, template) carries its owner scope. Admins can edit only objects inside their scope, and tenant-wide objects need tenant scope. |
| C-26 | High | **Factory and field managers rarely open the HRMS.** Approvals stall. | F6/F8: quick decisions from a notification (signed, single-use, expiring link; mobile-friendly page). **Not allowed for sensitive request types** (salary, bank, access, F&F). |
| C-07 | High | A **"role within scope" resolver** can return 0 people (stuck) or 60 (everyone gets pinged). It also does not handle an approver who is on leave. | F6: each resolver has a completion rule (any / all / first N), a maximum fan-out warning, and a **route preview**. An approver on approved leave → their delegate, otherwise the next level (tenant setting). |
| C-50 | Medium | **Bulk actions create floods of approvals.** 300 increment letters means 300 requests. | F6/F13: a **batch request**: one approval item holding many lines, each approvable or rejectable individually, with one summary. |

## 3 · Configurability lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-03 | Critical | **Over-configurability.** Hundreds of settings, and one wrong attendance or leave policy publish affects every employee's pay inputs. HR cannot be expected to foresee every interaction. | F5: **simulation is mandatory** when a publish affects more than a threshold of employees (default 10). Settings pages use **progressive disclosure**: "Basic" shows pack defaults; "Advanced" reveals the rest. Setup health checks run on publish. Locked periods are never recomputed. Optional four-eyes approval of policy publishes (`POLICY_PUBLISH`). |
| C-04 | Medium | The architecture proposed a **CEL-style expression language**. HR administrators cannot write or test expressions safely. | F4: a visual condition builder only in v1. Expressions are reserved for platform-authored pack logic. |
| C-30 | High | **Dynamic groups rewrite history.** If "Plant 2 shift workers" changes its definition today, policies resolved for last month would silently change. | F4: group definitions are **versioned and effective-dated**, and membership is materialised **with dates**. Past dates resolve against the membership as it was then. |
| C-10 | Critical | **Statutory values shown as facts.** PF/ESIC ceilings, gratuity rules, maternity weeks and OT limits change. India's Labour Codes took effect 21 Nov 2025, and state rules are still arriving. A wrong default in a pack becomes a wrong deduction for every tenant. | A plan-wide principle (README): **statutory values are verified data**. Each value has a source, `verified_by` and `verified_on`; verification expires (default 6 months, which raises a setup-health flag); a tenant must confirm before activation; there is no automatic legal calculation without a verified rule. Applied in M7 (statutory leave), M13 (gratuity eligibility), M14 (rates and due dates). |
| C-44 | Medium | The draft named Hindi and Marathi as the first regional languages. That is a guess: the right languages depend on where each tenant's plants are. | F14: the language list is tenant demand. The first languages are a decision (D-9). |

## 4 · Time and data lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-19 | High | **Leave approved after the period close for a closed date** (common: a manager approves late). The draft locked attendance but did not say what leave does. | M7: a leave approval touching a locked date becomes a **post-close adjustment** (LOP reversal line in the next period's payroll input). It never edits locked attendance. |
| C-14 | Medium | **Which clock decides "due"?** A Dubai location (later) or a night-shift plant raises the question for reminders. | F7: due dates for employee obligations use the employee's **location time zone**; establishment obligations use the establishment's location. |
| C-29 | High | **Unified policy resolution could slow attendance computation.** Resolving six layers per employee per day for a large tenant's monthly recompute means millions of lookups. | F5: a **materialised resolution table** (employee × policy type × effective range), refreshed on assignment, group and employment events. Attendance and leave read ranges, not layers. |

## 5 · Scale lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-08 | High | **Obligation and reminder volume.** 50,000 employees × a dozen obligation types, with daily reminders, means notification spam and a slow nightly job. | F7: **digest by default** for managers and HR (one message a day). The generator is **incremental**: event-driven, plus a nightly reconciliation of changed subjects only. Done obligations are archived. Obligations are indexed per tenant and due date. Per-user caps apply. |
| — | — | **Performance budgets** were missing from the definition of done. | [04](04-delivery-roadmap.md): budgets for the Action Centre, roster grid, obligation generation, report runs and imports, measured on the golden tenants at 10× SURAJ size with `backend/perf/`. |

## 6 · Security, privacy and law lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-12 | High | **Selfies and kiosks.** Selfie punches are images of employees; kiosks allow punching on someone else's behalf. | M6: selfie retention defaults to 90 days (configurable). Face-match is opt-in with recorded consent. Kiosk sessions auto-expire, PIN attempts are throttled, and there is an anomaly report for one device punching many people in a short window. |
| C-24 | Medium | **Tamper-evident audit and SIEM export** are in the architecture but were not in the plan. Enterprise buyers ask for them. | [04](04-delivery-roadmap.md): a security track WP (hash-chained audit log, SIEM export, access review evidence) in Phase F. |
| C-09 | Critical | **India SMS requires DLT registration** of the sender and every template, which takes weeks and needs the company's own documents. OTP login for shop-floor workers depends on it. Without it, factory workers cannot log in. | Roadmap: DLT registration comes first whenever SMS is picked up (since 2026-10-09 SMS is *Upcoming*, D-3). The no-SMS fallback already exists (employee-number login + an HR-issued password with forced change; review V-2). Q6 adds bulk issue and printable slips; kiosk mode follows in C1. |

## 7 · Migration and operations lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-02 | Critical | **Replacing core mechanisms on a live system.** Roles (hard-coded dictionary → database), enums → lookups, approvals, and policy resolution are all changed while the testing site serves real users from the working tree. A subtle difference locks people out or changes attendance numbers. | Roadmap: a **parity harness** for each replacement. For every user, the old and new permission sets are compared; for every employee-day of the last 3 months, the old and new policy resolution and attendance results are compared. Then **shadow mode** (new code computes, old code decides, differences are logged), then switch per tenant. No switch while there is any unexplained difference. |
| C-31 | Critical | **The working tree is the live testing site** until the cut-over. Any Phase A edit in `/home/aiserver/HRMS` reaches real users immediately. | Phase 0 gate: **no Phase A code in the live folder until the cut-over is done.** Until then, work happens in branches or worktrees and releases are deployed deliberately. |
| C-15 | High | **History migration.** New tenants (and the remaining Suraj legacy data) need prior transfers, opening leave balances and previous employment imported, and the result must be checked. EXIM data already showed duplicates and inconsistent company IDs. | F13: a **migration playbook** per tenant. Reconciliation reports (counts per entity, balances per bucket, a sample of employee timelines) are signed off by HR, and data-quality rules run immediately after import. |
| C-52 | Medium | **Per-tenant export, backup and restore** (offboarding, a tenant asking for its data, recovering one tenant's mistake) were missing. | Roadmap: an operations WP in Phase F (tenant export bundle, point-in-time restore runbook for one tenant). |

## 8 · Delivery lens

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-01 | High | **Phase A had nothing visible for HR for about 3 months.** Engines built without a real consumer drift from what HR needs, and sponsors lose patience. | 01: the rule "no foundation ships alone". 04: a **Quick-wins track** in Phase 0/A using what already exists: promotion / confirm / notice / separation wizards on the existing backend, the onboarding template editor, grade / position / cost-centre screens, and a PF/ESIC official-links page. Each Phase A WP ends in a user-visible screen. |
| C-22 | Critical | **Capacity.** About 143 pair-weeks is about 3 years for one pair. The draft did not say what to cut if the team is small. | 04: every WP is tagged **Must / Should / Later**, with a **"business-complete minimum"** cut line: the §42 checklist passing for SURAJ. |
| C-23 | High | **Payroll undecided** blocks increment letters with amounts, F&F and salary revision. | 04: decision deadline before Phase E. M11 and M13 already work in "inputs and manual F&F lines" mode either way. |
| — | Medium | **No pilot step.** Golden synthetic tenants prove the configuration model, but not real HR behaviour. | 04: each phase is piloted with one real Suraj company (logistics first, then the factory) before group roll-out. |

## 9 · Fit lens (requirements and existing code)

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| C-20 | Medium | **"Policies" means two things.** The current menu item holds attendance and leave *rules*; §23 means company policy *documents*. | M17: rules move to "Attendance and leave rules" under Settings; the new module is "Company policies". |
| C-48 | Medium | **"Consistent definitions" (§30, §39)** needs to be visible to users, not only in code. For example: does headcount include trainees, contract workers, people on hold? | M18: a **Definitions** page generated from the metric layer, linked from every dashboard number. |
| C-27 | Medium | **Employee number on rehire and inter-company transfer** (architecture D9) was not decided in the plan. | Decision D-7 below. |
| C-25 | Medium | **Accessibility** was not in the definition of done. | 04: WCAG 2.1 AA for employee-facing screens added to the definition of done. |
| — | Low | **Fit with existing code.** Several items reuse what exists rather than replacing it: configured approval flows (named stages stay valid), leave ledger, holiday calendars, employee-ID schemes, the jobs runner with checkpoints, document encryption, the KYC access log. | Recorded in each module's "Today" line. Nothing that works is thrown away. |

---

## What changed in the plan, in short

1. Each foundation ships with a visible first consumer, and a quick-wins track starts immediately (C-01).
2. Old → new mechanisms switch only after a parity harness and shadow mode (C-02), and no new work happens in the live folder before the cut-over (C-31).
3. Statutory values are verified, sourced, expiring data, never silent defaults (C-10).
4. Factory realities are explicit:
   - days-worked leave after close (C-05)
   - non-calendar pay periods (C-06)
   - offline and late punches (C-18)
   - absconding (C-41)
   - contract workers' data boundary (C-11)
   - biometric data never stored (C-43)
5. Settings are scoped like data (C-49). HR cannot edit their own sensitive record (C-35).
6. Simulation is mandatory for wide-impact policy changes, and settings use progressive disclosure (C-03).
7. Groups and policy resolution keep history and are precomputed for speed (C-29, C-30).
8. Reminders default to digests and generate incrementally (C-08). Approvals can be quick-decided from a notification, except sensitive types (C-26).
9. SMS registration starts early. The existing employee-number login and kiosk mode are the fallbacks (C-09).
10. Must / Should / Later tags and a business-complete cut line (C-22), plus per-phase pilots with real Suraj companies.

---

## Second review (v1.2): verification against the code, requirements tracing, optimisation

After v1.1, the plan was checked three more ways:

1. every "Today" statement was re-verified against the code
2. every section of the requirements (§1–§44), and every §42 test, was traced to a WP
3. the roadmap was checked for dependency errors and wasted effort

### Corrections from the code (V)

| ID | What v1.1 said | What the code shows | Fixed in |
|---|---|---|---|
| V-1 | Personnel actions have a `PENDING_APPROVAL` status (implying an approval step) | **There is no approval.** `people.write` is treated as the approval, and the status is set and cleared in the same request. The dashboard's "Personnel actions to approve" count is always zero. §27 needs approval for promotion, transfer, salary and exit. | 01 F6, 02 M2, 04 Q1 / A6 |
| V-2 | Login is email/password; build an employee-code + PIN fallback | Login already accepts **email, employee number or mobile** (migration 0033), and forced change after an admin reset exists | 02 M20, C-09, 04 Q6 (S instead of new auth) |
| V-3 | No legal-entity rename from the tenant UI | Legal entities, locations, units, jobs and ID schemes all have PATCH. Only the tenant name is platform-console-only. | 02 M1 |
| V-4 | Optional holidays and back-dating / document rules missing | Optional holidays exist on calendars. Back-dating, half-day, maximum-consecutive-days and document-required rules exist for legacy-imported leave policies. | 02 M7, 04 C4 |
| V-5 | "Commit the 106 uncommitted files, migrations 0044–0048" | The count moves daily (another session added migration 0049 and theme changes while this plan was written) | 04 Phase 0.1 (no hard numbers; coordinate the commit order) |
| V-6 | Onboarding v2 (Phase B) auto-completes from policies, training, assets and PF/ESIC | Those modules arrive in Phases C–E | 02 M3: completion signals plug in as each module lands |
| V-7 | M-1 "Lifecycle live" included letters | Letters are in B2 (Phase B) | 04: letters at M-2 |
| V-8 | Exit (E1) clearance pulls assets | Assets (D4) had no ordering guarantee before E1 | 04: D4 sits before E1 in the People stream |
| V-9 | Quick decisions from a notification (A6) | They need notifications (A5) | 04: A5 before A6 in the same stream |

### Requirements gaps found by tracing (G)

| ID | Requirement | Gap in v1.1 | Fixed in |
|---|---|---|---|
| G-1 | §20 PF and ESIC employer: *official notices* | Not covered | 02 M14: notices register with response due date |
| G-2 | §20 employee side: *contribution status* | Not covered per employee | 02 M14: ECR / contribution file upload marks each employee's month |
| G-3 | §4 statuses for Training and Compliance | Not stated | 02 M9, M14 |
| G-4 | §7 *Designation change* action | Missing from the wizard list | 02 M8, 04 Q1 |
| G-5 | §17 inputs: *incentives, bonuses* | Not in the payroll input snapshot | 02 M11, 04 P2 |
| G-6 | §26 reminders for recruitment (target date, inactivity) and *before training* | No obligation types | 01 F7 |
| G-7 | §36 complete employee journey | No end-to-end test named | 04 engineering rule 5 |
| G-8 | §38 UI rules | Not in the definition of done | 04 definition of done |
| G-9 | §42 user acceptance checklist | No traceability to WPs | 04 traceability table |
| G-10 | §37 implementation phases | Our phasing differed without explanation | README phase mapping |
| G-11 | §41 decisions before development | Not mapped | Table below |

### Optimisations (O)

| ID | Optimisation | Effect |
|---|---|---|
| O-1 | **Wrap, do not migrate**, the working attendance and leave policy storage. An adapter gives them explain, simulation, group targets and materialised resolution. | Removes a data migration on the most sensitive calculations; A0 shrinks from M to S; less parity risk |
| O-2 | Reuse the existing employee-number login as the shop-floor fallback | Factory workers can log in at the quick-wins stage, not after Phase C |
| O-3 | Generalise the legacy leave rule keys into the policy-set editor | Less new code in C4; one rule format |
| O-4 | **Spread Phase A over all three streams**, and balance the streams to about 50–55 pair-weeks each | First milestone (M-1) moves from about month 8 to about month 3.5; the total is unchanged |
| O-5 | Only 4 of the 15 §41 decisions block building (KPI is deferred); the other 10 are configuration inputs HR provides before each module goes live | Development does not wait for policy decisions. This is the main benefit of configurability. |
| O-6 | A "factory first" ordering option for the Time stream (D-11) | The time-office core at about month 4.5 if factory operations are the bigger pain |

### §41 decisions: which block building, which only block go-live

The requirements say the technical team must not guess company policy. Because policy is now configuration, most of these decisions are **inputs HR enters in Settings before go-live**, not blockers for development. **Since 2026-10-09 none of them blocks building**: the four that did are decided (D-1, D-2) or deferred (D-12).

| §41 decision | Blocks building? | Where it goes |
|---|---|---|
| Companies / legal entities | No: go-live input | Organisation settings. *The Suraj entity list was derived from data in September and still needs your confirmation* (including whether "Suraj Forwarders" and "Suraj Forwarders Private Limited" are one entity). |
| Branches / locations | No: go-live input | Organisation settings |
| Attendance source | Was yes; **deferred** (D-12). Punches are imported until the device list arrives. | C1 import, C7 later |
| Payroll responsibility | Was yes; **decided**: inside the HRMS (D-2) | M11, Payroll stream |
| Leave policy | No: go-live input | Leave policy sets (already configurable) |
| Probation / confirmation policy | No: go-live input | Lifecycle policy (A4) |
| Notice policy | No: go-live input | Notice and exit policy (E1) |
| Asset categories | No: go-live input | Asset types (D4) |
| KPI method | Deferred | D-4 |
| PF/ESIC ownership (HR or Accounts) | No: go-live input | Role assignment and checklist owners (E2) |
| Document retention | No: go-live input (confirm with counsel for DPDP) | Document types (B3) |
| Approval hierarchy | No: go-live input | Approval flows (A6) |
| Employee access | Was yes; **decided**: the Admin signs off the matrix (D-1) | A1 |
| Management reports | No: go-live input | Standard report pack plus the builder (F-2) |
| Integration priority | Was yes; **deferred** with D-12 | C7 |

---

## Third review (v1.3): payroll inside the HRMS

Decision D-2 (2026-10-09) puts final payroll inside the HRMS. Payroll is the one area where a silent bug becomes a wrong salary, a wrong statutory payment or a tax error for real people. So the new scope (M11, the Payroll stream in 04) was critiqued on its own.

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| PY-1 | Critical | **Trust is lost on the first wrong payslip.** A new engine must prove itself against the payroll it replaces. | P7 parallel-run tooling. **Go-live gate: two consecutive months reconciled to the rupee for every employee and component**, with every difference explained and signed off by Accounts and the reviewer (D-13). |
| PY-2 | Critical | **Statutory calculators are complex and change often**: PF and EPS split and ceilings, ESIC contribution periods, PT slabs by state, LWF periodicity, TDS rules every budget, and the Labour Codes "wages" definition affecting PF bases. | Calculators are country-pack plugins reading **verified rule tables** (C-10); golden test cases from official examples; certification by a named payroll / tax reviewer (D-13) before go-live and after every budget or rule change. |
| PY-3 | High | **Mid-year go-live breaks TDS and statutory totals**: the annual tax projection needs income and tax already deducted this year. | B6 / P4a: **YTD opening import** per employee, component and month, reconciled to the old payroll's register; previous-employer income for mid-year joiners. Go-live month is decision D-14. |
| PY-4 | High | **Back-dated changes** (revisions, late attendance corrections, leave after close) must pay or recover the difference, including PF and ESIC on arrears. | P2 arrears engine: re-compute affected locked periods in shadow, post difference lines into the current run, never edit a locked run. |
| PY-5 | High | **Payroll needs formulas** (HRA as a % of basic by city, a balancing special allowance, caps), which conflicts with the "no expressions for HR" rule (C-04). | Structured calculation types cover most cases. A restricted, type-checked formula language is available only with the `payroll.structure.formula` permission, with test cases, sample-employee preview and versioning. |
| PY-6 | Critical | **Money movement and fraud.** A bank-account change just before the pay date is the classic payroll fraud, and a wrong bank file pays wrong amounts. | Bank changes only through `BANK_CHANGE` (maker ≠ checker, step-up MFA) with a **cooling-off period** before the pay date. The bank file is generated only from a locked run, with a control sheet (count, total, hash). Download is logged. **No bank API; people upload the file.** |
| PY-7 | High | **Payroll staff would see everyone's salary**, including management. | Restricted pay groups visible only to named users; Payroll Administrator and Approver role templates separate from HR; every salary and payslip view logged. |
| PY-8 | High | **Minimum wages** (state × skill category × zone, revised several times a year) are a legal floor, and factories are most exposed. | Minimum-wage table as verified pack data; an employee skill category field; a pre-lock check that blocks or warns; a `MINIMUM_WAGE_REVISION` obligation when the pack changes. |
| PY-9 | Medium | **Statutory file formats** (ECR, ESIC upload, 24Q) change. | Formats are versioned pack data with validators; people still file on the portals (A10). |
| PY-10 | High | **Inputs change while a run is being reviewed.** | The run computes from a versioned input snapshot. Later changes flag the employee "changed since compute"; recompute is per employee; locking is blocked while flags are open. Budget: 5,000 employees in under 5 minutes. |
| PY-11 | Medium | **Negative net pay, salary holds, loan EMIs larger than net pay.** | Rules: a negative net carries the recovery forward; holds release through an off-cycle run; skipping an EMI needs approval. |
| PY-12 | Medium | **Accounting** needs the payroll cost in its books. | Journal export by GL account and cost centre, with the GL mapping in Settings; CSV first, Tally and other formats as pack data. |
| PY-13 | High | **F&F deadlines.** The Code on Wages sets a short deadline for paying dues after separation (verify the current rule). | F&F is an off-cycle run (P6), with a due date from the verified rule as an obligation (F7). |
| PY-14 | Medium | **Workers without email still need payslips.** | Payslips in the PWA (employee-number login); a bulk print per department with sealed-slip layout, logged. |
| PY-15 | High | **Year end**: proofs, Form 16, 24Q. | P4b before the first year end after go-live; statutory dates are pack data. |
| PY-16 | High | **Domain expertise.** Payroll needs a specialist, and squeezing it into three streams delays everything by about 3 months. | Recommend a **fourth pair dedicated to payroll** (D-10) and a **named payroll / tax reviewer** (D-13). |

**What changed:**

- M11 rewritten as a full in-house payroll
- a Payroll stream with P1–P7 replacing F-1
- E1's F&F calculated by P6
- B7 bank change promoted to Must (cooling-off)
- payroll request and obligation types added to F6 and F7
- Payroll Settings group
- minimum-wage and piece-rate rows in 03
- payroll rules in the engineering rules and the definition of done
- a new milestone M-6 "In-house payroll live"

---

## Fourth review (v1.4): no shifts, everything per entity, bypass by choice

**Your decisions (2026-10-09):**

- **D-15:** there is no shift concept. People punch in at any time, and the system counts the total time.
- **D-16:** the timeline is fully dynamic **per entity**. Each company sets its own rules (notice period, probation, attendance hours, reminders…), and **if a company wants to bypass a rule, it bypasses it**.

**What changed:**

- M6 rewritten as duration-based attendance per entity
- shift master, rosters, roster planner, shift swap and roster reports removed everywhere
- F9 rewritten from "approved exceptions" to **bypass modes chosen per entity per rule** (`BLOCK` / `ALLOW` / `ALLOW_WITH_REASON` / `ALLOW_WITH_APPROVAL`)
- the entity made the primary layer of the policy framework (F5)
- the notice period is set per entity, with release-early as a bypass (M13)
- C1 shrank from L to M
- A7 grew from S to M

These decisions were critiqued in turn:

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| E-1 | High | **Late and early-leaving marks (§12 statuses) need a reference time.** Without shifts they disappear. Today's Suraj and RABS policies do use 09:30–18:30-style times for late marks and OT. | The start and end times become **optional reference times per entity**, off by default for new entities. Existing policies keep them until their HR switches them off (wrap, O-1). **Confirmed by you as D-17: optional, each company decides.** |
| E-2 | Medium | **No rosters means no "who should be on duty".** An absence is only known at day end, and there is no staffing-coverage view (hospitals, security). | A residual by decision. The live "present now" board shows who is in. Duty planning stays out of scope unless you ask for it later. |
| E-3 | High | **Legal working-hour limits** (daily, weekly, continuous hours, rest between days) still apply to factories and shops even without shifts. | Optional per-entity **working-hours alerts** computed from durations (M6). They raise bypassable warnings and never block a punch. |
| E-4 | Medium | **Night allowance and women's night-work rules** need to know night hours. | Optional per-entity **night band** (for example 22:00–06:00) counting minutes worked inside it. This is a time band, not a shift (M6, M11). |
| E-5 | High | **Unlimited bypass touches money and law.** Bypassing a minimum-wage check, a payroll lock or the bank-change cooling-off can cause real loss. | Kept as your decision: every rule can be bypassed if the entity chooses. The **pack default for money controls** (payroll lock, bank-change cooling-off, maker ≠ checker on bank and salary) **is `BLOCK`**, and the entity can change it. Statutory checks show a plain warning. Every bypass is recorded. |
| E-6 | Medium | **Per-entity everything multiplies settings.** A group with 8 companies maintains 8 sets of rules, which drift apart. | F15: copy settings between entities, and a side-by-side comparison of entities with differences highlighted. |
| E-7 | Low | **The bypass record is the one thing that is not optional.** | It adds no step for the user in `ALLOW` mode. The requirements need it (§5, §28), and it is the company's own protection in audits and disputes. |
| E-8 | Low | **Earlier findings mention shifts** (C-06 night shift period, C-14 night-shift plant, C-30 "shift workers", C-49 plant shifts and rosters). | Read them as: the day belongs to its first IN; groups are any employee set; settings are scoped per entity. Their substance stands. |

---

## Fifth review (v1.5): one developer, daily payroll, Admin-assigned reviewer

**Your decisions (2026-10-09):**

- **D-10:** a single developer builds the plan.
- **D-13:** the Admin assigns the Payroll Reviewer who checks the payroll calculations.
- **D-14:** payroll is calculated every day.

**What changed:**

- the multi-stream plan (O-4) and milestones M-1…M-6 are replaced by **one release train, R0–R11** (04)
- groups (A3) moved to Should, and the policy framework (A4) starts lean, because rules are per entity
- P2 gained the daily calculation
- go-live became "first month after two clean month-ends" instead of a chosen month
- a Payroll Reviewer role was added

| ID | Sev. | Finding | Change made |
|---|---|---|---|
| S-1 | Critical | **One person holds all the knowledge (bus factor).** Illness or departure stops the programme, and nobody else can run a deploy or fix payroll on pay day. | Every release ships its module guide and runbook (definition of done). Deploys are scripted (`deploy/`). Decisions are recorded in `docs/`. **Recommendation: name a backup person** with repository access who can at least deploy, restore and read the runbook. |
| S-2 | High | **Nobody reviews the code.** At this speed a subtle bug, especially in payroll, can pass unnoticed. | Hard CI gates (tests, coverage, API-doc coverage, permission matrix); an automated code review on every release; golden payroll cases; the parity harness; the human check by the Payroll Reviewer; and HR acceptance per release. |
| S-3 | High | **Live users compete with new work.** Suraj and RABS already use the testing site, so support will interrupt development. | 20 % of time is reserved for support in the estimates; fixes are batched into releases; nothing is built in the live folder (C-31). |
| S-4 | High | **Estimates for one person are uncertain.** The project's measured pace is very high but short. | Dates are ranges. **Re-plan after R2** using actual against planned. The things AI cannot speed up (real month-ends, reviewer and HR time, data reconciliation) are listed separately. |
| S-5 | Medium | **Scope creep hurts most with one developer.** | Strict order: every Must (R0–R10) before any Should (R11); new requests go to the end of the train unless they replace something. |
| DC-1 | High | **Daily payroll figures could be mistaken for final pay.** | Labelled *Provisional*; never produce payslips, bank or statutory files; only a locked month-end run does. |
| DC-2 | Medium | **Monthly statutory rules** (PT slabs, ESIC contribution-period eligibility, TDS) do not apply per day. | They are applied to the projected month, and the screen states the method. |
| DC-3 | Medium | **Calculating everyone every night costs time.** | Incremental (only employees whose inputs changed), in the jobs runner with checkpoints; budget under 10 minutes for 5,000 employees. |
| DC-4 | Medium | **Employees seeing "earned so far"** can cause disputes over provisional numbers. | Off by default; each entity decides. |
| DC-5 | High | **A daily calculation is only useful if its inputs are clean daily.** Late punch imports and late approvals change yesterday's figures. | Expected and shown: each day's figure is recalculated as inputs arrive, and the dashboard shows "changed since yesterday". The month-end lock is the only fixed point. |
| DC-6 | Medium | **One Reviewer for many entities** becomes a bottleneck at month end. | The Admin can assign a Reviewer per entity; sign-off is per entity. |

**Superseded by this review:** O-4 (three-stream balancing), the stream and milestone tables of v1.3–v1.4, the "four pairs" recommendation in PY-16, and V-7's milestone wording. The work packages and their contents still stand.

---

## Residual risks that cannot be designed away

**No plan can promise that no organisation will ever face an issue.** What the plan does promise is that a new need is met by *configuration* or by *extending a shared foundation for everyone*, never by a fork. The risks that remain:

| Risk | Why it stays | How it is managed |
|---|---|---|
| Law changes faster than packs | Labour codes, state rules and portal procedures change without notice | Verified-data model with expiry; the tenant confirms; the HRMS is explicitly not the legal authority (§20) |
| A configuration that is valid but wrong for the business | Simulation shows the effect, but cannot know intent | Pack defaults, mandatory simulation, four-eyes publish, Change history with rollback to the previous version |
| Device vendors and their protocols | Each vendor differs; some have no push API | Adapter framework plus CSV fallback; device health alerts |
| Industries not yet seen | Some unique process will appear (for example, labour camps or tips distribution) | Custom fields, groups and lookups first; custom objects (Phase G) next; a pack update after that |
| People and change management | HR teams used to Excel or the old ERP | Pilots, HR administrator guides per module, the setup wizard, in-app help |
| Team capacity | The scope is a multi-year programme | Must/Should/Later cut line; phases deliver usable modules |

---

## Decisions: status as of 2026-10-09

| ID | Decision | Status / recommendation | Affects |
|---|---|---|---|
| D-1 | **Access matrix sign-off** | **Decided: the Admin signs off** (instead of HR as §33 suggests). The default role templates are presented as an access-matrix page for Admin approval before A1 switches over; later changes and quarterly reviews are signed off by the Admin in the app. | A1 |
| D-2 | **Payroll inside or outside the HRMS** | **Decided: inside.** See M11, the Payroll stream and the third review above. | M11, P1–P7, E1 |
| D-3 | **SMS / WhatsApp provider and DLT registration** | **Deferred: Upcoming.** Shown as Upcoming in Settings, built in Phase G. In-app and email carry notifications; login uses email, employee number or mobile with a password. | C6, F8 |
| D-4 | **KPI / Performance** | Stays out; hooks kept. | — |
| D-5 | **Employee record at offer acceptance (pre-hire) or on joining day** | Pre-hire, so the pre-joining portal works before day 1. | B5 |
| D-6 | **Concurrent employment** in more than one group company | Allow it. | B1 |
| D-7 | **Employee number on rehire and inter-company transfer** | Same number on rehire; a new number per entity only if the entity's scheme demands it. | B2 |
| D-8 | **Which companies pilot each phase** | A logistics company first; Paramount Propack or RABS for the time office and the payroll parallel runs. | Pilots |
| D-9 | **First regional languages** | Based on where the plants are. | F14 |
| D-10 | **Team size** | **Decided: a single developer.** The plan is one release train, R0–R11 ([04](04-delivery-roadmap.md#single-developer-release-train-d-10)). Name a backup person for deploys and restores (S-1). | Schedule |
| D-11 | **Lifecycle first or time office first** | **Settled by the release train:** time office (R3) and the payroll engine (R4) first, because payroll needs real month-ends; lifecycle approvals right after (R5). Can be swapped on request. | Release order |
| D-12 | **Attendance device list** | **Deferred.** Device adapters become C7 (Later); punches come in through the import wizard (C1) until the list arrives. | C7 |
| D-13 | **Payroll reviewer** | **Decided: the Admin assigns a Payroll Reviewer in the app** (one per entity if wanted). The Reviewer checks statutory values, golden cases, each month-end comparison and, optionally, each pay run before lock. | P3, P4, P7 |
| D-14 | **Payroll go-live** | **Decided: payroll is calculated every day.** Go-live is the first month after two consecutive clean month-ends of the daily calculation, signed off by the Reviewer. YTD openings are imported at go-live (PY-3). | P2, P7 |
| D-15 | **Shifts** | **Decided: no shift concept.** Punch any time; total time counted; rules per entity. | M6, C1 |
| D-16 | **Per-entity rules and bypass** | **Decided:** every rule is per entity (including notice period and probation); each entity sets each rule's bypass mode. Money controls default to `BLOCK`, changeable by the entity. | F5, F9, A7 |
| D-17 | **Late / early marks** | **Decided 2026-10-09: optional, each company decides.** A company that wants them sets reference in / out times and grace; one that does not gets pure total-time rules. Existing Suraj and RABS policies keep theirs until their HR changes it. | M6, C1 |
