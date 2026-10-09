# 4 · Delivery roadmap

This is the order of work, the work packages (WP), their sizes, the single-developer release train, the engineering rules, the §42 traceability and the definition of done.

**v1.5 (2026-10-09)** records your decisions:

- D-1: Admin signs off the access matrix
- D-2: payroll inside the HRMS
- D-3: SMS is Upcoming
- D-12: device adapters are deferred
- **D-15: there is no shift concept**; people punch any time and the total time is counted
- **D-16: every rule is set per entity**, and each entity decides whether and how its rules can be bypassed
- **D-10: a single developer** builds it, so the plan is one release train
- **D-13: the Admin assigns the Payroll Reviewer** who checks the payroll calculations
- **D-14: payroll is calculated every day**, and goes live after two clean month-ends

Critique and review IDs appear in brackets ([05](05-critique.md)).

**Sizes** are for one pair: one backend and one frontend engineer, with QA support. They are indicative.

| Size | Duration |
|---|---|
| S | ≈ 1 week |
| M | 2–3 weeks |
| L | 4–6 weeks |
| XL | 7–10 weeks |

**Priority tags (C-22):**

- **Must**: needed for SURAJ to pass the §42 checklist, now including in-house payroll
- **Should**: needed for other organisations, or strongly expected
- **Later**: expansion or deferred by decision

---

## Decision status

| ID | Decision | Status |
|---|---|---|
| D-1 | Access matrix sign-off | **Decided: the Admin signs off** (F1) |
| D-2 | Payroll inside or outside | **Decided: inside the HRMS** (M11, Payroll work packages P1–P7) |
| D-3 | SMS / WhatsApp provider | **Deferred: Upcoming** (Phase G); in-app and email meanwhile |
| D-12 | Attendance device list | **Deferred**: device adapters become C7 (Later); punches import meanwhile |
| D-15 | Shifts | **Decided: no shift concept.** Punch any time; total time is counted; per-entity duration rules (M6) |
| D-17 | Late / early marks | **Decided: optional per company.** Reference in / out times and grace are set only by companies that want late and early marks (M6, C1) |
| D-16 | Per-entity rules and bypass | **Decided: everything is per entity**, including notice periods. Each entity sets each rule's bypass mode (F9). |
| D-10 | Team size | **Decided: a single developer.** One release train, R0–R11 (below) |
| D-11 | Lifecycle first or time office first | **Settled by the release train:** time office and payroll engine first (payroll needs real month-ends), lifecycle approvals right after (R5). Tell me if you want R5 before R3. |
| D-13 | Payroll reviewer | **Decided: the Admin assigns a Payroll Reviewer** in the app (a role, F1). The reviewer checks statutory values, the golden test cases, each month-end comparison and, if the entity wants, each pay run before lock. |
| D-14 | Payroll go-live | **Decided: payroll is calculated every day.** Go-live is not a chosen month: it is the first month after two consecutive month-ends where the daily calculation matches the current payroll (signed off by the Reviewer). |

---

## Phase 0 · Stabilise, and a gate before new code

| WP | Work | Size | Tag |
|---|---|---|---|
| 0.1 | Commit all uncommitted work in reviewed batches (over 100 files on 2026-10-09, migrations 0044 onward). Reconcile `/home/aiserver/HRMS` with `origin/main`. CI green. Another session was changing the live folder while this plan was written (theme migration 0049), so coordinate the commit order. | M | Must |
| 0.2 | Testing-site cut-over to the deploy stack (`docs/ENVIRONMENTS.md`). This needs you: release tag, secrets, tunnel, sudo. | S | Must |
| 0.3 | No open decisions remain. **The Admin assigns the Payroll Reviewer (D-13)** and names a backup person (S-1). **Collect the current payroll's last 3 months of registers and its component list now**: the parallel run (P7) compares against them. | — | Must |

**Gate (C-31).** Until 0.2 is done, `/home/aiserver/HRMS` *is* the live testing site. No Phase A code is written there.

---

## Quick wins (C-01)

