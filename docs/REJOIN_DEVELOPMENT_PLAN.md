# Employment lifecycle: rejoin, settlement, transfer. Development plan

**Version 1.0, 2026-10-21.** Companion to [REJOIN_PLAN.md](REJOIN_PLAN.md) (scenarios and research). This file is the build programme: scope, design, work packages, tests, pipeline, rollout, rollback and risks.

Style follows [enterprise-plan](enterprise-plan/README.md): single developer, one release train, effective-dated and per-entity rules, expand/contract migrations, no hidden behaviour change.

---

## 1. Goal and non-goals

**Goal.** When a person leaves and later returns (same company, another company in the group, or from outside), HR can record exactly what happens to leave, service, gratuity, PF identity and access. Every outcome is a recorded, auditable decision. Nothing is silent.

**In scope:** leave settlement at separation, rejoin with Continue or Start fresh, duplicate and incomplete-exit guards, UAN continuity, prior service from outside, inter-company transfer, reports, help, rollout.

**Out of scope (now):** full and final settlement payroll, gratuity calculation, legal opinions in the UI, automatic back-payment of leave for the gap, shift logic (none exists).

## 2. Decisions (recommended defaults, need the user's confirmation)

| # | Question | Recommended default | Why |
|---|---|---|---|
| D1 | Does Start fresh restart the service date used for leave eligibility? | Yes, balances and eligibility both restart | A half-reset is the commonest source of disputes |
| D2 | Company default mode | Continue if the gap is at most 30 days **and** nothing was paid out at exit; otherwise Start fresh | Matches "technical resignation" practice and avoids double payment |
| D3 | Unused leave at separation | Per leave type: Lapse, Encash, or Hold. Default Hold for 30 days then lapse. Where the OSH Code applies, Encash is the legal default | Law says leave is paid out on exit for covered workers (secondary source; verify) |
| D4 | Gap that forces Start fresh | 90 days (configurable per company) | Long gaps are real breaks |
| D5 | Order of work | A, B, E, F first; D and C later | Same-company rejoin is the main case |

All values are per legal entity, with the bypass options the enterprise plan already uses (direct, with reason, with approval, never). Every bypass is audited.

## 3. Design

### 3.1 Data model (expand only; all columns nullable or defaulted)

| Table | Change |
|---|---|
| `employments` | add `continuity_start_date date` (service start used for eligibility and gratuity; backfilled = `hire_date`), `current_spell_no int default 1` |
| `employment_spells` (new) | `id, tenant_id, employment_id, spell_no, joined_on, left_on, exit_reason, gratuity_paid bool, leave_settled bool, created_by, created_at`. One row per stint, so the history survives rejoins |
| `rejoin_records` (new) | `id, tenant_id, employment_id, personnel_action_id, mode (CONTINUE/FRESH), break_start, break_end, break_condoned bool, reason text, approved_by, previous_spell_id, new_spell_id, restored_leave jsonb` |
| `leave_separation_rules` (new, per legal entity, effective-dated) | `leave_type_id, on_separation (LAPSE/ENCASH/HOLD), hold_days, max_encash_days, rejoin_default_mode, force_fresh_after_days, bypass_policy` |
| `leave_separation_settlements` (new) | `employment_id, spell_id, leave_type_id, days, action, balance_transaction_id, amount_ref, settled_on` |
| `prior_service` (new) | `person_id, employer_name, from_date, to_date, recognised_for_gratuity bool, recognised_for_leave bool, document_id` |
| `inter_entity_transfers` (new) | `person_id, from_employment_id, to_employment_id, effective_date, leave_mode, reason, approved_by` |
| UAN / ESIC number | They live in the encrypted KYC record (`employee_kyc_records`, keyed by employment and person), not on `persons`. R4 adds the rule "never create a second UAN for the same person" there; no new column is needed |

All new tables carry `tenant_id`, row-level security, indexes and the audit columns in [database-conventions.md](database-conventions.md). Migrations 0067 onward, one concern per migration, each reversible where data allows.

### 3.2 Leave ledger rules

- Every change is a `LeaveBalanceTransaction` (`LAPSE`, `ENCASHMENT`, `CARRY_FORWARD`, `OPENING`, `MANUAL`); no balance is edited directly.
- Invariant held by tests: `closing = opening + accrued + granted + adjustment − taken − lapsed − encashed`, and each row's opening equals the previous closing.
- **Continue** restores only the held (unsettled) balances. If leave was encashed or lapsed at exit, it stays gone.
- **Start fresh** posts a `LAPSE` for whatever is still held, then opens new balances from the rejoin date through the normal entitlement and accrual rules.
- The gap months are never accrued (the accrual job already skips separated people and does not back-fill).

