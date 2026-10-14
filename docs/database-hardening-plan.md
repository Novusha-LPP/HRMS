# Database plan: correct in every case (DB-1 → DB-4)

**Status:** DB-1 decisions taken 2026-10-13. W0 is built on branch `db-1-hardening` (`/home/aiserver/HRMS-db1`); nothing is on `main`. Decisions DB-D6..D12 are open (§3.2). Progress is in §11.

**Sources:**
- two audits on 2026-10-13, run on a private database migrated to 0051 and seeded with 2,000 synthetic employees
- a code survey for the concepts in §4

The live and testing data was never read.

**What "perfect for every case" means here.** For every operation the system performs (§5) and every way it can go wrong (§5.2), this plan names:
- the rule that must hold
- the mechanism that enforces it (the database first, the application where a rule spans rows or time)
- the automated check that keeps it enforced

"Perfect" is therefore a checkable state: no known gap without an owner, and every rule enforced and tested. It is not a promise that bugs can't happen; §9.7 lists what no database can guarantee.

---

## 1. Goal

1. **An invalid row can't be written.** This holds whether the row comes through the API, an import script, or raw SQL.
2. **Every derived number can be re-derived.** Balances, attendance and pay can be recomputed from stored inputs, and a nightly check proves that they still agree.
3. **Every change is attributable, and history can't be rewritten.**
4. **Each tenant's data is isolated, classified, retained only as long as allowed, and removable on request.**
5. **A new migration that breaks a convention fails CI**, so the rules hold as the schema grows.

## 2. Principles

| # | Principle | How it shows up |
|---|---|---|
| P-1 | **Guardrails before fixes** | The schema linter (W0) landed first, with today's violations frozen in a baseline that may only shrink |
| P-2 | **Measure the data before constraining it** | A read-only pre-flight (W1) counts violations on the testing data. Nothing is constrained until its count is 0 |
| P-3 | **Expand → switch → contract** | Add, move the code, and drop in a later release (roadmap engineering rule 1) |
| P-4 | **No long locks** | `NOT VALID` → `VALIDATE`, `CONCURRENTLY` indexes, a 5 s `lock_timeout` on migrations |
| P-5 | **One source of truth** | Allowed values live in Python `StrEnum`s, and a test fails if a CHECK disagrees |
| P-6 | **Every exception is written down** | Each allowlist entry in `conventions.py` carries its reason, and stale entries are reported |
| P-7 | **Re-measure, don't assume** | The perf harness runs before and after (§10) |
| P-8 | **The database enforces what it can** | Single-row rules become constraints; cross-table rules become triggers when imports could bypass the app; cross-row and time rules use race-safe app patterns, with a nightly detector |
| P-9 | **Every invariant has a detector** | Each invariant (W11) is an SQL query, run after every test module and nightly in production |
| P-10 | **Privacy by default** | Every sensitive column is classified, minimized, encrypted where it identifies a person, retained for a set period, then anonymized |
| P-11 | **Reproducibility** | A pay run, balance or report can be explained from stored, immutable inputs |

## 3. Decisions

### 3.1 Taken (2026-10-13)

| ID | Question | Decided | Why |
|---|---|---|---|
| **DB-D1** | What do the 42 actor columns (`recorded_by`, `reviewed_by`, …) reference when a background job writes them? | A per-tenant "System" account with id `00000000-0000-0000-0000-000000000000`, status `SYSTEM`, no email, no password and no employment | The PK is `(tenant_id, id)`, so that id is valid in every tenant. The existing `SYSTEM_ACTOR` writers stay unchanged, and every actor column gets a real FK. Cost: about 33 `user_accounts` read sites must ignore `SYSTEM` |
| **DB-D2** | Precision of leave quantities | **Whole or half days.** `numeric(6,1)` with `CHECK (x * 2 = trunc(x * 2))`. Accrual credits the earned-to-date amount rounded **down** to a half day, minus what was already credited (25/yr: 2, 2, 2, 2, 2, 2.5, 2, 2, 2, 2, 2, 2.5 = 25.0). Days-worked accrual (R3) uses the same rule | The smallest leave anyone takes is 0.5. Cumulative rounding never credits a day early, and keeps the yearly total exact without a stored remainder |
| **DB-D3** | Platform console access | A separate role, `hrms_platform`. `hrms_app` loses access to `platform_*` and keeps `SELECT` on `tenants` | Today a tenant request path holds DML on platform admin password hashes and on the platform audit log |
| **DB-D4** | Partitioning `punches` / `attendance_days` | Not now. Start at 50 M rows or 20 GB, or when the attendance p95 is over budget. The design is written now (W9.1, executed as W21) | Partitioning forces the partition key into the PK and every FK; at today's size that cost buys nothing |
| **DB-D5** | Where to build | **Never on `main`.** Branch `db-1-hardening` in `/home/aiserver/HRMS-db1`. Migrating testing waits for the cut-over and the user's approval | Edits in `/home/aiserver/HRMS` go live on testing. `feature/payslips` stops at 0050, so DB-1 uses 0052+; whichever branch merges second renumbers |

### 3.2 Open (needed before the release named)

| ID | Question | Recommendation | Needed by |
|---|---|---|---|
| **DB-D6** | How is a closed pay period protected? | A `pay_periods` row per legal entity and month (OPEN / CLOSED). A database trigger on every period-scoped table refuses writes dated in a closed period. A reopen is a recorded action with a reason. Changes after close become adjustments in the next open period | DB-3 (W13), with roadmap R3 "month close" |
| **DB-D7** | How long is each kind of record kept? | Proposal: payroll, attendance and leave registers, change history and KYC access logs **8 years** after the employee leaves; candidates who were not hired 1 year; raw punches 3 years after their period closes. **The periods must be confirmed by the company's legal/compliance adviser**; this plan does not establish them | DB-3 (W15) |
| **DB-D8** | What data does the testing environment hold after the cut-over? | Synthetic golden tenants (roadmap rule 7), plus at most a **masked** copy of production for import rehearsals. No real PII outside production | DB-3 (W15) |
| **DB-D9** | How are duplicate PAN / Aadhaar / bank accounts detected, given that they are encrypted? | A blind index: HMAC-SHA256 of the normalized value, under a key kept separate from the encryption key. Unique per tenant for PAN and Aadhaar; a duplicate *flag* only for bank accounts (families can share one) | DB-3 (W15) |
| **DB-D10** | How do reports and BI read data? | A read-only role, `hrms_report`, under RLS, reading only documented `rpt_*` views that exclude encrypted fields. A read replica once report load needs it | DB-4 (W18), with roadmap R10 |
| **DB-D11** | Tamper evidence for audit tables? | A nightly per-tenant hash anchor over each day's audit rows, stored append-only and copied off-site. This avoids a per-row hash chain, which would serialize every write | DB-3 (W17) |
| **DB-D12** | Erasure after retention: delete or anonymize? | **Anonymize.** Identity fields are cleared or replaced, and encrypted values and documents are destroyed; non-identifying rows stay, so aggregates still add up. Legal hold blocks it | DB-3 (W15) |

---

## 4. Concept catalogue

Every concept a production HR/payroll database needs. Each row gives the state today (verified 2026-10-13), the plan item that completes it, and the automated guard that keeps it.

### A. Structure and integrity

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-01 | Entity integrity | Every table has a PK; tenant PKs start with `tenant_id` | 100 % | — | L1 |
| C-02 | Referential integrity | Every reference has an FK, or a recorded reason | 46 uuid columns unlinked | W2.3, W2.4, W2.5 | L4 |
| C-03 | Tenant-scoped references | No row can point into another tenant | 100 % | — | L3 |
| C-04 | Business keys | Natural keys are unique (codes, names, logins, punches) | Several missing | W2.2, W2.6, W2.7 | L14, pre-flight |
| C-05 | Domain integrity | Every status/type column allows only its enum's values | 55 CHECKs, none in core HR | W3.1 | L7 |
| C-06 | Range and sanity rules | Dates ordered, quantities positive, coordinates valid | Few | W3.2 | L8 |
| C-07 | Required fields | NOT NULL wherever the business requires a value | Reviewed; one gap | W3.4 | review in PR checklist |
| C-08 | Normalization | One fact stored once; no ids hidden in text | Role scopes in JSON text; 3 leftover copies | W4.2, W4.3 | L4 |
| C-09 | Exact quantities | Money exact; leave in half days; no floats | 29 float columns | W4.1 | L6, half-day CHECK |
| C-10 | JSONB governance | Each JSONB column has a typed model, a shape CHECK and a version | 29 JSONB columns, some typeof CHECKs | W22 | L15 |
| C-11 | Naming and type conventions | `*_at` is an instant (`timestamptz`), `*_date` a calendar day, `is_*` a NOT NULL boolean | Mostly followed | W23 | L16 |