| WP | Work | Size | Tag |
|---|---|---|---|
| Q1 | Wizards for promotion, confirmation, probation extension, designation change, notice, separation, rehire and manager change, on the existing backend. They apply immediately for HR with `people.write`, as transfer does today; approval routing is added by A6. | M | Must |
| Q2 | Onboarding template editor UI on the existing API | S | Must |
| Q3 | Grades, positions and cost centres: API and UI | M | Must |
| Q4 | PF/ESIC official links page, with employee and employer/HR groups separated | S | Must |
| Q5 | Global employee search (Ctrl/⌘+K) | S | Should |
| Q6 | Shop-floor login on what exists: bulk initial passwords, printable credential slips, numeric short-password option (O-2) | S | Must |

**Until A6 lands**, limit `people.write` to a few senior HR users. Every action is already kept in history.

---

## Phase A · Configurable core

| WP | Work | First consumer | Size | Tag |
|---|---|---|---|---|
| A0 | Parity harness for permissions and lookup codes (C-02, O-1) | A1, A2 switches | S | Must |
| A1 | Access control builder, menu by permission, scoped settings (C-49), no self-edit of sensitive data (C-35), **Admin sign-off of the matrix (D-1)** | Admin/IT, HR Executive, **Payroll Administrator / Approver** roles | L | Must |
| A2 | Masters and lookups; enums → lookups | Employee type | M | Must |
| A3 | Condition builder; employee groups with dated membership (C-30). **Now Should**: with every rule per entity (D-16), groups are only for companies that need finer targeting. | Attendance and leave policy by group | L | Should |
| A4 | Policy framework, **lean first**: entity layer + employee override, explain, simulation; adapters for attendance and leave (O-1); native lifecycle policy. Unit and group layers come with A3. | Probation per entity | M | Must |
| A5 | Obligations, reminders (digest, incremental), Action Centre v2; in-app and email notifications | Probation and confirmation reminders | L | Must |
| A6 | Workflow v2: resolvers, conditions, parallel stages, SLA, quick decisions, batch requests, **approval for personnel actions and salary revisions** | Promotion and confirmation approvals | L | Must |
| A7 | Bypass framework (F9): per-entity bypass modes per rule, bypass permissions, the automatic bypass record, the Settings matrix | Notice shortfall, correction after close | M | Must |
| A8 | Settings console shell, configuration audit, setup health | — | M | Should |

---

## Phase B · Core HR complete

| WP | Work | Size | Tag |
|---|---|---|---|
| B1 | Profile sections, nominees, custom fields, form designer; concurrent employment if D-6 says yes | L | Must |
| B2 | Lifecycle module complete; letters and numbering | L | Must |
| B3 | Documents engine | M | Must |
| B4 | Employee 360 page and history timeline | M | Must |
| B5 | Onboarding v2: auto-completion, pre-joining portal (email OTP) | L | Should |
| B6 | Import wizard for all other entities (people with history, balances, YTD payroll openings), migration playbook, data-quality rules | L | Must |
| B7 | Self-service profile change; **bank change with payroll cooling-off** (PY-6) | M | Must (because of payroll) |

---

## Phase C · Daily operations (time office)

| WP | Work | Size | Tag |
|---|---|---|---|
| C1 | **Per-entity duration rules** (full-day and half-day hours, OT threshold, optional reference times, D-15); **pay groups and pay calendars** (C-06); capture methods (web, mobile geo / selfie, kiosk); **punch import wizard (CSV / Excel)**; late and offline punches (C-18); capture privacy (C-12). The punch import is here, not in B6, because device adapters are deferred (D-12). No shifts or rosters (D-15). | M | Must |
| C2 | OD, WFH, hours permission, late penalties (only for entities with reference times), correction limits | M | Should |
| C3 | Period close, post-close adjustments, **payroll input snapshot** | L | Must |
| C4 | Leave v2: days-worked accrual after close, leave on closed dates, legacy rules generalised (O-3), sandwich, negative balance, optional-holiday choice | M | Must |
| C5 | HR requests, announcements, company policies and acknowledgement | L | Must |
| C6 | PWA with an offline punch queue (OTP login is Upcoming, D-3) | M | Must |
| C7 | Device adapters (push and pull) and device health | M | **Later (D-12)** |

