# HRMS code analysis — 28 September 2026

The project has a useful modular foundation, but the reviewed implementation has significant authorization and HR-data correctness gaps. The highest priorities are permission-aware scope resolution, session isolation, approval enforcement, and consistent attendance/leave accounting.

This review covers the current working tree, including existing uncommitted changes and migrations 0015–0016. Findings are about that tree, not necessarily regressions introduced by those changes. Application source was not modified. No production data, credentials, or employee export contents were inspected, and no database migrations or seeded integration tests were executed.

## Architecture and code flow

| Layer | Current design | Implication |
|---|---|---|
| React application | One application-level QueryClient, tenant and platform auth contexts, route-based pages, typed fetch wrappers | Clear API boundary, but cached server data must follow authentication boundaries. |
| FastAPI application | Domain routers mounted by `backend/src/hrms/main.py` | Most business logic, queries, authorization checks, and response assembly live together in routers. |
| Authentication | Signed JWT creates a Principal; separate token types for tenant and platform | Good separation of the two operating planes. Tenant account status is not revalidated on every request. |
| Authorization | Database role assignments resolve to one Scope containing permissions and visible entities/employments | Centralized enforcement is useful, but independent unions lose the association between a permission and its scope. |
| Persistence | Async SQLAlchemy sessions, commit/rollback dependency, transaction-local tenant setting | Tenant RLS is valuable when the runtime connection uses the restricted role. It does not enforce permissions within a tenant. |
| HR model | Person → Employment → dated Assignment; UserAccount is separate | Suitable foundation for rehires and organizational history, but several reads treat the open-ended assignment as current regardless of its start date. |
| Attendance | Punch endpoint incrementally updates AttendanceDay; correction endpoint separately changes AttendanceDay | Two write paths disagree about the source of truth. |
| Leave | Draft/submission/approval/cancellation states plus mutable yearly balance totals | Needs stronger validation, year allocation, and concurrent transaction handling. |

The core request path is browser → API client → Principal → tenant-scoped session → Scope → domain router → database. Platform requests use a separate principal and live platform-admin checks. Policy selection resolves employee, department ancestors, legal entity, tenant default, then system fallback.

Useful existing choices include parameterized SQL in the reviewed paths, transaction-local tenant context, distinct platform authentication, shared attendance calculation helpers, database uniqueness for daily attendance, and atomic `UPDATE ... RETURNING` for employee-number allocation. These should be preserved during fixes.

## Findings

P1 means a high-priority authorization or data-integrity defect. P2 means a correctness, reliability, or operational problem. “Reproduced” below means an isolated executable check against actual application functions with fake persistence; it is not an end-to-end database exploit demonstration.

### 1. P1 — Query cache survives user and tenant changes

**Evidence:** `frontend/src/App.tsx:29`, `frontend/src/context/AuthContext.tsx:127`, `frontend/src/pages/ProfilePage.tsx:98`, and `frontend/src/context/PlatformAuthContext.tsx:65`.

The QueryClient persists above auth providers. Logout removes tokens and user state but never cancels or clears queries. Keys such as `my-profile`, `employees`, `dash-hr`, and `leave-applications` contain no tenant/user identity. Signing out and signing in as someone else in the same SPA can show the previous account's cached data. The 30-second stale time can suppress a new fetch entirely; older stale data can still render while refetching.

**Reproduced:** the installed query library returned the previous user's profile with zero calls to the new query function. This verifies cache behavior; browser account-switch rendering was not exercised.

**Fix:** cancel in-flight queries and clear identity-dependent caches on every authentication transition; include tenant/user context in query keys. Apply the same handling to platform sessions.

### 2. P1 — Department scope grants company-wide access

**Evidence:** `backend/src/hrms/core/authz.py:151` and `:252`.

`_entities_for_org_units` maps departments to their legal entities. `resolve_scope` then discards the employment restriction. Queries filter by company rather than department membership, so a grant for one department can expose sibling departments and permit scoped writes there.

**Reproduced:** an ORG_UNIT grant produced an unrestricted employment set and a company-ID filter. The current user-creation schema does not expose ORG_UNIT, so this affects existing or otherwise provisioned assignments using that scope type.

**Fix:** resolve department descendants to employees, and preserve actual department scope for organization operations.

### 3. P1 — Combining roles expands stronger permissions into weaker roles' scopes

