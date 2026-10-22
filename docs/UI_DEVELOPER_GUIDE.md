# UI developer guide

How to build a user interface on the HRMS API. The reference web app in [`frontend/`](../frontend/) is built exactly this way, so everything it can do, your UI can do.

This guide is the map. The API itself is the source of truth for every endpoint, field and error:

| Where | What |
|---|---|
| `{API}/docs` | Swagger UI. Try any call from the page. |
| `{API}/redoc` | The same reference on one page. |
| `{API}/openapi.json` | OpenAPI 3.1 schema. Generate a typed client from this. |
| [API.md](API.md) | How the docs are produced and kept accurate |
| [EMPLOYEE_INTEGRATION_API.md](EMPLOYEE_INTEGRATION_API.md) | Focused guide for punch in/out, corrections and leave from a kiosk, portal or mobile app |
| [THIRD_PARTY_INTEGRATION_GUIDE.md](THIRD_PARTY_INTEGRATION_GUIDE.md), [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) | ERP/CRM system-to-system sync (not for UIs) |
| [ui/](ui/) | Design rules: theming, terminology and locale, status vocabulary, restricted data |
| [FEATURES.md](FEATURES.md) | What each module does, in product terms |

> **Use a live schema, not `backend/openapi.json`.** The checked-in file is a snapshot and lags the code (it predates Payroll, Integrations and several People endpoints). Fetch `{API}/openapi.json` from a running API, or regenerate it:
> `cd backend && uv run python -m hrms.core.openapi openapi.json`
>
> Docs pages are off on deployed environments unless `HRMS_API_DOCS_ENABLED=true`. Ask the backend team for a dev API, or run one locally (below).

> **The testing site holds real employee data.** Develop against a local API with demo data, or a test account on a sandbox. Never experiment with real people's records.

---

## 1. Get an API to build against

Run the backend locally (see [README.md](../README.md) and [RUNBOOK.md](../RUNBOOK.md) for full setup; demo data is opt-in via `seed_demo.py`). Locally the API listens on `http://127.0.0.1:8015` and serves `/docs`.

Generate a typed client:

```bash
npx openapi-typescript http://127.0.0.1:8015/openapi.json -o src/api/schema.d.ts
```

Operation IDs are the route function names (`create_leave_type`, `list_balances`). Where two modules share a name, the tag is prefixed (`leave_management_list_applications`, `recruitment_list_applications`).

The API returns new fields over time. **Ignore fields you don't recognise.**

---

## 2. Authentication

There are three separate sign-ins. A token from one does not work on the others.

| Who | Sign in | Token works on |
|---|---|---|
| Employees, managers, HR, payroll | `POST /v1/auth/login` | everything except the two below |
| Connected apps (ERP/CRM) | API key or OAuth | `/v1/integrations/*` only |
| Platform operators (SaaS owner) | `POST /v1/platform/login` | `/v1/platform/*` only |

A UI for company users only needs the first. Build the platform console only if you are the platform team.

### Sign-in request

```http
POST /v1/auth/login
Content-Type: application/json

{ "identifier": "hr@example.com", "password": "…", "tenant": "SURAJ", "otp": "123456" }
```

- `identifier`: email, employee code or mobile number.
- `tenant` (company code): optional. Send it only after the API answers `409 COMPANY_REQUIRED`.
- `otp`: 6 digits. Send it only after the API answers `401 MFA_REQUIRED`.

Response: `{ access_token, token_type, expires_in, user }`. `user` is the same object `GET /v1/auth/me` returns: `id, name, email, employment_id, tenant_id, tenant_name, roles[], permissions[], is_all_scope, legal_entities[], must_change_password, mfa_required`.

### Two ways to carry the session

**Option A: HttpOnly cookie (recommended for a browser app, what `frontend/` does).**
Send header `X-HRMS-Session: cookie` on **every** request, and `credentials: "include"` on `fetch`.

- The server sets an `HttpOnly`, `SameSite=Lax` cookie (`hrms_session`, or `__Host-hrms_session` on deployed hosts) and returns `access_token: ""` in the body. Your JavaScript never sees the token, which is the point.
- Every **write** (anything but GET/HEAD/OPTIONS) is checked against the allowed-origins list. Your UI's origin must be in the API's `HRMS_CORS_ORIGINS` setting (https only when deployed), otherwise writes fail with `403 Untrusted browser request origin`. Ask the backend team to add it.
- Because the cookie is host-only, the UI and API should be served so that the cookie reaches the API (same site, or via a reverse proxy). The reference app uses a proxy path.

