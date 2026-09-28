# ERP Integration Plan — Suraj Group (EXIM) & Sharanga Production (RABS)

**Status: planning, not implemented.** v2, 2026-09-25. Revises a pasted
draft plan against (a) the actual source files (`exim.users.json`,
`Sharanga_Production.login.json`, `Sharanga_Production.employee_profiles.json`
— repo root, gitignored, never committed) and (b) the current codebase. The
draft's overall shape — two tenants, dual login modes, server-to-server SSO,
JIT provisioning — is sound and kept. This revision corrects factual claims
that didn't hold up, adds field-level mapping tables, a compliance section,
idempotency/rollback design, and a risk register — the things a draft
needs before a team can actually build against it. **Two items remain open
and block implementation** — [Open Decisions](#open-decisions).

## 1. Scope & System of Record

**Explicit decision needed, not addressed in the draft at all**: after
migration, which system owns HR data going forward?

- **Option A — HRMS becomes the system of record.** One-time import, then
  ERP only ever calls the SSO endpoint (identity + auth), never pushes
  profile/department/designation updates again. Edits in HRMS (Scenario 9)
  are final. This is the assumption the rest of this document builds on,
  because it's the only option consistent with the draft's design — the
  draft never proposes a recurring sync job.
- **Option B — ERP stays the system of record, HRMS is downstream.**
  Requires a recurring reconciliation sync (not in the draft, not scoped
  here), and Scenario 9 edits in HRMS would need a "this field is
  ERP-owned, don't edit here" lock or they'd be silently overwritten by
  the next sync. Significant extra scope, not designed in this document.

Everything below assumes **Option A**. If that's wrong, say so before
Phase 2 — it changes the shape of Scenario 9 and Scenario 5 materially.

## 2. What's already true — not something to build

Checked against the running code, not assumed:
- `user_accounts` (`kernel/models.py`) already has `email`, `employee_code`,
  `mobile`, `password_hash`, `status`. The migration only needs to *add*
  `erp_system`, `erp_user_id`, `must_change_password`.
- Password hashing (`core/security.py`) is real `bcrypt` via `hash_password()`
  / `verify_password()`. Copying existing bcrypt hashes verbatim is sound
  where the source hash is genuinely bcrypt (true for Suraj, not Sharanga
  — see §3).
- Multi-legal-entity-per-tenant is already proven in production use (the
  demo tenant, SFPL Group, runs 4 legal entities under one tenant today).
- KYC storage tables already exist: `EmployeeKycRecord` (`pan_number`,
  `aadhaar_number`, `uan_number`, `pf_number`, `bank_name`, account
  number, etc. — all plain `Optional[str]`, no encryption) and
  `EmployeeKycDocument` (file metadata + `storage_path`, with a
  `DocumentType` enum: `PAN_CARD`, `AADHAAR_FRONT`, `AADHAAR_BACK`,
  `BANK_PROOF`, `PHOTO`, `ADDRESS_PROOF`, `EDUCATION_CERT`,
  `EXPERIENCE_LETTER`, `OTHER`). This import writes into existing tables,
  not new ones — see §4 for the mapping and §5 for why writing 50 real
  Aadhaar numbers into an unencrypted column is a bigger deal than writing
  demo data into it.

## 3. What the draft plan got wrong — corrected here

1. **`login_lookup()` already exists** (migration `0005`), **email-only**:
   `login_lookup(p_email text) RETURNS TABLE(tenant_id, id, password_hash,
   status, employment_id)`. The draft's replacement changes both the
   parameter name and the return columns — Postgres rejects a return-type
   change via plain `CREATE OR REPLACE` (this exact failure already
   happened once in this project's history). Migration must `DROP
   FUNCTION login_lookup(text)` first.
2. **`LoginRequest.email` is typed `EmailStr`** — a mobile number or
   employee code fails Pydantic validation before it reaches the lookup
   function at all. Auth-core work has to generalize this field, not just
   the SQL underneath it.
3. **Migration numbering**: current head is `0016` (records the approving account on leave/correction approvals; `0015` was employee ID schemes); the ERP migration will be `0017`.
4. **Sharanga passwords are pbkdf2 (`$pbk...`), not bcrypt** — none are
   portable. Every one of the 76 accounts gets a fresh password, not just
   ones missing a hash (§6 confirms this is the accepted tradeoff).
5. **Sharanga's `user_info.employees_role` is not a job role** — it's
   `"Contract"` / `"Permanent"` (employment type). The actual job-role
   signal is `login.json`'s `role` field (`"Moulding_Helper"`,
   `"QC_QC Engineer"`, etc.). The draft doesn't distinguish these at all;
   conflating them would have mapped "Permanent"/"Contract" into the HRMS
   role system, which is wrong.
6. **The 9 named Suraj legal entities in the draft don't exist in the
   data at all** — see §4.1.

## 4. Data Mapping

### 4.1 Suraj Group (`exim.users.json`, 310 records)

| Draft claim | Verified | Detail |
|---|---|---|
| RABS excluded: 68 | ✅ | `RABS INDUSTRIES INDIA PRIVATE LIMITED` (42) + case variant (26) |
| Ghost/blank records: 52 | ✅ | `company` field empty |
| Demo user: 1 | ✅ | `company: "Novusha Client Demo"` |
| Net usable: 189 | ✅ | 310 − 68 − 52 − 1 |
| Password format: bcrypt | ✅ | all 310 are `$2b$...`, 60 chars |
| 9 named legal entities | ❌ | none of the draft's names appear anywhere in the data |

Real entities, grouped by normalized `company` name (decision: name is
truth, `company_id` is not — see below):

| Real company name (raw casing varies) | Records |
|---|---|
| Suraj Forwarders & Shipping Agencies | 37 |
| Suraj Forwarders Private Limited | 35 |
| SR Container Carriers | 37 |
| Novusha Consulting Services India LLP | 22 |
| Sansar Tradelink | 16 |
| Suraj Forwarders *(no suffix)* | 13 |
| EXIMBIZ Enterprise | 13 |
| Alluvium IoT Solutions Private Limited | 10 |
| Paramount Propack Private Limited | 6 |

`company_id` has two anomalies that make it untrustworthy as the grouping
key: "Suraj Forwarders" and "Suraj Forwarders Private Limited" carry two
*different* `company_id`s despite being probably-the-same company, and
"Alluvium IoT Solutions" / "Novusha Consulting Services" — two
different-*named* companies — share *one* `company_id`. Decision
(2026-09-25): group by name, treat `company_id` collisions/splits as
source-system noise.

**Field mapping — `exim.users.json` → HRMS schema** (per record, once the
canonical entity list from Open Decision 1 exists):

| Source field | Target | Notes |
|---|---|---|
| `_id` | `user_accounts.erp_user_id`, `erp_system = 'EXIM'` | |
| `email` | `user_accounts.email`, `persons.*` (via `Person`) | 16 records share dummy addresses (`abc@gmail.com` etc.) — set `email = NULL` for those, per draft's Rule 2.1.3; identify by exact string match against a small denylist, not a heuristic |
| `username` | `user_accounts.employee_code` *or a dedicated field* | confirm this is unique per record before using as identifier — not yet checked |
| `password` | `user_accounts.password_hash` | copy verbatim, format confirmed bcrypt |
| `first_name` + `middle_name` + `last_name` | `persons.legal_first_name` / `legal_last_name` | `Person` has no middle-name field today — concatenate into first name or drop; decide before import |
| `isActive` | `user_accounts.status` (`ACTIVE`/`INACTIVE`), `employments.employment_state` (`ACTIVE`/`SEPARATED`) | |
| `company` (normalized) | `employments.legal_entity_id` | via the entity list from Open Decision 1 |
| `role` | *not a clean HRMS role* | this field is EXIM's own RBAC role, not comparable to Sharanga's `role` or to HRMS's 5 roles — needs its own mapping, not yet built |
| `pan_no`, `pan_photo` | `employee_kyc_records.pan_number`, `employee_kyc_documents` (`PAN_CARD`) | |
| `bank_account_no`, `ifsc_code`, `bank_name`, `bank_account_status` | `employee_kyc_records.account_number` / `.ifsc_code` / `.bank_name` | field names confirmed against `kyc/models.py` |
| `kyc_approval`, `kyc_date` | `employee_kyc_records` verification status/date | map to `DocumentStatus` where applicable |
| `monthly_salary` | **no target — payroll doesn't exist** ([`docs/payroll-design.md`](payroll-design.md)) | store nowhere yet, or add a placeholder field; do not silently drop real compensation data without deciding |
| `shift_id`, `shift_ids`, `week_off`, `attendance_settings` | `policy_templates` / `employee_policy_assignments` (this session's dept/company assignment work) | needs its own translation from EXIM's shift model to `work_days`/`saturday_pattern`/`expected_start_time` — not designed here |
| `assigned_branch`, `sub_team`, `crmManagedTeams`, and the ~15 other operational fields (fleet/tyre/CRM modules) | **no HRMS equivalent** | these are EXIM-operational, not HR data — explicitly out of scope, not imported |

### 4.2 Sharanga Production (`login.json` 76 records + `employee_profiles.json` 74 records, joined on `emp_id`)

| Draft claim | Verified | Detail |
|---|---|---|
| 76 total, 41 active / 35 inactive | ✅ | `is_deleted: true` count is exactly 35 |
| Username = 10-digit Indian mobile | ⚠️ partial | 66/76 match `[6-9]\d{9}` exactly; the other 10 are still digit-only strings of length 9–10 (one 9-char alphanumeric) — likely malformed/landline entries, not a different identifier scheme. Needs manual review of those 10, not a blanket rule. |
| Password → `Firstname@1234` | ⚠️ applies to **all 76** | existing hashes are pbkdf2 (`$pbk...`), 0 of 76 portable |
| Profile join via `emp_id` | ⚠️ | 74/76 join; 2 logins have no profile |
| `employees_role` → HRMS role | ❌ wrong field | `user_info.employees_role` is `"Contract"`/`"Permanent"` (employment type), **not** a job role. The real role signal is `login.json.role` (free text, 29 distinct values, includes `super_admin` ×4) |

**Field mapping — Sharanga → HRMS schema**:

| Source field | Target | Notes |
|---|---|---|
| `login.json._id` | `user_accounts.erp_user_id`, `erp_system = 'SHARANGA'` | |
| `login.json.username` | `user_accounts.mobile` (66/76) or TBD (10/76) | |
| `login.json.email` | `user_accounts.email` | |
| `login.json.emp_id` | `user_accounts.employee_code`, join key to profile | |
| new random password | `user_accounts.password_hash` via `hash_password()` | `must_change_password = true` |
| `login.json.role` | HRMS role, via mapping table (Open Decision 3) | |
| `login.json.is_deleted` | `user_accounts.status`, `employments.employment_state` | |
| `profiles.user_info.full_name` | `persons.legal_first_name`/`legal_last_name` | split on first space; verify against `login.json.full_name` for consistency |
| `profiles.user_info.dob` | `persons.date_of_birth` | |
| `profiles.user_info.gender` | `persons.gender` | |
| `profiles.user_info.marital_status`, `.blood_group` | `employee_kyc_records.marital_status` / `.blood_group` | confirmed on `EmployeeKycRecord`, not `Person` |
| `profiles.user_info.aadhaar_number` (50/74) | `employee_kyc_records.aadhaar_number` | **see §5 before writing any of these** |
| `profiles.user_info.salary_account_number` (18/74) | `employee_kyc_records.account_number` | real bank account numbers — same §5 caveat |
| `profiles.user_info.department`, `.designation`, `.section` | `assignments.org_unit_id`, `.job_id` | needs an org-unit tree built for the one Sharanga legal entity first — not designed here |
| `profiles.user_info.employees_role` | `assignments.worker_type` or similar (Contract/Permanent) | **not** the HRMS role — see correction above |
| `profiles.user_info.qualification`, `.qualification_level`, `.experience`, `.experience_level` | no confirmed target | not covered by `EmployeeKycRecord` — decide where they go or drop them explicitly |
| `profiles.user_info.emergency_contact_number` | `employee_kyc_records.emergency_contact_phone` | name/relation fields also exist (`emergency_contact_name`/`_relation`) but aren't in the source data — leave null |
| `profiles.user_info.address` | `employee_kyc_records.current_address` | `permanent_address` also exists but has no source field — leave null |
| `profiles.user_info.user_documents` (`avatar`, `id_proof`, `education_certificates`, `experience_letters`, `other_documents`) | `employee_kyc_documents` (`PHOTO`, `AADHAAR_FRONT`/`PAN_CARD`, `EDUCATION_CERT`, `EXPERIENCE_LETTER`, `OTHER`) | these are almost certainly file paths/URLs into Sharanga's own storage — the import script needs to either re-host the files into HRMS's storage or reference them externally; not designed here |
| `profiles.employee_skills` | no target | consistently `null` in the sample checked; likely unused, confirm across all 74 before dropping |

## 5. Compliance & PII Handling

This is not hypothetical — both files contain real government-ID and
financial data for real people: **50 Aadhaar numbers** (Sharanga), **18
bank account numbers** (Sharanga), and Suraj's PAN numbers + bank account
numbers + IFSC codes for a subset of 189 records.

- **`EmployeeKycRecord.aadhaar_number`/`pan_number` are plain,
  unencrypted `str` columns today.** This is a pre-existing gap in the
  codebase (built before this integration), not something this plan
  introduces — but importing 50+ real Aadhaar numbers into it is a much
  bigger consequence than whatever demo data lives there now. Recommend
  column-level encryption (e.g. pgcrypto or application-level encryption
  before write) before this import runs, or at minimum: mask on every
  read path (show only last 4 digits in any API response/UI), and add
  access logging on `EmployeeKycRecord` reads. This should be resolved
  before Phase 4, not after.
- **India's DPDP Act 2023** treats Aadhaar and financial account numbers
  as personal data requiring purpose limitation and consent basis for
  processing. Migrating an employee's Aadhaar number from a legacy HR/ERP
  system into a new one is normally covered under existing
  employment-relationship consent, but this should be confirmed with
  whoever owns compliance for Suraj Group / Sharanga, not assumed by an
  engineering plan.
- **`user_documents`** (Sharanga) reference files outside this
  environment — the import script must not silently leave broken links;
  either re-host into HRMS's own storage (`storage_path` pattern already
  used by `EmployeeKycDocument`) or explicitly flag as "not migrated."

## 6. Decisions Made (2026-09-25)

- **No hard delete.** The draft's Scenario 10 (cascading `DELETE FROM
  role_assignments/user_accounts/assignments/employments/persons` in one
  transaction) is dropped entirely — this codebase has zero hard-delete
  precedent anywhere; every delete in every module is soft via
  `archived_at`. Employee record management is **Edit** (`PATCH
  /v1/people/employees/{id}`, already exists) **+ Active/Inactive**
  (status toggle, already the pattern for offboarding/rehire) only.
- **Initial passwords**: `Firstname@1234` for the Sharanga population, as
  the draft specified — accepted with the guessability tradeoff noted.
- **Entity grouping**: by normalized company name, not `company_id`.

## 7. Idempotency & Re-run Safety

Not addressed in the draft at all, and necessary — the import will
realistically run as dry-run, get corrected, and run again more than
once.

- **Every import must be an upsert, not an insert.** Keyed on
  `(tenant_id, erp_system, erp_user_id)` — add a unique index on
  `user_accounts(erp_system, erp_user_id)` (already proposed as a plain
  index in the migration; make it `UNIQUE`). Re-running the script against
  the same source file must update existing rows, not create duplicates.
- **JIT auto-provisioning (Scenario 5) needs the same unique constraint**
  to survive a race: two concurrent SSO calls for a brand-new employee
  must not create two `Person`/`Employment`/`UserAccount` sets. Wrap
  provisioning in a transaction with `ON CONFLICT (erp_system,
  erp_user_id) DO NOTHING` (or equivalent SELECT-then-insert-with-retry),
  not a bare insert.
- **Batch traceability**: add an `import_batches` table (`id`,
  `source_system`, `imported_at`, `imported_by`, `record_count`,
  `dry_run: bool`) and an `import_batch_id` FK on `user_accounts` only
  (not sprayed across every table). This is enough to answer "which
  accounts came from which run" without tagging every downstream table.
- **Dry-run output**: a reconciliation report (created / updated /
  skipped / errored counts, per entity) compared against this document's
  verified numbers (189 Suraj, 76 Sharanga) before any real run.

## 8. Security Architecture (expanding the draft's §11–12)

- **API key lifecycle**: the draft covers storage (SHA-256 hash) and
  scoping (tenant-bound, IP-allowlisted) but not rotation or revocation.
  Add `expires_at` and a revoke endpoint; rotating a key must not require
  downtime on the ERP side (support two active keys per tenant briefly
  during rotation).
- **Tenant scope enforcement must be server-side and tested**: the schema
  correctly binds `erp_api_keys.tenant_id`, but the implementation has to
  actually verify the resolved user belongs to that same tenant before
  issuing a token — write a test that a Suraj key cannot mint a token for
  a Sharanga user, don't just rely on the schema shape.
- **JIT auto-provisioning always forces role = `EMPLOYEE` server-side**,
  regardless of what the ERP payload claims — no field in the
  `auto_provision` payload should be able to grant `SUPER_ADMIN`/
  `HR_MANAGER`.
- **Do not put the access token in `redirect_url` as a query parameter**
  — leaks via browser history, server access logs, Referer headers. Use a
  short-lived one-time exchange code in the URL; the frontend swaps it
  for the real JWT via a POST.
- **No rate-limiting infrastructure exists in this codebase** (no Redis,
  no existing middleware). "5 attempts per 15 minutes" is its own small
  infra phase — a DB-backed failed-attempt counter is enough to start,
  doesn't require standing up Redis for this alone.
- **Audit every SSO token exchange** (who, when, from which IP, which API
  key) — the draft's Scenario 9 already writes audit entries for edits;
  SSO issuance is at least as sensitive and isn't covered.

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Wrong legal-entity mapping silently merges/splits real companies | Medium | High — wrong company on 189 real employment records | Blocked on Open Decision 1; dry-run reconciliation report reviewed before real run |
| Aadhaar/bank data at rest, unencrypted, now populated at scale | High (already true) | High — regulatory + breach exposure | §5 — encrypt or mask before Phase 4 |
| Predictable `Firstname@1234` passwords guessed before first login | Medium | Medium — account takeover on factory-floor accounts | Accepted tradeoff (decision made); mitigate with `must_change_password` enforced hard (block all other actions until changed) |
| Duplicate accounts from re-running import or concurrent JIT calls | Medium | Medium — data integrity, confusing support load | §7 — unique constraint + upsert semantics |
| SSO endpoint becomes a cross-tenant token-minting bug | Low if tested | Critical — full tenant data breach | §8 — explicit test for tenant-scope enforcement before go-live |
| JWT leaks via `redirect_url` in logs/history | Medium | Medium — session hijack window | §8 — exchange-code pattern instead |
| Import silently drops fields with no confirmed target (salary, qualifications, documents) | High | Low–Medium — data loss, discovered later | §4 tables mark every "no target" explicitly rather than silently mapping nothing |

## 10. Open Decisions

Nothing below should be guessed at — each affects real people's identity
or company assignment.

1. **The real list of Suraj Group legal entities and canonical names.**
   You said you'll provide this — migration and import are blocked on it.
2. **Is "Suraj Forwarders" (13 records) the same entity as "Suraj
   Forwarders Private Limited" (35 records)?**
3. **Sharanga `role` → HRMS role mapping** — proposed default pending
   confirmation: `super_admin` → `SUPER_ADMIN`; contains
   "Manager"/"Supervisor"/"Head" → `MANAGER`; `HR_*` → `HR_MANAGER`;
   `Accounts_*` → `ACCOUNTANT`; else → `EMPLOYEE`.
4. **The 10 Sharanga usernames that aren't clean 10-digit mobiles** —
   need manual inspection, not yet done.
5. **The 2 Sharanga logins with no profile record** — login-only import,
   or excluded until reconciled?
6. **System of record** (§1) — confirm Option A (HRMS becomes primary
   post-migration) or say otherwise.
7. **Aadhaar/PAN encryption** (§5) — encrypt at rest before import, or
   proceed with masking-on-read only as an interim measure?
8. **Fields with no confirmed target** — `monthly_salary` (Suraj, no
   payroll module to hold it), `qualification`/`qualification_level`/
   `experience`/`experience_level` (Sharanga), and how `user_documents`
   file paths get re-hosted into HRMS's own storage — need explicit
   yes/drop decisions, not silent handling either way.

## 11. Phased Execution Plan

Each phase has a go/no-go gate — don't start the next until the current
one's output is verified, not just "written."

| Phase | Output | Verified by |
|---|---|---|
| 0 | Open Decisions 1–8 resolved | This document updated with real answers, re-reviewed |
| 1 | Migration `0017` (additive schema, corrected `login_lookup`, unique constraint from §7) | `alembic upgrade head` clean; existing login flow still works (regression test) |
| 2 | Auth core: generalized login identifier, `must_change_password` flow | Login via email still works (no regression) + new mobile/employee_code login path tested |
| 3 | Import script, `--dry-run` only | Reconciliation report matches this document's verified counts (189 / 76) exactly, entity-by-entity |
| 4 | Import script, real run | Spot-check a sample of imported accounts against source records; confirm §5 PII handling was applied, not skipped |
| 5 | ERP SSO endpoint + `erp_api_keys` admin management | Cross-tenant isolation test (§8) passes; exchange-code pattern verified, not raw JWT in URL; rate-limit counter functioning |

Phase 5 is last and highest-risk (the only network-facing, unauthenticated
-until-key-checked surface) — it should not go live until Phases 1–4 are
proven with the real, imported accounts.
