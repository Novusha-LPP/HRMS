# ERP / CRM Integration Plan: live employee sync and employee self-service through the ERP

**Status: plan v1.5, 2026-10-12. v1 (I-1 to I-4) is built on a branch; see *Implementation status*.**

- v1.5: **scoped to what Suraj and Sharanga use (D-12).** The ERP and CRM *read* HRMS's API; they don't receive webhooks.
  There is no access control, canteen, Google Workspace, Microsoft 365, Slack or Teams. So v1 is the sync API, the settings,
  the read API with an **events feed**, and self-service through the ERP (about 23 pair-weeks). Push webhooks, file feeds,
  connectors, SSO and SCIM stay designed, as a **product backlog** to build when a customer needs them (§16).

- v1.4: **not every app has a webhook URL.** Each connected app uses whichever of four methods it can support: webhook, read
  API, connector, or a **scheduled file** (CSV or Excel to SFTP, S3 or email) for systems that only import files (§9.2).

- v1.3: **HRMS can send data to any third-party application** (§9), not only the ERP and CRM. It does this by push
  (webhooks), by pull (read API), or through direct connectors (SCIM, Google Workspace, Microsoft 365). Each app sees only the
  events, fields and people it is given.

- v1.2: **enterprise-grade and dynamic.** Every integration rule is a per-company setting with versions and history, and is
  changed in the UI (§6). That includes who owns each field, where people may be hired, password rules and matching rules.
  It also adds OAuth 2.0 client credentials, single sign-on (OIDC/SAML) and SCIM.
- v1.1: employees can now be onboarded in **either** the ERP or
HRMS (D-7), and each company's employee ID scheme decides who issues employee codes (D-8). See §7.7 and §7.8. The only part that exists is the `api_keys` table (migration
`0018`). It is not wired to anything.

**What this covers.** A customer's own ERP or CRM connects to the HRMS while it runs, every day:

1. **Employee sync, in both directions.** An employee can be onboarded in the ERP or in HRMS. Either way, the other system
   gets the employee, and the two records are linked.
2. **Self-service through the ERP.** Employees punch in and out, and see their own attendance, leave and profile, from inside
   the ERP's screens.

**How it relates to other documents.**

- [erp-integration-plan.md](erp-integration-plan.md) is the *one-time import* of Suraj Group and Sharanga. This plan is the live
  connection that comes after that import. It replaces that plan's Phase 5, *"ERP SSO endpoint, key administration"*.
- [enterprise-plan F19](enterprise-plan/01-platform-foundations.md) (Integration framework) lists API keys, webhooks and SSO.
  This plan brings forward the API-key and inbound-sync parts of F19, because the ERP is where onboarding happens for these
  tenants.
- [EMPLOYEE_INTEGRATION_API.md](EMPLOYEE_INTEGRATION_API.md) documents the existing self-service endpoints. §8 below reuses
  them unchanged.