### 3.3 Services and API

- `separation` personnel action gains settlement: computes held days per leave type from the rules, posts ledger entries, writes `employment_spells` and `leave_separation_settlements`. Idempotent per action id.
- `rehire` personnel action gains `mode`, `break_condoned`, `reason`. Server decides the allowed modes from the entity rules and the gap, returns a **preview** (`POST …/rehire/preview`) showing what will be restored, lapsed, or reset before anything is written.
- Integration `POST /employees/{id}/rehire` accepts the same optional fields; omitted means the company default. Event `employee.rehired` carries `mode` and `previous_spell_id`.
- Hire: if the person has any past employment, the API returns a typed error `PAST_EMPLOYMENT_EXISTS` with the employments, unless `confirm_new_employment=true` with a reason.
- Rehire is refused (typed errors) unless the employment is SEPARATED, the exit is complete, and no rehire is pending.
- Every new endpoint is documented in `core/endpoint_docs/` (the docs-coverage test fails otherwise) and permission-gated (`people.rehire`, `leave.settle`, `people.transfer`).

### 3.4 Frontend

- Separation sheet: leave settlement table with the computed action per leave type, editable where the entity allows.
- Rehire sheet: gap length, what was settled, gratuity-paid toggle, Continue/Start fresh with a live preview, required reason, approval when the entity demands it.
- Person page: employment timeline (spells and rejoin records), prior service list, UAN reminder.
- Hire form: past-employment warning.
- Settings → Leave: separation rules per entity; Settings → People: defaults.
- In-app help topics for each screen, with a worked example, through the existing `usageHelp` mechanism. No legal wording until verified against the Gazette.

### 3.5 Events, notifications, audit

- Audit events for settlement, rehire decision, transfer, override. Existing audit log; no new store.
- Notifications: HR on pending approval; the manager on a rehire; payroll on a rejoin date.
- Metrics: `rejoin_total{mode}`, `separation_settlement_total{action}`, `rejoin_preview_ms`, duplicate-guard hits. Dashboards in the existing Grafana set.

## 4. Work packages (single developer, one release train)

| WP | Work | Days | Depends on |
|---|---|---|---|
| R0 | Decisions confirmed (section 2); characterisation tests that pin today's rehire and accrual behaviour; feature flag `lifecycle_v2` per tenant (off) | 1.5 | none |
| R1 | Migrations 0067–0069 (expand), models, backfill of `continuity_start_date` and one spell per existing employment, RLS, schema diagram update | 2.5 | R0 |
| R2 | Leave separation rules (CRUD, effective-dated, bypass policy) and settlement engine, idempotent | 3 | R1 |
| R3 | Rehire modes, preview endpoint, rehire records, service/eligibility date handling, integration endpoint, events | 4 | R2 |
| R4 | Guards: past-employment at hire, incomplete exit, double rehire, UAN uniqueness per person | 1.5 | R1 |
| R5 | Frontend: settlement and rehire sheets, timeline, hire warning, settings, help topics | 5 | R3, R4 |
| R6 | Prior service (API, UI, eligibility and gratuity-date reads) | 2.5 | R1 |
| R7 | Inter-company transfer (service, API, UI, leave carry rules) | 4 | R2, R3 |
| R8 | Reports and exports (rejoiners, settlements, breaks), notifications, metrics | 2 | R3 |
| R9 | Hardening: load test, security review, documentation (FEATURES, API guide, runbook), rollout and rollback rehearsal on a copy | 2.5 | all |

About 29 working days. R0–R5 give the main value (scenarios A, B, E, F) and can ship alone, around 18 days.

## 5. Delivery pipeline

### 5.1 Branching and environments

- Work on `feature/lifecycle-rejoin`, never on `main`. Integration branch is `testing`; the user commits and pushes (house rule). Environments: local → testing (AWS) → production (cut-over later), per [ENVIRONMENTS.md](ENVIRONMENTS.md).
- Testing holds real personal data. No experiment runs against it. Local runs use the private throwaway Postgres on a unix socket (see the safe-test-environment recipe in the project notes). Never print or commit Aadhaar, PAN, bank or salary data; tests use generated fixtures only.

### 5.2 Per-change loop (every work package)