### B. Time

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-12 | Effective dating | No overlapping versions; one declared meaning of `effective_to` per table | 3 of 7 history tables guarded; two meanings undeclared | W3.2, W3.3 | L8 |
| C-13 | Business date vs instant; time zones | Instants in UTC (`timestamptz`); a work date derived from the location's time zone; a 24 h window for night shifts | Done (`business_today()`, work_date, 24 h rule) | W3.4 (`work_date` NOT NULL), W23 | L12, L16, EC tests |
| C-14 | Period close and retroactive change | Nothing dated in a closed period changes; later changes become adjustments | `attendance_days.is_locked` exists and is checked, but **nothing ever sets it**; no period entity | W13 | L19 |
| C-15 | Reproducibility | A pay run, balance or report can be explained from frozen inputs | Leave ledger yes; pay-run inputs not yet (payroll not built) | W13.4, W11 | invariant tests |

### C. Correctness under concurrency and failure

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-16 | Pessimistic locking | Balances and counters are changed under a lock | 44 `FOR UPDATE` sites, advisory locks on leave | — (keep) | race tests (EC-01, EC-02) |
| C-17 | Optimistic locking | A stale edit gets 409, never a silent overwrite | Approvals and recruitment only | W6 | W6.3 test |
| C-18 | Idempotency | A retried create never duplicates | Integrations and personnel actions only | W2.6 (punches), W14 | W14 tests |
| C-19 | State machines | Only legal status transitions, safe under races | Implicit in code; no transition tables | W12 | W12.3 test |
| C-20 | Derived-data invariants | Balances = ledger; attendance explained by punches/leave; one current assignment | Not checked | W11 | invariant runner |
| C-21 | Atomic operations, side effects | Multi-table writes are one transaction; side effects go out after commit, via the outbox | Done (integration outbox, file deletes after commit) | W11.4 (check it stays so) | invariant + review |

### D. Isolation and security

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-22 | Tenant isolation | Forced RLS, one standard policy, on every tenant table | 80/80 have RLS; 5 use non-standard forms | W5.1, W25.2 | L2, per-table probe |
| C-23 | Least privilege | Each role only what it needs; no app role can bypass RLS | App role touches platform tables | W5.3, W16 | L10, L17 |
| C-24 | Encryption of identifiers and documents | KYC identifiers and documents encrypted at rest (AES-GCM, key ids) | Done (writes encrypt only where keys are set) | W16.3 (key presence check at start) | startup check |
| C-25 | Unique or searchable encrypted identifiers | Duplicate PAN/Aadhaar detectable without decrypting | Not possible today | W15.2 (DB-D9) | unique index + tests |
| C-26 | Secrets and key rotation | Every key and password can be rotated with a runbook | Field keys rotate by key id; no runbook | W16.3 | runbook drill |
| C-27 | Injection surface | Definer functions pin `search_path`; no SQL built from input | Definer functions pinned | W16.4 | L11 + grep test |
| C-28 | Data classification | Every sensitive column labelled (PII, sensitive PII, financial) | None | W15.1 | L20 |

### E. Privacy and data lifecycle

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-29 | Retention schedule | Each record class has a retention period, applied by a job | Integration logs and snapshots only | W9.2, W15.3 (DB-D7) | job metrics |
| C-30 | Erasure, anonymization, legal hold | After retention, identity is removed unless on hold | Candidate erase only | W15.4 (DB-D12) | tests + job metrics |
| C-31 | Data-subject requests | An employee's data can be exported, corrected and (where allowed) erased | Not built | W15.5 | API tests |
| C-32 | Non-production data | No real PII outside production; masked copies only | Testing holds real data | W15.6 (DB-D8) | mask-script test |
| C-33 | Tenant lifecycle | Provision, export, offboard, purge, with proof that nothing is left | Provision + `purge_tenant.py` | W19 | catalog-driven purge check |

### F. History and audit

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-34 | Field-level change history | Who changed what, when, for every master record and role grant | Org, payroll, logins, integrations | W7.1, W7.2 | W7.2 test |
| C-35 | Immutable history | The app can't edit or delete history rows | 3 of 8 history tables | W5.2 | L10 |
| C-36 | Tamper evidence | Altered history is detectable | None | W17 (DB-D11) | anchor verification job |
| C-37 | Access logging for sensitive reads | Who looked at KYC and salary data | KYC yes, salary no | W17.2 | test |

### G. Performance and scale

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-38 | Indexing | Every FK and hot query indexed; no duplicates | 99 FKs without a leading index; 5 duplicates | W8 | L5, L9 |
| C-39 | Query budgets, N+1 | Statement and latency budgets per endpoint in CI | Perf harness; budgets planned (perf plan step 7) | W25.4 | CI budget test |
| C-40 | Pagination | Keyset pagination on every growing list | Leave list done | W25.5 | route test |
| C-41 | Partitioning and archiving | Big time-series tables partitioned and archived by rule | Design only | W9.1, W21 | size alert (W9.4) |
| C-42 | Maintenance | Autovacuum tuned, bloat and statistics watched | Defaults | W9.3, W20.4 | Grafana alerts |
| C-43 | Connections | Pooling compatible with RLS (`set_config(…, true)` only) | Direct connections | W20.2 | grep test + pooled test run |
| C-44 | Reporting separation | Reports use a read-only role and stable views, a replica when needed | Same role and tables | W18 (DB-D10) | L17, view tests |

### H. Operations

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-45 | Backup, PITR, restore drill | RPO ≤ 15 min, RTO ≤ 60 min, proven by a drill | Nightly dump only | W9.5 | backup-age alert, drill record |
| C-46 | High availability | Failover without data loss | Single instance | W20.1 (hosting decision) | failover drill |
| C-47 | Zero-downtime migrations, rollback | Expand/contract, short locks, tested downgrade | Built in W0 | — | L12, `check_migrations.py` |
| C-48 | Observability and alerting | Query stats, seq scans, bloat, long transactions, backup age, invariant and orphan counts | Prometheus/Grafana exist | W9.4, W11.3 | alerts |
| C-49 | Upgrades and extensions | Major Postgres upgrades rehearsed; extensions inventoried | None | W20.3 | rehearsal record |
| C-50 | Runbooks | A written procedure for every operational event in §5 X-cases | Partial (`RUNBOOK.md`) | W20.5 | runbook checklist |

### I. Maintainability

| # | Concept | Perfect means | Today | Plan | Guard |
|---|---|---|---|---|---|
| C-51 | Automated conventions | Schema rules in CI with a shrinking baseline | **Built (W0)** | W0 | ratchet tests |
| C-52 | Single source of truth for values | Enums drive CHECKs | Built (L7) | W3.1 | L7 |
| C-53 | Migration helpers | The conventional way is the easy way | **Built (W0.3)** | — | `test_migration_kit.py` |
| C-54 | Documentation | Table/column comments, ER diagram, data dictionary, decision records | Conventions page built | W10, W24 | L13, stale-doc check |
| C-55 | Ownership | Every table has an owning module | Implicit | W24.1 | L18 |
| C-56 | Test strategy | Invariants after tests, cross-tenant probes, role tests, property tests, golden tenants | Partial | W25 | CI |
| C-57 | Developer environment | One command for a private test database; never the live one | Manual recipe | W26 | script test |
| C-58 | Safe change on real data | Every constraint is measured on real data before it ships; cleanup is decided, not forced | Recipe only | W1.1, W1.2, W1.3 | `db_preflight.py` count per constraint (PR checklist) |

---

## 5. Case catalogue

### 5.1 Operations

Every business operation the system performs, the rule that must always hold, and how it is enforced (**DB** = by the database, **App** = by race-safe application code with a test).