- It follows the enterprise plan's principles: **configuration, not code** (2), **effective-dated everything** (3), **safe
  change, with a preview first** (7), and **every rule per company, with the company choosing whether it can be bypassed**
  (9). See [enterprise-plan README](enterprise-plan/README.md#principles).

---

## Implementation status (2026-10-12)

**Built on branch `feature/integrations`** (worktree `HRMS-integrations`). It is not merged and not
deployed. It was tested only on a private database.

| Phase | State |
|---|---|
| I-1 Foundation | **Built.** Migration `0051`; keys (HMAC-hashed, test/live, scopes, IP allow-list, per-key rate limit, revocation that also ends sessions, two active keys per app); OAuth client credentials; the sync log; `integrations.manage` and `integrations.configure` (held by `SUPER_ADMIN`'s `*` until the role builder exists). |
| I-2 Employee sync | **Built.** Reference data; link (dry run); create, update and link; exit with the safety valve and held exits; rehire; bulk; reconcile; dry run; idempotency keys; ordering by `source_updated_at`; mappings and the unmapped queue; possible duplicates; pending managers; employee codes per the ID scheme (the generator now skips codes in use). |
| I-2a Settings and ownership | **Built.** Versioned profiles (tenant default and company overrides; draft, preview, publish from a date); presets; field ownership enforced on HRMS's own write paths (personnel actions, own profile, login creation, hiring), with a guard test; `field-control`; health warnings. |
| I-2b Onboarding in HRMS | **Built.** The outbox written in the same transaction (personnel-action hooks cover HR screens, the scheduler and sync); the events feed with the in-flight-transaction rule; per-app cursors; delivery timing (held hires, moved when the joining date changes); not-linked list. |
| I-2c Connected apps and read API | **Built.** Connected apps of three kinds; read endpoints (employees, org, holidays, approved leave, daily attendance); per-app events, fields, data classes and people; the *What does this app receive?* report. |
| I-3 Self-service through the app | **Built.** `/sessions`; the `via` claim checked at authentication and on every request (key still active, route list, the company's feature switches); grants limited to EMPLOYEE/MANAGER; no forced password change or MFA for these sessions; punches recorded as `INTEGRATION` with the app's code. |
| I-4 Hardening | **Built.** Metrics and six alerts with runbook entries (including a key used from a new address); [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md); endpoint docs; integration tests plus the API-contract and route-list guards; a security review and a load test (below); the reference client [examples/hrms_client.py](examples/hrms_client.py), run against the API in CI; a browser test of the admin screens (`frontend/e2e/integrations.spec.ts`). |
| Admin screens | **Built.** Settings → Integrations (apps, keys shown once, settings with presets, preview and versions, mappings, sync log, needs review). On the employee record, a *Managed by ERP · ID* badge lists the locked fields; the transfer form explains the lock and asks for the override reason (and says when approval is needed); on *My profile*, fields an app owns are read-only with a note. |

**Security review (2026-10-12).** An adversarial pass over the module and its hooks found three
issues, all fixed and covered by tests:

1. **(High) Takeover of an HR or admin login.** A key with `passwords.sync` could link an unlinked
   HR employee by `employment_id` and set their HRMS password. Sync now refuses to change the
   password, email, mobile or code of a login that holds any role beyond EMPLOYEE/MANAGER
   (`PRIVILEGED_ACCOUNT_PROTECTED`).
2. **(Medium) Company limit missing from the events feed.** A key limited to one company received
   events about others. The feed now skips them.
3. **(Medium) Mappings across companies.** A department or location mapping that pointed at another
   company's record placed the employee there. It is now refused (`MAPPING_OTHER_COMPANY_*`).

Checked and found sound:

- only constant SQL fragments are interpolated;
- user tokens and integration tokens are separate token types;
- RLS is on every new table, and the lookup functions expose nothing but what they must;
- app sessions are limited by route, by role and by the app's features;
- punch sources can't be spoofed;
- passwords are never logged, and contact details are masked in the log.

**Load test (2026-10-12, 2,800 synthetic employees, 4 API workers, private database).**

| Operation | p50 | p95 | Target | |
|---|---|---|---|---|
| Update an employee | 22 ms | 62 ms | 300 ms | ✓ |
| Create an employee | 266 ms | 383 ms | 300 ms | ✗ (see below) |
| Bulk of 200 | — | 2.3 s | 20 s | ✓ |
| Session issue (10 at once) | 12 ms | 35 ms | 150 ms | ✓ |
| Punch with an app session (10 at once) | 18 ms | 48 ms | — | ✓ |
| Events page of 500 | — | 150 ms | — | ✓ |
| Morning rush | 225 employees/s at 10 at once, 131/s at 50 at once | | ≈ 6/s needed | ✓ |

- **Creating an employee misses the target.** Every new login gets a bcrypt-hashed password, which is
  deliberately slow (~170 ms). The target for creates is revised to 500 ms rather than weakening the
  hashing.
- **What the first run found, and what was fixed:**
  - Every call with one key updated the same row (usage counter and the minute's rate counter), so
    concurrent calls queued. Counters are now spread over 8 rows, and "last used" is refreshed at most
    every 15 seconds; the key list shows calls in the last hour.
  - Bulk hashed its passwords one by one (36 s for 200). It now hashes them in parallel (2.3 s).

**Where the build differs from the plan:**

- **OAuth uses the API keys themselves** (client id = the key's public part, client secret = the
  key) instead of a separate `oauth_clients` table: one credential to manage, rotate and revoke.
- **"HR may override with approval"** uses the existing approval flows: a new request type,
  `FIELD_OVERRIDE`, assigned per employee like the others. The change is held as a pending
  personnel action, the approver sees the reason in the inbox, and it applies on the final approval.
  HR can withdraw it while it is pending. Without an assigned flow, the change is refused with
  instructions.
- **The safety valve has a floor of 3 exits a day**, so a small company's ordinary leavers aren't
  all held for review.
- **Onboarding checklist** (§9.5): each case gets a *Set up in <app>* task per app that receives the
  new joiner. It is not required, so an outside system that is down never blocks onboarding. It
  ticks itself when a two-way app links the employee, or when another app confirms the hire event.
- **A key used from a new address** is recorded in the sync log (operation `NEW_IP`), and raises
  the `HrmsApiKeyNewAddress` alert.
- **Employees without an HRMS login** get a passwordless EMPLOYEE login when an app first asks for
  their session, so people hired in HRMS can use it through the ERP.
- **Ownership checks look only at real changes:** forms that resend unchanged values (the
  transfer form, *My profile*) aren't refused for fields nobody is changing.
- **Sign-in emails are unique across all companies** (an existing database rule), so sync checks
  them globally and returns `EMAIL_IN_USE`.

## 1. Decisions

### Made by you on 2026-10-12

| # | Decision |
|---|---|
| D-1 | The customer's ERP and CRM already hold the employees. *(Its second half, "onboarded only in the ERP or CRM", is replaced by D-7.)* |
| D-2 | **Push model.** The ERP or CRM calls the HRMS API when someone joins, changes or leaves. HRMS does not poll the ERP. |
| D-3 | ~~Both sides can edit anything.~~ **Replaced by D-9:** each field has an owner, set per company. "Both edit, latest wins" is still available for any field as the **Shared** owner (§6.2, §7.4). |
| D-4 | **Login password:** the employee's existing ERP password. If the ERP has none, the default is `Firstname@1234`. |
| D-5 | **Custom, in-house ERP and CRM systems**, like Suraj (EXIM) and Sharanga. No packaged connectors (Zoho, SAP, Salesforce). |
| D-6 | **Employees use HRMS through the ERP:** they punch and view their own data in the ERP's screens. |
| D-7 | **Onboarding can happen in the ERP or in HRMS.** Whichever system is used first, the other one gets the employee. |
| D-8 | **Who issues employee codes is set in HRMS, per company, with the existing Employee ID scheme setting** (Organization → Employee ID schemes). A company with a scheme gets its codes from HRMS. A company without one uses the code typed in, which is the ERP's code. |
| D-9 | **Enterprise-grade and dynamic** (2026-10-12): every integration rule is configuration that authorised people change in the UI, per company, with versions, history and a preview of the effect. Nothing is fixed in code. |
| D-10 | **HRMS sends data to other third-party applications too** (2026-10-12), with HRMS as the hub: any number of connected apps, each with its own permissions. |
| D-11 | **Each app connects the way it can** (2026-10-12): webhook, read API, connector, or scheduled file. "Add app" suggests the method (§9.2). |
| D-12 | **What Suraj and Sharanga actually use** (2026-10-12): the ERP and CRM **only read HRMS through its API**, polling the events feed and read endpoints, and still write through the sync API (§7). They don't receive webhooks. There is **no access control or canteen system**, and **no Google Workspace, Microsoft 365, Slack or Teams**. |

### Defaults this plan assumes (confirm or change; see §17)

| # | Default |
|---|---|
| A-1 | The ERP connects **server-to-server only**. HRMS tokens and keys never reach a browser or a mobile app. |
| A-2 | Sync covers **identity and job data only** (name, contact details, company, department, location, designation, manager, dates). KYC, bank and salary data are not accepted through sync. They stay in HRMS. |
| A-3 | Sync can grant only the `EMPLOYEE` and `MANAGER` roles. HR, Accounts and Admin roles are granted in HRMS, where MFA applies. This is a fixed security rule, not a setting. |
| A-4 | Integrations are **off for every tenant** until its administrator creates the first key. |

---

## 2. How it works

```
 Employee ── uses ──► ERP / CRM screens
                          │
                          ▼
                     ERP / CRM server ── X-API-Key ──►  HRMS  /v1/integrations/*
                          │                               │  (1) employee sync
                          │                               │  (2) issue an employee session token
                          └──── Bearer <employee token> ─►  HRMS  existing /v1 self-service endpoints
                     ERP / CRM server ◄── signed webhook ───  HRMS  (3) employee hired / changed / exited in HRMS
```

There are two credentials, with different jobs:

| Credential | Who holds it | What it can do | Lifetime |
|---|---|---|---|
| **API key** | The ERP's server, one key per system (ERP, CRM) per tenant | Sync employees, and request a session token for one employee. **It cannot read or change attendance, leave or anything else.** | Up to 1 year, revocable instantly |
| **Employee session token** | The ERP's server, one per employee at a time | Exactly what that employee could do signed in to HRMS themselves: their own data, or their team's if they are a manager | 60 minutes by default |

---

## 3. Scope

**In v1:** API keys and their administration; mapping of reference data; linking existing employees; create, update, exit and
rehire through sync; bulk sync; **onboarding in HRMS with automatic linking and duplicate detection (§7.7)**; **the events
feed**, through which the ERP and CRM read HRMS's employee events (§7.8); employee session tokens; recording ERP punches; the
sync log; reconciliation; metrics and alerts; the developer guide.

**Also in v1:** connected apps with the read API, the event catalogue and per-app permissions (§9); the integration settings,
with versions, preview and per-company overrides (§6); OAuth 2.0 client credentials as well as API keys (§11.1).

**Product backlog: designed in this plan, built when a customer needs it (§16):**

- **B-1 push webhooks** (§9.2.1): for customers whose apps can receive `https` calls.
- **B-2 scheduled file feeds** (§9.2.4): for access control, canteen and other file-only systems.
- **B-3 direct connectors** (§9.2.3): Google Workspace, Microsoft 365, and outbound SCIM (Slack, Zoom, Atlassian).
- **B-4 single sign-on:** OIDC and SAML per tenant, plus one-click opening of HRMS from the ERP.
- **B-5 inbound SCIM 2.0**, for identity providers.

**Not in this plan:**

- payroll amounts in events (payroll has its own files, §9.3)
- syncing KYC and bank data (§6.4)
- packaged connectors

---

## 4. What the code looks like today, and what has to change

This was checked against the code on 2026-10-12.

| Area | Today | Change needed |
|---|---|---|
| Authentication | `core/authn.py` accepts only an HRMS JWT, from the `Authorization` header or the session cookie (`core/browser_sessions.py`) | A separate `get_integration_principal` dependency reads `X-API-Key`. **It is accepted only on `/v1/integrations/*`.** Ordinary routes never accept an API key. |
| `api_keys` table | Has name, prefix, `key_hash`, `scopes`, `allowed_ips`, expiry, `rate_limit_per_minute`, usage counters. Unused. | Add `system_code`, `legal_entity_ids`, `session_ttl_minutes`, `revoked_at` and `revoked_by`. Look keys up through a `SECURITY DEFINER` function, the same way `login_lookup` works, because no tenant context exists yet when the key is checked. |
| Link to the external system | `user_accounts.erp_system` / `erp_user_id`: **one** external ID per login | A new `external_identities` table holds **one row per system**, because one person can be in both the ERP and the CRM under different IDs. Existing values are copied over, and the old columns are kept until a later contract migration. |
| Per-request account check | `core/database.get_session` rejects inactive or separated accounts and stale `token_epoch` values, enforces `must_change_password`, and requires MFA for `PRIVILEGED_ROLES` | For ERP session tokens (claim `via`): (a) also check, in the same query, that the issuing key is still active; (b) skip `must_change_password`, because the employee authenticated in the ERP; (c) allow only the routes on the self-service list (§8.4). |
| Scope | `core/authz.resolve_scope` builds the scope from `role_assignments` | When `principal.via` is set, drop every grant except `EMPLOYEE` and `MANAGER` (A-3). Because of that, the MFA requirement never applies to an ERP session. |
| Creating an employee | Three calls today: `POST /v1/persons`, then `POST /v1/employees`, then `POST /v1/users`, plus an assignment that needs `org_unit_id`, `location_id` and `job_id` | One sync service creates all of these in one transaction, using the same internal functions the routers use, not HTTP calls. |
| Job changes and exit | Personnel actions: `TRANSFER`, `PROMOTION`, `SEPARATION` and others, with an `idempotency_key`. A separation sets `SEPARATED`, and `get_session` then locks the account out. | The sync turns changes into personnel actions, so history, effective dates and audit records work as they do today. |
| Employee codes | `EmployeeIdScheme` (`modules/org/models.py`), per company or for the whole tenant: a prefix plus a running number. `_next_employee_number` in `people/router.py` adds 1 and issues that number **without checking whether it is already used**. | The generator skips numbers already in use. When a code arrives from the ERP that matches a company's scheme pattern, the counter moves past it (§7.7). Without this, an ERP code `SFPL-0050` and the counter's next `SFPL-0050` would collide. |
| HRMS hiring | The employee page and `POST /v1/employees` create employees with no link to any outside system | After each hire, termination, rehire or change, write an **outbox** row in the same transaction. The ERP reads it from the events feed (§7.8). |
| HRMS edit paths | People `PATCH` endpoints, personnel actions, `PATCH /v1/persons/me` and imports change any field. Nothing knows about an outside owner. | One `assert_fields_editable` check in all of them, with a guard test, and `GET /v1/employees/{id}/field-control` for the UI (§6.2) |
| Settings with versions | Attendance policies already keep versions with effective dates. There is no general settings framework yet (enterprise plan F5). | Integration profiles use the same draft → publish → effective date pattern. When F5 lands they move onto it, without changing behaviour. |
| Punch source | `PunchSource` = `WEB`, `MOBILE`, `DEVICE`, `MANUAL` | Add `INTEGRATION`, plus a nullable `source_system` column. The value is **taken from the token, not from the request body**. |
| Change audit | `core/change_audit.record_change`, append-only `entity_change_log` | Add `api_key` and `external_identity` to `ENTITY_TYPES`. Sync changes are recorded with the actor "*Key name* (ERP)". |
| Rate limiting | Exists only for login (`core/throttle.py`, in Postgres). No Redis in the stack. | A per-key, per-minute counter in Postgres, using the same pattern as `auth_throttle`. |
| Background jobs | `jobs/runner.py` `JOBS` | Add three jobs: sync-log retention, key-expiry warnings, and resolving pending managers. |
| API docs | `core/endpoint_docs/*`. Tests check that every endpoint is documented, and check the `PUBLIC` list. | Document every new endpoint. `/v1/integrations/*` is **not** public, so it is described with its own `ApiKeyAuth` security scheme. |

---

## 5. Data model (migration `0051_integrations`)

All new tables are tenant-scoped, with RLS and `hrms_app` grants like the rest of the schema. The migration only adds and
copies (expand/contract), because the testing database holds real data.

**`api_keys`: new columns**

| Column | Purpose |
|---|---|
| `system_code` varchar(20) | `ERP`, `CRM`, or a tenant-chosen code. It decides which external IDs the key works with. |
| `legal_entity_ids` jsonb null | Limits the key to these companies. Null means every company in the tenant. |
| `session_ttl_minutes` int, default 60 | Lifetime of the employee tokens this key issues (allowed range 5–480). |
| `revoked_at`, `revoked_by` | Revocation, with an audit trail. Revoking also ends the sessions this key issued. |

**Scopes:**

| Scope | Allows |
|---|---|
| `employees.sync` | Create, update, exit and rehire employees |
| `employees.read` | Read back employees and reference data |
| `passwords.sync` | Set or change passwords through sync |
| `sessions.issue` | Issue employee session tokens |

**`external_identities`**: `(tenant_id, id, system_code, external_id, employment_id, user_account_id,
pending_manager_external_id, last_source_updated_at, created_at, updated_at)`

- Unique on `(tenant_id, system_code, external_id)` and on `(tenant_id, system_code, employment_id)`.
- `last_source_updated_at` is the ordering guard described in §7.4.

**`integration_mappings`**: `(tenant_id, id, system_code, kind, external_value, target_id)`

- `kind` is `LEGAL_ENTITY`, `DEPARTMENT`, `LOCATION`, `DESIGNATION` or `ROLE`.
- Unique on `(tenant_id, system_code, kind, lower(external_value))`.

**`integration_requests`** (the sync log, append-only: `hrms_app` gets only `INSERT` and `SELECT`, the same rule as
`entity_change_log`):

- **Columns:** `id`, `api_key_id`, `system_code`, `operation`, `external_id`, `employment_id`, `idempotency_key`,
  `request_hash`, `outcome`, `error_code`, `error_detail`, `changes` jsonb, `http_status`, `duration_ms`, `request_id`,
  `created_at`.
- **`operation`:** `UPSERT`, `EXIT`, `REHIRE`, `BULK`, `LINK`, `SESSION`, or `RECONCILE`.
- **`outcome`:** `CREATED`, `UPDATED`, `NO_CHANGE`, `STALE_IGNORED`, `REJECTED`, `FAILED`, or `HELD_FOR_REVIEW`.
- **`changes`** is the field-level diff. Passwords are never stored, and contact fields are masked.
- **Indexes:** `(tenant_id, created_at desc)`, `(tenant_id, external_id)`, and a unique index on `(tenant_id, api_key_id,
  idempotency_key)` where the key is not null.

**`api_key_rate_windows`**: `(api_key_id, window_start, count)`. Updated with one `INSERT … ON CONFLICT … RETURNING count` per
request.

**`punches`: new column** `source_system` varchar(20) null.

**`integration_profiles`**: `(tenant_id, id, system_code, legal_entity_id null, version, status, effective_from, settings jsonb,
field_ownership jsonb, created_by, published_by, published_at)`.

- `status` is `DRAFT`, `PUBLISHED` or `SUPERSEDED`.
- A null `legal_entity_id` is the tenant default. A row with a company set holds only that company's overrides.
- A published version is never edited; a change is a new version.
- The profile in force is the latest `PUBLISHED` row whose `effective_from` is on or before today. It is cached per request.
- `settings` is checked against a versioned JSON schema in code, so a bad setting can't be saved.

**`connected_apps`**: `(tenant_id, id, code, name, kind, status, created_by, created_at, paused_at, disconnected_at)`.

- `kind` is `TWO_WAY`, `RECEIVE_ONLY` or `READ_ONLY`, and `status` is `ACTIVE`, `PAUSED` or `DISCONNECTED`.
- `code` is the `system_code` every other table refers to. Each app's events, fields, people and data classes live in its
  integration profile (§6.1), under `settings.outbound`.

**`file_feeds`**: `(tenant_id, id, app_id, name, content, mode, columns jsonb, format jsonb, filename_pattern, schedule,
destination_type, destination_config_enc, pgp_public_key, done_marker, cursor, is_active, created_by, created_at)`.

- `mode` is `FULL` or `DELTA`. `schedule` is cron-like, or `ON_EVENT`. `destination_type` is `SFTP`, `S3`, `EMAIL` or `NONE`.
- `destination_config_enc` holds the host, user and key (or bucket and role, or addresses), encrypted with
  `core/field_crypto.py`.

**`file_feed_runs`**: `(tenant_id, id, feed_id, started_at, finished_at, rows, sha256, file_ref, outcome, error, cursor_from,
cursor_to, attempt)`. `file_ref` points to the kept copy in the document store (30 days).

**`integration_reads`**: `(tenant_id, id, app_id, path, cursor, rows, employment_ids_hash, created_at)`. The read-API part of the
per-app log (§9.4). It stores a hash of the employee list, and the full list for 30 days.

**`oauth_clients`**: `(tenant_id, id, system_code, client_id, secret_hash, scopes, allowed_ips, legal_entity_ids, is_active,
expires_at, created_by, created_at, revoked_at)` (§11.1).

**`webhook_endpoints`**: `(tenant_id, id, system_code, url, secret_hash, events jsonb, is_active, created_by, created_at,
disabled_reason)`. One endpoint per system. `events` lists what it receives (e.g. `employee.hired`). The signing secret is
shown once, like an API key.

**`integration_outbox`**: `(tenant_id, id, event_type, employment_id, payload jsonb, created_at, origin)`.

- It is written **in the same transaction** as the HR change, so an event is never lost and never sent for a change that
  rolled back.
- `origin` records which system made the change (`HRMS` or a system code). A change that came *from* the ERP is not sent back
  to that ERP, which avoids loops.

**`webhook_deliveries`**: `(tenant_id, id, outbox_id, endpoint_id, attempt, status, http_status, response_ms, next_attempt_at,
last_error, delivered_at)`. `status` is `PENDING`, `DELIVERED`, `FAILED` or `DEAD`.

**`possible_duplicates`**: `(tenant_id, id, system_code, external_id, employment_id, match_reason, status, resolved_by,
resolved_at)`. A queue for HR (§7.7).

---

## 6. Integration settings: everything configurable (D-9)

### 6.1 The integration profile

Each connected system (ERP, CRM) has **one integration profile per tenant**:

- **Per-company overrides.** Any company can override any setting. Otherwise it inherits the tenant default, and the screen
  shows each setting as *inherited* or *overridden*.
- **Versions.** Profiles are versioned: **draft → preview (§6.3) → publish with an effective date**. Earlier versions are kept,
  and every change is in the change history (`entity_change_log`). To roll back, publish an earlier version again.
- **Who can change them:**
  - `integrations.manage` (tenant administrator): keys, OAuth clients, webhook endpoints.
  - `integrations.configure` (HR Head, if the administrator grants it): ownership, lifecycle, mappings, matching, logins,
    self-service.
  - Both go through the role builder (enterprise plan F1) once it exists.

| Group | Setting | Options | Default |
|---|---|---|---|
| **Field ownership** | The owner of each field (§6.2) | the system / HRMS / Shared / Not synced | Preset *"ERP is master for job data"* |
| | When the system sends a field it doesn't own | Ignore with a warning / Reject | Ignore with a warning |
| | When HR edits a field the system owns | Not allowed / Allowed with a reason / Allowed with approval | Allowed with a reason |
| **Lifecycle** | Where hiring is allowed | the system / HRMS / Both | Both (D-7) |
| | Where job changes, exits and rehires are allowed (each set separately) | the system / HRMS / Both | Both |
| **Employee codes** | Who issues codes | Read from the company's Employee ID scheme (D-8). Shown here, with a link to Organization → Employee ID schemes. | — |
| **Value mappings** | ERP value → HRMS company, department, location, designation, role | A table, plus a default location per company | — |
| | Unknown value | Reject and queue for mapping / Create automatically | Reject and queue |
| **Matching** | Link automatically when these match an unlinked HRMS employee | Code + name + date of birth / Code + email / Never automatically | Code + name + date of birth |
| **Logins** | Password for a new login | ERP password if sent, otherwise the default pattern / Always the default pattern / Random password plus an invite / No direct HRMS sign-in (through the ERP only) | ERP password, otherwise the default pattern (D-4) |
| | Default password pattern | A template, e.g. `{FirstName}@1234` | `{FirstName}@1234` |
| | Force a change at the first direct sign-in | Yes / No | Yes |
| | ERP role value → HRMS role | A mapping. It can only map to `EMPLOYEE` or `MANAGER` (§6.4). | Everything → `EMPLOYEE` |
| **Self-service through the ERP** | Features | Punch / Attendance view / Corrections / Leave / Profile edit / Manager approvals, each on or off | All on |
| | Session lifetime | 5–480 minutes | 60 |
| **Safety** | Exit safety valve | Maximum count and % in 24 hours; what happens over the limit (Hold for review / Reject) | 20 or 5%, Hold |
| **Webhooks** | Events sent, and the fields included | Per event; only fields this system doesn't own | All four employee events |
| **Retention** | How long the sync log is kept | 90–1,095 days | 400 days |

### 6.2 Field ownership

**The field catalog** is a registry in code that lists every field that can be synced:

| Kind | Fields |
|---|---|
| Name and personal | first name, last name, preferred name, date of birth, gender |
| Contact | email, mobile |
| Job | employee code, company, department, location, designation, manager |
| Dates | hire date, last working day |
| Later | grade and employment type, once R1 adds them; **custom fields**, which join automatically once the custom-fields registry (enterprise plan F3) exists |

A new field joins the catalog in one place, and the screens, enforcement and webhooks pick it up.

**What each owner means:**

| Owner of a field | An incoming change from that system | Editing it in HRMS (screens, API, the employee's own profile) | A change in HRMS is sent to that system |
|---|---|---|---|
| **The system** (e.g. ERP) | Applied | **Locked**, shown as *"Managed by ERP"*. It can be edited only if the override setting allows it; an override is recorded as a bypass with its reason, and the next ERP update to that field replaces it. | Only overrides, flagged `override: true` |
| **HRMS** | Ignored with a warning `FIELD_OWNED_BY_HRMS`, or rejected, per the setting | Normal | Yes |
| **Shared** | Applied. The latest change in the source wins (§7.4). | Normal | Yes |
| **Not synced** | Ignored | Normal | No |

**HRMS is the hub between systems.** Each field has **at most one external owner**. When a tenant connects both an ERP and a
CRM, a field the ERP owns reaches the CRM through HRMS's webhooks. The CRM can't also own it, so the two systems never fight
over a value.

**Presets.** These fill in the matrix in one click; any field can then be changed.

| Preset | What it sets |
|---|---|
| **ERP is master for job data** (recommended, the usual enterprise setup) | **ERP:** name, date of birth, gender, code, company, department, location, designation, manager, hire date, last working day. **Shared:** email, mobile. **HRMS:** everything else. |
| **HRMS is master** | HRMS owns everything, and the ERP only receives changes. |
| **Shared** | Every field Shared, latest change wins. This is the original D-3. |

**Enforcement is in one place.**

- `assert_fields_editable(session, employment_id, fields, actor)` is the only function that decides whether a field can be
  changed. It is called by every HRMS write path: the people and employee `PATCH` endpoints, personnel actions,
  `PATCH /v1/persons/me`, and imports.
- A guard test fails the build if a write endpoint for a catalog field doesn't call it, in the same way as the existing
  endpoint-docs guard tests.
- The UI reads `GET /v1/employees/{id}/field-control`, which returns each field's owner, whether it is locked and the override
  rule. That shows the locks and the *"Managed by ERP"* badge without the UI repeating the rules.

### 6.3 Preview and safe change

- **Preview a draft.** Shows how many employees are affected, which fields become locked or unlocked, and which events start or
  stop. It also lists recent HR edits to fields that would switch to the ERP, because the ERP's next update to those fields
  will replace them.
- **Dry run.** `PUT /v1/integrations/employees/{id}?dry_run=true` returns exactly what would change under the published
  profile (or the draft, with `&profile=draft`) without saving. ERP developers use it while building.
- **Publishing** takes effect at the start of the effective date in the tenant's business time zone (`business_today()`). A
  change in the middle of a day never splits a request.
- **Health check.** The Settings page warns about settings that conflict, for example:
  - hiring set to *HRMS only* while the ERP owns `employee_code` and the company has no ID scheme;
  - a webhook event switched off while hiring is allowed in HRMS.

### 6.4 Fixed rules (never settings)

These are security rules. Making them configurable would turn a mistaken setting into a breach:

- Sync and ERP sessions can grant only `EMPLOYEE` and `MANAGER` (A-3).
- Credentials are used server-to-server only, and CORS is never opened (A-1).
- No KYC, bank or salary data is accepted or sent through sync in v1 (A-2).
- Passwords are never logged or sent out.
- The tenant always comes from the credential.
- RLS on every table, and the audit log and sync log are always on.
- The exit safety valve can be set higher, but **never switched off**.

---

## 7. Employee sync API

The base path is `/v1/integrations`, and every call needs `X-API-Key`. The key decides the tenant and the system, so **the
payload never names a tenant or a system**. An ERP key therefore cannot write CRM identities, or reach another tenant.

### 7.1 Endpoints

| Method and path | Scope | Purpose |
|---|---|---|
| `GET /reference-data` | `employees.read` | The companies, departments, locations, designations and roles HRMS knows, with their codes and the mappings already set. The ERP developer uses it to build their mapping. |
| `POST /employees/link` | `employees.sync` | Links employees who are already in HRMS to their ERP IDs, by employee code (or email). `dry_run: true` returns the match report without saving. Run once at go-live. |
| `PUT /employees/{external_id}` | `employees.sync` | **Create or update** one employee. This is the main call. |
| `GET /employees/{external_id}` | `employees.read` | What HRMS holds now, for reconciliation. |
| `POST /employees/{external_id}/exit` | `employees.sync` | Separation, with `last_working_day` and `reason_code`. |
| `POST /employees/{external_id}/rehire` | `employees.sync` | Rehire, with a new `hire_date`. |
| `POST /employees/bulk` | `employees.sync` | Up to 200 upserts in one call, at most 1 MB. Each record gets its own result. |
| `POST /reconcile` | `employees.read` | The ERP sends its full list of active external IDs, and HRMS returns the differences: in the ERP but not in HRMS, active in HRMS but not in the ERP, and status mismatches. **It reports differences only and never changes anything.** |
| `POST /sessions` | `sessions.issue` | Issues an employee session token (§8). |

### 7.2 Upsert payload

```json
PUT /v1/integrations/employees/EMP-1042
X-API-Key: hrms_live_ab12cd34_…
Idempotency-Key: 7f3c2e9a-…            (optional on PUT, required on POST)

{
  "source_updated_at": "2026-10-12T09:14:03+05:30",
  "employee_code": "SFPL-1042",
  "first_name": "Ramesh",
  "last_name": "Patil",
  "email": "ramesh.patil@surajgroup.in",
  "mobile": "+919876543210",
  "date_of_birth": "1991-04-18",
  "gender": "MALE",
  "company": "SFPL",
  "department": "Operations",
  "location": "Nhava Sheva",
  "designation": "Executive",
  "manager_external_id": "EMP-0877",
  "role": "EMPLOYEE",
  "hire_date": "2026-10-15",
  "effective_date": "2026-10-15",
  "password_hash": "$2b$12$…"
}
```

**Required to create an employee:** `employee_code`, `first_name`, `last_name`, `company`, `department`, `designation`,
`hire_date`, and `location` (or a default location set per company, O-8).

**Updates:**

- Only the fields that are present are changed. A field that is left out stays as it is.
- An explicit `null` clears an optional field.
- `effective_date` (default: today) sets when a change of company, department, location, designation or manager takes effect.

**Responses:**

- `201` with `outcome: CREATED`, or `200` with `UPDATED` / `NO_CHANGE` / `STALE_IGNORED`.
- The body carries `employment_id`, `user_account_id`, `employee_code`, `changes[]` and `warnings[]` (for example
  `MANAGER_PENDING`).

### 7.3 What an upsert does

1. **Check the key:** it is active, not expired, the IP is allowed, it has the right scope, and the request is within the rate
   limit.
2. **Take a transaction-level advisory lock** on (tenant, system, external_id). Two concurrent `PUT`s for the same person then
   run one after the other. The unique index is a second guard, so concurrent calls can never create two people.
3. **Resolve `company`, `department`, `location`, `designation` and `role`.** First through `integration_mappings`, then by exact
   code, then by exact name, ignoring case.
   - A value that doesn't match is **rejected** (`UNKNOWN_DEPARTMENT` etc., with the value), and goes into the *Unmapped
     values* queue in the admin screen. HR maps it, and the ERP's retry then succeeds (O-2).
   - A company outside the key's `legal_entity_ids` gives `ENTITY_NOT_ALLOWED`.
   - A `role` other than `EMPLOYEE` or `MANAGER` gives `ROLE_NOT_ALLOWED` (A-3).
4. **Load the profile in force** for the employee's company (§6.1). Check the lifecycle setting: if hiring from this system
   is not allowed, the result is `OPERATION_NOT_ALLOWED`. **Apply field ownership** (§6.2): fields this system doesn't own are
   dropped with a `FIELD_OWNED_BY_HRMS` warning, or rejected, per the setting.
5. **Ordering guard (§7.4).**
6. **Create** (no identity row yet). Run the matching rules first (§7.7). Then create the person, employment, assignment,
   manager link, user account (password per the profile's login settings, §10), role assignment (`SELF` for `EMPLOYEE`,
   `DIRECT_REPORTS` for `MANAGER`) and the external identity, all in one transaction. The employee code is set per D-8: the
   ERP's code if the company has no ID scheme, otherwise the next HRMS code, which is returned.
7. **Update:**
   - **Person and contact fields** are updated in place, and each change goes through `record_change`.
   - **Job fields** become a personnel action: a different department, location or manager is a `TRANSFER`; a different
     designation is a `PROMOTION` or a transfer, per O-9. The action's `idempotency_key` is derived from the request. It is
     applied straight away if `effective_date` is today or earlier, otherwise scheduled.
8. **Manager not synced yet:** store `pending_manager_external_id` and return warning `MANAGER_PENDING`. When the manager is
   synced, the link is made automatically, and the hourly job tries again.
9. **Uniqueness:** an email or mobile number used by another login gives `409 EMAIL_IN_USE` / `MOBILE_IN_USE`, and an employee
   code already in use gives `EMPLOYEE_CODE_IN_USE`. Nothing is half-saved.
10. **Write the `integration_requests` row and commit.** The log row is written even when the request fails; a failed request
   logs it in its own short transaction, the same way `core/throttle.py` handles failures.

### 7.4 Ordering, and Shared fields

Field ownership (§6.2) settles most conflicts: a field has one owner, so only one side can change it. Two cases still need an
order: **Shared** fields, and repeated messages from the owner itself. For both, HRMS uses the **time the change was made in
the source**, not the order requests happen to arrive in:

- The ERP sends `source_updated_at`, the time the record changed in the ERP.
- HRMS keeps `last_source_updated_at` for each external identity. A request older than that is a delayed retry or arrived out
  of order. It is **ignored and logged as `STALE_IGNORED`**, so an old message can't undo a newer one.
- For a **Shared** field, an HR edit in HRMS *after* the last ERP update stays until the ERP sends a newer change to that same
  field.
- **The rule for ERP developers is to send only the fields that changed.** It matters only for Shared fields, because fields
  owned by HRMS are dropped anyway. The sync log shows every overwritten Shared field (old → new).

### 7.5 Exit and rehire

**Exit** creates a `SEPARATION` personnel action effective on `last_working_day`.

- From the day after it, the existing `get_session` check locks the account out, and the ERP can no longer get a session token
  for that person.
- Leave balances, attendance and payroll records are kept. Nothing is deleted (this follows the import plan's "no hard delete"
  rule).
- A `last_working_day` inside a locked payroll period is rejected with `PERIOD_LOCKED`. HR handles those cases in HRMS.

**Safety valve.** If one key exits more than **20 employees, or 5% of the tenant's active headcount, within 24 hours**
(configurable, O-5), further exits are saved as `HELD_FOR_REVIEW`, and HR gets a notice. HR releases or rejects them in the
admin screen. A faulty ERP job or a stolen key therefore cannot lock out a whole company.

**Rehire** uses the existing `REHIRE` action and reactivates the same login.

### 7.6 Bulk and first load

- **`POST /employees/link` (dry run first):** matches the ERP's existing employees to HRMS employees by employee code. It
  returns *matched*, *not in HRMS*, *not in the ERP* and *ambiguous*. A second call without `dry_run` saves the links.
- **`POST /employees/bulk`:** each record runs in its own savepoint, the same pattern as `scripts/migrate_tenants.py`, so one bad
  record doesn't fail the rest. The response is a result per record, in the same order as the request.
- **Order for a first load:** run `link` first, then bulk-create the people still missing, managers before their reports. Any
  `MANAGER_PENDING` links resolve automatically once the manager exists.

### 7.7 Onboarding in HRMS, and in both systems (D-7, D-8)

**Who issues the code.** Each company's Employee ID scheme setting already decides this. HRMS reads it; nothing new to set up:

| The company in HRMS has… | Onboarded in the ERP | Onboarded in HRMS |
|---|---|---|
| **No ID scheme** (the ERP issues codes) | The ERP sends its code in `employee_code`, and HRMS uses it as is. | HR types the employee's ERP code when hiring, as the hiring form already requires when there is no scheme. HRMS publishes `employee.hired` to the events feed, and the ERP links the person by that code. If HR hires before the person exists in the ERP, the ERP creates them from the event with that code. |
| **An ID scheme**, e.g. `SFPL-` + 4 digits (HRMS issues codes) | The ERP may leave out `employee_code`. HRMS issues the next code and returns it in the response, and the ERP must save it. If the ERP does send a code, HRMS accepts it if unused and moves the counter past it if it matches the pattern. | HRMS issues the code as it does today, and publishes it in `employee.hired`. |

**HRMS-first flow:**

1. HR hires the employee in HRMS, in the usual screens.
2. In the same transaction, HRMS writes an `employee.hired` event to the outbox.
3. The ERP reads it from the events feed on its next poll (§7.8), within a minute at the recommended polling interval. The
   event carries the code, name, contact details, company, department, location, designation, manager, hire date and
   `employment_id`.
4. The ERP creates its record, then calls `PUT /v1/integrations/employees/{erp_id}` with `"employment_id": "emp_…"` (or the
   same `employee_code`). That links the two. From then on everything works exactly as for an ERP-first employee.
5. **Not linked within 24 hours:** the employee appears in the admin screen's *Not linked* list and the
   `HrmsIntegrationUnlinkedHires` alert fires. Nothing is blocked: the employee works in HRMS normally.

**Logins for HRMS-first employees:** the login is created as it is today, in HRMS. There is no ERP password to reuse, so D-4's
default applies. The ERP never receives the HRMS password.

**Matching when the ERP sends someone not yet linked.** HRMS does this before creating anything:

| What matches an existing, unlinked HRMS employee | Result |
|---|---|
| The `employment_id` sent | Linked. `outcome: LINKED` |
| `employee_code` **and** first name, last name and date of birth (or email) | Linked automatically. `outcome: LINKED` |
| `employee_code` alone, or email or mobile alone | **Not linked and not created.** A row goes into `possible_duplicates`, and the response is `409 POSSIBLE_DUPLICATE` with the HRMS `employment_id`. HR confirms ("same person") or rejects ("different person") in the admin screen. The ERP's retry then succeeds. |
| Nothing | Created as a new employee (§7.3) |

An employee already linked to another external ID **in the same system** is never re-linked automatically
(`ALREADY_LINKED`).

**The "Add employee" button follows the lifecycle setting** (§6.1).

- **Hiring allowed in HRMS** (the default, D-7): the button is on, and the hiring form shows a note: *"This company is connected
  to ERP. The new employee will be sent to ERP after saving."*
- **Hiring set to the ERP only:** the button is off for that company, with the note *"New employees for this company are
  onboarded in ERP."*

Exits, rehires and job changes follow their own settings in the same way.

### 7.8 Events, HRMS → ERP

**How the ERP gets them in v1: the events feed (pull).** Push webhooks are backlog item B-1, and use the same events and
payloads.

```
GET /v1/integrations/events?after=<cursor>&limit=500
X-API-Key: hrms_live_…

200 → { "events": [ { "id": "evt_…", "event": "employee.hired", "occurred_at": "…", "employment_id": "emp_…",
                      "external_id": null, "employee": { … }, "changes": null }, … ],
        "next_cursor": "c_000000123457", "has_more": false }
```

- **Polling.** The ERP polls every 30–60 seconds and passes the `next_cursor` it last received. An empty page means it is
  up to date, and an empty poll costs one indexed query.
- **Nothing is skipped.** A plain "id greater than the cursor" query can miss an event: a transaction that took id 101 can
  commit *after* one that took id 102, by which time the reader has already moved past 101. The feed therefore returns only
  events from transactions that are already finished, using `pg_current_snapshot()` and `pg_snapshot_xmin`, so the cursor
  never moves past an event that is still being committed. A test forces this ordering on purpose.
- **Order.** Events come in the order they were saved, so one employee's events are always in order.
- **The cursor confirms receipt.** When an app sends a later cursor, it has received everything before it. HRMS records each
  app's position. This is what the *app is falling behind* alert and the checklist ticks use.
- **Retention.** Events are kept 30 days. An ERP that falls further behind resyncs with
  `GET /v1/integrations/employees?updated_since=` and then carries on from the current cursor, which a `resync_cursor` field
  gives it.
- **Delivery timing (§9.5)** works the same way: an event scheduled for later only appears in the feed once it is due.

**Confirmation for HRMS-first hires.** "Sent to the ERP" is confirmed when the ERP *links* the employee (§7.7, step 4), not
merely when it reads the event. That link is what ticks the onboarding checklist task.

**Events in v1:**

| Event | Sent when |
|---|---|
| `employee.hired` | A hire is saved in HRMS |
| `employee.updated` | Any synced field changes in HRMS (name, contact details, company, department, location, designation, manager) |
| `employee.separated` | A separation is saved (with the last working day), or is applied on its effective date |
| `employee.rehired` | A rehire is saved |

**Which fields are sent:** only the fields the receiving system doesn't own (§6.2), and only for the events switched on in its
profile. Overrides of fields it does own are sent with `override: true`. Changes that came from the ERP itself are not sent back to it. The same change is still sent to the *other* system (the CRM),
if that system subscribes.

**Payload:**

```json
POST https://erp.example.com/hrms/webhook
HRMS-Event: employee.hired
HRMS-Delivery: dlv_01J…           (unique per delivery, so the ERP can ignore duplicates)
HRMS-Timestamp: 1760245200
HRMS-Signature: v1=4f9c…           (HMAC-SHA256 of "timestamp.body" with the endpoint's secret)

{ "event": "employee.hired", "occurred_at": "2026-10-12T10:02:11+05:30",
  "employment_id": "emp_…", "external_id": null,
  "employee": { "employee_code": "SFPL-0213", "first_name": "…", "…": "…" },
  "changes": null }
```

- `employee.updated` lists only the changed fields in `changes`, as old → new.
- The ERP must check the signature, and reject any timestamp more than 5 minutes old. The developer guide includes the check in
  Python and Node.

**Delivery:**

- **Order:** events for the same employee are sent one at a time, in order. Events for different employees are sent in
  parallel.
- **Retries:** after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours, then every 6 hours, for up to 3 days. After that the
  delivery is `DEAD`, the alert fires, and HR or the admin can resend it from the admin screen.
- **Success** is any `2xx` response within 10 seconds.
- **Repeated failure:** an endpoint that fails 100 deliveries in a row is disabled automatically, and the admin is told.
  Deliveries keep queuing while it is disabled, and are sent once it is re-enabled.
- **Who sends them:** a new job in `jobs/runner.py` delivers every few seconds. It locks rows with `FOR UPDATE SKIP LOCKED`, so
  several workers never send the same delivery.
- **Privacy:** no KYC, bank or salary data is sent (A-2), and no passwords.

**Webhook URLs:** must be `https` (in testing, a `http` URL on a private network is allowed). Only the tenant administrator can
change them, and each change is audited.

---

## 8. Self-service through the ERP (D-6)

### 8.1 Getting a token

```json
POST /v1/integrations/sessions
X-API-Key: hrms_live_ab12cd34_…
{ "external_id": "EMP-1042" }

200 → { "access_token": "eyJ…", "token_type": "bearer", "expires_in": 3600,
        "employment_id": "emp_…", "roles": ["EMPLOYEE"] }
```

**HRMS refuses the token (`403`, with a code)** when:

- the employee isn't linked (`NOT_LINKED`),
- their account is disabled (`ACCOUNT_INACTIVE`),
- they are separated (`EMPLOYEE_SEPARATED`),
- their company is outside the key's companies (`ENTITY_NOT_ALLOWED`),
- or the tenant is suspended.

**What the token is.** A normal HRMS access token (`create_access_token`) with three extra claims:

- `via`: the API key's ID
- `ext`: the system code
- `amr: ["integration"]`

It carries the account's current `token_epoch`, so a password change or reset in HRMS ends it. Each issued token is logged
(operation `SESSION`). The token itself is never logged.

**Reuse.** The ERP should keep the token for that employee until it is about to expire, not ask for a new one on every click.
Session requests are rate-limited per key like everything else.

### 8.2 Using it

The ERP calls the **existing** endpoints with `Authorization: Bearer <token>`, for example `POST /v1/time/punches`
`{ "punch_type": "IN" }`. Every existing rule applies unchanged:

- scope checks,
- the punch state machine,
- server time on every punch, with no backdating,
- `LONG_DAY_CONFIRM`,
- leave balance rules,
- approval routing.

### 8.3 How a token is limited

| Rule | Why |
|---|---|
| Only the `EMPLOYEE` and `MANAGER` grants carry over. HR, Accounts and Admin grants are left out (A-3). | A stolen ERP token can never do HR work. Privileged work happens in HRMS, behind MFA. |
| `must_change_password` is not enforced. | The employee authenticated in the ERP. Without this, every employee on the default `Firstname@1234` password would be blocked in the ERP until they signed in to HRMS. |
| Every request re-checks the account status, `token_epoch`, *and that the issuing key is still active* (one join in `get_session`'s existing account query). | Revoking a key, or separating an employee, takes effect on the next request, not when the token expires. |
| Only the self-service routes are allowed (§8.4). Anything else returns `403 NOT_AVAILABLE_VIA_INTEGRATION`. | Defence in depth, if a future endpoint forgets a permission check. |
| Punches made with it are saved as `source = INTEGRATION`, `source_system = <ext>`. These come from the token, never from the body. | HR can see and report which punches came through the ERP. The ERP can't pass them off as `WEB` or `DEVICE`. |
| CORS is **not** opened for ERP origins. | Tokens stay on the ERP's server (A-1). |

### 8.4 Routes an ERP session may call (v1)

- **Identity:** `/v1/auth/me`
- **Profile:** `/v1/persons/me` (read and update)
- **Attendance:** punches (create, list), own day and month attendance, corrections (create, list, cancel)
- **Leave:** types, balances, applications (draft, submit, cancel, list)
- **Calendar:** holiday calendar
- **Managers only:** approvals inbox, approve and reject, team attendance (scope is still enforced, so only their own reports)

The exact list is kept in code next to `PASSWORD_CHANGE_EXEMPT_PATHS`, and a test keeps it in step with the router.

---

## 9. Connected apps: sending HRMS data to any application (D-10)

### 9.1 What a connected app is

The ERP and CRM become two cases of a general idea, the **connected app**. A tenant can connect any number of them, and each
has its own credentials, integration profile (§6), events, field permissions and log.

| Kind | Direction | Examples |
|---|---|---|
| **Two-way** | Sends employees to HRMS and receives changes (§7) | ERP, CRM |
| **Receive only** | Gets HRMS data, never changes it, through a webhook, a connector or a scheduled file (§9.2) | Active Directory / Microsoft 365, Google Workspace, Slack / Teams, LMS, access control and canteen systems, insurance and travel portals, a payroll vendor, a custom in-house app |
| **Read only** | Pulls data when it needs it | BI and reporting tools (Power BI, Metabase), data warehouses |

The `system_code` used throughout this plan is the connected app's code. Everything already designed carries over unchanged:
keys and OAuth, the profile and its versions, the sync log, webhooks, rate limits and alerts.

### 9.2 Four ways HRMS sends data

Not every app has a webhook URL. **Each connected app uses whichever method it can support**, chosen when the app is added.
All four sit on the same engine:

- the same events, held in the outbox (§7.8);
- the same per-app limits on events, fields, people and data classes (§9.4);
- the same delivery timing (§9.5), retries, logs, alerts and onboarding-checklist ticks.

| # | Method | Who does the work | Speed | Typical apps |
|---|---|---|---|---|
| **A** *(backlog B-1)* | **Webhook (push)**: HRMS sends a signed `https` message to the app's URL | The app's developer builds one endpoint | Seconds | Your own ERP, CRM, in-house LMS or portals |
| **B** *(v1)* | **Read API (pull)**: the app asks HRMS what changed since its last call | The app's developer writes a scheduled job | Minutes to hours, as often as the app polls | Custom apps behind a firewall; BI tools and data warehouses |
| **C** *(backlog B-3)* | **Connector**: HRMS calls the app's own public API | Nobody builds anything. The app's admin does a one-time setup in the app and pastes the credentials into HRMS. | Seconds | Google Workspace, Microsoft 365, and SCIM apps (Slack, Zoom, Atlassian, Okta, Entra ID) |
| **D** *(backlog B-2)* | **Scheduled file**: HRMS produces a CSV or Excel file on a schedule and drops it on SFTP, S3 or email | Nobody builds anything. The app's admin sets the app to pick the file up. | On the schedule (e.g. hourly, nightly) | Biometric and access-control software, canteen, insurance and travel portals, banks' employee lists, legacy systems |

**Which one to use.** The "Add app" screen asks these questions in order and suggests the method:

```
Is it Google Workspace, Microsoft 365, or an app that supports SCIM? ─ yes ─► C  Connector
        │ no
Can the app receive https calls from the internet? ──────────────────── yes ─► A  Webhook
        │ no
Can the app call an https API on a schedule? ────────────────────────── yes ─► B  Read API
        │ no
Can it import a CSV or Excel file? ──────────────────────────────────── yes ─► D  Scheduled file
        │ no
Manual: HR downloads the same file from the app's page (D, with no destination)
```

**An app can use more than one method.** For example, a webhook for live changes plus a nightly full file to check it is
complete, or a connector plus the read API for reporting.

#### 9.2.1 A: Webhooks

Delivery, signing, ordering and retries are as described in §7.8.

#### 9.2.2 B: Read API

All calls are `GET`, cursor-paged, and filtered to the app's allowed fields and people (§9.4).

| Path | Scope | Returns |
|---|---|---|
| `/v1/integrations/employees?updated_since=` | `employees.read` | Employees and their current job |
| `/v1/integrations/org/companies`, `/departments`, `/locations`, `/designations` | `org.read` | The organisation structure |
| `/v1/integrations/holidays?year=` | `org.read` | Holiday calendars and which companies use them |
| `/v1/integrations/leave?from=&to=&status=APPROVED` | `leave.read` | Approved leave, e.g. for planning or access control |
| `/v1/integrations/attendance/daily?date=` | `attendance.read` | Each employee's day: present or absent, first IN, last OUT, worked time |
| `/v1/integrations/events?after=<cursor>` | the app's event scopes | The events, in order, with a cursor (§7.8). **This is how the ERP and CRM receive changes in v1.** |

#### 9.2.3 C: Connectors (backlog B-3)

- **Outbound SCIM 2.0 client.** One connector covers every app that accepts SCIM, which includes Slack, Zoom, Atlassian,
  Microsoft Entra ID and Okta. A hire creates the user, a change updates them, and an exit deactivates them on the last
  working day.
- **Google Workspace and Microsoft 365:** create the account on joining (name, email pattern, department as the org unit),
  suspend it on exit, and add the person to department groups.
- This is "HR-driven provisioning", the enterprise standard, in which the HR system is what starts and stops access everywhere.
  It also feeds IT clearance at exit (enterprise plan E1).
- **The first password for a new email account** is random and sent before the joining date to the joiner's personal email (or
  to their manager). The joiner must change it at first sign-in. HRMS never stores it.
- Connector credentials (service-account keys, client secrets, SCIM tokens) are encrypted with the existing field encryption
  (`core/field_crypto.py`), never shown again after saving, and checked with a **Test connection** button.

#### 9.2.4 D: Scheduled files (backlog B-2)

For apps that only import files. Each **file feed** belongs to one connected app, and has the settings below.

| Setting | Options | Default |
|---|---|---|
| **Content** | Employees (current job) / Joiners and leavers / Organisation structure / Approved leave / Daily attendance / Holidays | — |
| **Rows** | Full list each time / Only changes since the last file (delta, with an `action` column: `ADD` / `UPDATE` / `REMOVE`) | Full for small feeds; delta for attendance |
| **Columns** | A **column mapper**: pick fields from the app's allowed fields (§9.4), rename the headers to what the app expects, set the order, add fixed-value columns, and set date, time and yes/no formats per column | — |
| **Format** | CSV (delimiter, quoting, UTF-8 with or without BOM, line endings) / Excel `.xlsx` / fixed-width text | CSV, UTF-8 |
| **File name** | A pattern, e.g. `employees_{company}_{yyyyMMdd_HHmm}.csv` | — |
| **Schedule** | Every N minutes / hourly / daily at a time / weekly, in the tenant's time zone; or **on event**, a file per joiner or leaver within a minute, for access-control systems that should lock out a leaver at once | Daily 02:00 |
| **Destination** | **SFTP** (key or password, with the server's host key pinned) / **Amazon S3** bucket (the customer's, with a role or keys) / **Email** to fixed addresses (see the rules below) / **None**, so HR downloads it from the app's page | — |
| **Encryption** | Optional PGP encryption with the receiving app's public key | Off; recommended for email |
| **Done marker** | Optionally write `filename.done` after the file, or upload as `.tmp` and rename, so the app never reads a half-written file | Upload as `.tmp`, then rename |

**How a run works:**

1. The job scheduler starts the run, using the existing `jobs/runner.py`, with one run per feed at a time.
2. It reads the data under the feed's profile: allowed fields, people and data classes.
3. It writes the file to a temporary area, and records the row count and a SHA-256 checksum.
4. It uploads with retries (1, 5 and 30 minutes, then the next scheduled run). Afterwards it checks the remote file size, or
   the S3 checksum.
5. It records the run (time, rows, checksum, destination, outcome) and ticks or flags the onboarding and exit checklist tasks
   for the employees in the file.

**For delta feeds,** each run's position (a cursor) is saved, so a failed run is not skipped. The next file includes
everything since the last *successful* one.

**The app's page:**

- the list of runs, with the option to download the exact file sent (kept 30 days, encrypted at rest with the existing
  document storage);
- **Run now**;
- **Preview**, which shows the first 20 rows with the current mapping before anything is sent.

**Email is the weakest destination.** Files with personal data sent by email can be forwarded and stay in inboxes. It is
therefore allowed only to addresses on the tenant's own email domains, with PGP or a password-protected `.zip`. The setup
screen shows a warning that recommends SFTP or S3. It also depends on outbound email (SES), which isn't configured yet
(observability open items).

**Inbound files are not part of this.** Punch files *from* biometric devices come in through the enterprise plan's punch import
(F13, C7).

### 9.3 Event catalogue

Each event has a versioned schema (`event_version`). Fields are only added within a version.

| Event | Sent when |
|---|---|
| `employee.hired` / `employee.updated` / `employee.separated` / `employee.rehired` | §7.8 |
| `employee.hire_cancelled` | A saved hire is cancelled before the joining date |
| `employee.manager_changed` | Reporting line changed (also part of `employee.updated`; separate for apps that only care about it) |
| `org.department.created` / `.updated` / `.archived`, the same for `location` and `designation` | The organisation structure changes |
| `leave.approved` / `leave.cancelled` | A leave application is approved or an approved one is cancelled |
| `attendance.day_finalised` | An employee's day is final, when its 24-hour punch window closes: worked time from the first IN to the last OUT, or `MISSED_PUNCH` |
| `attendance.correction_approved` | A finalised day changed after a correction |
| `holiday_calendar.published` | A holiday calendar is published or changed |
| `ping` | The test-send button |

Payroll amounts are not in the catalogue. Payroll output reaches banks, accounting and statutory portals through the payroll
module's own files (bank file, journal, PF/ESIC, enterprise plan P5), which have their own approvals.

### 9.4 What each app may see

This is what makes it safe to connect many apps. It applies equally to push, pull and connectors, and **each app sees only what
it is given**:

| Control | Set per app (and per company, §6.1) |
|---|---|
| **Events** | Which events it receives |
| **Fields** | Which fields are in each event and API response, chosen from the field catalogue (§6.2), with a sample payload shown as fields are ticked |
| **People** | Which companies, departments or employee types it covers, e.g. the LMS gets only Sharanga, and access control only one plant's staff |
| **Data classes** | Fields are grouped as *Basic* (name, code, company, department, designation, manager), *Contact* (email, mobile), *Personal* (date of birth, gender) and *Attendance and leave*. Each class must be switched on for the app. *Sensitive* (KYC, bank, salary) can never be switched on in v1 (§6.4). |

**Privacy:**

- **"What does this app receive?"** is a report per app: its events, fields, people, the last delivery, and the number of
  employees shared. It supports data-minimisation reviews, e.g. under India's DPDP Act 2023.
- **Every delivery and every read is logged** per app, including which employees it covered.
- **Disconnecting an app** revokes its credentials, stops deliveries, and keeps the log.

### 9.5 Onboarding: one hire reaches every app

When an employee is hired, **wherever the hire happened** (in HRMS, or in the ERP and synced in, §7), HRMS writes one
`employee.hired` event. Every connected app subscribed to it receives the new joiner within its own people and fields
(§9.4). A hire from the ERP therefore also reaches Google Workspace, the LMS and the rest, because HRMS is the hub.

**When each app receives the new joiner** is a setting per app (§6.1), because a hire is often saved weeks before the joining
date:

| Timing | Typical use | Default for |
|---|---|---|
| **When the hire is saved** | The ERP and CRM, so their records exist early | Two-way apps |
| **N days before the joining date** (e.g. 3) | The email account, so the employee can be sent sign-in details before day one | Google Workspace, Microsoft 365 |
| **On the joining date** | Access control, LMS, Slack/Teams, insurance | Other receive-only apps |

- An event scheduled for later is held in the outbox until then.
- If the joining date changes, or the hire is cancelled before it, the held event moves or is dropped. An app that has already
  received the hire gets `employee.updated` or `employee.hire_cancelled`.

**Values an app creates come back.** A connector can return what it created:

- the email address Google Workspace or Microsoft 365 created, and
- the user ID each app assigned (kept as that app's external identity, §5).

HRMS saves the work email on the employee, if the field-ownership rules allow it (§6.2), and passes it on to the other apps in
`employee.updated`.

**The onboarding checklist shows progress.** The HRMS onboarding module gets a task for each app, for example *"Google
Workspace account created"* or *"Added to LMS"*. The task is ticked automatically when the delivery succeeds, and flagged when
it fails, so HR sees from the onboarding screen what is done and what is stuck. Nobody has to check the apps one by one.

**Exit works the same way in reverse.** On the last working day, `employee.separated` reaches every app. Connectors suspend
the accounts, and the exit checklist shows each app's access as removed. This feeds IT clearance (enterprise plan E1).

### 9.6 Starting and recovering an app

- **First load.** A newly connected app can call the read API from the start, or ask HRMS to **resync**. Resync sends a
  `snapshot` event for each employee (and each department, location and designation) within the app's people and fields, then
  continues with live events.
- **Replay.** "Resend everything since [date]" re-queues an app's events from the outbox after the app lost data. The outbox
  keeps 30 days, and resync covers anything older.
- **Pause** stops deliveries without losing them. Events queue until the app is resumed.

---

## 10. Passwords (D-4)

| The ERP sends | HRMS does |
|---|---|
| `password_hash` in **bcrypt** format (`$2a$` / `$2b$` / `$2y$`, cost 10–14) | Checks that it is a well-formed bcrypt hash, then stores it as is. The employee signs in to HRMS with their ERP password. `must_change_password = false`. |
| `password` (plain text, over HTTPS) | Checks length (bcrypt's 72-byte limit, `password_fits_bcrypt`) and the password policy, then hashes it. |
| Neither | The profile's **default password pattern** (§6.1). The default is `{FirstName}@1234`: the first name with its first letter capitalised and spaces removed, the same rule as the Sharanga import. With *force a change* on (the default), `must_change_password = true`, which applies only when signing in to HRMS directly. The profile can instead choose *random password plus an invite* or *no direct HRMS sign-in*. |
| Any other hash format (PBKDF2, MD5, SHA-1, Argon2…) | **Rejected with `UNSUPPORTED_PASSWORD_HASH`** (O-1). Falling back silently would leave the employee locked out with no explanation. Support for a specific format, checked at sign-in and then re-hashed to bcrypt, can be added once the ERP's exact format is known. |

**Rules for passwords:**

- Setting a password needs the `passwords.sync` scope.
- On an update, a new password bumps `token_epoch`, which ends that employee's HRMS sessions.
- Passwords are never written to the sync log, the logs or Sentry. The existing redaction in `core/logging.py` already
  covers `password`.
- If an employee changes their password in HRMS, the ERP doesn't know, and the two passwords now differ. That is expected,
  because the ERP never reads HRMS passwords. The developer guide states it.
- `Firstname@1234` is easy to guess. The sign-in throttle limits guessing, and the forced change covers direct sign-in, but it
  remains the weakest point. See O-3.

---

## 11. Security

### 11.1 API keys

- **Format:** `hrms_<env>_<8-char prefix>_<32 random chars>`, with `env` = `test` or `live`. A `test` key is refused in
  production and a `live` key in testing.
- **Storage:** only `HMAC-SHA256(server pepper, key)` is stored. The full key is shown **once**, when it is created.
- **Who manages keys:** creating, rotating and revoking a key needs a new `integrations.manage` permission. It is given to
  `SUPER_ADMIN` only, and that role already requires MFA. Every change is recorded in `entity_change_log`.
- **Rotation:** create the new key, switch the ERP over, then revoke the old one. Two active keys per system are allowed so this
  can happen without downtime.
- **Expiry:** the default is 365 days. Warnings go out 30, 7 and 1 day before.
- **Allowed IPs:** CIDR ranges. Strongly recommended, and the admin screen warns when the list is empty.
- **Rate limit:** per key, 600 requests a minute by default. Over the limit, `429` with `Retry-After`.

**OAuth 2.0 client credentials.** Larger customers' security teams often require OAuth instead of a static key, so it is
offered alongside API keys, and the tenant chooses which to use:

- The ERP calls `POST /v1/integrations/oauth/token` with `grant_type=client_credentials`, its `client_id` and its
  `client_secret` (HTTP Basic auth).
- HRMS returns a **15-minute** access token, with the same scopes, allowed IPs and company limits as a key.
- Every other rule is the same: rate limits, logging, revocation, `test` or `live` environment.
- `X-API-Key` and `Authorization: Bearer <client token>` are both accepted on `/v1/integrations/*`, and nowhere else.
- **Optional later hardening, if a customer asks:** signing in with a private key instead of a secret (`private_key_jwt`), and
  mTLS.

**API versioning.**

- `/v1/integrations` is a **stable contract**. Fields are only added, never renamed or removed, within v1.
- A breaking change means `/v2`, with v1 kept for **at least 12 months** after v2 ships.
- Every change goes in a published changelog, and deprecations are announced in a `Deprecation` response header.

### 11.2 Threats and how they are handled

| Threat | Handling |
|---|---|
| The API key leaks | Allowed IPs; the key's scopes, with no data reads beyond reference data; instant revocation that also ends its sessions; the exit safety valve; an alert when a key is used from a new IP. |
| A session token leaks | It is limited to one employee, lasts 60 minutes, is limited to the self-service routes and carries no HR roles. It dies when the key is revoked or the employee's password changes. |
| Privilege escalation through sync | `role` accepts only `EMPLOYEE` or `MANAGER`. Role assignments are always `SELF` or `DIRECT_REPORTS`, never company-wide (the lesson from the import's first version). |
| Access across tenants or companies | The tenant comes from the key, never the payload. `legal_entity_ids` limits companies. RLS applies to all new tables. |
| Replays and duplicates | `Idempotency-Key`; the `source_updated_at` ordering guard; an advisory lock plus a unique index on creation. |
| Mass exits, by accident or on purpose | The safety valve (§7.5). |
| Using error messages to probe for employees | Every `/sessions` failure for an unlinked or unknown ID returns the same code and timing. |
| Personal data in logs | Contact fields are masked in `integration_requests.changes`; passwords are never stored; KYC and bank data aren't accepted (A-2). |

---

## 12. Reliability

**Retries.** The ERP retries on `429`, `5xx` and timeouts, with exponential backoff (1 s, 2 s, 4 s, … up to 5 minutes, with
jitter). It never retries `4xx` responses other than `409 RETRY_LATER` and `429`. The developer guide includes a reference
retry function.

**Idempotency.**

- `PUT` is idempotent by nature.
- `POST` (exit, rehire, bulk) requires `Idempotency-Key`. A repeated key with the same body returns the first response. A
  repeated key with a *different* body returns `422 IDEMPOTENCY_KEY_REUSED`.
- Keys are kept for 7 days.

**Transactions.** One employee per transaction, with savepoints in bulk calls. The existing `hrms_app` statement timeouts apply.

**Interruptions.** If HRMS is down, the ERP keeps its outgoing changes and retries them in order; `source_updated_at` protects
against the order getting mixed up.

**Weekly reconciliation.** Recommended: the ERP calls `/reconcile`, and the differences appear in the admin screen. HRMS never
corrects anything automatically.

**Performance targets:**

| Measure | Target |
|---|---|
| Upsert, p95 | < 300 ms |
| Session issue, p95 | < 150 ms |
| Bulk of 200, p95 | < 20 s |

Load test: the morning punch peak for 5,000 employees (≈ 5,000 sessions and punches within 15 minutes, about 6 per second, with
10× headroom), run with the `backend/perf/` harness.

---

## 13. Observability

**Prometheus metrics:**

- `hrms_integration_requests_total{system,operation,outcome}`
- `hrms_integration_request_seconds` (histogram)
- `hrms_integration_rate_limited_total`
- `hrms_integration_sessions_issued_total`
- `hrms_integration_held_exits`
- `hrms_webhook_deliveries_total{system,event,status}`
- `hrms_webhook_queue_age_seconds`

**Alerts (Alertmanager):**

| Alert | Condition |
|---|---|
| `HrmsIntegrationRejectRateHigh` | More than 10% rejected over 15 minutes |
| `HrmsIntegrationSilent` | A key with traffic over the last 7 days has none for 24 hours |
| `HrmsApiKeyExpiring` | A key expires within 7 days |
| `HrmsIntegrationExitsHeld` | Exits are being held for review |
| `HrmsIntegrationNewIp` | A key is used from a new IP |
| `HrmsEventsFeedLagging` | An app's cursor is more than 15 minutes behind the newest event while events are waiting (v1) |
| `HrmsWebhookDeliveryDead` | A webhook delivery failed for 3 days, or an endpoint was disabled (B-1) |
| `HrmsFileFeedFailed` | A file feed run failed after its retries, or a scheduled run didn't start (B-2) |
| `HrmsIntegrationUnlinkedHires` | An HRMS hire hasn't been linked by the ERP within 24 hours |

Alertmanager still has no receiver, which is an open item from the observability work.

**Grafana:** an "Integrations" row on the existing dashboard.

**Logs and Sentry:** structured logs carry `request_id`, the tenant, the key's *prefix* (never the key) and the external ID.
`5xx` errors go to Sentry, with the payload redacted.

---

## 14. Admin screens (Settings → Integrations)

1. **Connected apps:**
   - A list of the apps, with their kind, status, last delivery and number of employees shared.
   - **Add app** asks how the app can receive data (§9.2) and suggests the method. Templates: *Two-way (ERP/CRM)*, *Custom
     webhook*, *Custom read API*, *SCIM app*, *Google Workspace*, *Microsoft 365*, *Scheduled file*.
   - **File feeds** (B-2): content, full or delta, the column mapper, format, file name, schedule, destination (with **Test
     connection**), PGP; then **Preview**, **Run now**, and the run list with a download of each file sent.
   - For each app: events, a field picker with a live sample payload, people filters and data classes; pause, resync, replay
     and disconnect; and the *"What does this app receive?"* report.
2. **Settings** (§6): one page per connected system.
   - A **company switcher** (the tenant default, or a company's overrides), with *inherited* / *overridden* shown on every
     setting.
   - The **field ownership matrix**: one row per field, the owner chosen per column, and the preset buttons.
   - Lifecycle, matching, logins, self-service, safety and retention.
   - **Preview**, which shows the impact before publishing, the **publish with effective date** action, the version history
     with differences between versions, and the health-check warnings.
This is a new page for the tenant administrator, the one place F19 planned for it.

3. **Keys:**
   - **List:** name, system, scopes, companies, allowed IPs, last used (time and IP), requests, expiry, status.
   - **Actions:** create (shows the key once, with a copy button and a "copied" confirmation), rotate, revoke (with a reason).
4. **Mappings:**
   - ERP value → HRMS company, department, location, designation, role.
   - An **Unmapped values** queue fills from rejected requests, each with a "Map to…" action.
5. **Sync log:**
   - Filter by employee, external ID, outcome, operation and date.
   - The detail view shows the field diff (old → new) and the error, plus a copyable request ID for the ERP team.
   - Exits held for review appear here too, with release and reject actions.
6. **Link existing employees:** a wizard that runs `link` as a dry run, shows the four lists, then saves.
7. **Reconciliation:** the result of the last `/reconcile`.
8. **Webhooks** (B-1):
   - The ERP's and CRM's URLs, their events, and secret creation (shown once).
   - The delivery log: status, attempts, response, and a resend action.
   - A test-send button, which sends a `ping` event.
9. **Possible duplicates and not linked:**
   - **Possible duplicates:** the ERP record next to the HRMS record, with "same person" and "different person" actions.
   - **Not linked:** employees hired in HRMS that the ERP hasn't linked within 24 hours.
10. **On each employee's page:**
   - a "Managed by ERP · EMP-1042" badge, and the date of the last sync;
   - **a lock icon on every ERP-owned field.** Hovering over it explains why the field is locked. If the override setting
     allows it, an *Override* action asks for a reason, and for approval if that is required.

---

## 15. Testing

All tests run on the private unix-socket Postgres (see the safe-test-environment rule), **never on the live dev database**.

| Layer | What is tested |
|---|---|
| Unit | Key format, hashing, parsing; payload validation; password rules (bcrypt detection, the 72-byte limit, the default-password rule, unsupported formats); mapping resolution order; the ordering guard |
| API | Each endpoint's success and every error code; partial-update semantics; explicit `null`; personnel actions created for job changes; pending manager resolved later; bulk with mixed results; link dry run versus saving; reconcile; idempotent replay and reuse with a different body; rate limit and `Retry-After`; a `test` key refused in production |
| Security | An ERP token for employee A can't read employee B; a manager sees only their reports; HR, Admin and Accounts grants are dropped; routes off the list return `403`; revoking a key ends a live session; separation refuses new sessions and ends live ones; `must_change_password` is skipped only for `via` tokens; an `X-API-Key` header on ordinary routes is ignored; RLS blocks other tenants; a company outside the key is refused |
| Concurrency | 20 parallel `PUT`s for the same external ID create exactly one person; an exit racing an upsert |
| Settings and ownership | Every owner × incoming change × HRMS edit × webhook combination in the §6.2 table; a company override beats the tenant default; publishing in the future takes effect on its date and not before; a published version can't be edited; rollback; the JSON schema rejects bad settings; `assert_fields_editable` blocks screen, API, self-profile and import edits alike; override with a reason and with approval; the guard test fails on a write path that skips the check; the health-check warnings; dry run under the published and the draft profile |
| File feeds (B-2) | Column mapping, renaming and formats; CSV quoting and BOM; Excel output opens cleanly; delta cursor: a failed run is included in the next file with no gaps and no repeats; `ON_EVENT` produces a leaver file within a minute; upload as `.tmp` then rename; SFTP host-key mismatch refused; S3 checksum checked; PGP output decrypts with the test key; email refused outside the tenant's domains; preview equals the first rows of the real file; only allowed fields and people appear. Tested against a throwaway SFTP container and a test S3 bucket |
| Connected apps | Delivery timing: an event held until N days before joining, moved when the joining date changes, dropped and `hire_cancelled` when the hire is cancelled; checklist tasks ticked on successful delivery and flagged on failure; work email written back from a connector; an app gets only its events, fields, people and data classes, for push, pull and resync alike; *Sensitive* can't be switched on; the read API's `updated_since` and cursor return no gaps and no repeats while records change; pause, replay since a date, resync, disconnect; every read and delivery is logged; the "What does this app receive?" report matches what was actually sent |
| OAuth | Token issue, expiry, revocation, scopes, IP limits; a client token refused outside `/v1/integrations` |
| Two-way onboarding | Hire in HRMS → outbox row in the same transaction → delivered, signed, in order → the ERP's `PUT` with `employment_id` links; automatic link on code plus name and date of birth; `POSSIBLE_DUPLICATE` on code alone; a change from the ERP is not sent back to it but is sent to the CRM; a rolled-back hire sends nothing; the ID scheme counter skips used codes and moves past codes from the ERP; retries, `DEAD`, resend; the endpoint is disabled after repeated failures; a signature check against the reference client |
| Safety valve | The 21st exit within 24 hours is held, and releasing it applies it |
| Endpoint docs | The existing guard tests cover the new routes |
| E2E (Playwright) | Create and revoke a key; map an unmapped value; read the sync log; release a held exit |
| Load | §12 targets, with the `backend/perf/` harness |
| Contract | A small reference client (Python), kept in the repo and run in CI against the API, so the developer guide's examples never go stale |

---

## 16. Delivery

The estimates use the enterprise plan's **pair-weeks** (traditional effort). At this project's measured pace, the build is
roughly 1–2 calendar weeks; the pilot takes calendar time no matter how fast the build goes.

**Prerequisite: R0 (commit, reconcile and cut-over).** Until then, code edited in `/home/aiserver/HRMS` is live on the testing
site. Until R0, this work is built in a separate worktree and tested only on the private database.

| Phase | Contents | Pair-weeks | Done when |
|---|---|---|---|
| **I-1 Foundation** | Migration 0051; key lookup function; `get_integration_principal`; **OAuth client credentials**; rate limiting; `integration_requests`; the Keys tab; `integrations.manage` and `integrations.configure` | 4 | A key can be created, used, rate-limited and revoked; every call is logged; security tests pass |
| **I-2 Employee sync** | `reference-data`, mappings and the Unmapped queue; `link`; upsert (create and update, through personnel actions); exit, rehire and the safety valve; bulk; reconcile; passwords; the sync log screen | 5 | The full API test suite passes; a first load of the Sharanga export through `link` and `bulk` on the private database reconciles to zero differences |
| **I-2a Settings and ownership** | Integration profiles (versions, per-company overrides, schema, preview, publish, history, health check); the field catalog; `assert_fields_editable` across every HRMS write path, with the guard test; `field-control`; locks and override in the employee screens; the dry run | 4 | Every combination in the §6.2 table is tested; HR can switch presets, preview and publish without a developer |
| **I-2b Onboarding in HRMS** | The outbox written on hire, change, separation and rehire (same transaction); the **events feed**, with the in-flight-transaction cursor rule, per-app cursors and the lag alert; matching and the possible-duplicates queue; the ID scheme fix; the hiring-form note; the Duplicates and Not-linked tabs | 2.5 | Hire in HRMS → visible to the ERP on its next poll and linked by its `PUT`; the forced out-of-order-commit test never skips an event; the duplicate tests pass |
| **I-2c Connected apps and read API** | `connected_apps`; the read endpoints (§9.2.2); the wider event catalogue; per-app events, fields, people and data classes; delivery timing; the onboarding and exit checklist tasks; resync; the Connected apps screen and its report; read logging | 3 | A read-only app sees exactly its allowed data; `updated_since` paging has no gaps or repeats while records change |
| **I-3 Self-service through the ERP** | `/sessions`; the `via` claim checks in `get_session` and `resolve_scope`; the route list; the `INTEGRATION` punch source and `source_system` column; register and report labels | 2.5 | Security tests pass; a punch made through the ERP appears in the attendance register labelled "ERP" |
| **I-4 Hardening** | Metrics, alerts, Grafana; developer guide (`docs/INTEGRATION_GUIDE.md`) with cURL, Python and Node examples, a **reference polling client**, and the error catalogue; reference client in CI; load test; `/security-review` | 2 | Performance targets met; no high findings from the security review |
| **I-5 Pilot** (testing site) | Sharanga's ERP developer integrates against a `test` key: link → bulk → daily changes → polling the events feed → sessions | 2 calendar weeks | Two weeks with no data mismatch in reconciliation, no `FAILED` outcomes, no feed lag alerts, and HR confirms the sync log |
| **I-6 Go-live** | Production keys per tenant, monitored in its first week | — | Turned on per tenant (A-4) |

Total for v1 (I-1 to I-4): about **23 pair-weeks**, plus the pilot. At this project's measured pace that is roughly 2 calendar
weeks of build. This becomes its own release, **RI**, between R0 and R1, because new joiners can't be onboarded for these
tenants until it exists.

**Product backlog** (designed above; build when a customer needs it; the estimates assume v1 is in place):

| Item | Contents | Pair-weeks | Build it when |
|---|---|---|---|
| **B-1 Push webhooks** | Endpoints, signing, the delivery job, retries, the delivery log, resend, auto-disable, the Webhooks tab (§7.8, §9.2.1) | 2 | A customer's app can receive `https` and needs changes within seconds |
| **B-2 File feeds** | §9.2.4 in full: the column mapper, CSV/Excel/fixed-width, SFTP/S3/email, PGP, preview, runs | 3 | A customer has access control, canteen, biometric software or another file-only system |
| **B-3 Direct connectors** | Google Workspace, Microsoft 365, outbound SCIM (§9.2.3) | 5 | A customer uses Google Workspace, Microsoft 365, Slack or another SCIM app |
| **B-4 Single sign-on** | OIDC and SAML per tenant; one-click opening of HRMS from the ERP | 4 | A customer wants sign-in through their identity provider |
| **B-5 Inbound SCIM 2.0** | `/scim/v2/Users`, through the sync service, ownership rules and safety valve | 3 | A customer's identity provider should create HRMS users |

---

## 17. Open decisions

| # | Question | Recommendation |
|---|---|---|
| O-1 | Password hash formats other than bcrypt: reject, or fall back to `Firstname@1234`? | **Reject**, then add the ERP's exact format once we know what it is |
| O-2 | A department, designation or location HRMS doesn't know: reject, or create it automatically? | Now a setting. The default is **reject and queue for mapping**, because creating them automatically fills HRMS with spelling variants ("Ops", "Operations", "OPERATIONS") |
| O-3 | ~~Employees who only use HRMS through the ERP: an HRMS password or not?~~ | **Now a setting** (§6.1, Logins). The default follows D-4 |
| O-4 | ~~Send HRMS changes back to the ERP through webhooks?~~ | **Decided by D-7:** yes, for employee events (§7.8) |
| O-5 | Safety-valve threshold for exits | Now a setting. The default is 20 a day or 5% of headcount, whichever is smaller |
| O-6 | ERP session lifetime | Now a setting. The default is 60 minutes |
| O-7 | Can managers approve leave and corrections from the ERP? | Yes, with scope still enforced. HR-level approvals stay in HRMS |
| O-8 | If the ERP has no "location": one default location per company? | Yes, set on the Mappings tab |
| O-9 | Is a designation change a `PROMOTION` or a `TRANSFER`? | Let the ERP send `change_reason` (`PROMOTION` / `TRANSFER` / `CORRECTION`). The default is `TRANSFER`. A `CORRECTION` fixes the current assignment without creating history |
| O-10 | Which tenant pilots first? | **Sharanga/RABS** (76 people, one company). Then Suraj Group (8 companies) |
| O-11 | ~~Can the ERP receive webhooks?~~ | **Decided (D-12):** no. The ERP and CRM poll the events feed (§7.8) |
| O-12 | For companies **without** an ID scheme, may HR hire in HRMS before the person exists in the ERP? | Yes. HR types the code the ERP will use, and the ERP creates the person from the `employee.hired` event |
| O-13 | Default field-ownership preset for new connections | **"ERP is master for job data"**, the usual enterprise setup. Each tenant can change it |
| O-14 | Default for HR editing an ERP-owned field | **Allowed with a reason**, so urgent fixes are possible and each is recorded |
| O-15 | API keys or OAuth by default for new tenants | **API keys** for in-house ERPs (simpler); OAuth offered for customers whose security policy requires it |
| O-16 | ~~Which apps to connect after the ERP and CRM?~~ | **Decided (D-12):** none for now. Connectors stay in the backlog (B-3) |
| O-17 | Should `attendance.day_finalised` go out per employee per day, or as one daily batch per company? | **Per employee**, with the read API's `/attendance/daily` for apps that want a batch |
| O-18 | ~~Which systems need file feeds?~~ | **Decided (D-12):** none for now (B-2) |
| O-19 | Allow email as a file destination at all? | Only matters when B-2 is built. Yes, restricted as §9.2.4 says |
| O-20 | How often the ERP and CRM poll the events feed | Every 30–60 seconds. The rate limit allows far more |

## 18. Risks

| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| The ERP resends full records and overwrites HR's edits | Low under field ownership (Shared fields only) | Data loss on Shared fields | Field ownership; the developer guide rule; overwritten fields visible in the sync log |
| A setting is changed wrongly (e.g. ownership flipped for every company) | Medium | Locks or overwrites on many records | Preview before publish; effective dates; versions and rollback; the health check; `integrations.configure` limited to named people |
| A file with personal data ends up in the wrong place (a wrong SFTP folder, a forwarded email) | Medium | Privacy exposure | Host-key pinning; Test connection; email limited to the tenant's domains, with PGP or a password; the 30-day copy and run log show exactly what was sent where |
| A legacy app expects an unusual file layout | High | Rejected imports | The column mapper, fixed-width format and preview; get the app's import template before setup (O-18) |
| An app is given more data than it needs | Medium | Privacy exposure | Data classes off by default; *Sensitive* never allowed; the per-app report; delivery and read logs; field picker with a live sample |
| Too many settings confuse admins | Medium | Wrong set-up | Presets; safe defaults; the health check; *inherited* / *overridden* shown on every setting; a setup checklist in the developer guide |
| The ERP's department and designation names are inconsistent | High | Many rejections at first load | Dry-run link, the Unmapped queue, mapping before go-live |
| The ERP stores passwords in a format HRMS can't use | Medium | Employees can't sign in to HRMS directly | O-1. Self-service through the ERP is not affected (§8.3) |
| The ERP team can't make outbound HTTPS calls, or can't keep a secret on its server | Medium | Push model not possible | A small relay script on their server; otherwise an HRMS-side pull connector (not in this plan) |
| The ERP and HRMS issue the same employee code to different people | Medium, if a company's ID scheme setting doesn't match how the ERP numbers people | Duplicate or blocked hires | One owner per company (D-8); the counter skips codes in use; `EMPLOYEE_CODE_IN_USE` instead of a silent overwrite; the possible-duplicates queue |
| The ERP stops polling, or falls behind | Medium | The ERP misses HRMS hires and changes | Events are kept 30 days; the `HrmsEventsFeedLagging` alert; the *Not linked* list; resync with `updated_since`; weekly reconciliation |
| A key leaks | Low | Wrong changes to employees | §11.2, with revocation in seconds |
| Work done before R0 affects the live testing site | Medium | Outage or data damage on the testing site | Worktree and private database only; nothing merged into the live folder without your approval |