---

## Phase D · Workforce

| WP | Work | Size | Tag |
|---|---|---|---|
| D1 | Manpower plan and requisitions | M | Should |
| D2 | Recruitment v2 | L | Should |
| D3 | Training | L | Must |
| D4 | Assets (before E1) | M | Must |

---

## Phase E · Exit and compliance

| WP | Work | Size | Tag |
|---|---|---|---|
| E1 | Exit, clearance, absconding flow, letters; loans and advances; F&F worksheet calculated by P6 | XL | Must |
| E2 | Compliance centre: establishments, India obligations with verified values, evidence, notices register, contribution-file upload. **It reuses the PF/ESIC files produced by P5.** | L | Must |
| E3 | Contract labour | M | Should (Must for factory tenants) |
| E4 | Employee relations cases | M | Should |

---

## Payroll work packages (new with D-2)

| WP | Work | Size | Tag |
|---|---|---|---|
| P1 | Compensation: components, calculation types and formula builder (PY-5), structures, CTC calculator, employee compensation (bitemporal), revisions via A6 | L | Must |
| P2 | Pay run engine: **daily calculation of the open period** (D-14), input snapshot from C3, compute with per-line explanation, review (variance, exceptions), recompute, approve and lock, **arrears engine** (PY-4), off-cycle runs, holds | XL+ | Must |
| P3 | India statutory calculators as pack plugins: PF, ESIC, PT, LWF, bonus, wage-base rules, **minimum-wage check** (PY-8); certified by the reviewer (D-13) | L | Must |
| P4a | TDS: regimes, declarations, monthly projection, previous-employer income, **YTD opening import** (PY-3) | L | Must |
| P7 | **Parallel-run tooling** (PY-1): import the current payroll's register, per-employee per-component difference report, explanation, and **sign-off by the Admin-assigned Payroll Reviewer** (D-13). **Go-live gate: two consecutive clean month-ends.** | M | Must |
| P5 | Outputs: payslips (F11), bank advice formats with control sheet (PY-6), PF ECR and ESIC files with validators (PY-9), accounting journal (PY-12), payroll and statutory registers | L | Must |
| P6 | F&F calculation (off-cycle), gratuity, encashment, loan recovery (with E1, M23) | M | Must |
| P4b | Year end: proof verification, Form 16 Part B data, quarterly 24Q data (PY-15). Before the first year end after go-live. | L | Must |

**In-house payroll goes live** on the first month after two consecutive clean month-ends of the daily calculation (D-14). Release R6 must be in place by then.

---

## Phase F · Reporting, packs, hardening

F-1 from v1.2 moved into the payroll work packages (P1, P5).