| # | Case | Must always hold | Enforced by | Plan | Test |
|---|---|---|---|---|---|
| T1 | Provision a tenant | System account, roles and defaults all created, or none | App, in one transaction | W2.1, W19.1 | provisioning-completeness test |
| T2 | Create a login | One login per employee; email unique (case-insensitive, global) | DB unique keys | W2.2, W2.7 | duplicate-login test |
| T3 | Grant / revoke a role | No duplicate active grant; scopes reference real companies/units; audited | DB FKs + App merge under lock | W2.6, W4.2, W7.1 | grant race test |
| T4 | Sign in (direct, or via a connected app) | Only ACTIVE accounts; never `SYSTEM`; first app sign-in creates one login | DB unique + App | W2.1, W2.2 | concurrent first-sign-in test |
| T5 | Platform admin action | Tenant data untouched by the platform role; console audit immutable | DB roles | W5.3, W5.2 | role tests |
| T6 | Offboard a tenant | Export first; purge leaves zero rows in every table | App + catalog check | W19.2, W19.3 | purge verification |
| P1 | Hire | Person + employment + assignment + manager + login are created together; employee number unique per company | DB keys + one transaction | W2, W11 | hire invariants |
| P2 | Rehire | Same person, new employment; history kept | DB FKs | W11 (I-6) | rehire test |
| P3 | Transfer / promotion (scheduled) | Exactly one current assignment; no overlap; applied once | DB EXCLUDE + idempotency key | W3.3, existing | property test |
| P4 | Change manager | No self-manager, no cycle, no overlap | DB CHECK + EXCLUDE; cycle via invariant | W3.3, W11 (I-4) | cycle test |
| P5 | Separation | `separation_date ≥ hire_date`; login disabled; state SEPARATED | DB CHECK + state machine | W3.2, W12 | lifecycle test |
| P6 | Two HR users edit the same record | The second save gets 409 | App versioned update | W6 | W6.3 |
| P7 | Bulk import of employees | All-or-nothing per batch; re-run doesn't duplicate; every row validated by constraints | DB + `import_batches` | W14, W2.6 | re-import test |
| P8 | Same person hired twice (same PAN) | Detected before saving | DB blind-index unique | W15.2 | duplicate-PAN test |
| O1 | Create / rename a master | Code unique per tenant, case-insensitive | DB unique | W2.6 | duplicate-code constraint test per master (W25.7) |
| O2 | Archive a master that's in use | No active assignment points at an archived unit, location, job, grade or position | App guard + invariant I-5 | W11, W12 | archive-in-use test |
| O3 | Move an org unit | No cycles in the unit tree | Invariant I-4b + App check | W11 | cycle test |
| A1 | Punch (web, mobile, device) | Valid coordinates; one punch per instant and type; not dated in a closed period | DB CHECK + unique + period trigger | W3.2, W2.6, W13 | punch constraint tests (W25.7); closed-period trigger test (W13.5) |
| A2 | Re-import device punches | No duplicates | DB unique + `ON CONFLICT DO NOTHING` | W2.6 | re-import test |
| A3 | Night shift across midnight | Punches attach to the right work date (24 h window) | App rule (existing) | — | existing tests |
| A4 | Daily attendance calculation | One row per employee and day; explained by punches, leave or holiday | DB unique + invariant I-2 | W11 | invariant |
| A5 | Correction request → approval | Only legal transitions; one decision per level; history immutable | App state machine + DB append-only | W12, W5.2 | race test |
| A6 | HR direct edit of a day | Audited; blocked in a closed period | Change log + period trigger | W7, W13 | direct-edit change-row test (W7.2); closed-period test (W13.5) |
| A7 | Holiday calendar changed mid-year | No overlapping calendar assignments; past closed periods unchanged | DB EXCLUDE + period trigger | W3.3, W13 | calendar-assignment overlap property test (W25.3) |
| A8 | Attendance policy changed mid-month | No overlapping policy assignments; inclusive end date honoured | DB EXCLUDE `[]` | W3.3 | property test |
| A9 | Close / reopen a period | Writes in a closed period refused, from any path; reopen recorded | DB trigger | W13 | trigger test, raw SQL included |
| LV1 | Apply for leave (half day, across months) | Half-day steps; from ≤ to; days = sum over months; enough balance | DB CHECKs + App under lock | W3.2, W4.1, W11 (I-8) | half-day and date-range constraint tests (W25.7); invariant I-8 (W11.2) |
| LV2 | Two applications race for the last day | Only one succeeds | Advisory lock (existing) | — | `test_concurrent_leave…` (exists) |
| LV3 | Multi-level approval | Legal transitions only; each level decides once | State machine CAS | W12 | race test |
| LV4 | Cancel after approval | Balance restored exactly once | State machine + ledger | W12, W11 (I-9) | `test_cancelling_approved_leave_can_require_approval_both_ways` (exists); invariant I-9 (W11.2) |
| LV5 | Monthly accrual (run twice) | Credited once; half-day steps; yearly total exact | Idempotent per month (existing) + DB-D2 | W4.1 | accrual totals test |
| LV6 | Year-end carry forward / lapse | Closing = opening + movements; carry ≤ the policy cap | Invariant I-1 | W11 | year-end carry/lapse test; invariant I-1 (W11.2) |
| LV7 | Encashment | Half-day steps; never more than the balance; once per request | DB CHECK + lock + idempotency | W4.1, W14 | over-balance and retried-encashment tests (W14) |
| LV8 | Comp-off grant | One per employee and work date | DB unique (existing) | — | `test_comp_off_credits_the_comp_off_type` (exists); duplicate comp-off constraint test (W25.7) |
| LV9 | Leave policy reassigned | No overlap; inclusive ends | DB EXCLUDE `[]` | W3.3 | leave-policy overlap property test (W25.3) |
| AP1 | An approval flow is edited while requests are running | Running instances keep their snapshot of steps | Existing (instance.steps copy) | W22 (JSON version) | `test_four_level_corrections_and_snapshot` (exists) |
| AP2 | Delegation | `valid_until > valid_from`; revocation audited | DB CHECK + append-only events | W3.2, W5.2 | `test_delegation_upper_authority_expiry_revoke_and_audit` (exists); range constraint test (W25.7) |
| AP3 | The approver leaves | Request routed to cover, never stuck | Existing (separated approvers skipped) | — | existing tests |
| PY1 | Salary structure versioning | A published version is never edited; supersedes chain valid | Existing (status + supersedes FK) | W12 | `test_editing_a_structure_keeps_assigned_salaries_on_their_version` (exists); transition test (W12.3) |
| PY2 | Compensation revision | No overlap; CTC > 0; retro handled as arrears | DB EXCLUDE (existing) + period trigger | W13 | `test_salary_assignment_revision_and_history` (exists); retro-after-close test (W13.5) |
| PY3 | Statutory rule change | No overlapping active values; verified-by recorded | DB EXCLUDE (existing) + actor FK | W2.3 | `test_a_new_statutory_value_ends_the_old_one` (exists) |
| PY4 | Pay run | Inputs frozen; payslip explainable; re-run gives the same result | Snapshot tables (append-only) | W13.4 | reproducibility test |
| PY5 | Change after the period closed | Not applied to the closed period; becomes next period's adjustment | Period trigger + adjustment records | W13.3 | retro-after-close adjustment test (W13.3) |
| RC1 | Job opening approval | Legal transitions; salary min ≤ max | DB CHECKs (existing) + state machine | W12 | `test_department_head_raises_and_hr_approves` (exists); transition test (W12.3) |
| RC2 | Erase a candidate | Applications and events removed; blocked once hired | Cascade + guard (existing) | — | existing test |
| RC3 | Hire from an application | One application per hired employment | DB unique (existing) | — | `test_pipeline_resume_feedback_and_hire` (exists); one-hire-per-application constraint test (W25.7) |
| K1 | Submit / verify KYC | One record per employee; legal transitions; identifiers encrypted and duplicate-checked | DB unique + encryption + blind index | W12, W15.2 | duplicate-PAN test (W15.2); KYC transition test (W12.3) |
| K2 | View KYC / salary | Every view logged, append-only | Access logs | W17.2 | `test_the_access_log_is_append_only_for_the_application` (exists); salary access-log test (W17.2) |
| K3 | Store a document | Encrypted object; reference stored, never the file | Existing document store | — | existing tests |
| IN1 | Inbound employee sync | Idempotent per key; one identity per app and employee | DB unique (existing) | — | existing tests |
| IN2 | Events feed | No event skipped or duplicated per app | Existing (xid8 visibility rule) | — | existing tests |
| IN3 | Revoke an API key | Sessions issued through it stop working | Existing (`via_ok` check) | — | existing tests |
| X1 | Deploy a migration | Short locks; failure leaves a consistent revision; old code keeps working | W0.4 + expand/contract | — | `check_migrations.py` |
| X2 | Restore after a disaster | RPO ≤ 15 min, RTO ≤ 60 min | PITR + drill | W9.5 | drill record |
| X3 | Rotate a key or password | No downtime; old data still readable | Key ids + runbook | W16.3 | drill |
| X4 | Data-subject request | Export only the subject's data; erasure respects legal hold | App + classification | W15.5 | API tests |
| X5 | Retention purge | Only records past retention and not on hold; counted and logged | Job + DB-D7 | W15.3 | job tests |

### 5.2 Edge cases