**Option B: Bearer token (native/mobile apps, scripts, server-side rendering).**
Omit `X-HRMS-Session`. Keep `access_token` and send `Authorization: Bearer <token>`. Store it in secure storage, never in `localStorage` of a browser app.

### Session lifecycle

- Tokens last `expires_in` seconds (60 minutes by default). **There is no refresh token.** On `401`, send the user back to sign-in. The reference client does this centrally in its `request()` wrapper and ignores the 401 from the login call itself.
- `POST /v1/auth/logout` ends the session (and clears the cookie).
- Changing a password ends **every** session of that account.
- Too many failed sign-ins return `429` with `Retry-After` seconds. Show a countdown.

### Sign-in states your UI must handle

| Response | Meaning | UI |
|---|---|---|
| `409 COMPANY_REQUIRED` | The identifier exists in more than one company | Show a company-code field and retry with `tenant` |
| `401 MFA_REQUIRED` | Account uses an authenticator app | Show a 6-digit field and retry with `otp` |
| `401 MFA_INVALID` | Wrong code | Let them retry |
| `403 PASSWORD_CHANGE_REQUIRED` | Temporary password | Route to a change-password screen. `POST /v1/auth/change-password`, then use the **new** token it returns. Until then every other call is refused. |
| `403 MFA_SETUP_REQUIRED` | Company policy requires MFA | `POST /v1/auth/mfa/enroll` (returns the secret/QR data), then `POST /v1/auth/mfa/confirm` with a code |
| `429` | Throttled | Wait `Retry-After` seconds |

`user.must_change_password` and `user.mfa_required` on the login/me response let you route the user before they hit a 403.

`POST /v1/auth/register-company` is a public self-service signup that creates a new company and its first admin.

---

## 3. Permissions and scope

Two independent checks decide what a user gets back. **The API enforces both; the UI only mirrors them to hide things the user can't use.** Never treat a hidden button as security.

**Permissions** say which *actions* are allowed (`leave.write`, `payroll.read`). They come from roles and are listed in `user.permissions`. `"*"` means everything (SUPER_ADMIN). A missing permission returns `403` with `Missing permission: <name>`.

**Scope** says which *records* are visible: all companies, chosen companies, chosen departments, direct reports, the whole reporting chain, or only the caller. List endpoints silently leave out records outside the scope. Single-record endpoints return `403` or `404`. `user.is_all_scope` and `user.legal_entities` summarise it.

### System roles

| Role | Typically sees / does |
|---|---|
| `SUPER_ADMIN` | Everything, all companies |
| `HR_MANAGER` | People, org, approvals, policy, reports, recruitment, KYC for companies in scope |
| `MANAGER` | Own team: approve leave and corrections, team dashboard, recruitment requests |
| `EMPLOYEE` | Self-service only |
| `ACCOUNTANT` | Read-only people and reports |
| `PAYROLL_ADMIN` | Salary structures, salaries, runs payroll |
| `PAYROLL_APPROVER` | Approves and locks pay runs |
| `PAYROLL_REVIEWER` | Checks statutory values and calculations |

A person can hold several roles. The effective access is the union. `GET /v1/roles` lists them.

### Gating the UI

```ts
const can = (perm: string) => user.permissions.includes("*") || user.permissions.includes(perm);
```

Use `can()` to decide which navigation items, tabs and action buttons to show. Common permissions: `self.read/write`, `people.read/write`, `org.read/write`, `leave.apply/read/approve/write`, `corrections.request/read/approve/write`, `time.write`, `onboarding.read/write`, `policy.read/write`, `approvals.manage/admin`, `reports.read/write`, `dashboard.hr/manager`, `kyc.self/read/write/verify`, `recruitment.request/read/manage/approve`, `payroll.read/write/review/approve`, `iam.read/write`, `integrations.configure/manage`. Each endpoint's description in Swagger shows its **Requires permission** line, which is authoritative.