| WP | Work | Size | Tag |
|---|---|---|---|
| F-2 | Report datasets, metric layer and Definitions page, as-of reports, scheduled delivery | L | Must |
| F-3 | Dashboards v2 and management dashboard | M | Should |
| F-4 | Packs, setup wizard, configuration bundles, sandbox | L | Should |
| F-5 | Privacy operations (DPDP) | M | Should (Must before the tenant's DPDP obligations apply) |
| F-6 | Security track: hash-chained audit, SIEM export | M | Should |
| F-7 | Operations: per-tenant export, single-tenant restore runbook | M | Should |

---

## Phase G · Upcoming and expansion

All Later:

- **SMS and WhatsApp, and OTP login (D-3)**
- **device adapters (C7, D-12)**
- SSO and SCIM
- regional languages
- KPI (D-4)
- custom objects
- contractor portal
- e-sign
- LMS integration
- travel and expenses
- timesheets
- other countries

---

## Effort

Sizes are in traditional pair-weeks. They measure the *amount of work*; calendar time for one developer is in the release train below.

| Block | Must | Should |
|---|---|---|
| Quick wins | 8 | 1 |
| A (A3 moved to Should: groups are optional now that rules are per entity; A4 lean) | 23.5 | 7.5 |
| B | 22.5 | 5 |
| C | 17.5 | 2.5 |
| D | 7.5 | 7.5 |
| E | 13.5 | 5 |
| Payroll (incl. daily calculation, D-14) | 41 | — |
| F | 5 | 15 |
| **Total** | **≈ 139** | **≈ 43.5** |

---

## Single-developer release train (D-10)

**One developer builds the plan.** There is no parallel work, so the order *is* the plan: one release at a time, every Must before any Should.

**The order is chosen so the slowest clock starts first.** In-house payroll can only go live after real month-ends have been checked (two clean ones), and no amount of coding speeds up a calendar. So the time office and the payroll engine come early, and the engine then calculates every day in the background while the rest is built. This also settles D-11: time office and payroll first, lifecycle approvals right after.

| Release | Contents | Work (pair-weeks) | What HR, Admin and Accounts get |
|---|---|---|---|
| **R0** | 0.1 commit and reconcile, 0.2 cut-over | — | A safe testing site; development stops happening in the live folder |
| **R1** | Q1, Q2, Q3, Q4, Q6 | 8 | Promotion / confirmation / notice / separation screens, onboarding templates, grades / positions / cost centres, PF/ESIC links, shop-floor logins |
| **R2** | A0, A1, A2, A7 | 11 | Admin-signed roles (incl. Payroll Administrator, Approver and **Reviewer**), editable lists, **per-entity bypass rules** |
| **R3** | C1, C3, C4 | 10 | Per-entity hour rules, pay calendars, punch import, month close, days-worked leave |
| **R4** | P1, P3, P2 (with **daily calculation**), P4a, P7 | 28.5 | Salary structures; payroll calculated **every night in shadow**; month-end comparison against the current payroll begins |
| **R5** | A4, A5, A6 | 12.5 | Probation and confirmation reminders, approvals for promotions, transfers and salary revisions |
| **R6** | P5, B7 | 7.5 | Payslips, bank file, PF/ESIC files, journal, bank change with cooling-off. **Payroll goes live on the first month after two clean month-ends** |
| **R7** | B1, B2, B3, B4, B6 | 20 | Full profile, letters, documents, Employee 360, import wizard, data quality |
| **R8** | D4, E1, P6, E2 | 18.5 | Assets, exit with clearance and calculated F&F, compliance centre |
| **R9** | C5, C6, D3 | 12.5 | HR requests, announcements, company policies, PWA, training |
| **R10** | F-2, P4b | 10 | Report datasets and definitions, tax year-end (before the first Form 16 is due) |
| **R11** | The Should list | 43.5 | Groups, settings console, onboarding v2, recruitment v2, OD/WFH, contract labour, cases, packs, dashboards, privacy, hardening |

### How long, for one developer

| Pace | Must list (R0–R10) |
|---|---|
| Traditional (no AI help) | **Several years.** Not viable. |
| **This project's measured pace** (24 Sep → 9 Oct 2026: about 73,000 lines including 15,000 lines of tests, 49 migrations and roughly 90 traditional pair-weeks of scope, all by one developer with AI) | **≈ 4–6 months**, assuming 8–15 pair-weeks per calendar week (well below the measured ~30, to allow for payroll's harder correctness work) and 20 % of time kept for supporting live users |

Indicative dates at that pace, to be re-measured:

| What | When |
|---|---|
| R1–R3 | November 2026 |
| Daily shadow payroll (R4) | ≈ December 2026 |
| **In-house payroll live** | ≈ February–March 2027 payroll, after the December and January (or January and February) month-ends reconcile |
| Must list complete | ≈ February–April 2027, plus UAT |

**Re-plan after R2.** Compare planned and actual effort for R1 and R2. If the pace is half the assumption, every date above doubles.

**What does not get faster with AI:**

- real month-ends for the payroll comparison
- the Admin-assigned reviewer's checking time (D-13)
- HR's acceptance testing and pilots
- reconciling migrated data with HR
- your decisions

---

## §42 acceptance traceability