1. Write the failing tests first for the rule (backend DB tests, frontend unit tests).
2. Implement; keep migrations expand-only.
3. Local gates, in order:
   - `ruff check` and `ruff format --check` on **changed files only** (never format the whole tree)
   - `mypy`
   - `pytest` (full suite on a fresh database; database-marked tests included)
   - `uv lock --check`, `pip-audit`
   - frontend: `tsc -b`, `oxlint`, `npm test`, `npm run build`
   - Playwright e2e for the new flows (`rejoin.spec.ts`, `separation-settlement.spec.ts`, `transfer.spec.ts`, plus the existing suite)
4. Push → GitHub Actions on `testing` runs the same gates, then the deploy workflow ships to the EC2 test environment through ECR and SSM, runs migrations, and runs the smoke test.

### 5.3 Test strategy

| Layer | What is proven |
|---|---|
| Unit | Settlement maths per leave type (lapse/encash/hold, caps), mode selection from gap and rules, ledger invariant as a property test with random sequences |
| Database | RLS tenant isolation on every new table; scope rules (an HR user of entity A cannot settle or rejoin entity B); idempotency of settlement; concurrency (two simultaneous rehires of one person: exactly one wins) |
| API | Typed errors, permission matrix, preview equals result, integration endpoint backward compatibility (old payload still works), docs coverage guard |
| Migration | Upgrade on a copy of the real schema, backfill counts equal employment counts, downgrade where designed, expand/contract compatibility: the previous release runs against the new schema |
| E2E | HR separates with settlement, rehires with Continue, with Start fresh, blocked cases (not separated, past employment on hire), transfer between entities |
| Non-functional | Settlement run for 10,000 employments within a time budget, no N+1 queries; accessibility check on new sheets |
| Regression | Existing attendance, leave, payroll and integration suites unchanged and green |

### 5.4 Release and rollout

1. **Flag off by default**; existing rehire keeps its current behaviour.
2. Deploy to testing; run the smoke test; rehearse on a scratch copy of the data, compare counts before and after (employments, spells, balances unchanged).
3. Enable `lifecycle_v2` for one test company; HR walks the scenarios using the in-app help.
4. Enable for the rest of testing; watch the dashboards for a week.
5. Production later, behind the same flag, per company.

### 5.5 Rollback

- Turn the flag off: behaviour returns to today's.
- Migrations are expand-only, so the previous release image runs on the new schema. Down-migrations drop only unused new columns and tables.
- Settlement entries are ledger rows; a mistaken settlement is corrected by a compensating entry, never by deleting history.

## 6. Security, privacy and compliance

- New permissions registered in the catalogue as sensitive: `people.rehire`, `leave.settle`, `people.transfer`, `prior_service.write`. Segregation: the person who records a rehire cannot approve it when the entity requires approval.
- Prior-service documents use the encrypted document store; no new file path.
- Audit trail for every decision includes actor, time, reason and before/after.
- Legal claims (gratuity thresholds, OSH payout) are configuration with a source link and a verified-by field, in line with the statutory-values principle; nothing is hard-coded or stated as legal advice.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Double payment or lost leave from a wrong settlement | Preview before write, idempotent ledger entries, invariant tests, compensating-entry correction |
| Backfill errors on real data | Dry run on a scratch copy, count checks, expand-only schema |
| Behaviour change for existing integrations | Optional new fields, old payload unchanged, flag off, contract tests |
| Legal rules change or differ by state | All rules are per-entity configuration with sources; verify against the Gazette before enabling defaults |
| Scope creep into payroll and F&F | Explicit non-goals; settlement emits a payroll hand-off record only |
| Single-developer capacity | Value-ordered packages; R0–R5 ship alone |

## 8. Definition of done (every package)

- Tests above written and green in CI on a fresh database; coverage for each new rule.
- Endpoint docs, permissions, audit events and metrics present.
- Migrations reviewed for expand-only, RLS and indexes; schema diagram regenerated.
- In-app help and docs updated; no unverified legal wording.
- Verified in the local app with real clicks, not only tests; checked on testing after deploy.
- Rollback path stated and, for migrations, rehearsed on a copy.

## 9. Sources

See [REJOIN_PLAN.md](REJOIN_PLAN.md) for the research table and links.

## 10. Progress log

