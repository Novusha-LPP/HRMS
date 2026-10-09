# Enterprise HRMS completion plan

**Version 1.5, 2026-10-09.**

- v1.1: the draft was critiqued.
- v1.2: every claim was re-verified against the code, every section of the requirements was traced, and the schedule was optimised ([05](05-critique.md#second-review-v12-verification-against-the-code-requirements-tracing-optimisation)).
- v1.3: your decisions are recorded. **Payroll runs inside the HRMS**; the Admin signs off access; SMS is Upcoming; device adapters are deferred. The payroll scope was critiqued ([05](05-critique.md#third-review-v13-payroll-inside-the-hrms)).
- v1.4: **no shift concept** (punch any time, total time counted), and **every rule is per entity, including whether it can be bypassed**. Critiqued in [05](05-critique.md#fourth-review-v14-no-shifts-everything-per-entity-bypass-by-choice).
- v1.5: **a single developer** builds it (one release train, R0–R11), **payroll is calculated every day** and goes live after two clean month-ends, and **the Admin assigns the Payroll Reviewer**. Critiqued in [05](05-critique.md#fifth-review-v15-one-developer-daily-payroll-admin-assigned-reviewer).

**Source:** Suraj Group *Enterprise HRMS — Business Requirements & Business Logic Master Document v2.0* (17 Sep 2026). Section numbers (§) refer to it.
**Relationship to other documents:** [docs/architecture](../architecture/) describes the *target design*. This plan is the *build programme* from the code as it is today to a business-complete, fully configurable product.

## The goal

Every process in the requirements works end to end for any organisation (a factory, a freight forwarder, an IT firm, a hospital, a 20-person office or a 50,000-person group). **Authorised people (tenant administrators, HR, managers, accounts, admin/IT) run and change it entirely from the UI**, without a developer, code changes or SQL.

## Documents

| File | Contents |
|---|---|
| [01-platform-foundations.md](01-platform-foundations.md) | The 19 shared capabilities that make every module configurable (roles, masters, custom fields, groups, policies, workflows, reminders, notifications, exceptions, documents, letters, numbering, import, terminology, governance, packs, search, entitlements, integrations), and the Settings console |
| [02-modules.md](02-modules.md) | Every module from §1 (plus contract labour, ER cases, loans, privacy, data quality): today → build → configurable from UI → flows → reports → access → done when |
| [03-industry-coverage.md](03-industry-coverage.md) | How factories, logistics, IT, retail, healthcare, construction and others are covered, including each Suraj Group company |
| [04-delivery-roadmap.md](04-delivery-roadmap.md) | Phases, work packages, Must/Should/Later, effort, streams, milestones, engineering rules, definition of done |
| [05-critique.md](05-critique.md) | The critique (nine lenses, 38 findings); the second review (9 code corrections, 11 requirement gaps, 6 optimisations); the payroll review (16 findings); the §41 decision split; residual risks; and the **decision status** |

## Principles

1. **One employee record from joining to exit** (requirements philosophy). Information entered once flows through the whole journey (§43).
2. **Configuration, not code.** Every business rule is a setting with an owner, an effective date, a version and a history. See the contract below.
3. **Effective-dated everything.** Changes apply from a date; the past stays reportable as it was (§28, §30).
4. **Statutory values are verified data** (critique C-10). Rates, ceilings, due dates and eligibility rules carry a source, who verified them and when. Verification expires, and tenants confirm before activation. The HRMS supports compliance; it is not the legal authority (§20).
5. **Industries differ by packs and settings, never by code branches** ([03](03-industry-coverage.md)).
6. **Nothing that works is thrown away.** The approval flows, leave ledger, holiday calendars, attendance policies, recruitment pipeline, encryption and jobs runner are extended, not replaced.
7. **Safe change.** Simulation before wide-impact publishes; parity checks and shadow mode before replacing a mechanism; expand/contract migrations, because the testing database holds real data.
8. **Least privilege for data *and* settings.** Access is by scope and data class. Settings are scoped too, and nobody edits their own sensitive record.
9. **Every rule is per entity, and the entity decides** (D-16). Each company sets its own attendance hours, notice period, probation, reminders and other rules. Each company also chooses, rule by rule, whether a rule can be bypassed: directly, with a reason, with approval, or not at all. The only fixed thing is that every bypass is recorded.
10. **No shifts** (D-15). People punch in at any time, and the system counts the total time worked against each entity's hour rules.

## The no-code administration contract

A module is not done until all twelve hold. This is the test of "complete, dynamic and manageable from the UI".

| # | Every module must… | Provided by |
|---|---|---|
| NC-1 | Keep every list (types, reasons, categories, status labels) editable in Settings | F2 Masters |
| NC-2 | Let HR add fields and arrange forms, including required-field rules by employee type | F3 Custom fields |
| NC-3 | Express each rule as a scoped, effective-dated, versioned policy with simulate and explain | F4 Groups, F5 Policies |
| NC-4 | Route every approval through the configurable engine (resolvers, conditions, SLA, delegation) | F6 Workflows |
| NC-5 | Turn every due date into an obligation with editable reminders and escalation | F7 Obligations |
| NC-6 | Send every message from an editable template, with recipients and channels chosen by HR | F8 Notifications |
| NC-7 | Let each entity choose, rule by rule, whether and how a rule can be bypassed, and record every bypass | F9 Bypass |
| NC-8 | Generate its letters and documents from editable templates, and keep document versions | F10, F11 |
| NC-9 | Grant every action through a permission that the role builder can grant, scoped | F1 Access |
| NC-10 | Offer import templates, bulk actions and permission-checked exports | F13 Import |
| NC-11 | Show history for every record, and change history for every setting | F15, F17 |
| NC-12 | Be switchable on or off per tenant and per company, and use the tenant's terminology | F14, F18 |

## Who administers what (default role templates; each tenant can re-cut them)

| Person | Maintains from the UI |
|---|---|
| Platform operator (the vendor) | Tenants, licensed modules, packs, platform health. **No tenant employee data.** |
| Tenant administrator | Roles and access, modules on/off, numbering, terminology, branding, integrations, setup health, configuration bundles |
| HR Head | Attendance, leave, lifecycle and exit policies; workflows; reminders; notification and letter templates; document types; masters; company policies |
| HR Executive (scoped to a company or location) | Daily operations; their company's attendance rules, holidays and bypass settings if granted |
| Department manager | Team approvals, probation reviews, team reports |
| Payroll Administrator / Approver (Accounts) | Pay components, structures and formulas, pay groups and calendars, monthly pay runs and approval, statutory rule values (with the reviewer), tax declaration windows, bank file formats, GL mapping, F&F runs |
| Payroll Reviewer (assigned by the Admin, D-13) | Checks statutory values and their sources, golden test cases, each month-end comparison, and optionally each pay run before lock |
| Admin / IT | Asset register and types, IT and Admin clearance items, devices |
| Compliance owner | Establishments, statutory rule values (with source), obligation calendar, evidence |
| Employee | Own profile (with approval for protected fields), requests, preferences, acknowledgements |

## Where things stand today (2026-10-09)

| Area | Built | Configurable from UI today | Biggest gap |
|---|---|---|---|
| Organisation | Mostly | Companies, departments, locations, jobs, ID schemes | Grades, positions, cost centres have no screens; registrations; org chart |
| Access and roles | Partly | Role *assignments* and scopes | **Role permissions are hard-coded** (`core/authz.py`); the menu uses role names |
| Employee master | Partly | No | Profile sections, service dates, custom fields, action wizards (only transfer has a screen); **personnel actions apply with no approval** |
| Employee 360 | Partly (side sheet) | — | Full page, all module tabs, history timeline |
| Onboarding | Partly | No (templates through the API only) | Template UI, auto-completion, pre-joining portal |
| Manpower | Partly (approved openings, position limits) | Opening approval | Headcount plan, replacement link |
| Recruitment | Mostly | Pipeline stages | Interviews, offers, duplicate check, privacy |
| Attendance | Mostly (already duration-based) | Policies, holiday calendars, correction / OT flows | Per-entity hour thresholds as the main rule, punch import, OD/WFH, period close, pay periods |
| Leave | Mostly | Rich (types, buckets, policy sets) | Days-worked accrual; application rules exist only for legacy-imported policies |
| Approvals | Partly | Flows for 4 request types, named approvers | Resolvers (manager, HOD, role in scope), all other request types including personnel actions |
| Lifecycle | Backend only | No | Due dates, reminders, review forms, letters |
| Exit | Backend actions only | No | Exit case, clearance, F&F, letters |
| PF/ESIC compliance | Statutory IDs only | No | Control centre, establishments, checklist, evidence, links |
| Documents | KYC uploads | No (fixed types) | Types master, versions, expiry, retention |
| Reports | 5 datasets with a builder | Yes, builder | Datasets for the other modules, as-of reporting |
| Dashboard | Mostly | Widget layouts | Action Centre items for missing modules |
| Self-service | Partly; login by email, employee number or mobile | — | My training / documents / requests / PF-ESIC / policies; OTP login; bulk credentials for shop floor |
| Training, Assets, HR requests, Company policies, Notifications, Search | **Not built** | — | Whole modules |
| **Payroll** (decided inside the HRMS, D-2) | **Not built** (empty `modules/payroll/`) | — | Compensation, pay run, statutory calculators, TDS, payslips, bank and statutory files, F&F |
| KPI | **Excluded by your decision (2026-09-21)** | — | Hooks kept; decision D-4 |

## The release train (one developer)

One developer builds the plan, so the order *is* the plan ([04](04-delivery-roadmap.md#single-developer-release-train-d-10)). Every Must comes before any Should, and the slowest clock (payroll's real month-ends) starts early.

| Release | What arrives |
|---|---|
| R0 | Commit everything, move testing off the live folder |
| R1 | Quick wins: promotion / confirmation / notice / separation screens, onboarding templates, grades / positions / cost centres, PF/ESIC links, shop-floor logins |
| R2 | Admin-signed roles (incl. Payroll Reviewer), editable lists, per-entity bypass rules |
| R3 | Time office: per-entity hour rules, pay calendars, punch import, month close, days-worked leave |
| R4 | Payroll engine **calculating every night in shadow**; month-end comparison with the current payroll starts |
| R5 | Reminders and approvals: probation, confirmation, promotions, transfers, salary revisions |
| R6 | Payslips, bank and PF/ESIC files, bank change with cooling-off. **Payroll goes live after two clean month-ends** |
| R7 | Full profile, letters, documents, Employee 360, import wizard, data quality |
| R8 | Assets, exit with clearance and calculated F&F, compliance centre |
| R9 | HR requests, announcements, company policies, PWA, training |
| R10 | Reports and definitions, tax year-end |
| R11 | Should list (groups, onboarding v2, recruitment v2, OD/WFH, contract labour, cases, packs, dashboards, privacy, hardening) |
| Later | SMS / WhatsApp / OTP, device adapters, SSO, KPI, … |

**Timing.** The Must work (R0–R10) is about 139 traditional pair-weeks, which is several years for one person without AI. At this project's measured pace (about 73,000 lines in its first 16 days, by one developer with AI), the estimate is **about 4–6 months**. Indicative dates:

- in-house payroll live with the **February–March 2027** payroll
- the Must list done by **February–April 2027**, plus UAT

**These dates are re-measured after R2.** What AI cannot speed up: real month-ends, the Reviewer's and HR's time, data reconciliation, and decisions.

**How this maps to the requirements' own phases (§37).** The content is the same; the order follows dependencies and payroll's calendar.

| §37 phase | Where it is here |
|---|---|
| 1 Core HR | R1, R7 |
| 2 Daily HR | R3, R5, R9 |
| 3 Workforce | R8–R9 (training, assets); recruitment v2 and manpower in R11; KPI excluded (D-4) |
| 4 Exit and compliance | R8 |
| 5 Payroll and management | R4, R6 (payroll early, because it needs real month-ends); R10 reports |
| 6 Expansion | Multi-company already built; the rest is Later |

## Decision status

The full table is in [05](05-critique.md#decisions-status-as-of-2026-10-09).

**Decided on 2026-10-09:**

- **D-1:** the Admin signs off the access matrix
- **D-2:** payroll inside the HRMS
- **D-10:** a single developer
- **D-11:** settled by the release order: time office and payroll first, approvals right after
- **D-13:** the Admin assigns the Payroll Reviewer
- **D-14:** payroll is calculated every day; go-live after two clean month-ends
- **D-15:** no shift concept
- **D-16:** every rule per entity, with bypass chosen by the entity
- **D-17:** late and early marks are optional; each company decides whether it wants them

**Deferred:**

- **D-3:** SMS, WhatsApp and OTP (Upcoming)
- **D-12:** the device list (adapters are Later; punches are imported meanwhile)

**No decisions are open.** One recommendation remains (S-1): name a backup person who can deploy and restore.