Where a permission is checked inside the handler rather than declared, Swagger doesn't show it; the endpoint's text mentions it. If unsure, call it and handle the `403`.

---

## 4. Request and response conventions

- **Base path** `/v1`. JSON in, JSON out. Multipart for file uploads.
- **IDs** are opaque strings with a type prefix: `emp_…` (employment), `per_…` (person), `le_…` (company), `ou_…` (department), `loc_…`, `job_…`, `la_…` (leave application), `usr_…`, `afl_…` (approval flow), `ain_…` (approval request), and so on. Store and send them back exactly as received. **Don't parse them.** An employee is identified by the **employment** ID (`emp_…`), not the person ID.
- **Dates** are `YYYY-MM-DD` and carry no time zone (joining date, leave days, work date). **Timestamps** are ISO 8601 in UTC; convert for display. "Today" follows the company's business day, not the browser clock. Use the server's `GET /v1/time/today` rather than computing it.
- **Money** is returned as numbers/strings per the schema; format with the company currency. Never do arithmetic on it in floating point in the UI.
- **Paging.** List endpoints return a **plain JSON array** (no envelope, no total). Most take `limit` and `offset`; a few (for example leave applications) use `limit` and an `after` cursor. Defaults and maximums are on each endpoint in Swagger. To page: request `limit` rows and, if you get exactly `limit` back, offer "load more". Filters use the names shown in Swagger (for example `filter[status]`, `from_date`, `to_date`).
- **Request IDs.** Every response has `X-Request-ID`. You may send your own (up to 64 chars: letters, digits `. _ : -`). Show it in error dialogs; support will ask for it.
- **Version.** `X-App-Version` on responses is the deployed backend version.
- **Optimistic locking.** Editable master records carry a `version`. Send back the version you loaded when you `PATCH`/`PUT`. If someone else saved first you get `409 STALE_VERSION`: tell the user, reload the record, and let them reapply. (Sending `version` is optional today but will become required, so send it now.)
- **Sensitive data.** Salary, KYC identity numbers and similar are encrypted at rest and masked or omitted by the API depending on permission. See [ui/04-restricted-data.md](ui/04-restricted-data.md). Don't cache, log or put them in URLs.

---

## 5. Errors

Every error has one shape:

```json
{
  "detail": "Validation error on from_date: Input should be a valid date",
  "code": "VALIDATION_ERROR",
  "request_id": "req_01J9…",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "…",
    "details": [{ "field": "from_date", "message": "Input should be a valid date", "type": "date_parsing" }],
    "request_id": "req_01J9…",
    "timestamp": "2026-10-06T09:30:00+00:00"
  }
}
```

Branch on `code`, never on `detail` text (it can change). Show `detail` to people.

| Status | Handle by |
|---|---|
| `400` | Request not valid for the record's current state (for example approving something already decided). Show `detail`. |
| `401` | Session over. Go to sign-in. `MFA_REQUIRED` / `MFA_INVALID` are part of sign-in. |
| `403` | Not allowed. Show `detail`. Codes: `PASSWORD_CHANGE_REQUIRED`, `MFA_SETUP_REQUIRED`. |
| `404` | Missing, or outside the user's scope. Treat both as "not found". |
| `409` | Conflict: `RESOURCE_CONFLICT`, `COMPANY_REQUIRED`, `STALE_VERSION`. |
| `422` | Field validation. Map `error.details[].field` onto form fields. |
| `429` | Wait `Retry-After` seconds. |
| `5xx` | Retry GETs with backoff. For writes, check state before retrying. Quote `request_id`. |

A minimal wrapper (this is what `frontend/src/api/client.ts` does):

```ts
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public requestId?: string, public details?: unknown) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as any) };
  if (!(init.body instanceof FormData)) headers["Content-Type"] ??= "application/json";
  headers["X-HRMS-Session"] = "cookie";                 // cookie mode (Option A)
  headers["X-Request-ID"] ??= crypto.randomUUID();
  const res = await fetch(BASE + path, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/v1/auth/login") onUnauthorized();
    throw new ApiError(res.status, b.code ?? b.error?.code ?? "UNKNOWN",
      b.detail ?? b.error?.message ?? res.statusText,
      b.request_id ?? res.headers.get("x-request-id") ?? undefined, b.error?.details);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
```