| §42 test | Delivered by | Release |
|---|---|---|
| Create employee | Exists; B1, B6 | Now; full at R7 |
| Convert candidate | Exists (recruitment hire) | Now |
| Change department | Exists; A6 approval, B4 history | R5 / R7 |
| Change salary | P1 + A6 | R5 |
| Apply leave | Exists; C4 | Now; full at R3 |
| Correct attendance | Exists; C3 post-close path | Now; full at R3 |
| Probation due | A4 + A5 | R5 |
| Confirmation | Q1 screens; A6 approval; B2 letter | R1 / R5 / R7 |
| Training | D3 | R9 |
| KPI | Excluded (D-4) | — |
| Issue asset | D4 | R8 |
| Resignation | E1 | R8 |
| Clearance | E1 (assets from D4) | R8 |
| F&F | E1 + P6 (calculated) | R8 |
| PF / ESIC employee and employer links | Q4 | R1 |
| Compliance evidence | E2 (files from P5) | R8 |
| Document expiry | B3 + A5 | R7 |
| Policy acknowledgement | C5 | R9 |
| HR request | C5 | R9 |
| Access | A1 + matrix tests + Admin sign-off | R2 |
| Historical report | B4 + F-2 | R10 |

---

## Engineering rules for every work package

1. **Expand / contract migrations only.** The testing database holds real employee data.
2. **Wrap working mechanisms instead of migrating them** (O-1). Replacements go through the parity harness first (C-02).
3. **Ship dark behind module switches (F18)**, then enable per tenant.
4. **The module contract.** Every module registers its permissions, data classes, lookups, facts, policy types, request types, obligation types, completion signals, notification events, report datasets, 360 tabs, widgets and import templates.
5. **Tests:**
   - unit and API tests
   - a permission matrix per role template
   - Playwright per journey, including the full §36 journey on each golden tenant from R8 onward
   - property tests for effective dating and condition evaluation
   - coverage gate (88 %)
6. **Payroll-specific rules:**
   - money is `Decimal`, never float
   - rounding rules are per component and per statute, and stored with the rule version
   - **golden payroll cases** built from published official examples and the reviewer's worked cases, run on every build
   - each payslip line keeps its calculation explanation
   - no pay run on the live testing data before the cut-over
7. **Synthetic golden tenants only:**
   - "Factory Co" (punch-any-time round-the-clock work, 26→25 pay period, contractors, days-worked leave, minimum wages, OT pay)
   - "Forwarder Co" (5 entities, field staff, inter-company transfers, mid-year joiners with previous-employer tax)
   - "IT Co" (WFH, both tax regimes)
8. **Performance budgets** (C-08, C-29), measured on 3,000 and 50,000 synthetic employees:

   | Operation | Budget |
   |---|---|
   | Action Centre (manager / HR) | p95 < 400 / 800 ms |
   | Employee search | p95 < 500 ms |
   | Monthly muster, 300 people × 31 days | < 1.5 s |
   | Nightly obligations, 50,000 employees | < 5 min |
   | Period close, 5,000 employees | < 10 min |
   | **Pay run compute, 5,000 employees** | **< 5 min** |
   | **Nightly daily-payroll calculation (incremental), 5,000 employees** | **< 10 min** |
   | Single-employee recompute | < 2 s |
   | Import validation, 10,000 rows | < 2 min |

9. **API documentation** per endpoint; **observability** per module; **an HR administrator guide** per module (Payroll gets an Accounts guide).

---

## Definition of done (per module)

- [ ] Normal process end to end
- [ ] Approval path with rejection reason and send-back
- [ ] Bypass path in each mode the entity can choose (F9), and the blocked-action message
- [ ] History: old → new, who, when, why
- [ ] Reports and dashboard numbers agree; definitions visible
- [ ] Access: matrix test passes; no self-edit of sensitive data; Admin-approved role templates
- [ ] **Every rule changeable from Settings by an authorised, correctly scoped user, with no code or SQL**
- [ ] Wide-impact rule changes show a simulation first
- [ ] Reminders and escalations fire as configured
- [ ] Import template works
- [ ] §38 UI rules and the `docs/ui` design system followed
- [ ] Phone-friendly for employee-facing parts; WCAG 2.1 AA
- [ ] Performance budgets met
- [ ] §42 tests for the module pass
- [ ] Administrator guide written
- [ ] **Payroll only:** two consecutive clean parallel-run months signed off by Accounts and the reviewer (D-13)