| Date | Package | Done |
|---|---|---|
| 2026-10-21 | R1 (part) | Migration `0067`: `employments.continuity_start_date` and `current_spell_no`, new `employment_spells` and `rejoin_records` (forced RLS, comments, tenant FKs), backfill of one spell per existing employment (checked on a two-tenant scratch database: counts equal, dates match, RLS restored). `people/spells.py` keeps stints consistent on hire (both paths), separation and rehire; behaviour is unchanged (a rejoin still continues service and records mode CONTINUE). Tests in `tests/test_employment_spells.py`. The previous release runs unchanged on the new schema. |
| 2026-10-21 | R2 | Migration `0068`: `leave_separation_rules` (per company and leave type, either may be "any"; LAPSE, ENCASH up to a cap with the rest lapsing, or HOLD with optional hold days) and `leave_separation_settlements` (one row per stint and balance, so repeating is harmless); `SEPARATION` added as a ledger reference type. `leave/separation.py`: most-specific-rule resolution, read-only plan (the preview), settlement as ledger entries, and `resolve_holds`. Hooked into the SEPARATION personnel action. New daily job `leave-holds`. API: rules (list, add, archive), preview, settlements list. With no rule nothing changes, so existing companies behave as before. 11 tests. |
| 2026-10-21 | R3 | Migration `0069`: `rejoin_policies` (per company or all; default CONTINUE or FRESH and `force_fresh_after_days`) and `REJOIN` as a ledger reference. `people/rejoin.py` is the one place the rules live (`decide`, used by the preview, by entry of the action and by applying it). CONTINUE restores held leave and keeps service; FRESH lapses unused leave as ledger entries, restarts `continuity_start_date`, and leave accrual now measures service from that date. A break over the limit can continue only if HR records it as condoned with a reason; gratuity paid at exit forces FRESH; FRESH needs a reason; with no choice the company default applies (and falls back to FRESH when CONTINUE is ruled out). A scheduled rejoin is checked when entered and again when it comes due. API: `rejoin` on `POST /v1/personnel-actions` (REHIRE only), `GET /v1/employees/{id}/rejoin-preview`, `/v1/people/rejoin-policies` (list, add, archive). The sync API's rehire accepts `rejoin_mode`, `break_condoned`, `reason`, `gratuity_paid_at_exit` (all optional, old payload unchanged) and answers `REJOIN_NOT_ALLOWED`; `employee.rehired` events carry `rejoin_mode`. With no policy and no choice, behaviour is as before. |
| 2026-10-21 | R4 | `POST /v1/employees` refuses a person who already has an employment with `PAST_EMPLOYMENT_EXISTS` unless `confirm_new_employment` is set (the message points to Rehire); `GET /v1/persons/{id}/employments` lets screens check first. A second scheduled rejoin is refused; a rejoin while still employed was already refused. One UAN per person: saving a different UAN on another employment of the same person is refused with `UAN_ALREADY_ASSIGNED` (shows only the last four digits). A hire-date correction through the sync API moves `continuity_start_date` along unless a fresh start had moved it. Three older tests that deliberately give one person two employments now pass `confirm_new_employment`. |
| 2026-10-21 | R5 | Screens. **Rehire** sheet: break length, company limit, Continue / Start fresh / company default, gratuity-paid and condoned-break boxes, reason, a table of what happens to each leave balance, and the blocking reason shown live. **Separation** sheet: lists each unused balance and what the company rule does with it. **Add employee**: warns when the name (and birth date, when both are known) matches someone already on record and asks before continuing. **Leave policies, Leavers & Rejoining**: add and remove the leave rules for leavers and the rejoin policies. **Employee profile**: "Time with the company" lists each stint and how each rejoin was decided (`GET /v1/employees/{id}/employment-history`). In-app help topics `leavers` and `rejoin` with worked examples. Browser test `e2e/rejoin.spec.ts` (4 steps) plus the existing people, recruitment and workflow browser tests all pass. |
| next | R6 | Prior service from outside (employer, dates, recognised for gratuity and leave eligibility) |

**Notes from building R4 and R5.**
- The Add employee form always creates a new person, so the backend guard on `POST /v1/employees` protects the API and sync paths, while the screen's duplicate warning is what catches a returning person entered as new.
- A not-yet-placed rejoin stays blocked in the preview, with the reason, until HR fixes it; saving never silently does nothing.
- Exit "incomplete" has no separate state today (there is no offboarding module), so the existing rule that only a SEPARATED employment can be rehired is the guard.

**Not done in R3 and why.** The "approval when the entity demands it" step is left for R5 with the screens, because approvals need an approval flow assigned per employee and a screen to decide in. Until then HR's `people.write` permission is the approval, as it is for every other personnel action.

**Deviations from the plan, on purpose.** Rules use the existing `leave.read` / `leave.write` permissions instead of a new `leave.settle` (a new permission needs role and screen changes that belong with the UI in R5). There is no `lifecycle_v2` flag: a company with no rule is unaffected, so the rule itself is the switch.