Also: put a deadline (timeout) on requests, and drop responses that arrive after the user signed out.

---

## 6. Files: uploads, downloads, photos

- **Upload** with `multipart/form-data` (`FormData`; do **not** set `Content-Type` yourself, the browser adds the boundary). Used for KYC documents, profile photos (`PUT`), and candidate resumes.
- **Download / preview** endpoints (`…/download`, `…/preview`, resume, report exports, CSV/Excel exports) return a file, not JSON. With cookie auth, `fetch` them with `credentials: "include"` and turn the response into a Blob URL; a plain `<a href>` also works in cookie mode. With Bearer auth you must fetch with the header and use a Blob.
- Profile photos change rarely. Cache them by employment ID and bust the cache after `PUT`/`DELETE`.
- Reads of KYC documents are logged server-side (`access-log`). Don't prefetch them.

---

## 7. Recommended app structure

The reference app is React 19, TypeScript, Vite, React Router, TanStack Query and Tailwind. You can use any stack, but this layout works well:

```
src/
  api/        one file per backend module, thin typed functions over request()
  context/    Auth (user, can(), login/logout), Theme
  lib/        dates, money, errors, session helpers
  pages/      one per route
  components/ shared UI (tables, badges, forms, modals)
```

Practices that matter:

1. **One auth context** holding `user` from `/v1/auth/me`. On app start call `/me`; a `401` means signed out.
2. **Cache by query key** (TanStack Query or similar). Invalidate the relevant lists after a write. **Clear the whole cache on sign-out or when the user changes**, so one person's data never shows for the next.
3. **Route guards.** Wrap routes so that signed-out users go to `/login`, `must_change_password` users go to `/change-password`, and users needing MFA go to `/security/mfa`.
4. **Server decides.** Compute nothing that the API computes: leave balances, attendance status, overdue, effective policy, payroll figures. Display what it returns.
5. **Optimistic UI only for harmless toggles.** For approvals, leave, payroll, wait for the response.
6. **Disable submit while a request is in flight**, to avoid double-posting.

---

## 8. Design rules to follow

These are product decisions, not suggestions. Read them before styling anything.

- [ui/01-tenant-theming.md](ui/01-tenant-theming.md): a tenant sets one brand colour, logo and name; status colours, neutrals, type and the focus ring never change.
- [ui/02-terminology-and-locale.md](ui/02-terminology-and-locale.md): never hard-code organisation nouns (Company/Branch/Plant, Department/Function, Employee/Associate). Use a terminology lookup. Format dates, numbers and money by locale (en-IN grouping, e.g. 1,24,860).
- [ui/03-status-vocabulary.md](ui/03-status-vocabulary.md): statuses always show word + tone + icon, never colour alone. "Overdue" is computed by the system, not set by people.
- [ui/04-restricted-data.md](ui/04-restricted-data.md): financial and identity data is masked by default and a reveal is logged; case data is absent, not locked.
- Approval screens: [ui/approval-workflows/](ui/approval-workflows/) and [APPROVAL_WORKFLOWS.md](APPROVAL_WORKFLOWS.md). Theme palettes: [CLASSIC_TEAL_THEME.md](CLASSIC_TEAL_THEME.md), [MIDNIGHT_BLUE_THEME.md](MIDNIGHT_BLUE_THEME.md), [EMBER_SAND_THEME.md](EMBER_SAND_THEME.md).

---

## 9. Screen-by-screen API map

Paths are relative to `/v1`. Swagger has request/response shapes, permissions and examples for every one. "Self" screens need only `self.*`/`*.apply`/`*.request`; admin screens need the permission shown in Swagger.

### Sign-in and account (all users)
| Screen | Calls |
|---|---|
| Login, MFA, company code | `POST /auth/login` |
| Change password | `POST /auth/change-password` |
| Set up authenticator | `POST /auth/mfa/enroll`, `POST /auth/mfa/confirm` |
| Session bootstrap | `GET /auth/me`, `POST /auth/logout` |
| Preferences (theme, default dashboard) | `GET/PATCH /me/preferences` |
| Register a company | `POST /auth/register-company` |

