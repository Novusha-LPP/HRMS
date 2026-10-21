# Connecting an ERP or CRM to HRMS: developer guide

A working reference client is in [examples/hrms_client.py](examples/hrms_client.py) (Python,
`httpx`). It covers retries, idempotency keys, linking and the events-feed poller, and CI runs it
against the API, so it always matches what the API does.

For the developers of a system (an ERP, a CRM, a BI tool) that connects to HRMS. The design and the
reasons behind it are in [erp-crm-integration-plan.md](erp-crm-integration-plan.md). Every endpoint
is also in the API reference at `/docs`, under **Integrations**.

## 1. Before you start

The HRMS administrator connects your system in **Settings → Integrations** and creates a key for it.
They give you:

- **the key**, e.g. `hrms_live_Ab3dE6gH_…`. Store it in your server's secret store. It is shown to
  them once and is never visible again.
- **the base URL**, e.g. `https://hrmsapi.example.com`.
- **the key's scopes**: what it may do (table below).
- **the allowed IP addresses**: calls from anywhere else are refused.

| Scope | Lets you |
|---|---|
| `employees.sync` | create, update, exit and rehire employees |
| `employees.read` | read employees, reference data and reconciliation |
| `passwords.sync` | set an employee's HRMS password |
| `sessions.issue` | get a session token for one employee (self-service inside your app) |
| `org.read` | read companies, departments, locations, designations and holidays |
| `events.read` | read the events feed |
| `attendance.read`, `leave.read` | read daily attendance and approved leave |

**Keys are server-side only.** Never put a key, or a session token, in a browser or mobile app.

## 2. Authenticating

Send the key on every call:

```bash
curl "$BASE/v1/integrations/reference-data" -H "X-API-Key: $HRMS_KEY"
```

If your security policy requires OAuth 2.0, use client credentials. The client id is the key's
public part (`hrms_<env>_<prefix>`), and the client secret is the whole key:

```bash
curl -X POST "$BASE/v1/integrations/oauth/token" \
  -u "hrms_live_Ab3dE6gH:$HRMS_KEY" -d grant_type=client_credentials
# → {"access_token": "…", "token_type": "bearer", "expires_in": 900, "scope": "…"}
curl "$BASE/v1/integrations/reference-data" -H "Authorization: Bearer $TOKEN"
```

A key only works on `/v1/integrations/*`. A `test` key works only on the testing site and a `live`
key only in production.

## 3. Go-live order

1. **Check the values HRMS accepts.** Call `GET /v1/integrations/reference-data`. Your company,
   department, location and designation values are matched by mapping first, then by exact code, then
   by exact name (ignoring case). Ask the HRMS administrator to map anything spelt differently.
2. **Link the employees who already exist in both systems.** Call `POST /v1/integrations/employees/link`
   with your IDs and employee codes. Read the dry-run report, fix what doesn't match, then repeat with
   `"dry_run": false`.
3. **Load anyone missing** with `POST /v1/integrations/employees/bulk`. Send managers before their
   reports.
4. **From then on**, send each joiner, change and exit as it happens (§4), and poll the events feed
   for changes made in HRMS (§5).
5. **Weekly**, call `POST /v1/integrations/reconcile` with your active IDs and review the
   differences.

## 4. Sending employees

### Create or update

```bash
curl -X PUT "$BASE/v1/integrations/employees/EMP-1042" \
  -H "X-API-Key: $HRMS_KEY" -H "Content-Type: application/json" -d '{
    "source_updated_at": "2026-10-12T09:14:03+05:30",
    "employee_code": "SFPL-1042",
    "first_name": "Ramesh", "last_name": "Patil",
    "email": "ramesh.patil@example.com", "mobile": "+919876543210",
    "company": "SFPL", "department": "Operations", "location": "Nhava Sheva",
    "designation": "Executive", "manager_external_id": "EMP-0877",
    "hire_date": "2026-10-15"
  }'
```

The path's ID (`EMP-1042`) is **your** ID for the employee. Use the same one forever.

- **Send only what changed.** Fields you leave out are left alone, and `null` clears an optional
  field. HRMS may own some fields under the company's settings; those are ignored, with a warning in
  the response.
- **Always send `source_updated_at`**, the time the record changed in your system. An update older
  than one already applied is ignored (`STALE_IGNORED`), so a delayed retry can't undo a newer change.
- **Employee codes.** If the company has an employee ID scheme in HRMS, you may leave `employee_code`
  out: HRMS issues it and returns it in the response, so store it. Otherwise send your code.
- **Job changes** (department, location, designation, manager) take effect on `effective_date`
  (default today), and HRMS keeps the history. Send `"change_reason": "PROMOTION"` for a promotion,
  or `"CORRECTION"` to fix a mistake without adding a history entry.
- **Passwords** (needs `passwords.sync`): send `password_hash` as a bcrypt hash (`$2a$`, `$2b$` or
  `$2y$`, cost 10–14), or `password` in plain text. Other hash formats are refused.
- **Try it first** with `?dry_run=true`: the response shows what would change, and nothing is saved.