| # | Edge case | Handled by | Test |
|---|---|---|---|
| EC-01 | The same request is submitted twice (double click, retry) | Idempotency key (W14) or a unique key | W14 tests |
| EC-02 | Two users act on the same row at the same moment | Row lock (balances), CAS transition (W12), version check (W6) | race tests |
| EC-03 | The client times out after the server committed | Idempotency key returns the stored response (W14) | W14 tests |
| EC-04 | A background job runs twice or overlaps itself | Advisory job lock + checkpoints (existing), idempotent per period | existing `test_jobs.py` |
| EC-05 | A migration meets live traffic | `lock_timeout` 5 s, retry procedure (W0.4) | `check_migrations.py` |
| EC-06 | A concurrent index build fails | Never skipped silently; L12 reports invalid indexes (W0 review) | `test_migration_kit.py` |
| EC-07 | A punch just after midnight on a night shift | 24 h window rule (existing) | existing tests |
| EC-08 | Leave across a month or financial-year boundary | `days_by_month` = days requested (I-8); ledger per month | W11 |
| EC-09 | 29 February and other calendar edges in accrual and tenure | Date arithmetic tests (W25.3) | property tests |
| EC-10 | A location in a different time zone from the tenant | work_date from the location's time zone (C-13) | W23 test |
| EC-11 | A device clock is wrong (punch in the future) | CHECK `punched_at <= recorded_at + 10 minutes`; anything older goes to review | W3.2 |
| EC-12 | An employee number with leading zeros or mixed case | Stored as text; unique case-insensitive per company | W2.6 |
| EC-13 | Unicode or very long names | `varchar` limits match the API schemas; NFC normalization on write | W23 |
| EC-14 | A user guesses another tenant's id | Composite FKs + RLS return nothing (C-03, C-22) | per-table cross-tenant probe (W25.2) |
| EC-15 | User input in sort/filter parameters | Allowlisted columns; no SQL built from input | grep test (W16.4) |
| EC-16 | Someone grants themselves a higher role | Grant checks the granter's scope (existing); grants audited (W7.1) | permission matrix tests |
| EC-17 | A master referenced by history is archived | History keeps the link; active rows may not point at it (I-5) | W11 |
| EC-18 | A manager reporting loop (A→B→A) | Invariant I-4 + app check on save | W11 |
| EC-19 | A retroactive salary change into a closed month | Period trigger; arrears in the next open period (W13.3) | W13 tests |
| EC-20 | A retroactive policy change | Closed periods untouched; open days recalculated | W13 |
| EC-21 | Erasure requested for someone on legal hold | Refused with a reason; retried after release (W15.4) | W15 tests |
| EC-22 | A 10,000-row import | Batched, inside `statement_timeout`; validated by constraints; resumable | W14, W25.4 |
| EC-23 | 50,000-employee accrual or nightly run | Bulk engine (existing), budget < 5 min (roadmap) | perf harness |
| EC-24 | The database fails over mid-transaction | Transaction rolled back; client retries with its idempotency key | W14 + failover drill (W20.1) |
| EC-25 | Disk fills or a table grows past its budget | Size and growth alerts (W9.4); partition trigger (DB-D4) | alert test |
| EC-26 | Encryption key missing in a deployed environment | Refuse to start (W16.3) | startup test |
| EC-27 | A wrong enum value arrives from an old client or import | CHECK rejects it (W3.1); the API returns 422 | W3.1 tests |
| EC-28 | A connected app sends an unknown employee | Logged as a possible duplicate, never auto-merged (existing) | existing tests |
| EC-29 | A pay run is repeated for the same period | Same inputs give the same result; the second run is a new version, the first is kept | W13.4 |
| EC-30 | A purge is interrupted halfway | Idempotent purge, re-runnable; verification shows what remains | W19.3 |

---

## 6. Workstreams

### DB-1 · Integrity, types, isolation, audit, indexing (W0–W10)

#### W0 · Guardrails first (built)

| Item | What | Closes |
|---|---|---|
| W0.1 | `tests/test_schema_conventions.py`: the schema linter on the migrated test DB, in CI (rules in §7) | F-25 |
| W0.2 | `tests/schema_baseline.txt`: today's violations, sorted. It fails on a new violation, and on a fixed one still listed. This is the ratchet | F-25 |
| W0.3 | `src/hrms/db/migration_kit.py`:<br>• `tenant_table()`, `enable_tenant_rls()`, `replace_tenant_policy()`, `make_append_only()`, `table_comment()`<br>• `tenant_fk()`, `add_tenant_fk()`, `check_in()`, `half_day()`, `add_check()`, `effective_range_check()`, `no_overlap()`<br>• `index(concurrently=…)`, `drop_index()`<br>Names over 63 bytes are refused; concurrent builds never skip a failed leftover | F-23, F-24 |
| W0.4 | `alembic/env.py`: `lock_timeout` 5 s, `statement_timeout` 15 min (env-overridable); one transaction per migration; `%` escaped in the database URL | F-23 |
| W0.5 | `src/hrms/db/conventions.py`: the registry (`DOMAINS`, `SOFT_REFERENCES`, `UNINDEXED_FK_OK`, `APPEND_ONLY`, `PLATFORM_ONLY`, `TENANT_CASCADE`, `NO_OVERLAP_EXEMPT`, `DOMAIN_EXEMPT`, `EFFECTIVE_END_EXCLUSIVE`, `EFFECTIVE_END_INCLUSIVE`, `ARCHIVE_UNIQUE_INCLUDES_ARCHIVED`) | P-5, P-6 |
| W0.6 | `docs/database-conventions.md`: rules, effective-date semantics, failure recovery, PR checklist | F-24 |
| W0.7 | Perf baseline (§10) | P-7 |

#### W1 · Pre-flight on real data (read-only, counts only)

| Item | What | Closes |
|---|---|---|
| W1.1 | `scripts/db_preflight.py`: read-only; refuses to write. One count per constraint planned in W2–W5 and W13–W15, plus every invariant (W11). Counts only, never names or values. `--ids` writes violating row ids to a mode-600 file | P-2 |
| W1.2 | The user runs it on testing (with approval) | P-2 |
| W1.3 | Cleanup for each non-zero count:<br>• duplicate logins → keep the most recently used, disable the rest<br>• bad status strings → map to the enum<br>• overlaps → close the older row<br>• unknown actors → the System account<br>• leave values that aren't half days → rounded per an HR decision | F-01, F-02, F-08, F-09, F-11 |

#### W2 · Keys and references

| Item | What | Closes |
|---|---|---|
| W2.1 | System account per tenant (DB-D1): migration for existing tenants, provisioning for new ones; excluded from login, user lists, active-user counts and approver pickers; a test proves it can't log in | F-02 |
| W2.2 | One login per employee: `UNIQUE (tenant_id, employment_id) WHERE employment_id IS NOT NULL`; `POST /users` → 409; the integration first sign-in uses `ON CONFLICT DO NOTHING`, then re-reads | F-01 |
| W2.3 | Actor FKs on 42 columns → `user_accounts`, `NOT VALID` then validated. `import_batches.imported_by` (varchar) goes to `SOFT_REFERENCES` | F-02 |
| W2.4 | The 4 missing references: `external_identities.user_account_id`, `onboarding_items.integration_app_id`, `integration_events.employment_id`, `integration_events.origin_app_id` | F-03 |
| W2.5 | Deliberately unlinked columns are registered with reasons (polymorphic, external, retention-pruned logs). **Done in W0.5** | F-28 |
| W2.6 | Business keys (case-insensitive; `WHERE archived_at IS NULL` where the table archives):<br>• role grants merge under a lock, and `role_assignment_scopes` gets a unique key<br>• `leave_types` code<br>• `legal_entities` name<br>• `jobs` / `grades` / `cost_centres` code<br>• `holidays (calendar, date, name)`<br>• `punches (employment, punched_at, punch_type)` for idempotent re-imports (predicate settled by W1)<br>• `employments (company, lower(employee_number))` | F-04 |
| W2.7 | Email: drop the case-sensitive duplicate index; check across tenants → 409 instead of 500 | F-06 |
| W2.8 | Tenant-delete rule: only `TENANT_CASCADE` tables cascade; `purge_tenant.py` is the offboarding path (L3) | F-07 |

#### W3 · Domain and temporal rules

| Item | What | Closes |
|---|---|---|
| W3.1 | Enum CHECKs for the 62 columns, generated from `DOMAINS`. New enums: `RecordStatus`, `OrgUnitType`, `LocationType`, `WorkerType`, `ManagerType`, `HolidayType`, `RoleScopeType`, `UserAccountStatus` (incl. SYSTEM), `Gender`, `ApprovalStatus`, `RequestType`. MIME types, free text and open vocabularies stay in `DOMAIN_EXEMPT` | F-09 |
| W3.2 | Range and sanity CHECKs:<br>• effective range per declared semantics (`>` exclusive, `>=` inclusive) on all 9 effective-dated tables<br>• leave `from_date <= to_date`, `days_requested > 0`<br>• delegation `valid_until > valid_from`<br>• balances `>= 0` where the policy forbids negatives<br>• punch latitude/longitude ranges, and `punched_at <= recorded_at + 10 minutes` (EC-11)<br>• `fte` ∈ (0,1]<br>• `separation_date >= hire_date`<br>• no self-manager<br>• `jsonb_typeof` on every JSONB column | F-10 |
| W3.3 | No-overlap exclusions with bounds matching end semantics:<br>• `'[]'` for policy, leave-policy and holiday-calendar assignments<br>• `'[)'` for `assignment_managers (assignment_id, manager_type)`<br>Property tests compare the API with the DB | F-11 |
| W3.4 | `punches.work_date` NOT NULL after backfill from the location's time zone | F-10 |