**Evidence:** `backend/src/hrms/core/authz.py:241`.

Permissions are unioned separately from visibility. An HR_MANAGER limited to company A plus an ACCOUNTANT for company B receives HR write permissions over both companies. A broad read grant therefore widens a narrower write grant.

**Reproduced:** a broad EMPLOYEE grant combined with a SELF HR_MANAGER grant produced all-company `people.write`.

**Fix:** resolve authorized targets per permission, retaining each role assignment's permission/scope pairing. Add mixed-role regression cases.

### 4. P1 — Visibility is treated as write authority

**Evidence:** `backend/src/hrms/modules/time/router.py:73`, `modules/leave/router.py:433`, `modules/corrections/router.py:100`, and `modules/onboarding/router.py:202`.

These paths authorize the target employee but do not consistently require an action permission or self-service ownership. An ACCOUNTANT has read access to people but can create punches within that scope. Onboarding updates also do not enforce the item's HR/IT/employee assignee type, allowing employees to complete their own HR-owned checklist items.

**Reproduced:** an ACCOUNTANT scope successfully created a backdated punch. Other listed paths were inspected statically.

**Fix:** distinguish “can see this employee” from “can perform this operation.” Allow self-service only for the caller's own employment; require explicit delegated write authority for other employees and task types.

### 5. P1 — Punch submission bypasses correction approval

**Evidence:** `backend/src/hrms/modules/time/schemas.py:10` and `modules/time/router.py:77`.

Ordinary punch creation accepts arbitrary `punched_at` and `source`, including historical timestamps and MANUAL/DEVICE source values. Employees can submit historical IN/OUT events through the normal punch endpoint instead of using the correction workflow. The write paths also do not enforce `AttendanceDay.is_locked`.

**Reproduced:** a punch dated 2020 was accepted by the handler.

**Fix:** use server time for ordinary self-service punches; separate trusted device ingestion and authorized historical adjustment, and enforce period locks in every attendance write path.

### 6. P1 — Approvers can approve their own requests and every level

**Evidence:** `backend/src/hrms/modules/leave/router.py:518` and `modules/corrections/router.py:140`.

Approval checks require a permission, target visibility, and pending status. They do not exclude self-approval, bind levels to designated approvers, or reject repeated approval by the same account. Manager scope explicitly includes the manager's own employment.

**Reproduced:** one manager approved their own leave three times, progressing through all levels to APPROVED.

**Fix:** define eligible approvers at each level, enforce separation of requester and reviewer where required, and persist unique approval transitions. If self-approval is an intentional policy, make it explicit rather than the unconditional default.

### 7. P1 — Tenant account suspension does not invalidate existing tokens

**Evidence:** `backend/src/hrms/core/authn.py:34`, `core/database.py:38`, and `core/authz.py:220`.

JWT authentication does not query the UserAccount. Session setup checks the tenant's status, and scope resolution checks role assignments, but neither validates the user's active status or current employment linkage. A disabled account with an unexpired token and remaining grants can continue using those grants. Platform admins have stronger live checks already.

**Fix:** validate tenant UserAccount status and identity linkage on authenticated requests; define revocation behavior for password and employment changes.

### 8. P1 — Verified KYC remains verified after edits

**Evidence:** `backend/src/hrms/modules/kyc/router.py:245` and `:523`.

Self-service edits change bank and identity details while only resetting NOT_SUBMITTED or REJECTED records to DRAFT. A VERIFIED record retains its status and reviewer metadata. HR editing has the same stale-verification problem.

**Reproduced:** changing a verified account number retained VERIFIED and the old verification timestamp.

**Fix:** invalidate verification for changed verified fields, or version the verified snapshot and require review of subsequent changes.

### 9. P1 — Leave balance accounting changes years during the workflow

**Evidence:** `backend/src/hrms/modules/leave/router.py:494`, `:533`, and `:802`.

Submission reserves pending days in the current UTC year. Approval, rejection, and cancellation generally use the leave start year. A next-year application can leave a reservation in the wrong year and debit another balance; applications spanning year-end are not split. Missing balances silently receive no update.

**Reproduced:** leave starting in January 2027 reserved 2026 balance and approved against 2027.

**Fix:** allocate working days to explicit entitlement periods once and use the same allocation for every transition. Require valid balances or an explicit unlimited/unpaid policy.