### Dashboard
`GET /dashboard/employee`, `/dashboard/team`, `/dashboard/manager`, `/dashboard/hr`, `/dashboard/super-admin` (pick by role; the others return 403). HR can arrange widgets per user: `GET/PUT/DELETE /dashboard/layout`. Birthdays/anniversaries: `GET /dashboard/celebrations`. Add a widget in the backend catalog (`dashboard/widgets.py`) **and** the frontend registry together.

### Employees and people
| Screen | Calls |
|---|---|
| Directory / list | `GET /employees` (`limit`, `offset`, `filter[status]`) |
| Employee profile | `GET /employees/{emp}`, `GET /persons/{per}/employments`, `GET /employees/{emp}/employment-history` |
| My profile | `GET/PATCH /persons/me` |
| Hire | `POST /persons` then `POST /employees` |
| Promotion, transfer, separation (can be future-dated) | `POST /personnel-actions`, `GET /personnel-actions`, `POST /personnel-actions/{id}/cancel` |
| Rejoin | `GET /employees/{emp}/rejoin-preview`, rejoin policies under `/people/rejoin-policies` |
| Move between companies | `GET /people/transfer-preview`, `POST /people/transfers` |
| Earlier service | `GET/POST/DELETE /persons/{per}/prior-service` |
| Reports | `/people/reports/rejoins`, `/people/reports/company-transfers` |

### Organisation (admin)
Companies `/org/legal-entities`, locations `/org/locations`, departments and teams `/org/org-units`, jobs, grades, cost centres, positions, and employee-ID schemes, each with list/create/update. Most have `…/{id}/history` for a change log. Use these to fill every dropdown in the hire and transfer forms.

### Users and roles (admin)
`GET /roles`, `GET/POST /users`, `PATCH /users/{id}` (activate/deactivate), `POST /users/{id}/reset-password`, `POST /users/sign-in-slips` (printable first-login slips).

### Time and attendance
| Screen | Calls |
|---|---|
| Punch in/out button, today card | `POST /time/punches`, `GET /time/today` |
| My attendance calendar | `GET /time/attendance-days` (`from_date`, `to_date`) |
| Overtime review | `GET /time/overtime/pending`, `PATCH /time/overtime/{day}` |
| Flagged day review | `POST /time/attendance-days/{day}/review` |
| HR day-wise register and direct edit | `GET /time/register/filters`, `/register/employees`, `/register/{emp}`, `PUT /time/register/{emp}/{work_date}` |
| Daily analysis + CSV export | `GET /time/daily-analysis`, `/time/daily-analysis/export` |

Rules the UI should reflect (not recompute): worked time is first IN to last OUT minus time out; a day with no OUT after 24 hours becomes a missed punch. See [ATTENDANCE_RULES.md](ATTENDANCE_RULES.md).

### Attendance corrections
`GET/POST /corrections`, then `/corrections/{id}/approve | reject | cancel`.

### Holidays
Holiday list (library) `/time/holiday-calendars/library`; calendars `/time/holiday-calendars`; per-calendar days `…/{id}/days`; assignment to company/entity/department `…/{id}/assignments`; coverage check `/time/holiday-calendars/coverage`. `GET /time/holidays` is the read endpoint for "my holidays". The `POST/DELETE /time/holidays` pair is legacy; use calendars.

### Leave
| Screen | Calls |
|---|---|
| My balances | `GET /leave/balances` |
| Apply / submit / cancel | `POST /leave/applications`, `…/{id}/submit`, `…/{id}/cancel` |
| My and team requests | `GET /leave/applications`, `GET /leave/applications/summary` |
| Approve / reject | `…/{id}/approve`, `…/{id}/reject`; cancellation: `cancel-approve`, `cancel-reject` |
| Ledger and history | `GET /leave/ledger`, `GET /leave/transactions` |
| HR actions | `POST /leave/comp-off`, `/leave/encashment`, `/leave/balances/adjust`, `/leave/accrual/run`, `/leave/year-end-close` |
| Leave policy admin | `/leave/types`, `/leave/buckets`, `/leave/bucket-mappings`, `/leave/policy-sets` (+ `bucket-policies`), `/leave/policy-assignments` |
| Leavers | `/leave/separation-rules`, `/leave/separation-preview`, `/leave/separation-settlements` |