#### W4 · Data types and normalization

| Item | What | Closes |
|---|---|---|
| W4.1 | Half-day leave quantities (DB-D2):<br>(a) code: `Decimal` in the leave engine, comp-off, encashment and schemas; cumulative half-day accrual; 0.5-step input validation (422)<br>(b) migration: 26 leave/comp-off columns + `attendance_days.comp_off_days` → `numeric(6,1)` + half-day CHECK; the two OT rates → `numeric(6,3)`<br>Tests: 25 / 14 / 10 / 7 days/yr land exactly; a full-balance application is accepted | F-08 |
| W4.2 | `role_assignment_scopes` with FKs (expand + backfill + dual write); `scope_value` dropped in DB-2 | F-17 |
| W4.3 | Stop writing `user_accounts.employee_code`, `erp_system`, `erp_user_id`; drop them in DB-2 | F-18 |

#### W5 · Isolation, privileges, immutability

| Item | What | Closes |
|---|---|---|
| W5.1 | Standard policy on the 3 holiday tables, `api_keys` and `import_batches` (`kit.replace_tenant_policy`); FORCE on `import_batches` | F-12 |
| W5.2 | Append-only `approval_events`, `leave_approval_actions`, `correction_approval_actions`, `recruitment_events`, `platform_audit_log`. Candidate erasure still cascades (it runs as the owner), and a test proves it. The full suite runs as `hrms_app` | F-14 |
| W5.3 | `hrms_platform` role (DB-D3) with its own session factory; `hrms_app` loses the `platform_*` tables and keeps `SELECT` on `tenants` | F-13 |

#### W6 · Optimistic locking

| Item | What | Closes |
|---|---|---|
| W6.1 | `apply_versioned_update(row, expected_version)` → 409 `STALE_VERSION` | F-15 |
| W6.2 | `version` accepted on every master-data PATCH (org 8, people, leave 4, policy, KYC 3); optional in DB-1, required in DB-2 | F-15 |
| W6.3 | Test: A loads, B loads, A saves, B saves → 409 | F-15 |

#### W7 · Change history

| Item | What | Closes |
|---|---|---|
| W7.1 | `record_change()` for person, employment, leave type and policies, attendance policies, holidays and calendars, approval flows, **role grants/revokes** | F-16 |
| W7.2 | Test: every table in `AUDITED_TABLES` has an entity type, and its PATCH writes a change row | F-16 |
| W7.3 | Nightly orphan check for soft references → `hrms_orphan_references{column}` alert | F-27 |

#### W8 · Indexing

| Item | What | Closes |
|---|---|---|
| W8.1 | Index the 99 FKs without a leading index (79 have no index on the column at all) `CONCURRENTLY`, starting with `assignment_managers(tenant_id, assignment_id)`. Exceptions go in `UNINDEXED_FK_OK` with reasons | F-05 |
| W8.2 | Drop the 5 redundant indexes | F-19 |
| W8.3 | `ix_punches_work_date` → `(tenant_id, work_date)` | F-20 |
| W8.4 | Re-measure daily-analysis and the HR dashboard (fixes stay in perf plan step 5) | F-26 |

#### W9 · Volume, retention, operations basics