Response (`201` when created, `200` otherwise):

```json
{"outcome": "CREATED", "external_id": "EMP-1042", "employment_id": "emp_…", "user_id": "usr_…",
 "employee_code": "SFPL-1042", "changes": null, "warnings": [], "request_id": "req_…"}
```

The `outcome` is one of: `CREATED`, `LINKED`, `UPDATED`, `NO_CHANGE`, `STALE_IGNORED`.

### Someone hired in HRMS

You receive `employee.hired` with `"external_id": null` (§5). Create the person in your system, then
link them by sending the HRMS `employment_id`:

```bash
curl -X PUT "$BASE/v1/integrations/employees/EMP-2001" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"employment_id": "emp_…"}'
# → {"outcome": "LINKED", …}
```

### Exit and rehire

These need an `Idempotency-Key` header. Use a value unique to the action, such as your own record or
event id. A retry with the same key returns the first answer.

```bash
curl -X POST "$BASE/v1/integrations/employees/EMP-1042/exit" -H "X-API-Key: $HRMS_KEY" \
  -H "Idempotency-Key: exit-EMP-1042-2026-10-31" -H "Content-Type: application/json" \
  -d '{"last_working_day": "2026-10-31", "reason_code": "RESIGNED"}'
```

If your system sends more exits in 24 hours than the company's safety valve allows, the response is
`202` with outcome `HELD_FOR_REVIEW`, and HR must release it. Rehire with
`POST …/{id}/rehire {"hire_date": "…"}`.

A rehire can also say what happens to the person's earlier service and leave. All four fields are
optional, and leaving them out uses the company's rejoin policy (without one, earlier service
continues, as it always has):

| Field | Meaning |
|---|---|
| `rejoin_mode` | `CONTINUE` keeps earlier service and held leave; `FRESH` starts over and lapses unused leave |
| `break_condoned` | The break is accepted as not interrupting service. Needed to continue after a break longer than the company allows |
| `reason` | Why. Required for `FRESH`, and for continuing after a long break |
| `gratuity_paid_at_exit` | Gratuity was paid when they left, so service restarts and only `FRESH` is allowed |

A choice the company's rules rule out is refused with `422` and code `REJOIN_NOT_ALLOWED`; the
message says why. The `employee.rehired` event carries `rejoin_mode` in its `changes`.

## 5. Reading changes made in HRMS: the events feed

Poll every 30–60 seconds. Pass the `next_cursor` from your last call as `after`, and store it only
after you have processed the events:

```python
import time

import requests

BASE, KEY = "https://hrmsapi.example.com", "hrms_live_…"
session = requests.Session()
session.headers["X-API-Key"] = KEY


def poll_forever(load_cursor, save_cursor, handle):
    cursor = load_cursor()  # None the first time
    while True:
        r = session.get(f"{BASE}/v1/integrations/events",
                        params={"after": cursor} if cursor else {}, timeout=30)
        if r.status_code == 410:  # too far behind: the feed keeps 30 days
            resync(handle)
            cursor = r.headers["X-Resync-Cursor"]
            save_cursor(cursor)
            continue
        r.raise_for_status()
        page = r.json()
        for event in page["events"]:
            handle(event)  # must be idempotent: an event can be redelivered after a crash
        cursor = page["next_cursor"]
        save_cursor(cursor)
        if not page["has_more"]:
            time.sleep(45)


def resync(handle):
    """Reload everyone, page by page; then continue the feed from the cursor in the 410."""
    cursor = None
    while True:
        r = session.get(f"{BASE}/v1/integrations/employees",
                        params={"cursor": cursor} if cursor else {}, timeout=60)
        r.raise_for_status()
        page = r.json()
        for employee in page["employees"]:
            handle({"event": "employee.snapshot", "employee": employee})
        if not page["has_more"]:
            return
        cursor = page["next_cursor"]
```

An event looks like this:

```json
{"id": "evt_8812", "event": "employee.updated", "occurred_at": "2026-10-12T10:02:11+05:30",
 "employment_id": "emp_…", "external_id": "EMP-1042",
 "employee": {"employee_code": "SFPL-1042", "first_name": "Ramesh", "department": {"name": "Sales", …}, …},
 "changes": {"department": {"old": "Operations", "new": "Sales"}}}
```

The event types are `employee.hired`, `employee.updated`, `employee.manager_changed`,
`employee.separated`, `employee.rehired` and `employee.hire_cancelled`.

- **Events arrive in order, and none is ever skipped.**
- **Your own changes are not sent back to you.**
- `employee` contains only the fields your app is given.

## 6. Self-service inside your app (punch, leave, own data)

After the employee signs in to your app, your server asks HRMS for a token for them (needs
`sessions.issue`):

```bash
curl -X POST "$BASE/v1/integrations/sessions" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"external_id": "EMP-1042"}'
# → {"access_token": "eyJ…", "expires_in": 3600, "employment_id": "emp_…", "roles": ["EMPLOYEE"]}
```

Then call the ordinary HRMS endpoints with `Authorization: Bearer <access_token>`:

| To | Call |
|---|---|
| Punch in / out | `POST /v1/time/punches {"punch_type": "IN"}` (or `OUT`, `BREAK_START`, `BREAK_END`) |
| Today's status | `GET /v1/time/today` |
| Attendance | `GET /v1/time/attendance-days?from_date=…&to_date=…` |
| Leave | `GET /v1/leave/types`, `GET /v1/leave/balances`, `POST /v1/leave/applications`, `…/{id}/submit`, `…/{id}/cancel` |
| Corrections | `GET /v1/corrections`, `POST /v1/corrections` |
| Profile | `GET /v1/persons/me`, `PATCH /v1/persons/me` |
| A manager's approvals | `GET /v1/approvals/inbox`, `POST /v1/approvals/requests/{id}/decision` |

How the token behaves:

- **It belongs to that one employee.** It sees exactly what they could see signing in to HRMS
  themselves, and never carries HR or admin rights.
- **It only works on the calls above,** and only for the features the company switched on. Other
  calls return `403 NOT_AVAILABLE_VIA_INTEGRATION`.
- **Reuse it until it is close to `expires_in`.** Don't request one per click.
- **It stops working at once** if your key is revoked, the employee leaves, or their password
  changes.
- **Employees without an HRMS login** (hired in HRMS and linked by you) get one automatically when
  you first ask for their session. It has Employee rights and no password: they use HRMS through
  your app only, until HR issues them HRMS credentials.
- **Punches made with it are recorded as coming from your app.**

The full request bodies are in [EMPLOYEE_INTEGRATION_API.md](EMPLOYEE_INTEGRATION_API.md).

## 7. Retries and errors

**What to retry:**

- Retry `429` (wait for `Retry-After`), `5xx` and timeouts, with exponential backoff (1 s, 2 s, 4 s …
  up to 5 minutes, with jitter).
- Don't retry other `4xx` errors: fix the data, or ask HR to.
- `PUT` is safe to repeat. `POST` calls are safe with the same `Idempotency-Key`.

Every error has the same body, with a stable `code`:

```json
{"detail": "HRMS has no department 'Ops Dept'. Map it on the Mappings tab, then retry.",
 "code": "UNKNOWN_DEPARTMENT", "request_id": "req_…", "error": {…}}
```

| Code | Meaning | What to do |
|---|---|---|
| `INVALID_API_KEY`, `API_KEY_REVOKED`, `API_KEY_EXPIRED` | The key is wrong or no longer valid | Get a new key from the administrator |
| `WRONG_ENVIRONMENT` | A test key on production, or the reverse | Use the right key |
| `IP_NOT_ALLOWED` | Your server's address isn't on the key's list | Ask the administrator to add it |
| `APP_PAUSED` | The administrator paused your app | Wait; events keep queuing |
| `SCOPE_MISSING` | The key doesn't allow this call | Ask for the scope |
| `RATE_LIMITED` | Too many calls this minute | Wait for `Retry-After` |
| `UNKNOWN_LEGAL_ENTITY` (company), `UNKNOWN_DEPARTMENT`, `UNKNOWN_LOCATION`, `UNKNOWN_DESIGNATION` | A value HRMS doesn't know | Ask HR to map it, then retry |
| `AMBIGUOUS_…` | The value matches more than one record | Ask HR to map it |
| `MAPPING_OTHER_COMPANY_DEPARTMENT` (or `…_LOCATION`) | The value is mapped to another company's record | Ask HR to correct the mapping |
| `FIELD_REQUIRED` | A field needed to create or place someone is missing | Send it |
| `ROLE_NOT_ALLOWED` | Sync can only grant `EMPLOYEE` or `MANAGER` | HR grants other roles in HRMS |
| `POSSIBLE_DUPLICATE` | Looks like an unlinked HRMS employee | Retry after HR confirms or rejects the match |
| `EMAIL_IN_USE`, `MOBILE_IN_USE`, `EMPLOYEE_CODE_IN_USE` | Another employee already has it | Fix the data |
| `PRIVILEGED_ACCOUNT_PROTECTED` | The employee's login has HR or admin rights, so its password and sign-in details are changed only in HRMS | Leave those fields out |
| `ALREADY_LINKED` | That HRMS employee is linked to another of your IDs | Use the linked ID |
| `UNSUPPORTED_PASSWORD_HASH` | The hash isn't bcrypt | Send the plain password, or none |
| `OPERATION_NOT_ALLOWED` | The company makes this change in HRMS, not through your app | Leave it to HR |
| `COMPANY_CHANGE_NOT_SUPPORTED` | Moving between companies | Exit, then create a new employment with a new ID |
| `IDEMPOTENCY_KEY_REUSED` | The same key with a different body | Use a new key for a new action |
| `RESYNC_REQUIRED` (410) | Too far behind the events feed | Reload from `/employees`, then continue (§5) |
| `SESSION_REFUSED` | No active employee is linked to that ID | Check the ID and the employee's status |

Quote the `request_id` when you report a problem: HR sees every call in the app's sync log.
