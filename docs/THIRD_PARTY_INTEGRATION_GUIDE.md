# HRMS third-party integration guide

One document for a developer connecting an outside system to HRMS, from the first conversation with
the HRMS administrator to a live, monitored integration. It covers:

| You want to… | Section |
|---|---|
| Understand what you can and cannot do | [1](#1-what-an-integration-can-do) |
| Get credentials and set up the connection | [2](#2-setup-who-does-what), [3](#3-authentication) |
| Load and keep employees in step, both directions (**onboarding**) | [4](#4-employees-both-directions), [5](#5-onboarding) |
| Let employees **punch in and out** from your app | [6](#6-employee-sessions-self-service-from-your-app), [7](#7-punch-in-and-punch-out) |
| Let employees **apply for leave** and managers approve it | [8](#8-leave) |
| Let employees raise **attendance corrections** | [9](#9-attendance-corrections) |
| Let managers **approve** from your app | [10](#10-approvals-for-managers) |
| Pull **reports** (attendance, leave, headcount) into your system | [11](#11-reports-reading-data-out-of-hrms) |
| Handle errors, retries, security and go live | [12](#12-errors-and-retries), [13](#13-security-checklist), [14](#14-go-live-checklist) |
| Copy working code | [15](#15-complete-example-client) |

Other documents: [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) is the shorter ERP/CRM sync guide and
[EMPLOYEE_INTEGRATION_API.md](EMPLOYEE_INTEGRATION_API.md) is the long self-service reference. This
guide is the one to start from. Every endpoint is also in the live API reference at `/docs`
(Swagger) and `/redoc`, which are on for testing and switched off on production. Ask the administrator for
the OpenAPI file if you cannot reach them.

---

## 1. What an integration can do

An integration uses **two kinds of credential**, for two different jobs:

| | **API key** (server to server) | **Employee session token** (acts as one employee) |
|---|---|---|
| Who holds it | Your backend only | Your backend only (it is handed out per employee) |
| Calls | `/v1/integrations/*` | The ordinary HRMS endpoints listed in [§6](#6-employee-sessions-self-service-from-your-app) |
| Used for | Employee sync, events feed, reference data, attendance and leave reports, issuing session tokens | Punch, today's status, attendance history, leave, corrections, profile, manager approvals |
| Rights | The key's scopes ([§3](#3-authentication)) | Exactly that employee's own rights, never more than `EMPLOYEE` or `MANAGER` |

What is and is **not** exposed. Read this before designing anything:

| Capability | Available to an integration? | How |
|---|---|---|
| Create, update, exit, rehire employees | Yes | API key, `employees.sync` |
| Learn about employees HR creates in HRMS, and about changes HR makes | Yes (**bi-directional**) | Events feed + employee list |
| Onboarding checklist | **Indirect.** You start onboarding by creating the employee, and HRMS adds a "Set up in your app" task that ticks itself. The checklist is run by HR in HRMS; there is no key-level onboarding API | [§5](#5-onboarding) |
| Punch in / out / break start / break end, live | Yes | Employee session |
| **Back-dated or batch punches** (biometric device dumps, `punched_at`) | **No.** The server stamps the time itself; sending `punched_at` or a `DEVICE` source is refused with `422`. Missed punches go through a correction | [§7](#7-punch-in-and-punch-out), [§9](#9-attendance-corrections) |
| Apply for, submit, cancel leave; read balances | Yes | Employee session |
| Raise and cancel attendance corrections | Yes | Employee session |
| Approve or reject leave and corrections | Yes, for managers | Employee session of the approver |
| Read daily attendance and approved leave for everyone | Yes | API key, `attendance.read`, `leave.read` |
| HR's report builder (`/v1/reports`), the daily-analysis export, payroll, recruitment, admin settings | **No** | Reachable only by signing in to HRMS as HR |
| Setting leave policies, holidays, approval flows | **No** | Done by HR in HRMS. You can read holidays |

---

## 2. Setup: who does what

**The HRMS administrator** (Settings → Integrations) does this once per connected system:

1. **Connect an app.** Choose its kind:
   - `TWO_WAY`: you send employees to HRMS and read changes back (a full ERP/CRM link).
   - `RECEIVE_ONLY`: HRMS sends you employees; you send nothing back.
   - `READ_ONLY`: you read attendance, leave and reference data only.
2. **Create an API key** with the scopes you need, an optional list of allowed IP addresses, an
   optional restriction to some companies, and a rate limit (default 600 calls a minute).
3. **Settings for the app** (a draft that is previewed, then published): which fields and events the
   app receives, when a new joiner becomes visible to it (on save, N days before joining, or on the
   joining date), the self-service features it may use (`punch`, `attendance`, `corrections`,
   `leave`, `profile_edit`, `approvals`), the session length (5–480 minutes, default 60), and a
   safety limit on exits per day.
4. **Mappings.** Where your department, location, designation or company names differ from HRMS's,
   the administrator maps them.

**You** receive:

- the **key**, e.g. `hrms_live_Ab3dE6gH_…` (shown once; store it in a secret manager),
- the **base URL**, e.g. `https://hrmsapi.example.com`,
- the **scopes**, **allowed IPs**, and which **companies** the key covers,
- a **test** key and test URL first. Test keys only work on the testing site and live keys only in
  production; the wrong one returns `WRONG_ENVIRONMENT`.

All dates are `YYYY-MM-DD`. All times are ISO 8601 with an offset (`2026-10-12T09:30:00+05:30`).
IDs have a type prefix (`emp_…`, `punch_…`, `la_…` for a leave application, `lt_…` for a leave type, `cor_…` for a correction) and must be treated as opaque strings. Send `X-Request-ID`
if you want to correlate calls; every response carries `request_id`, which HR can find in the app's
sync log.

---

## 3. Authentication

### 3.1 API key

Send it on every `/v1/integrations/*` call:

```bash
curl "$BASE/v1/integrations/reference-data" -H "X-API-Key: $HRMS_KEY"
```

Or, if your security policy requires OAuth 2.0 client credentials, exchange it for a 15-minute
token. The client id is the key's public part (`hrms_<env>_<prefix>`) and the secret is the whole key:

```bash
curl -X POST "$BASE/v1/integrations/oauth/token" \
  -u "hrms_live_Ab3dE6gH:$HRMS_KEY" -d grant_type=client_credentials
# → {"access_token":"…","token_type":"bearer","expires_in":900,"scope":"employees.read events.read"}
curl "$BASE/v1/integrations/reference-data" -H "Authorization: Bearer $TOKEN"
```

A key works only on `/v1/integrations/*`.

### 3.2 Scopes

| Scope | Lets you |
|---|---|
| `employees.sync` | Create, update, link, exit and rehire employees |
| `employees.read` | Read employees, reference data; reconcile |
| `passwords.sync` | Set an employee's HRMS password |
| `sessions.issue` | Get a session token for one employee ([§6](#6-employee-sessions-self-service-from-your-app)) |
| `org.read` | Read companies, departments, locations, designations and holidays |
| `events.read` | Read the events feed |
| `attendance.read` | Read daily attendance |
| `leave.read` | Read approved leave |

Ask for the smallest set you need. A missing scope returns `403 SCOPE_MISSING`.

### 3.3 Why not sign in as the employee?

HRMS also has `POST /v1/auth/login` for people. **Do not use it for an integration:** it needs the
employee's own password (and MFA code), which your system should never hold. Use
[`POST /v1/integrations/sessions`](#6-employee-sessions-self-service-from-your-app) instead.

---

## 4. Employees, both directions

The path ID in sync calls (`EMP-1042` below) is **your** ID for the employee. Pick one that never
changes and use it forever. HRMS keeps the link between your ID and its own `employment_id`.

### 4.1 Read what HRMS accepts

```bash
curl "$BASE/v1/integrations/reference-data" -H "X-API-Key: $HRMS_KEY"
```

Returns the companies, departments, locations and designations (with their codes and IDs) you may
use. Company, department, location and designation values you send are matched by the
administrator's mapping first, then exact code, then exact name (case-insensitive). An unknown value
is refused with a code such as `UNKNOWN_DEPARTMENT`; ask HR to map it, then retry. The same lists are
available one at a time from `GET /v1/integrations/org/{kind}` (`org.read`), where `kind` is `companies`, `departments`, `locations` or `designations`.

### 4.2 Link people who already exist in both systems (once, at go-live)

```bash
curl -X POST "$BASE/v1/integrations/employees/link" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{
    "dry_run": true,
    "records": [
      {"external_id": "EMP-1042", "employee_code": "SFPL-1042"},
      {"external_id": "EMP-1043", "email": "asha.rao@example.com"}
    ]}'
```

It matches by employee code or email, up to 2,000 records a call. The response groups people into
matched, not in HRMS, ambiguous and already linked. Fix what does not match, then send the same body
with `"dry_run": false`.

### 4.3 Create or update an employee (your system → HRMS)

```bash
curl -X PUT "$BASE/v1/integrations/employees/EMP-1042" \
  -H "X-API-Key: $HRMS_KEY" -H "Content-Type: application/json" -d '{
    "source_updated_at": "2026-10-12T09:14:03+05:30",
    "employee_code": "SFPL-1042",
    "first_name": "Ramesh", "last_name": "Patil",
    "email": "ramesh.patil@example.com", "mobile": "+919876543210",
    "date_of_birth": "1992-04-18",
    "company": "SFPL", "department": "Operations", "location": "Nhava Sheva",
    "designation": "Executive", "manager_external_id": "EMP-0877",
    "hire_date": "2026-10-15"
  }'
```

```json
{"outcome": "CREATED", "external_id": "EMP-1042", "employment_id": "emp_…", "user_id": "usr_…",
 "employee_code": "SFPL-1042", "changes": null, "warnings": [], "request_id": "req_…"}
```

`201` when created, otherwise `200`. `outcome` is `CREATED`, `LINKED`, `UPDATED`, `NO_CHANGE` or
`STALE_IGNORED`.

Rules that matter:

- **Unknown fields are refused** (`422`), so a misspelt field is caught in testing.
- **Send only what changed.** Omitted fields are left alone; `null` clears an optional field. Fields
  HRMS owns under the company's settings are ignored with a `warnings` entry.
- **Always send `source_updated_at`** (when it changed in *your* system). An update older than one
  already applied returns `STALE_IGNORED`, so a delayed retry cannot undo a newer change.
- **Employee code.** If the company has an ID scheme, leave `employee_code` out: HRMS issues it and
  returns it. Store what comes back.
- **Job changes** (department, location, designation, manager) take effect on `effective_date`
  (default today) and HRMS keeps history. `"change_reason": "PROMOTION"`, `"TRANSFER"`, or
  `"CORRECTION"` (fixes a mistake without adding a history entry).
- **Managers** are named by `manager_external_id`. Send managers before their reports.
- **Role.** Sync can only grant `EMPLOYEE` or `MANAGER`. Anything else is `ROLE_NOT_ALLOWED`.
- **Passwords** (needs `passwords.sync`): `password_hash` as bcrypt (`$2a$`, `$2b$`, `$2y$`, cost
  10–14) or plain `password` (8–72 characters). Other hash formats are refused. You do not need a
  password for employees who use HRMS only through your app ([§6](#6-employee-sessions-self-service-from-your-app)).
- **Dry run.** Add `?dry_run=true` to see what would change without saving.
- **Idempotency.** `PUT` is safe to repeat. An `Idempotency-Key` header is optional here.

### 4.4 Bulk load

```bash
curl -X POST "$BASE/v1/integrations/employees/bulk" -H "X-API-Key: $HRMS_KEY" \
  -H "Idempotency-Key: load-2026-10-12-batch-1" -H "Content-Type: application/json" \
  -d '{"records": [ {"external_id": "EMP-1042", "first_name": "Ramesh", "…": "…"} ]}'
```

Up to 200 records, each shaped like §4.3 plus `external_id`. `Idempotency-Key` is required. The
response lists a status per record and totals `created`, `updated`, `unchanged`, `failed`. One bad
record does not stop the rest; fix and resend only the failures.

### 4.5 Exit and rehire

Both require an `Idempotency-Key` unique to the action (for example your own record id). A retry
with the same key returns the first answer; the same key with a different body is
`IDEMPOTENCY_KEY_REUSED`.

```bash
curl -X POST "$BASE/v1/integrations/employees/EMP-1042/exit" -H "X-API-Key: $HRMS_KEY" \
  -H "Idempotency-Key: exit-EMP-1042-2026-10-31" -H "Content-Type: application/json" \
  -d '{"last_working_day": "2026-10-31", "reason_code": "RESIGNED"}'

curl -X POST "$BASE/v1/integrations/employees/EMP-1042/rehire" -H "X-API-Key: $HRMS_KEY" \
  -H "Idempotency-Key: rehire-EMP-1042-2027-02-01" -H "Content-Type: application/json" \
  -d '{"hire_date": "2027-02-01", "rejoin_mode": "CONTINUE", "reason": "Returned after sabbatical"}'
```

- If more exits arrive in a day than the company's safety limit allows, the answer is `202` with
  outcome `HELD_FOR_REVIEW`. HR releases or rejects it. Do not retry.
- Rehire may also carry `department`, `location`, `designation`, `manager_external_id`, and the
  rejoin choices `rejoin_mode` (`CONTINUE` keeps earlier service and held leave, `FRESH` starts over),
  `break_condoned`, `reason` (required for `FRESH` and for continuing after a long break) and
  `gratuity_paid_at_exit`. A choice the company's rules forbid is `422 REJOIN_NOT_ALLOWED`; the
  message says why.

### 4.6 HRMS → your system: the events feed

Employees HR creates or changes in HRMS reach you through a feed you poll. This is the other half of
"bi-directional".

```bash
curl "$BASE/v1/integrations/events?after=$CURSOR&limit=200" -H "X-API-Key: $HRMS_KEY"
```

```json
{"events": [
  {"id": "evt_8812", "event": "employee.updated", "occurred_at": "2026-10-12T10:02:11+05:30",
   "employment_id": "emp_…", "external_id": "EMP-1042",
   "employee": {"employee_code": "SFPL-1042", "first_name": "Ramesh", "department": {"name": "Sales"}},
   "changes": {"department": {"old": "Operations", "new": "Sales"}}}
 ],
 "next_cursor": "…", "has_more": false}
```

Event types: `employee.hired`, `employee.updated`, `employee.manager_changed`,
`employee.separated`, `employee.rehired`, `employee.hire_cancelled`.

- **Poll every 30–60 seconds.** Start with no `after`. Afterwards pass the `next_cursor` of your last
  call, and **store it only after you have processed the events**.
- **Order and completeness.** Events arrive in order and none is skipped, even if the transaction that
  produced one commits late.
- **Handle each event idempotently.** After a crash you will see some again.
- **Your own changes are not sent back to you.**
- **`external_id` is `null` for someone HR hired in HRMS.** Create them in your system, then link
  them (§4.7).
- The `employee` block holds only the fields the administrator gave your app.
- A new joiner can be held back until your app's timing rule (on save, N days before joining, on
  joining day), and later events about that person wait behind the held hire.
- **`410 RESYNC_REQUIRED`**: you fell behind; the feed keeps 30 days. Reload everyone from
  `GET /v1/integrations/employees` (pages of up to 200, `cursor` / `next_cursor`, `include_separated`,
  `updated_since`), then continue the feed from the cursor in the `X-Resync-Cursor` response header.
  The employee list's `events_cursor` is the same position.

### 4.7 Link someone HR hired in HRMS

When `employee.hired` arrives with `"external_id": null`, create the person in your system, then
tell HRMS which of your records is theirs:

```bash
curl -X PUT "$BASE/v1/integrations/employees/EMP-2001" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"employment_id": "emp_…"}'
# → {"outcome": "LINKED", …}
```

### 4.8 Reconcile weekly

```bash
curl -X POST "$BASE/v1/integrations/reconcile" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"active_external_ids": ["EMP-1042", "EMP-1043"]}'
```

It reports differences between your active employees and HRMS's and changes nothing.

---

## 5. Onboarding

HRMS runs onboarding as a checklist per new hire (documents, IT, induction and so on). An integration
takes part in two ways.

**1. You start it.** Creating an employee with a `hire_date` (§4.3) is what a new joiner is. The
administrator's default onboarding template then opens a case for them in HRMS.

**2. Your system gets its own task on the checklist.** For each connected app that receives the
joiner, HRMS adds an optional task, **"Set up in <your app>"**, to the case:

| App kind | The task ticks itself when |
|---|---|
| `TWO_WAY` | you link the employee to your own record (§4.3 or §4.7) |
| `RECEIVE_ONLY` / `READ_ONLY` | you read the `employee.hired` event from the feed |

The task is not required, so an outage on your side never blocks HR's onboarding. HR sees it open.

The complete onboarding flow, end to end:

```
HR hires in HRMS ─────────────► employee.hired event (external_id null)
        │                                   │
        │                        you create the person in your system
        │                                   │
        │                        PUT /employees/{your id} {"employment_id": "emp_…"}
        │                                   │            → LINKED, "Set up in <app>" ticks
        ▼
HR completes the rest of the checklist in HRMS
```

or, the other way round:

```
Your system hires ───► PUT /employees/{your id}  (CREATED, HRMS issues employee_code)
        │                    └─ HRMS opens the onboarding case and adds the "Set up in" task
        ▼
You store employee_code and employment_id; HR runs the checklist in HRMS
```

To show **onboarding status in your own UI**, there is no key-level API for checklist items. Use the
employee's `employment_state` from the events feed or the employee list (§4.6), and ask the
administrator if you need progress exposed. The checklist screens and `/v1/onboarding/*` are
HR-only.

---

## 6. Employee sessions: self-service from your app

For screens where an employee punches in, applies for leave, or a manager approves: your server asks
HRMS for a token for that one employee, **after the employee has signed in to your app**. Needs the
`sessions.issue` scope.

```bash
curl -X POST "$BASE/v1/integrations/sessions" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"external_id": "EMP-1042"}'
```

```json
{"access_token": "eyJ…", "token_type": "bearer", "expires_in": 3600,
 "employment_id": "emp_…", "roles": ["EMPLOYEE"]}
```

Then call the HRMS endpoints below with `Authorization: Bearer <access_token>` (no API key):

| Feature setting | Calls the token may make |
|---|---|
| always | `GET /v1/auth/me`, `POST /v1/auth/logout`, `GET /v1/persons/me`, `GET /v1/dashboard/employee` |
| `profile_edit` | `PATCH /v1/persons/me` |
| `punch` | `POST /v1/time/punches`, `GET /v1/time/today` |
| `attendance` | `GET /v1/time/attendance-days`, `GET /v1/time/today` |
| `attendance` or `leave` | `GET /v1/time/holidays` |
| `corrections` | `POST /v1/corrections`, `POST /v1/corrections/{id}/cancel`, `GET /v1/corrections` |
| `leave` | `GET /v1/leave/types`, `/balances`, `/applications`, `/applications/summary`; `POST /v1/leave/applications`, `…/{id}/submit`, `…/{id}/cancel` |
| `approvals` | `GET /v1/approvals/inbox`, `GET /v1/approvals/requests/{id}`, `POST /v1/approvals/requests/{id}/decision`; `POST /v1/corrections/{id}/approve` and `/reject`; `POST /v1/leave/applications/{id}/approve`, `/reject`, `/cancel-approve`, `/cancel-reject`; `GET /v1/dashboard/team`, `GET /v1/dashboard/manager` |

Any other call, or a feature the administrator switched off, returns
`403 NOT_AVAILABLE_VIA_INTEGRATION`.

How the token behaves:

- It is **that employee only**, with their normal visibility, and never carries HR or admin rights.
  Managers see their team exactly as in HRMS.
- **Cache it** per employee and reuse it until it is close to `expires_in` (the company's session
  length, 60 minutes by default). Do not request one per click.
- It **stops working immediately** if your key is revoked, the employee leaves, or their HRMS
  password changes. On `401`, request a new one.
- **No HRMS password needed.** An active employee who has no HRMS login gets one automatically on
  first request, with `EMPLOYEE` rights and no password. They can use HRMS through your app until HR
  issues them credentials.
- `403 SESSION_REFUSED` means no active employee is linked to that `external_id` (the same answer
  for every cause, deliberately).
- **Never send this token, or the key, to a browser or phone.** Your backend calls HRMS; your
  front end calls your backend.

---

## 7. Punch in and punch out

```bash
curl -X POST "$BASE/v1/time/punches" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "punch_type": "IN", "source": "MOBILE",
    "latitude": 12.9716, "longitude": 77.5946, "device_id": "pixel-8-abc123"
  }'
```

| Field | Notes |
|---|---|
| `punch_type` | `IN`, `OUT`, `BREAK_START`, `BREAK_END` |
| `source` | Send `WEB` or `MOBILE` (default `WEB`). **Anything else is `422`.** HRMS records every punch made through a session as source `INTEGRATION`, tagged with your app's code, whatever you send |
| `latitude`, `longitude`, `device_id` | Optional, stored with the punch |
| `confirm_long_day` | Set `true` only after `LONG_DAY_CONFIRM` (below) |
| `punched_at` | **Do not send.** The server uses its own clock. Sending it is `422 Historical and device punches must use an authorized correction workflow` |

```json
{"id": "punch_…", "employment_id": "emp_…", "punch_type": "IN",
 "punched_at": "2026-10-12T03:35:14.238192Z", "source": "INTEGRATION",
 "latitude": 12.9716, "longitude": 77.5946, "is_corrected": false}
```

Valid order each working day:

| Previous punch today | Allowed next |
|---|---|
| none | `IN` |
| `IN` | `OUT`, `BREAK_START` |
| `BREAK_START` | `BREAK_END`, `OUT` |
| `BREAK_END` | `OUT`, `BREAK_START` |
| `OUT` | `IN` (an employee may re-enter) |

An out-of-order punch returns `409 Invalid punch sequence; use a correction for missing events`.

Rules from the attendance policy:

- **Hours worked** are the first `IN` to the last `OUT`, minus time actually spent out.
- **A session stays open for 24 hours.** A check-out after midnight closes the session that is still
  open. An `IN` left without an `OUT` for over 24 hours becomes a **missed punch**, and punching `OUT`
  the next day returns `409 Missed punch: …`. The employee raises a correction ([§9](#9-attendance-corrections)).
- **`409 LONG_DAY_CONFIRM`**: an `OUT` more than 16 hours after the `IN`. Show the message to the
  employee. If they confirm, resend with `"confirm_long_day": true` and the day goes to HR for review
  before any overtime counts. If they forgot to check out, raise a correction instead.

### Today's status

```bash
curl "$BASE/v1/time/today" -H "Authorization: Bearer $TOKEN"
```

Returns `employment_id`, `work_date`, `is_punched_in`, `first_punch_in`, `last_punch_out`,
`effective_minutes`, `status` and the day's `punches`. Use it to decide which button to show (IN or
OUT). Optional `work_date=YYYY-MM-DD`.

### Attendance history

```bash
curl "$BASE/v1/time/attendance-days?from_date=2026-10-01&to_date=2026-10-31" \
  -H "Authorization: Bearer $TOKEN"
```

Each day: `work_date`, `first_punch_in`, `last_punch_out`, `effective_minutes`, `late_by_minutes`,
`early_departure_minutes`, `status`, `ot_minutes`, `ot_status`, `comp_off_days`, `review_flags`,
`needs_review`. `status` is one of `PRESENT`, `ABSENT`, `HALF_DAY`, `LATE`, `EARLY_DEPARTURE`,
`ON_LEAVE`, `HOLIDAY`, `WEEKEND`, `PENDING`, `MISSED_PUNCH`, `OFF_DAY_WORKED`.

### Hardware (biometric, RFID, kiosks)

A kiosk can punch an employee **in real time** by obtaining that employee's session and calling the
same endpoint, with your backend in the middle. HRMS does not accept device logs after the fact.
If a device was offline, its missed events become corrections (§9), raised by or for the employee and
approved by the usual flow.

---

## 8. Leave

### 8.1 Flow

```
GET /v1/leave/types ──► GET /v1/leave/balances ──► POST /v1/leave/applications  (DRAFT)
                                                          │
                                         POST …/{id}/submit ──► PENDING_L1 → PENDING_L2 → PENDING_L3
                                                          │                       │
                                                          ▼                       ▼
                                                     APPROVED               REJECTED
                                                          │
                                       POST …/{id}/cancel ──► CANCELLED
                                       (or a cancellation request that needs approval)
```

Applying is **two calls**: create a draft, then submit it. A draft holds nothing; submitting checks
the rules and puts the days on hold. A leave type that needs no approval goes straight from submit to
`APPROVED`.

### 8.2 Types and balances

```bash
curl "$BASE/v1/leave/types"    -H "Authorization: Bearer $TOKEN"
curl "$BASE/v1/leave/balances" -H "Authorization: Bearer $TOKEN"
```

Types carry `id` (`lt_…`), `name`, `code`, `requires_approval`, `approval_levels`,
`min_days_per_application`, `max_days_per_application`, `advance_notice_days`, `requires_document`,
`is_paid`. Balances carry `leave_type_id`, `year`, `allocated_days`, `carry_forward_days`,
`used_days`, `pending_days` and `available_days`.

### 8.3 Apply

```bash
curl -X POST "$BASE/v1/leave/applications" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "leave_type_id": "lt_…",
    "from_date": "2026-11-09", "to_date": "2026-11-10",
    "half_day_option": "NONE",
    "reason": "Family function"
  }'
```

`half_day_option` is `NONE`, `FIRST_HALF` or `SECOND_HALF`. The response (`201`) is the application in
status `DRAFT` with `days_requested` already worked out. Weekends and holidays are handled by the
company's policy, so show `days_requested` back to the employee instead of counting it yourself. Some
leave types require a supporting document (`document_id`); the document must exist in HRMS first.

Then submit:

```bash
curl -X POST "$BASE/v1/leave/applications/$APP_ID/submit" -H "Authorization: Bearer $TOKEN"
```

Submission fails with `400`/`422` and a plain-language message when the balance is too low, notice is
too short, the dates overlap another application, or the type's limits are broken. Show the message.

### 8.4 Track, list, cancel

```bash
curl "$BASE/v1/leave/applications?status=PENDING_L1,PENDING_L2&limit=50" -H "Authorization: Bearer $TOKEN"
curl -X POST "$BASE/v1/leave/applications/$APP_ID/cancel" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"cancel_reason": "Plans changed"}'
```

The list is newest first, with drafts at the top. Page with `limit` (1–200) and `after` (the `id` of the
last item). A page shorter than `limit` is the last. Each application has `status`, `current_level`,
`total_levels`, `cancel_reason`, and an `approval_history`. Cancelling a draft cancels it at once.
Cancelling a submitted or approved application cancels it, or starts a cancellation request, depending
on the leave type's `cancel_requires_approval`. Managers decide cancellations with
`…/cancel-approve` and `…/cancel-reject`.

---

## 9. Attendance corrections

Use a correction when a punch is missing or wrong, or to give a reason for lateness. It is reviewed by
the company's approval flow (one or more levels, set by HR).

```bash
curl -X POST "$BASE/v1/corrections" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "work_date": "2026-10-10",
    "correction_type": "REGULARIZE",
    "requested_punch_in":  "2026-10-10T09:15:00+05:30",
    "requested_punch_out": "2026-10-10T18:30:00+05:30",
    "reason": "Biometric terminal was offline during morning check-in."
  }'
```

| `correction_type` | You must send |
|---|---|
| `PUNCH_IN` | `requested_punch_in` |
| `PUNCH_OUT` | `requested_punch_out` |
| `MISSED_PUNCH` | `requested_punch_in` or `requested_punch_out` |
| `REGULARIZE` | both |
| `MARK_PRESENT` | both |
| `MARK_ABSENT` | neither |
| `LATE_REASON`, `EARLY_DEPARTURE_REASON` | `reason` only |

Every correction needs a `reason` (1–1000 characters). Punch times **must carry a timezone offset**
and `requested_punch_out` must be after `requested_punch_in`; otherwise `422`.

```json
{"id": "cor_…", "employment_id": "emp_…", "work_date": "2026-10-10",
 "correction_type": "REGULARIZE", "reason": "…",
 "status": "PENDING_L1", "current_level": 1, "total_levels": 1,
 "submitted_at": "2026-10-12T10:15:00Z", "approval_history": []}
```

Statuses: `PENDING_L1`, `PENDING_L2`, … `APPROVED`, `REJECTED`, `CANCELLED`. On approval, HRMS rewrites the
day's attendance and recalculates it; read it back with `GET /v1/time/attendance-days`.

```bash
curl "$BASE/v1/corrections?status=PENDING_L1" -H "Authorization: Bearer $TOKEN"
curl -X POST "$BASE/v1/corrections/$ID/cancel"  -H "Authorization: Bearer $TOKEN"
```

---

## 10. Approvals for managers

A manager's token (role `MANAGER`) sees what the manager sees in HRMS.

```bash
curl "$BASE/v1/approvals/inbox" -H "Authorization: Bearer $TOKEN"
curl "$BASE/v1/approvals/requests/$INSTANCE_ID" -H "Authorization: Bearer $TOKEN"
curl -X POST "$BASE/v1/approvals/requests/$INSTANCE_ID/decision" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"action": "APPROVE", "comments": "Verified with team lead."}'
```

`action` is `APPROVE` or `REJECT`; `comments` is optional (up to 1000 characters). The inbox mixes
request types (leave, leave cancellation, attendance correction, overtime). Leave and corrections also
have direct endpoints that take the same body:

```bash
curl -X POST "$BASE/v1/leave/applications/$ID/approve"  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"action": "APPROVE", "comments": "OK"}'
curl -X POST "$BASE/v1/corrections/$ID/reject"          -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"action": "REJECT", "comments": "Times do not match."}'
```

An employee cannot approve their own request, and someone outside the approval route is refused with
`403`. Do not try to work around it.

---

## 11. Reports: reading data out of HRMS

These are API-key calls (no employee session) for feeding a data warehouse, payroll or BI tool. Each
needs its scope, and results are limited to the companies the key covers.

| Report | Call | Scope |
|---|---|---|
| Daily attendance for one date | `GET /v1/integrations/attendance/daily?date=2026-10-12` | `attendance.read` |
| Approved leave in a range (max one year) | `GET /v1/integrations/leave?from=2026-10-01&to=2026-10-31` | `leave.read` |
| Holiday calendars for a year | `GET /v1/integrations/holidays?year=2026` | `org.read` |
| Headcount and employee master | `GET /v1/integrations/employees` | `employees.read` |
| What changed since last time | `GET /v1/integrations/events` | `events.read` |
| Companies, departments, locations, designations | `GET /v1/integrations/org/{kind}` (`companies`, `departments`, `locations`, `designations`) | `org.read` |
| Differences against your list | `POST /v1/integrations/reconcile` | `employees.read` |

Daily attendance:

```bash
curl "$BASE/v1/integrations/attendance/daily?date=2026-10-12" -H "X-API-Key: $HRMS_KEY"
```

```json
[{"employment_id": "emp_…", "external_id": "EMP-1042", "employee_code": "SFPL-1042",
  "date": "2026-10-12", "status": "PRESENT",
  "first_in": "2026-10-12T03:35:14+00:00", "last_out": "2026-10-12T12:50:02+00:00",
  "worked_minutes": 512}]
```

Approved leave:

```bash
curl "$BASE/v1/integrations/leave?from=2026-10-01&to=2026-10-31" -H "X-API-Key: $HRMS_KEY"
```

```json
[{"id": "la_…", "employment_id": "emp_…", "external_id": "EMP-1042",
  "employee_code": "SFPL-1042", "leave_type": "Casual Leave",
  "from": "2026-10-20", "to": "2026-10-21", "days": 2.0, "half_day": "NONE"}]
```

For a month-end pull, call attendance once per day and leave once for the month. Join on
`external_id`, falling back to `employment_id`. A range longer than 366 days, or `to` before `from`,
is `422`.

For one employee's history use their own session ([§7](#7-punch-in-and-punch-out)). HR's report builder
and exports are not part of the integration API.

---

## 12. Errors and retries

Every error has this body; branch on `code`, never on the wording:

```json
{"detail": "HRMS has no department 'Ops Dept'. Map it on the Mappings tab, then retry.",
 "code": "UNKNOWN_DEPARTMENT", "request_id": "req_…", "error": {…}}
```

**Retry** `429` (wait for `Retry-After`), `5xx` and timeouts, with exponential backoff (1 s, 2 s, 4 s,
up to 5 minutes, with jitter). **Do not retry** other `4xx`: fix the data or ask HR.

| Code | Meaning | What to do |
|---|---|---|
| `INVALID_API_KEY`, `API_KEY_REVOKED`, `API_KEY_EXPIRED` | The key is wrong or no longer valid | Get a new key |
| `WRONG_ENVIRONMENT` | Test key on production or the reverse | Use the right key |
| `IP_NOT_ALLOWED` | Your server's address is not on the key's list | Ask the administrator |
| `APP_PAUSED` | The app is paused | Wait; events keep queuing |
| `SCOPE_MISSING` | Key lacks the scope | Ask for it |
| `RATE_LIMITED` | Too many calls this minute | Wait for `Retry-After` |
| `UNKNOWN_LEGAL_ENTITY`, `UNKNOWN_DEPARTMENT`, `UNKNOWN_LOCATION`, `UNKNOWN_DESIGNATION` | Value HRMS does not know | Ask HR to map it |
| `AMBIGUOUS_…` | Value matches more than one record | Ask HR to map it |
| `FIELD_REQUIRED` | A needed field is missing | Send it |
| `ROLE_NOT_ALLOWED` | Sync grants only `EMPLOYEE` or `MANAGER` | HR grants the rest |
| `POSSIBLE_DUPLICATE` | Looks like an unlinked HRMS employee | HR confirms or rejects, then retry |
| `EMAIL_IN_USE`, `MOBILE_IN_USE`, `EMPLOYEE_CODE_IN_USE` | Taken by another employee | Fix the data |
| `ALREADY_LINKED` | That HRMS employee is linked to another of your IDs | Use the linked ID |
| `PRIVILEGED_ACCOUNT_PROTECTED` | The login has HR or admin rights, so sign-in details change only in HRMS | Leave those fields out |
| `UNSUPPORTED_PASSWORD_HASH` | Not bcrypt | Send plain password or none |
| `OPERATION_NOT_ALLOWED` | The company makes this change in HRMS | Leave it to HR |
| `COMPANY_CHANGE_NOT_SUPPORTED` | Moving between companies | Exit, then create a new employment with a new ID |
| `REJOIN_NOT_ALLOWED` | The rejoin choice breaks the company's rules | Read the message |
| `IDEMPOTENCY_KEY_REUSED` | Same key, different body | New key for a new action |
| `RESYNC_REQUIRED` (410) | Fell behind the events feed | Reload, then continue ([§4.6](#46-hrms--your-system-the-events-feed)) |
| `SESSION_REFUSED` | No active employee linked to that ID | Check the ID and status |
| `NOT_AVAILABLE_VIA_INTEGRATION` | Call or feature not open to app sessions | Use another path or ask HR |
| `LONG_DAY_CONFIRM` (409) | `OUT` after more than 16 hours | Confirm or raise a correction |

Plain `401` on a session token means it expired or was revoked: request a new one. `422` on a
request body names the field. `409` on a punch is a sequence problem, not a transient one.

**Which calls are safe to repeat:** all `GET`s; `PUT /employees/{id}`; every `POST` that takes an
`Idempotency-Key` when you reuse the key. **Punches, leave applications and corrections have no
idempotency key.** After a timeout, read first (`GET /v1/time/today`, `GET /v1/leave/applications`,
`GET /v1/corrections`) before sending again, or you may duplicate or get a `409`.

---

## 13. Security checklist

- Keys and session tokens live on your server only. Never in a browser, mobile app, repository or log.
- Ask for the fewest scopes and the shortest list of allowed IPs. One key per system, so revoking one
  does not disturb another.
- Rotate keys by creating the new key, deploying it, then revoking the old.
- Only request an employee session after your own sign-in has authenticated that person, and map the
  signed-in user to the right `external_id` on the server.
- Treat HRMS data as personal data. Store only what you need, and honour exits (`employee.separated`).
- Log `request_id` with every failure; do not log tokens.

---

## 14. Go-live checklist

1. Test key, test URL: `GET /v1/integrations/reference-data` works.
2. Mappings agreed; `link` dry run clean, then applied.
3. Employee create, update, exit and rehire tested, including `STALE_IGNORED` and `HELD_FOR_REVIEW`.
4. Events feed running with a stored cursor, tested after a kill and restart, and a forced `410`
   handled.
5. One employee end to end: session → `today` → `IN` → `OUT` → attendance day; leave draft → submit →
   manager approves → appears in `GET /integrations/leave`; correction raised → approved.
6. Error handling: `429` backoff, `409` punches, `LONG_DAY_CONFIRM`, expired token.
7. Production key received, stored, IPs allowed. Run [§4.8](#48-reconcile-weekly) once; schedule it weekly.
8. Monitoring on your poller's lag, and an alert on repeated `4xx`/`5xx`. The administrator can see
   your app's sync log, feed position and lag in Settings → Integrations.

---

## 15. Complete example client

Python 3.11+, `pip install httpx`. A tested version with retries and the feed poller is in
[examples/hrms_client.py](examples/hrms_client.py); this one shows the whole journey in one file.

```python
"""HRMS integration: employee sync, feed, and an employee's punch, leave and correction."""
import time
from datetime import date

import httpx

BASE = "https://hrmsapi.example.com"
KEY = "hrms_live_…"  # from your secret store


class Hrms:
    def __init__(self):
        self.http = httpx.Client(base_url=BASE, timeout=30)
        self._tokens: dict[str, tuple[str, float]] = {}  # external_id -> (token, expires_at)

    # ── generic call with retry ─────────────────────────────────────────────────
    def call(self, method, path, *, token=None, **kw):
        headers = kw.pop("headers", {})
        headers.update({"Authorization": f"Bearer {token}"} if token else {"X-API-Key": KEY})
        for attempt in range(6):
            try:
                r = self.http.request(method, path, headers=headers, **kw)
            except httpx.TransportError:
                r = None
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                if r.status_code >= 400:
                    raise RuntimeError((r.status_code, r.json()))
                return r.json() if r.content else None
            wait = float(r.headers.get("Retry-After", 0)) if r is not None else 0
            time.sleep(max(wait, min(2 ** attempt, 300)))
        raise RuntimeError("HRMS unavailable")

    # ── employees ───────────────────────────────────────────────────────────────
    def upsert_employee(self, external_id, body):
        return self.call("PUT", f"/v1/integrations/employees/{external_id}", json=body)

    def exit_employee(self, external_id, last_day: date, reason="RESIGNED"):
        return self.call(
            "POST", f"/v1/integrations/employees/{external_id}/exit",
            headers={"Idempotency-Key": f"exit-{external_id}-{last_day}"},
            json={"last_working_day": last_day.isoformat(), "reason_code": reason})

    def poll_events(self, load_cursor, save_cursor, handle):
        cursor = load_cursor()
        while True:
            try:
                page = self.call("GET", "/v1/integrations/events",
                                 params={"after": cursor} if cursor else {})
            except RuntimeError as e:
                if e.args[0][0] == 410:
                    raise  # reload /employees, then resume from X-Resync-Cursor
                raise
            for event in page["events"]:
                handle(event)  # idempotent
            cursor = page["next_cursor"]
            save_cursor(cursor)  # only after handling
            if not page["has_more"]:
                time.sleep(45)

    # ── employee session ────────────────────────────────────────────────────────
    def token_for(self, external_id):
        token, expires = self._tokens.get(external_id, (None, 0))
        if token and time.time() < expires - 60:
            return token
        s = self.call("POST", "/v1/integrations/sessions", json={"external_id": external_id})
        self._tokens[external_id] = (s["access_token"], time.time() + s["expires_in"])
        return s["access_token"]

    def as_employee(self, external_id, method, path, **kw):
        try:
            return self.call(method, path, token=self.token_for(external_id), **kw)
        except RuntimeError as e:
            if e.args[0][0] == 401:  # expired or revoked: get a new one once
                self._tokens.pop(external_id, None)
                return self.call(method, path, token=self.token_for(external_id), **kw)
            raise

    def punch(self, external_id, punch_type, **extra):
        return self.as_employee(external_id, "POST", "/v1/time/punches",
                                json={"punch_type": punch_type, "source": "MOBILE", **extra})

    def today(self, external_id):
        return self.as_employee(external_id, "GET", "/v1/time/today")

    def apply_leave(self, external_id, leave_type_id, start: date, end: date, reason):
        draft = self.as_employee(external_id, "POST", "/v1/leave/applications", json={
            "leave_type_id": leave_type_id, "from_date": start.isoformat(),
            "to_date": end.isoformat(), "half_day_option": "NONE", "reason": reason})
        return self.as_employee(external_id, "POST",
                                f"/v1/leave/applications/{draft['id']}/submit")

    def correct(self, external_id, work_date: date, punch_in, punch_out, reason):
        return self.as_employee(external_id, "POST", "/v1/corrections", json={
            "work_date": work_date.isoformat(), "correction_type": "REGULARIZE",
            "requested_punch_in": punch_in, "requested_punch_out": punch_out, "reason": reason})

    def decide(self, manager_external_id, instance_id, approve: bool, comments=""):
        return self.as_employee(
            manager_external_id, "POST", f"/v1/approvals/requests/{instance_id}/decision",
            json={"action": "APPROVE" if approve else "REJECT", "comments": comments})

    # ── reports ─────────────────────────────────────────────────────────────────
    def attendance(self, on: date):
        return self.call("GET", "/v1/integrations/attendance/daily", params={"date": on.isoformat()})

    def leave(self, start: date, end: date):
        return self.call("GET", "/v1/integrations/leave",
                         params={"from": start.isoformat(), "to": end.isoformat()})


if __name__ == "__main__":
    hrms = Hrms()
    print(hrms.upsert_employee("EMP-1042", {
        "source_updated_at": "2026-10-12T09:14:03+05:30", "first_name": "Ramesh",
        "last_name": "Patil", "email": "ramesh.patil@example.com", "company": "SFPL",
        "department": "Operations", "designation": "Executive", "hire_date": "2026-10-15"}))
    print(hrms.punch("EMP-1042", "IN"))
    print(hrms.today("EMP-1042"))
    print(hrms.punch("EMP-1042", "OUT"))
    print(hrms.attendance(date.today()))
```

Notes: this example does not add idempotency to punches, leave or corrections; see the end of
[§12](#12-errors-and-retries) for what to do after a timeout.