### 10. P1 — Attendance corrections do not maintain the punch history

**Evidence:** `backend/src/hrms/modules/corrections/router.py:216` and `:266`.

`_apply_correction` updates AttendanceDay but never creates a corrected Punch, despite its contract and the model's correction-chain fields. Punch timelines and current in/out state therefore disagree with corrected attendance. A lone missing IN correction is a no-op unless an OUT is already available: first_punch_in is assigned only inside the branch requiring both values.

**Reproduced:** an approved lone IN recorded neither its timestamp nor a Punch; a complete correction updated the daily summary without adding a Punch.

**Fix:** write auditable corrected events, support partial punches, and derive the summary through one shared recomputation path.

### 11. P1 — Future personnel actions take effect immediately

**Evidence:** `backend/src/hrms/modules/people/router.py:532`, `:576`, `:669`; `modules/policy/engine.py:135`.

All actions are applied immediately. A future separation immediately sets employment_state to SEPARATED. A future transfer closes the existing assignment and creates an open-ended future assignment, while current employee/policy queries select `effective_to IS NULL` without checking effective_from. Historical department policy resolution similarly uses today's open assignment rather than the assignment on work_date.

**Reproduced:** a separation dated January 2099 immediately changed an ACTIVE employee to SEPARATED.

**Fix:** distinguish scheduled events from current state and consistently query assignments by an as-of date. Validate destination organization references and authorization when applying actions.

### 12. P2 — Leave rules are stored but not enforced

**Evidence:** `backend/src/hrms/modules/leave/schemas.py:71` and `modules/leave/router.py:433`.

The request accepts reversed dates and arbitrary half-day strings. Any half-day value other than NONE forces the entire range to 0.5 days. Submission does not enforce available balance, overlap, configured notice periods, or min/max application duration. Leave counting excludes tenant-wide holidays only, ignoring company-specific holidays.

**Reproduced:** schema accepts reversed dates and an arbitrary half-day value. Remaining omissions were traced in creation/submission code.

**Fix:** validate date order, half-day range and enum, overlap, balance, active leave type, configured rules, and the employee's applicable holiday calendar at the backend boundary.

### 13. P2 — Concurrent balance and approval updates can race

**Evidence:** `backend/src/hrms/modules/leave/router.py:509`, `:802`, and `backend/alembic/versions/0003_policy_leave_corrections.py:132`.

Approval and balance updates perform read-modify-write without row locking or checked versions. Two requests can both observe a pending application or overwrite balance increments. Balance indexes do not enforce uniqueness on tenant/employment/type/year. Similar concurrency review is needed for accrual and get-or-create attendance/KYC paths.

**Evidence level:** static concurrency analysis; no concurrent database reproduction was performed.

**Fix:** lock or conditionally transition applications, update totals atomically, add the missing unique balance constraint, and test parallel submit/approve/cancel sequences.

### 14. P2 — Attendance day boundaries and breaks are inconsistent

**Evidence:** `backend/src/hrms/modules/time/router.py:93`, `:158`, `:399`, and `core/datetime_utils.py:247`.

Day assignment uses the submitted timestamp's date; today/history queries use server or UTC day boundaries rather than the employee policy timezone. Equivalent timestamps in different offsets can therefore fall into different work dates. A night shift's OUT on the next day updates a different row from its IN. BREAK_START/BREAK_END events are accepted but do not contribute to effective-minute calculation; calculations use first IN to last OUT and optional fixed deductions.

**Fix:** define work-date/shift ownership in policy timezone, normalize incoming timestamps, pair sessions and breaks, and share those rules with daily analysis and reporting.

### 15. P2 — KYC preview and download bypass the authenticated API client

**Evidence:** `frontend/src/components/kyc/KycSection.tsx:1385`, `:1391`, `:1404`; `frontend/src/api/kyc.ts:214`; `frontend/vite.config.ts`.

The UI places relative API URLs directly into img/iframe/anchor elements. With separate Vite/API origins these hit the frontend server; even with a proxy, those requests do not attach the required bearer token. An authenticated `fetchDocumentBlob` helper exists but is not used by these components.

**Fix:** load documents through authenticated fetch, display/download the resulting object URL, and revoke it on cleanup. Browser verification remains to be done.