| Item | What | Closes |
|---|---|---|
| W9.1 | Capacity model: 2k × 6 months = 154 MB punches + 123 MB attendance, so 20k × 5 yr ≈ 15 + 12 GB. Partition trigger (DB-D4) and design written down | F-21 |
| W9.2 | Retention classes registered in `conventions.py`; the periods come from DB-D7 | F-21 |
| W9.3 | Autovacuum settings for high-churn tables, after measurement | F-21 |
| W9.4 | `pg_stat_statements`; Grafana panels and alerts: seq scans on big tables, dead tuples, longest transaction, backup age, table size | F-21, F-22 |
| W9.5 | PITR + restore-drill script; RPO/RTO measured (hosting is the user's choice) | F-22 |

#### W10 · Documentation

| Item | What | Closes |
|---|---|---|
| W10.1 | `COMMENT ON TABLE` for all 87 tables | F-24 |
| W10.2 | Generated ER diagram (`scripts/schema_diagram.py` → `docs/architecture/schema.md`); CI fails if it is stale | F-24 |

### DB-2 · Contract (next release after DB-1)

| Item | What |
|---|---|
| D2.1 | Drop `role_assignments.scope_value`, `user_accounts.employee_code`, `erp_system`, `erp_user_id` |
| D2.2 | `version` required on PATCH |
| D2.3 | Remove the deselection of tests that depend on legacy files |
| D2.4 | Role scopes as rows (was W4.2): table with FKs, backfill, switch the authorization query, drop `scope_value` — together, behind the permission tests |
| D2.5 | Retire `user_accounts.employee_code`, `erp_system`, `erp_user_id` (was W4.3): move the integration field mapping and the legacy scripts to `external_identities` first |
| D2.6 | The API requires `version` on every edit (the frontend already sends it) |

### DB-3 · Correct in every case (W11–W17)

#### W11 · Invariants and reconciliation

| Item | What | Concepts |
|---|---|---|
| W11.1 | `src/hrms/db/invariants.py`: a registry of named SQL checks, each returning violating row ids:<br>• **I-1** leave balance = opening + ledger movements, per employee, type and year<br>• **I-2** every attendance status is explained by punches, leave, holiday, week-off or a correction<br>• **I-3** every active employment has exactly one current assignment<br>• **I-4** no manager cycles or self-managers; **I-4b** no org-unit cycles<br>• **I-5** no active assignment points at an archived master<br>• **I-6** every employment has a person; separated employments have a separation date<br>• **I-7** approval instance status agrees with its request's status<br>• **I-8** leave days requested = sum of `days_by_month`<br>• **I-9** the leave ledger's holds and takes match application status<br>• **I-10** one current compensation per employment with a structure<br>• **I-11** every tenant has exactly one System account | C-20, C-15 |
| W11.2 | A pytest fixture runs every invariant after each API test module: any violation fails the build | C-20, C-56 |
| W11.3 | A nightly job runs them per tenant → `hrms_invariant_violations{invariant}`, alert if above 0 | C-20, C-48 |
| W11.4 | A test asserts every external side effect goes through the outbox or `session.info` after-commit hooks | C-21 |

#### W12 · State machines

| Item | What | Concepts |
|---|---|---|
| W12.1 | `TRANSITIONS` per status enum (leave, correction, personnel action, onboarding, KYC, opening, application, approval instance, employment state) | C-19 |
| W12.2 | `transition(row, to)`: `UPDATE … SET status = :to WHERE id = :id AND status = ANY(:allowed_from)`, and 0 rows → 409. Race-safe without a lock | C-19, C-16 |
| W12.3 | Tests: every enum in `DOMAINS` with a status has a `TRANSITIONS` entry; terminal states are final; property tests run random sequences | C-19 |

#### W13 · Period close and reproducibility (with roadmap R3/R4)

| Item | What | Concepts |
|---|---|---|
| W13.1 | `pay_periods (tenant, legal_entity, period_start, period_end, status, closed_at/by, reopened_at/by, reason)`, no overlap per company (DB-D6) | C-14 |
| W13.2 | `guard_closed_period()` trigger on `PERIOD_SCOPED` tables (punches, attendance days, corrections, leave applications/ledger, comp-off, compensation inputs). It refuses inserts and updates dated in a CLOSED period. Override only inside a recorded reopen (`SET LOCAL hrms.period_override`). `attendance_days.is_locked` becomes derived | C-14 |
| W13.3 | Adjustments: a change after close is written to the next open period (leave ADJUSTMENT, payroll arrears) with a link to what it corrects | C-14 |
| W13.4 | Pay-run snapshots: frozen inputs per run (attendance summary, leave, compensation, statutory values, rule versions), append-only. A re-run creates a new version | C-15 |
| W13.5 | Rule L19: every `PERIOD_SCOPED` table has the trigger | C-14 |

#### W14 · Idempotency everywhere

| Item | What | Concepts |
|---|---|---|
| W14.1 | `idempotency_keys (tenant, key, user, route, request_hash, response, status, created_at)`, PK `(tenant, key)`, kept 72 h | C-18 |
| W14.2 | Middleware for every create (POST). The same key + same body returns the stored response; the same key + a different body → 422 | C-18 |
| W14.3 | Applied to leave, punches, corrections, hires, imports, encashment and pay runs; the frontend sends a key per submit | C-18 |

#### W15 · Privacy and data lifecycle

| Item | What | Concepts |
|---|---|---|
| W15.1 | `DATA_CLASSES` in `conventions.py`: PUBLIC / INTERNAL / PII / SENSITIVE_PII / FINANCIAL per column. L20: every column matching a sensitive pattern (pan, aadhaar, bank, account, ifsc, salary, ctc, dob, birth, mobile, phone, email, address, passport, voter) is classified | C-28 |
| W15.2 | Blind indexes (DB-D9): `*_bidx` HMAC columns; unique per tenant for PAN/Aadhaar, a duplicate flag for bank accounts; backfill through `deploy encrypt-pii` | C-25 |
| W15.3 | Retention job driven by the classes and DB-D7 periods; skips anything on legal hold; counts and logs every action | C-29 |
| W15.4 | Anonymization (DB-D12): clear identity fields, destroy encrypted values and documents, keep non-identifying rows; `legal_hold` on person/employment | C-30 |
| W15.5 | Data-subject requests: export bundle of one person's data (from `DATA_CLASSES`), correction through the normal audited edits, erasure through W15.4 | C-31 |
| W15.6 | `scripts/mask_copy.py`: a masked copy for non-production (deterministic fake names, nulled identifiers, documents dropped); refuses to write to a production URL (DB-D8) | C-32 |

#### W16 · Roles, keys, injection surface

| Item | What | Concepts |
|---|---|---|
| W16.1 | Roles: `hrms` (owner/migrations only), `hrms_app`, `hrms_platform`, `hrms_report` (read-only, RLS), `hrms_backup` | C-23 |
| W16.2 | L17: application roles are NOSUPERUSER, NOBYPASSRLS, NOCREATEROLE, NOCREATEDB; no table privilege granted to PUBLIC | C-23 |
| W16.3 | Runbooks and drills: field-key rotation (key ids), blind-index key rotation (recompute), database password rotation. Deployed environments refuse to start without encryption keys (EC-26) | C-24, C-26 |
| W16.4 | Test: no f-string SQL built from request input (a grep with an allowlist); sort and filter columns are allowlisted | C-27 |

#### W17 · Tamper evidence and access logs

| Item | What | Concepts |
|---|---|---|
| W17.1 | `audit_anchors (tenant, day, table, row_count, sha256)`, append-only, written nightly; a verifier recomputes and alerts on mismatch; the anchors are copied off-site (DB-D11) | C-36 |
| W17.2 | `salary_access_log` (like `kyc_access_log`) for every read of compensation or payslips | C-37 |

### DB-4 · Scale and operate (W18–W21)

#### W18 · Reporting separation

| Item | What | Concepts |
|---|---|---|
| W18.1 | `hrms_report` role; documented `rpt_*` views (no encrypted columns) as the BI contract (DB-D10) | C-44 |
| W18.2 | Read replica and routing for heavy reports, when the budgets need it | C-44 |

#### W19 · Tenant lifecycle

| Item | What | Concepts |
|---|---|---|
| W19.1 | Provisioning-completeness test (System account, roles, defaults) | C-33 |
| W19.2 | Tenant export: every tenant table (found from the catalog), JSON/CSV with a manifest and checksums | C-33 |
| W19.3 | Offboarding: export → hold period → idempotent `purge_tenant.py` → catalog check that zero rows remain in every table | C-33 |
| W19.4 | Single-tenant restore runbook: PITR into a scratch database, then copy that tenant's rows through the export format | C-33, C-45 |

#### W20 · Operations

| Item | What | Concepts |
|---|---|---|
| W20.1 | Managed Postgres with failover (hosting decision); a failover drill | C-46 |
| W20.2 | PgBouncer (transaction pooling): a test that the app uses only transaction-local `set_config(…, true)`; the suite runs through the pooler | C-43 |
| W20.3 | Major-upgrade rehearsal runbook; extension inventory (`btree_gist`, `pg_stat_statements`, `uuid-ossp`) | C-49 |
| W20.4 | Bloat checks and `REINDEX CONCURRENTLY` schedule | C-42 |
| W20.5 | Runbooks for every X-case in §5.1, and for lock timeouts, failed migrations, period reopen and tenant purge | C-50 |

#### W21 · Partitioning (only when the DB-D4 trigger fires)

| Item | What | Concepts |
|---|---|---|
| W21.1 | Monthly range partitions on `work_date` for `punches` and `attendance_days`; PK `(tenant_id, id, work_date)`; old partitions detached and archived under the retention rules | C-41 |

### Continuous · Conventions that keep it perfect (W22–W26)

| Item | What | Concepts |
|---|---|---|
| W22 | **JSONB governance**: `JSON_DOCUMENTS` registry (table.column → Pydantic model + version); a `schema_version` key in each document; upgrade functions for old shapes; L15 | C-10 |
| W23 | **Naming and types**: L16 (`*_at` timestamptz, `*_date` date, `is_*`/`has_*` boolean NOT NULL, `*_amount`/`*_ctc` numeric(14,2), `LEAVE_QUANTITIES` numeric(6,1) + half-day CHECK); work date from the location's time zone (EC-10); NFC normalization for names (EC-13) | C-11, C-13 |
| W24 | **Ownership and documentation**: W24.1 `TABLE_OWNERS` (table → module), L18; W24.2 generated data dictionary (columns, types, comments, data classes); W24.3 decision records in `docs/adr/` (DB-D1… onward) | C-54, C-55 |
| W25 | **Test strategy**:<br>• W25.1 the suite also runs as `hrms_app`<br>• W25.2 a cross-tenant probe generated for **every** tenant table from the catalog (write as tenant A, read as tenant B → 0 rows)<br>• W25.3 property tests for effective dating, accrual and calendar edges<br>• W25.4 per-endpoint query and latency budgets in CI (perf plan step 7)<br>• W25.5 a keyset-pagination check on list routes<br>• W25.6 golden tenants (roadmap rule 7)<br>• W25.7 every new CHECK, UNIQUE, EXCLUDE and trigger gets a test that a violating row is rejected (PR checklist) | C-56, C-39, C-40, C-22 |
| W26 | **Developer environment**: `scripts/dev_db.sh` starts a private unix-socket cluster, migrates it and prints the three env vars, so nobody points tests at a shared database | C-57 |

---

## 7. Schema rules (built: L1–L14; planned: L15–L20)

| Rule | Asserts | State |
|---|---|---|
| L1 | Every table has a PK; a tenant PK starts with `tenant_id` | built |
| L2 | Every non-global table is tenant-scoped: tenants FK, RLS enabled and forced, exactly the standard policy | built |
| L3 | Tenant-to-tenant FKs include `tenant_id`; only `TENANT_CASCADE` tables cascade from `tenants` | built |
| L4 | Every uuid `*_id` / `*_by` column has an FK or a `SOFT_REFERENCES` entry | built |
| L5 | Every FK has a leading index, or an `UNINDEXED_FK_OK` entry | built |
| L6 | No `real` / `double precision` | built |
| L7 | Status-like columns are in `DOMAINS` or `DOMAIN_EXEMPT`; each CHECK equals its enum | built |
| L8 | Effective-dated tables declare end semantics, have a matching range CHECK and EXCLUDE (unless exempt) | built |
| L9 | No redundant btree index | built |
| L10 | `hrms_app` can't change `APPEND_ONLY` tables or touch `PLATFORM_ONLY` ones | built |
| L11 | `SECURITY DEFINER` functions set `search_path` | built |
| L12 | `timestamptz`, `jsonb`; no `NOT VALID` constraint or invalid index at head | built |
| L13 | Every table has a comment | built |
| L14 | Unique keys on archivable tables declare whether archived rows count | built |
| L15 | Every JSONB column is in `JSON_DOCUMENTS` and has a `jsonb_typeof` CHECK | W22 |
| L16 | Naming ↔ type conventions (`*_at`, `*_date`, `is_*`, money, leave quantities) | W23 |
| L17 | Role attributes as declared; nothing granted to PUBLIC | W16.2 |
| L18 | Every table is in `TABLE_OWNERS` | W24.1 |
| L19 | Every `PERIOD_SCOPED` table has the closed-period trigger | W13.5 |
| L20 | Every sensitive-pattern column is in `DATA_CLASSES` | W15.1 |

Every rule also reports stale registry entries, so an exception can't outlive the thing it excused.

## 8. PR checklist for any migration

- [ ] Built with `migration_kit`; names ≤ 63 bytes.
- [ ] Constraints on existing tables added `NOT VALID` → `VALIDATE`; indexes on tables with data `CONCURRENTLY`.
- [ ] Expand only; drops are scheduled for a later release.
- [ ] A new enum value goes into the `StrEnum` **and** a CHECK migration (L7). A new status also gets its `TRANSITIONS` (W12).
- [ ] Each new constraint and invariant has a `db_preflight.py` count.
- [ ] Each new constraint has a test that a violating row is rejected (W25.7).
- [ ] New columns are classified if sensitive (L20); new tables have an owner (L18) and a comment (L13); period-scoped tables get the trigger (L19).
- [ ] The schema rules pass without new baseline lines; invariants pass after the tests.
- [ ] `downgrade()` works, or the migration is listed as irreversible in `check_migrations.py`.

---

## 9. Check of the plan

### 9.1 Finding traceability: every audit finding has an owner

| F | Finding (2026-10-13 audits) | Closed by |
|---|---|---|
| F-01 | One employee can have several logins | W1.3, W2.2 |
| F-02 | 42 actor columns without FK; `SYSTEM_ACTOR` | DB-D1, W1.3, W2.1, W2.3 |
| F-03 | 4 real references without FK | W2.4 |
| F-04 | Business keys not unique | W2.6 |
| F-05 | FKs without index; `assignment_managers` hotspot | W8.1 |
| F-06 | Two global email indexes; cross-tenant clash → 500 | W2.7 |
| F-07 | Inconsistent cascade from `tenants` | W2.8 |
| F-08 | Leave days as float; accrual drift 9.9996 | DB-D2, W1.3, W4.1 |
| F-09 | 62 enum-like columns without CHECK | W1.3, W3.1 |
| F-10 | Missing range / sanity checks | W3.2, W3.4 |
| F-11 | Effective-dated tables without overlap guard | W1.3, W3.3 |
| F-12 | Holiday RLS errors on an empty tenant; non-standard policies | W5.1 |
| F-13 | App role holds DML on platform tables | DB-D3, W5.3 |
| F-14 | History tables editable | W5.2 |
| F-15 | Last-write-wins on master data | W6.1, W6.2, W6.3 |
| F-16 | Change log misses employees, leave config, policies, holidays, role grants | W7.1, W7.2 |
| F-17 | Role scopes in a JSON text column | W4.2 |
| F-18 | Leftover duplicate columns | W4.3 |
| F-19 | 5 redundant indexes | W8.2 |
| F-20 | Punch date index lacks `tenant_id` | W8.3 |
| F-21 | No growth, retention or partitioning plan | DB-D4, W9.1, W9.2, W9.3, W9.4 |
| F-22 | Nightly dump only; no PITR | W9.4, W9.5 |
| F-23 | Migrations lock tables; no lock timeout | W0.3, W0.4 |
| F-24 | No table comments / schema docs | W0.6, W10.1, W10.2 |
| F-25 | `alembic check` blind to indexes, policies, grants, integrations | W0.1, W0.2 |
| F-26 | Slow endpoints (daily-analysis, HR dashboard) | W8.4 |
| F-27 | Polymorphic references can't be FK-checked | W7.3 |
| F-28 | Integration logs deliberately unlinked | W2.5 |

### 9.2 Concept coverage

All 58 concepts in §4 name a plan item (or "—" where today's state is already complete) and an automated guard. The mechanical check in §9.5 verifies this.

### 9.3 Case coverage

All operations (§5.1) and edge cases (§5.2) name their mechanism and a plan item or existing mechanism, and a test (planned or existing).

### 9.4 Maintainability

| Question | Answer |
|---|---|
| Can a new table skip RLS, an FK, an index, a CHECK, a comment, an owner or a classification? | No. L1–L20 fail CI |
| Can an enum value be added without the database? | No. L7 compares them |
| Can a status gain an illegal transition unnoticed? | No. W12.3 tests every status enum |
| Can derived data drift silently? | No. Invariants run after every test module and nightly (W11) |
| Can a closed period be changed by an import or raw SQL? | No. The trigger is in the database (W13) |
| Does fixed debt stay fixed? | Yes. The ratchet fails on new violations and on fixed ones still listed |
| Is every exception explained, and removed when obsolete? | Yes. Every entry has a reason, and stale entries are reported |
| Where does a developer learn the rules? | `docs/database-conventions.md`, the registry and the helpers |

### 9.5 How this plan was checked

A script parsed this document and verified:
- every F-finding names items that exist, and every item it names is defined
- every concept names a plan item and a guard
- every case and edge case names a mechanism and a test
- every rule L1–L20 is defined, and every planned rule has an owning item
- every workstream item is referenced by at least one finding, concept or case

### 9.6 Gaps found while extending the plan

- **Period close.** A lock flag exists, but nothing ever sets it, and no period entity exists. Added: DB-D6, W13.
- **Duplicate identity.** Encrypted PAN/Aadhaar can't be checked for duplicates today. Added: DB-D9, W15.2.
- **Derived data.** Nothing proves that balances, attendance and assignments stay consistent. Added: W11.
- **State machines.** Transitions are only implicit in code. Added: W12.
- **Idempotency.** Only integrations and personnel actions have it. Added: W14.
- **Privacy lifecycle.** No classification, retention, anonymization or data-subject requests. Added: W15.
- **Testing environment.** It holds real PII. Added: DB-D8, W15.6.
- **Reporting.** Reports read the transactional tables with the app role. Added: DB-D10, W18.
- **Tamper evidence and salary access logging.** Added: DB-D11, W17.
- **Connection pooling.** It must stay compatible with RLS. Added: W20.2.
- **Cases without a test.** The mechanical check (§9.5) found 20 operations naming a mechanism but no test. Each now names an existing test (verified by name) or a planned one, and W25.7 makes a rejection test part of every new constraint.
- **A concept dropped in the rewrite.** "Safe change on real data" (the pre-flight) had no concept row. Restored as C-58.
- **Clashing IDs.** Leave cases were L1–L9, the same as schema rules, and recruitment cases R1–R3 the same as roadmap releases. Renamed LV, RC and IN.
- **Unverified legal claim corrected.** An earlier draft called 8 years "statutory". Retention periods are now an open decision (DB-D7), for a compliance adviser to confirm.
- **Earlier rounds** (kept): idempotent punch re-imports; autovacuum; archived rows in unique keys; tenant cascade; orphan detection; tests as `hrms_app`; role-grant merging; MIME exemptions; effective-date semantics; two extra policies; the `%` URL bug; `integration_requests` retention deletes; DB-D2 half days; the four W0 self-review fixes.

### 9.7 What no database plan can guarantee

- **Business decisions:** retention periods, erasure policy and period-close rules need the company's (and its adviser's) decisions (DB-D6, D7, D12).
- **Infrastructure:** high availability and off-site backups depend on hosting choices outside the schema (W9.5, W20.1).
- **Cross-row rules over time:** these can't be single constraints. They are enforced by race-safe code, and detected by invariants within a day if anything slips through.
- **Correct input:** a valid but wrong value (a wrong salary typed correctly) passes every rule. Approvals, audit history and reports are the defence.

### 9.8 Risks

| Risk | Mitigation |
|---|---|
| Testing data violates a new constraint | W1 runs first; `NOT VALID` + `VALIDATE` fails cleanly |
| The Decimal refactor breaks leave arithmetic | W4.1(a) ships first, behind the leave suite and the accrual equivalence test |
| The System account appears in lists | A test enumerates every user-list endpoint and count |
| Revoked privileges break a hidden path | The suite runs as `hrms_app` (W25.1) |
| The period trigger blocks a legitimate correction | Reopen is a recorded action; corrections go to the next open period (W13.3) |
| Invariant checks are slow on big tenants | Each is indexed and tenant-scoped; the nightly run is batched; tests run them on small data |
| Blind-index key leak enables guessing | Separate key, HMAC, rotation runbook (W16.3); only equality is possible, never decryption |
| Scope grows beyond one developer | Releases are independent: DB-1 stands alone, and DB-3/DB-4 follow the roadmap releases that need them (§10) |

---

## 10. Delivery

**Branch:** `db-1-hardening` in `/home/aiserver/HRMS-db1`; later releases on their own branches. Never `main` (DB-D5).

**DB-1 migrations, as built (one deploy window):**

| Migration | Contents |
|---|---|
| 0052 | System account per tenant (trigger on `tenants`), one login per employee, email index (W2.1, W2.2, W2.7) |
| 0053 | 42 actor FKs, 4 references, business keys, live-punch key `CONCURRENTLY` (W2.3, W2.4, W2.6) |
| 0054 | Range and sanity CHECKs, no-overlap guards checked at commit, same-start keys (W3.2, W3.3) |
| 0055 | Standard RLS policy on 5 tables, insert-only history (W5.1, W5.2) |
| 0056 | 79 FK indexes, 5 redundant indexes dropped, punch date index, all `CONCURRENTLY` (W8) |
| 0057 | Table comments (W10.1) |
| 0058 | `daily_report_rows` tenant key (L2) |
| 0059 | Allowed values on 43 state columns (W3.1) |
| 0060 | Exact leave quantities: half days where entered, `numeric(9,4)` history, exact OT rates (W4.1) |
| 0061 | `hrms_platform` role; the app role loses the platform tables (W5.3) |
| 0062 | Change-history triggers on 15 tables (W7.1) |
| 0063 | `version` on `leave_bucket_policies` (W6) |
| 0064 | Merge identical role grants and keep them unique; `job_runs.findings`; `pg_stat_statements` where preloaded (W2.6, W7.3, W9.4) |

**Deploying DB-1 needs, from the user:** a new secret `HRMS_PLATFORM_ROLE_PASSWORD` in the
environment file (deploy/preflight.sh checks it), the W1 pre-flight run on testing with 0 counts
(or HR decisions for what it finds), and a deploy window (0060 rewrites the leave tables).

**Sequence with the roadmap:**

| Release | Lands | Why then |
|---|---|---|
| DB-1 (W0–W10) | before R1 | New R1 tables are born compliant |
| DB-2 (contract) | the release after DB-1 | Expand/contract |
| W11, W12, W14 | with R1–R2 | Invariants, transitions and idempotency protect the new lifecycle screens |
| W13 (period close) | with R3 (month close); W13.4 with R4 (payroll) | Payroll needs closed periods and frozen inputs |
| W15, W16, W17 | before R7–R8 (documents, exit, compliance centre) | Privacy and erasure are needed when employees leave |
| W18 | with R10 (report datasets) | Reporting contract |
| W19, W20 | before a second paying tenant / production cut-over | Tenant lifecycle and HA |
| W21 | when DB-D4's trigger fires | Only when size requires it |
| W22–W26 | alongside, item by item | Each rule is cheap once the linter exists |

**Effort for one developer (days):**

| Work | Days |
|---|---|
| DB-1: W0 4 (done), W1 2, W2 5, W3 4, W4 6, W5 4, W6 4, W7 3, W8 2, W9 2, W10 1.5 | 37.5 |
| DB-2 | 2 |
| DB-3: W11 5, W12 4, W13 8, W14 3, W15 8, W16 3, W17 2 | 33 |
| DB-4: W18 3, W19 5, W20 5 (W21 ≈ 8 more, only when triggered) | 13 |
| Continuous: W22 3, W23 2, W24 3, W25 5, W26 1 | 14 |
| **Total** | **≈ 100 days (≈ 5 months), plus W21 if triggered** |

**Definition of done:**

*DB-1*
- [ ] `schema_baseline.txt` is empty; every exception is registered with a reason.
- [ ] `db_preflight.py` reports 0 on testing for every constraint before its migration.
- [ ] `alembic check`, `check_migrations.py`, the rules and the full suite (also as `hrms_app`) are green; coverage ≥ 88 %.
- [ ] Perf re-run: nothing slower than the baseline; the manager lookup stays flat as company size grows.
- [ ] Accrual of 25 / 14 / 10 / 7 days/yr is exact in half days; a full-balance application is accepted.
- [ ] A restore drill has been run and RPO/RTO recorded.

*DB-3*
- [ ] All invariants are 0 on testing and in every test module; the nightly alert is wired.
- [ ] Every status enum has transitions; race tests pass.
- [ ] Writes into a closed period are refused from the API, imports and raw SQL; a reopen is recorded.
- [ ] Every create route accepts an idempotency key.
- [ ] Every sensitive column is classified; duplicate PAN is refused; the retention and anonymization jobs pass their tests; testing holds no real PII.
- [ ] The anchor verifier passes; salary reads are logged.

*DB-4*
- [ ] Reports run on `hrms_report` views; tenant export → purge leaves zero rows; failover and upgrade drills recorded.

## 11. Measurements and progress

### 11.1 Measurements

| Measure | Before (2026-10-13, 2k employees) | After |
|---|---|---|
| Manager lookup (`assignment_managers` join) | Seq scan of all rows: 0.80 ms; 0.42 ms with the index | |
| `assignments` / `assignment_managers` rows read during seed + bench | 6.3 M / 6.1 M | |
| daily-analysis (hr_all) p50 | 164 ms | |
| dashboard/hr (hr_all) p50 | 90 ms | |
| Redundant index space (attendance) | 19 MB | |

### 11.2 Progress

| Step | State |
|---|---|
| Decisions DB-D1..D5 | Taken 2026-10-13 |
| Decisions DB-D6..D12 | Open (§3.2); not needed for DB-1 |
| W0 guardrails | Built and self-reviewed (schema rules, ratchet, migration kit, timeouts, registry, conventions page) |
| W1.1 pre-flight | Built: `scripts/db_preflight.py`, read-only, 169 checks, counts only. **W1.2 (running it on testing) waits for the user's approval** |
| W2 keys | Built: 0052 (System account by trigger on `tenants`, one login per employee, email index), 0053 (42 actor FKs, 4 references, business keys, live-punch key) |
| W3 rules | Built: 0054 (ranges, sanity, no-overlap, same-start keys), 0059 (allowed values on 43 state columns) |
| W4.1 exact leave | Built: 0060 + cumulative half-day accrual (`leave/engine.monthly_credit`) |
| W4.2, W4.3 | **Moved to DB-2** (see corrections below) |
| W5 isolation | Built: 0055 (standard policies, insert-only history), 0058 (report rows tenant key), 0061 (`hrms_platform` role, platform session, deploy config) |
| W6 stale edits | Built: `core/versioning.require_version` on 16 update routes, every response carries `version`, and the frontend sends it from all 12 edit screens (`Versioned` in `src/api/client.ts`). A refused edit reloads the screen's data (`MutationCache` in `App.tsx`). Still optional in the API until DB-2 |
| W7.1 change history | Built: 0062 (database triggers on 15 tables, actor from the request) |
| W8 indexes | Built: 0056 (79 FK indexes, 5 redundant dropped, punch date index) |
| W10.1 comments | Built: 0057 |
| Clear error messages | Built: `CONSTRAINT_MESSAGES` for every constraint a user can trigger, with a test that each name exists |
| W2.6 role-grant merge | Built: 0064 merges identical grants and adds `uq_role_assignments_grant`; the integration sync locks the login while it changes roles |
| W7.3 orphan check | Built: `hrms/db/integrity.py` (6 checks) run nightly by the `integrity` job; totals on `job_runs.findings`, exported as `hrms_integrity_violations`, alert `HrmsIntegrityViolations`. On the full test suite's 352 tenants it found only the 4 references tests plant on purpose |
| W9.4 observability | Built: `hrms_db_*` metrics (table size, live/dead rows, scans, database size, oldest transaction), 6 alerts with runbooks in `docs/OBSERVABILITY.md`, a *Data health* row on the database dashboard, `pg_stat_statements` preloaded in `deploy/compose.yml` (0064 creates it) |
| W9.5 backups | Already in place: nightly dump, off-site copy, restore and restore-drill scripts, backup-age alerts. PITR depends on the hosting decision |
| W9.3 autovacuum | Measured by `HrmsDeadRowsPiling` and the dashboard; per-table settings only once testing shows a need (runbook says how) |
| W9.2 retention | Waits for DB-D7 (retention periods) |
| W10.2 schema diagram | Built: `scripts/schema_diagram.py` → `docs/architecture/schema.md` (11 area diagrams, table index); `tests/test_schema_diagram.py` fails when it is stale |

**Schema rules:** 377 violations at the start → **0**. `tests/schema_baseline.txt` is empty.

**Corrections made while building (each verified against the code or a test):**

| Plan said | Built instead | Why |
|---|---|---|
| 42 actor columns → `user_accounts` | 39 → `user_accounts`, 3 → `employments` | `ot_reviewed_by`, `granted_by` and `processed_by` hold the acting employee; the API reports them as employment ids |
| CHECK `punched_at <= recorded_at + 10 min` | Not a constraint | A device with a fast clock would lose real punches; a detector belongs in W11 |
| CHECK "no self-manager" | Not a constraint | It spans two tables; a detector belongs in W11 |
| `effective_to > effective_from` on exclusive tables | `>=` | A same-day change leaves an empty row legitimately |
| No-overlap on policy and leave-policy assignments | Unique start date per target instead | "Latest start wins" by design: an overlap is a temporary override; only a same-day start is ambiguous |
| All leave columns `numeric(6,1)` half days | Entered/configured values `numeric(6,1)` + half-day CHECK; history and balances `numeric(9,4)` | Past monthly accruals (0.8333) can't satisfy a half-day rule without rewriting history |
| `record_change()` calls in every route | Database triggers | Covers imports and raw SQL too, and can't be forgotten in a new route |
| W4.2 role scopes as rows in DB-1 | Moved to DB-2 | Scope ids are base32 inside JSON text; a half-way table nobody reads adds risk to authorization for no gain |
| W4.3 stop writing leftover columns | Moved to DB-2 | They are still used: the integration sync maps `employee_code`, and the legacy import scripts find accounts by `erp_system` |
| Cross-tenant email clash returned 500 | It returned a generic 409 | The global IntegrityError handler already mapped it; the fix was a clear message |

**Problems found in existing code while building:**
- Five leave-configuration writes recorded `recorded_by = principal.id`, which doesn't exist, so "who changed this" was always empty. Fixed.
- The "same person can't approve twice" guard compared employments, not people: someone with two employments could approve at two levels. Fixed (compares `person_id`).
- Gender is stored as `F`, `FEMALE` and `M` by different paths. Left open: which values are canonical is a decision (§3.2 follow-up).
- Location and org-unit types are free text in the API. Left open, same reason.