### Approvals (unified inbox)
`GET /approvals/inbox`, `GET /approvals/requests/{ain}`, `POST /approvals/requests/{ain}/decision`. Flow builder: `/approvals/flows`, `/approvals/directory` (who can be a step), per-employee flows `/approvals/employees/{emp}/flows`. Temporary cover: `POST/GET /approvals/delegations`, `…/{id}/revoke`. Leave, corrections and recruitment openings all route through this.

### HR policy (attendance)
`/policies/templates`, `/policies/assignments`, and `GET /policies/employee/{emp}/effective` to show the policy in force for a person.

### Onboarding
Templates `/onboarding/templates` (versioned; `PUT` saves a new version; `…/standard` adds the default), cases `/onboarding/cases`, ticking items `PATCH /onboarding/items/{id}`.

### KYC
Self: `/kyc/me`, `/kyc/me/submit`, `/kyc/me/documents`. HR: `/kyc/summary`, `/kyc/employees`, `/kyc/employees/{emp}`, verify document or record, `…/access-log`, documents `download`/`preview`, profile photo `GET/PUT/DELETE /kyc/employees/{emp}/photo`.

### Recruitment
Access probe `GET /recruitment/access` (use it to decide what to show), stages `/recruitment/stages`, openings (raise, submit, withdraw, decide, hold/close/reopen, history) under `/recruitment/openings`, a Kanban pipeline from `…/openings/{id}/applications` with `POST /recruitment/applications/{id}/move`, notes and rating, `…/hire` to link an employee, and the talent pool and resumes under `/recruitment/candidates`. Flow: [RECRUITMENT.md](RECRUITMENT.md).

### Reports
`GET /reports/meta/{module}` (public; column and filter metadata to build the report designer), `GET/POST /reports`, `GET/DELETE /reports/{id}`, `POST /reports/{id}/run`, `POST /reports/{id}/export-attendance` (Excel).

### Payroll
Statutory values `/payroll/statutory-rules`, components `/payroll/components`, salary structures `/payroll/structures` (+ `/structures/preview` for a live CTC breakdown as the user types), per-employee salary `/payroll/employees/{emp}/compensation`, and `GET /payroll/salaries`. Needs `payroll.*`; the API masks salary data for everyone else. Design: [payroll-design.md](payroll-design.md), [PAYROLL_ENCRYPTION.md](PAYROLL_ENCRYPTION.md).

### Integration settings (admin)
`/admin/integrations/*`: catalog, connected apps, API keys, settings drafts → preview → publish, value mappings, unmapped values, sync log, duplicates, held exits. `GET /employees/{emp}/field-control` tells your profile form which fields a connected system owns, so you can make them read-only.

### Platform console (SaaS operators only)
`/platform/*` with its own login. Tenants, admins, audit log, company registration.

---

## 10. Things the UI must not do

- Don't store passwords, tokens, salary or ID numbers in `localStorage`, URLs, logs or analytics.
- Don't build the company into a request. The company comes from the token; no header or parameter switches it.
- Don't assume a field exists. Optional and role-dependent fields may be missing or masked.
- Don't hard-code status wording, colours, or organisation nouns.
- Don't poll aggressively. Dashboards and inboxes refresh on focus or a slow interval.
- Don't call `/v1/integrations/*` from a user UI. That is for connected systems with their own key.

---

## 11. Checklist before you ship a screen

- [ ] Uses generated types from the live `openapi.json`
- [ ] Every action is hidden when `can()` is false **and** a 403 is still handled
- [ ] Loading, empty, error (with `request_id`) and no-permission states
- [ ] 401 → sign-in, 409 `STALE_VERSION` → reload, 422 → field errors, 429 → wait
- [ ] Dates are plain dates, timestamps shown in the right zone, numbers formatted by locale
- [ ] Statuses use word + icon + tone from the shared vocabulary
- [ ] Sensitive values masked by default
- [ ] Works at phone width and with the keyboard; focus ring visible
- [ ] Cache cleared on sign-out

## Getting help

Quote the `X-Request-ID` of the failing call. If an endpoint's behaviour, fields or error text in `/docs` look wrong or missing, tell the backend team: the endpoint text lives in `backend/src/hrms/core/endpoint_docs/` and a test keeps it complete.