### 16. P2 — Migration autogeneration has incomplete model metadata

**Evidence:** `backend/alembic/env.py:7`.

Only kernel, organization, and people model modules are imported. Twenty application tables from attendance, leave, KYC, policies, onboarding, corrections, and reports are absent from this metadata import path. Alembic autogeneration against an existing database can consequently propose dropping valid tables.

**Verified:** compared SQLModel metadata after those imports with metadata after loading the complete application; 20 tables were missing. No migration was generated or applied.

**Fix:** use a complete model-registration module for Alembic and verify expected tables in CI before trusting autogeneration.

### 17. P2 — Database relationships are not consistently enforced

**Evidence:** `backend/alembic/versions/0001_initial_schema.py:238`, `:256`, and `backend/src/hrms/modules/people/router.py:400`.

Many domain UUID references have only a tenant foreign key, without composite foreign keys to their referenced domain rows. Employment creation accepts person_id without establishing that the person exists in that tenant. Employee-number indexing is also non-unique. RLS checks the new row's tenant_id; it does not validate its foreign references.

**Fix:** add tenant-aware composite foreign keys and business uniqueness constraints after auditing existing data. Validate referenced entities at API boundaries and map violations to useful 4xx responses.

### 18. P2 — Deployment defaults do not fail closed

**Evidence:** `backend/src/hrms/core/config.py:16`, `:21`, `core/database.py:23`, `modules/kyc/router.py:754`, and `docker-compose.yml`.

The application accepts a known default signing secret and falls back to the migration database connection when app_database_url is absent. Production startup does not reject either condition or verify the database role. KYC files are written to local storage, with no upload size/type enforcement in the helper and no storage volume in the supplied Compose service; replacing the API container can lose uploaded files.

**Evidence level:** configuration and code inspection, not a claim about live deployment settings.

**Fix:** validate production secrets and runtime DB privileges at startup, persist document storage, bound uploads on the server, and reconcile file writes/deletes with database transaction failures.

## Validation performed

| Check | Result |
|---|---|
| Frontend TypeScript + Vite production build | Passed using installed Node 24.3.0. |
| Frontend Oxlint | Completed with 14 warnings and no errors. |
| Production bundle | Main JavaScript chunk 662.94 kB, 178.00 kB gzip; Vite warned about chunk size. All major pages are eagerly imported. |
| Backend Ruff | 812 findings: primarily annotation modernization and line length, plus import/style issues. This is not 812 runtime defects. |
| Standard backend health pytest | Hung in synchronous Starlette/AnyIO TestClient; bounded rerun timed out. Cause was not established. |
| Equivalent asynchronous ASGI smoke checks | `/health` and `/openapi.json` returned 200; schema contained 83 paths. |
| Isolated backend probes | Ten problematic behaviors reproduced with fake persistence against actual functions. Probe file: `/tmp/hrms_review_probes.py`. |
| Frontend cache probe | Previous profile returned with zero fetches under the existing stale-time setting. |
| Alembic model-registration check | Twenty application tables absent from env.py's model imports. |

Existing KYC/daily-analysis integration tests target a running server and seeded accounts; some mutate records. They were not run against the shared database. The repository currently lacks broad automated coverage of tenant boundaries, mixed grants, workflow transitions, attendance edge cases, concurrency, and migrations. No real-database RLS verification or browser end-to-end checks were performed.

## Recommended implementation order

1. Fix cache isolation, permission-specific scopes, write authorization, live account checks, and historical-punch restrictions. Add adversarial tests across roles, departments, companies, and tenants.
2. Enforce approval eligibility, preserve KYC verification integrity, and repair leave year allocation and validation.
3. Consolidate attendance event processing and correction recomputation; test timezone boundaries, night shifts, breaks, and partial punches.
4. Correct effective-dated personnel actions and as-of queries; add database references, business uniqueness, and concurrency controls.
5. Repair Alembic metadata registration and production configuration/storage checks. Establish isolated database tests and CI before extending payroll or ERP integration.

Refactor business operations into small domain services as these behaviors are repaired. A rewrite or microservice split is unnecessary for the identified problems. Performance work should then address unbounded lists and N+1 query patterns, particularly policy resolution inside daily-analysis employee loops, onboarding item loads per case, and accrual queries per employee/type. Route-level frontend loading can reduce the initial bundle independently.
