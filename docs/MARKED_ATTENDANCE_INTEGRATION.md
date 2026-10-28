# Marked attendance from a third-party application

This guide is for a developer whose application needs to put marked attendance into HRMS. Marked
attendance is the present or absent days of people who don't punch, such as drivers, guards and
cleaners. Read [MARKED_ATTENDANCE.md](MARKED_ATTENDANCE.md) first for how marking works inside
HRMS, and [THIRD_PARTY_INTEGRATION_GUIDE.md](THIRD_PARTY_INTEGRATION_GUIDE.md) for API keys,
connected apps and the error format. This guide only adds what is specific to marking.

| You want to… | Section |
|---|---|
| Choose the right pattern | [1](#1-two-ways-to-integrate) |
| Know what works today | [2](#2-what-is-available-today) |
| Set it up | [3](#3-setup-who-does-what) |
| Mark days, record leave, read results | [4](#4-the-calls) to [7](#7-reading-results-back) |
| Push from a system that already has the attendance (transport platform) | [8](#8-pattern-a-sync-from-a-system-that-already-has-the-attendance) |
| Handle errors and retries | [9](#9-errors-retries-and-repeating-a-call) |
| Copy working code | [10](#10-example-client-python) |

---

## 1. Two ways to integrate

| | **A. Sync**: your system already has the attendance | **B. Marking screen**: your app is where supervisors mark |
|---|---|---|
| Example | The transport platform records driver attendance; HRMS should match it | A guard supervisor marks the guards in your mobile app instead of in HRMS |
| Who acts | A scheduled job on your server | A supervisor signed in to your app |
| HRMS records the mark as | Made by the **marker account** you send it as, source `INTEGRATION` | Made by **that supervisor**, source `INTEGRATION` |
| Sections | [8](#8-pattern-a-sync-from-a-system-that-already-has-the-attendance) | [4](#4-the-calls) to [7](#7-reading-results-back) |

Both patterns use the same HRMS calls, so the rules are the same as on the HRMS marking page.
Nobody marks their own day. Days can't be in the future or locked, can't already have the
person's own punches, and can't already be on approved leave. A save that breaks one rule saves
nothing.

## 2. What is available today

| Piece | Status |
|---|---|
| Marking API: `GET /v1/time/marking`, `PUT /v1/time/marking/{date}`, leave types, `POST /v1/time/marking/leave` | **Built.** Used by the HRMS marking page |
| Marks from a connected app recorded with source `INTEGRATION` | **Built** (`marking.py`) |
| Creating the people (drivers, guards…) as employees through the API (`employees.sync`) | **Built** ([guide §4](THIRD_PARTY_INTEGRATION_GUIDE.md#4-employees-both-directions)) |
| Reading the resulting days through the API (`attendance.read`) | **Built** ([§7](#7-reading-results-back)) |
| A connected-app session allowed to call the marking API | **Built**, behind the app setting **Mark attendance groups** (`self_service.marking`), **off by default** |
| Adding or removing group members, or giving View/Mark access, through the API | **Not planned.** HR does this in HRMS (Settings → Attendance groups) |
| Half-day marks without times | **Not built.** Send times, or record half-day leave |

While **Mark attendance groups** is off, an app's sessions get
`403 NOT_AVAILABLE_VIA_INTEGRATION` on every marking call. Don't work around it with stored HRMS
passwords ([guide §3.3](THIRD_PARTY_INTEGRATION_GUIDE.md#33-why-not-sign-in-as-the-employee)).

## 3. Setup: who does what

**HRMS administrator, once** (Settings → Integrations, [guide §2](THIRD_PARTY_INTEGRATION_GUIDE.md#2-setup-who-does-what)):

1. Connect the app as `TWO_WAY`. Only a two-way app may hold `sessions.issue`, which marking
   needs, even if your system doesn't create the employees.
2. Create an API key with these scopes:
   - `sessions.issue`, always;
   - `employees.read`, to map your IDs to HRMS employments;
   - `attendance.read`, to read days back;
   - `employees.sync`, if your system creates the people.
3. In the app's settings (Self-service through the app), switch on **Mark attendance groups**.
   It also covers recording leave for the group. Settings are per company, and two companies
   count:
   - the **marker's** company must have it on, or every marking call is refused;
   - the sheet then lists only people from companies that **the key covers and that have it
     on**. A group can mix companies, so a key limited to one company marks only that company's
     people. The others are left off the sheet, and marking them is refused like someone outside
     the group.

**HR, in HRMS** (Settings → Attendance groups):

4. Create the group (Drivers, Guards…), optionally for one company.
5. **Add people** from the date their days start being marked. Someone who punches can't also
   be marked on the same day. A person is in one group at a time.
6. **Who can view or mark**: give **Mark** on the group to every account that will mark through
   your app:
   - **Pattern B**: each supervisor;
   - **Pattern A**: one dedicated marker account, an employee such as the transport in-charge,
     linked to your system with an external ID. Their name is what HRMS shows as "marked by".

**You:**

7. Link every person who is marked, and every marker, to your own ID. Either create them with
   `employees.sync`, or link people who already exist
   ([guide §4.2](THIRD_PARTY_INTEGRATION_GUIDE.md#42-link-people-who-already-exist-in-both-systems-once-at-go-live)).
8. Keep a map from your ID to the HRMS `employment_id`, which you read with
   `GET /v1/integrations/employees/{external_id}`. The marking calls use `employment_id`.

## 4. The calls

All marking calls use the **marker's** session token, `Authorization: Bearer <token>`, never the
API key. Get the token from your server after the marker signed in to your app (Pattern B), or
for the marker account (Pattern A):

```bash
curl -X POST "$BASE/v1/integrations/sessions" -H "X-API-Key: $HRMS_KEY" \
  -H "Content-Type: application/json" -d '{"external_id": "SUP-0007"}'
# → {"access_token": "eyJ…", "expires_in": 3600, "employment_id": "emp_…", "roles": ["EMPLOYEE"]}
```

Cache the token per marker until it is close to `expires_in`. `GET /v1/auth/me` with that token
lists `attendance.view` / `attendance.mark` only when the marker has group access **and** the app
may mark for their company, so use it to decide whether to show your marking screen. The marker's rights come from the
**Mark/View access HR gave them on the group**, not from a role. A session from an app never
carries HR rights, so the token sees exactly the groups that account was given.

| Call | Does |
|---|---|
| `GET /v1/time/marking?work_date=YYYY-MM-DD[&group_id=…][&legal_entity_id=…]` | The day's sheet: everyone in the groups the marker can see |
| `PUT /v1/time/marking/{work_date}` | Mark, change or clear up to 500 people for that day, all or nothing |
| `GET /v1/time/marking/leave-types` | Leave types the marker can record |
| `POST /v1/time/marking/leave` | Record leave from one date to another for one person |

## 5. Reading the day's sheet

```bash
curl "$BASE/v1/time/marking?work_date=2026-10-27" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "work_date": "2026-10-27",
  "counts": {"PRESENT": 30, "NOT_MARKED": 5, "WEEKEND": 1},
  "rows": [
    {
      "employment_id": "emp_…", "employee_number": "DRV-0042", "name": "Jayram Kumar",
      "company": "SR Container Carriers", "department": "Transport",
      "group_id": "agrp_…", "group_name": "Drivers", "access": "MARK",
      "status": "NOT_MARKED", "is_off_day": false, "holiday_name": null, "leave_type": null,
      "has_punches": false, "punch_in": null, "punch_out": null,
      "worked_minutes": 0, "late_by_minutes": 0, "timezone": "Asia/Kolkata",
      "is_locked": false, "can_mark": true, "blocked_reason": null, "mark": null
    }
  ]
}
```

- `status` can be:
  - `PRESENT` or `ABSENT`: marked;
  - `NOT_MARKED`: a working day nobody marked. It is never counted as absent;
  - `ON_LEAVE`, `HOLIDAY`, `WEEKEND`, `UPCOMING`;
  - `OFF_DAY_WORKED`: marked present on a day off;
  - a punched day's own status.
- `can_mark: false` comes with `blocked_reason` (locked, has punches, on leave, view only…).
  Skip those rows rather than sending them.
- `mark` is the latest mark: who made it, when, its remark and `source` (`MANUAL` / `INTEGRATION`).
  Times entered through an app are kept as punches that also name the app.
- Only people **employed and in the group that day** are listed. Someone who left, or who joined
  later, is absent from the sheet, not marked absent.

## 6. Marking a day

```bash
curl -X PUT "$BASE/v1/time/marking/2026-10-27" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "remark": "From transport platform",
    "marks": [
      {"employment_id": "emp_A", "status": "PRESENT"},
      {"employment_id": "emp_B", "status": "PRESENT", "punch_in": "08:30", "punch_out": "19:15"},
      {"employment_id": "emp_C", "status": "PRESENT", "punch_in": "21:00", "punch_out": "06:00"},
      {"employment_id": "emp_D", "status": "ABSENT", "remark": "No show"},
      {"employment_id": "emp_E", "status": null}
    ]}'
```

```json
{"work_date": "2026-10-27", "changed": 4, "unchanged": 1, "rows": [ …the rows after saving… ]}
```

| Field | Rules |
|---|---|
| `marks` | 1–500 entries, each person once |
| `status` | `PRESENT`, `ABSENT`, or `null` to clear the mark (the day goes back to `NOT_MARKED`) |
| `punch_in`, `punch_out` | Optional, `"HH:MM"` on the **person's own clock** (the sheet's `timezone`, e.g. `Asia/Kolkata`), not UTC. Only with `PRESENT`. An out time needs an in time. An out time before the in time is the next morning (night shift). Equal times are refused. Neither may be later than now |
| `remark` | Up to 500 characters, per row or for all rows |

What HRMS does with it:

- **Without times**, the day is simply present or absent.
- **With times**, the times count like punches: worked hours, late, half day and overtime follow
  the person's attendance policy. The times are stored as punches with source `MARKED`, apart
  from the person's own punches.
- **Present on a weekly off or holiday** is off-day work. **Absent on a day off is refused**:
  leave those days out.
- **Sending the same thing again changes nothing**: the row counts as `unchanged` and no history
  is added. A `PUT` is safe to repeat.
- Every change is kept, append-only, with the marker, the time and `source: "INTEGRATION"`.

## 7. Reading results back

**Leave.** Recording leave puts an approved leave application through the leave engine. Type,
overlap, length and balance are all checked; use an unpaid type when the balance is short.

```bash
curl "$BASE/v1/time/marking/leave-types" -H "Authorization: Bearer $TOKEN"
curl -X POST "$BASE/v1/time/marking/leave" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "employment_id": "emp_D", "leave_type_id": "lt_…",
    "from_date": "2026-10-28", "to_date": "2026-10-30", "reason": "Village visit"}'
```

- Up to 93 days at a time. Half day (`"half_day_option": "FIRST_HALF"` / `"SECOND_HALF"`) only
  for one date.
- The marker needs Mark on the person's group on **every** day of the range.
- Absent marks inside the range are cleared, with a note. **Present marks block it**: clear
  them first.
- There is no idempotency key. After a timeout, check `GET /v1/time/marking?work_date=<from>`
  (the row shows `ON_LEAVE`) before sending again.
- Cancelling recorded leave is done by HR in HRMS (Leave).

**Attendance.** With the API key (`attendance.read`), the same days come back in the normal daily
feed, next to everyone who punches:

```bash
curl "$BASE/v1/integrations/attendance/daily?date=2026-10-27" -H "X-API-Key: $HRMS_KEY"
# → [{"employment_id": "emp_…", "external_id": "DRV-0042", "employee_code": "DRV-0042",
#     "date": "2026-10-27", "status": "PRESENT", "first_in": null, "last_out": null,
#     "worked_minutes": 0}, …]
```

A marked day reads like any other day, so payroll, reports and dashboards in HRMS need nothing
special. A person with no row on a working day has nothing recorded for it (`NOT_MARKED` on the
sheet).

## 8. Pattern A: sync from a system that already has the attendance

Example: the transport platform's driver attendance API (`GET …/transport/api/attendance`) is the
record. A job on **your** server copies it into HRMS. HRMS doesn't call the transport API itself;
a built-in pull is listed as not built in [MARKED_ATTENDANCE.md](MARKED_ATTENDANCE.md).

**Status mapping** (transport → HRMS):

| Transport `status` | Send to HRMS |
|---|---|
| `present` | `PRESENT`, with `punch_in`/`punch_out` if the record has times |
| `absent` | `ABSENT` |
| `leave` | A leave range via `POST /v1/time/marking/leave` (group consecutive days), or `ABSENT` with a remark if the company doesn't want leave balances used |
| `halfday-1st`, `halfday-2nd` | `PRESENT` with times, or half-day leave for that date (no half-day mark without times) |
| `holiday`, `weekoff` | **Nothing.** HRMS takes holidays and weekly offs from the person's calendar and policy. Absent on a day off is refused |

**The job, once a night and again for yesterday in the morning:**

1. Fetch the transport records for the date (or the last few days, to pick up late edits).
2. Translate each driver ID to an HRMS `employment_id` using the map from §3 step 8. Report
   unknown drivers; don't guess.
3. `GET /v1/time/marking?work_date=…` as the marker account. Keep the rows with
   `can_mark: true`, and leave out rows whose `status` and times already match.
4. `PUT /v1/time/marking/{date}` with the rest, at most 500 per call. Days are independent: one
   date's failure doesn't block the others.
5. On `422` the message names each refused person and why, and nothing for that date was saved.
   Drop or fix those rows and send the date again. Typical causes: the person left, a day off
   marked absent, a day already on leave.
6. Send `leave` ranges after the marks.
7. Log `changed` / `unchanged` per date. On a quiet re-run everything should be `unchanged`.

**Rules for the source of truth.** Choose one place where the days are marked. If supervisors also
mark in HRMS, the job overwrites their marks, because the latest mark wins and both are kept in
the history. Either have the job skip rows whose `mark.source` is `MANUAL`, or agree that HRMS is
read-only for those groups. Locked (closed) days can't be changed by either. A correction after
payroll closed the period goes to HR.

## 9. Errors, retries and repeating a call

The error body and codes follow [guide §12](THIRD_PARTY_INTEGRATION_GUIDE.md#12-errors-and-retries).
For marking:

| Status | Meaning | What to do |
|---|---|---|
| `401` | Session token expired or revoked, or the marker left | Get a new session; if refused, the marker is no longer active |
| `403 NOT_AVAILABLE_VIA_INTEGRATION` | **Mark attendance groups** is off for the marker's company | Ask the administrator |
| `403 "You can't mark attendance"` / `"You can't record leave"` | The marker has no Mark access on any group | HR gives Mark on the group |
| `422 "Nothing was saved. N row(s) can't be marked: …"` | One or more rows broke a rule. Up to 10 are named | Fix or drop those rows and resend the date |
| `422` naming a field | The body is wrong: time format, times without `PRESENT`, same person twice, more than 500 rows | Fix the request |
| `409 "… while you were marking. Reload."` | The day was locked, punched or put on leave between your read and your write | Read the sheet again and resend |
| `409` on leave | A day in the range is locked, has punches, or is marked present | Read the message; clear present marks first |
| `429`, `5xx`, timeout | Transient | Retry with backoff. `PUT /v1/time/marking/{date}` is safe to repeat; leave is not |

## 10. Example client (Python)

```python
import time
import requests

BASE = "https://hrmsapi.example.com"
KEY = "hrms_live_…"  # from your secret manager, never shipped to a browser or phone


class Hrms:
    def __init__(self, marker_external_id: str):
        self.marker = marker_external_id
        self.token, self.expires = None, 0.0

    def _session(self) -> str:
        if not self.token or time.time() > self.expires - 60:
            r = requests.post(f"{BASE}/v1/integrations/sessions", headers={"X-API-Key": KEY},
                              json={"external_id": self.marker}, timeout=30)
            r.raise_for_status()
            body = r.json()
            self.token, self.expires = body["access_token"], time.time() + body["expires_in"]
        return self.token

    def _call(self, method: str, path: str, **kw):
        for attempt in range(5):
            r = requests.request(method, f"{BASE}{path}", timeout=60,
                                 headers={"Authorization": f"Bearer {self._session()}"}, **kw)
            if r.status_code == 401:
                self.token = None
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            return r
        r.raise_for_status()
        return r

    def sheet(self, day: str) -> list[dict]:
        r = self._call("GET", "/v1/time/marking", params={"work_date": day})
        r.raise_for_status()
        return r.json()["rows"]

    def mark(self, day: str, wanted: dict[str, dict]) -> dict:
        """wanted: employment_id -> {"status": "PRESENT"/"ABSENT", "punch_in"?: "HH:MM", ...}"""
        rows = {row["employment_id"]: row for row in self.sheet(day)}
        marks = []
        for emp, entry in wanted.items():
            row = rows.get(emp)
            if row is None or not row["can_mark"]:
                print(f"{day} {emp}: skipped ({row and row['blocked_reason'] or 'not on the sheet'})")
                continue
            if entry["status"] == "ABSENT" and row["is_off_day"]:
                continue  # absent on a day off means nothing
            marks.append({"employment_id": emp, **entry})
        if not marks:
            return {"changed": 0, "unchanged": 0}
        result = {"changed": 0, "unchanged": 0}
        for i in range(0, len(marks), 500):
            r = self._call("PUT", f"/v1/time/marking/{day}",
                           json={"marks": marks[i:i + 500], "remark": "Synced from transport"})
            if r.status_code == 422:
                raise ValueError(f"{day}: {r.json()['detail']}")  # nothing saved for this batch
            r.raise_for_status()
            body = r.json()
            result["changed"] += body["changed"]
            result["unchanged"] += body["unchanged"]
        return result


hrms = Hrms(marker_external_id="TRANSPORT-INCHARGE")
print(hrms.mark("2026-10-27", {
    "emp_A": {"status": "PRESENT"},
    "emp_B": {"status": "PRESENT", "punch_in": "08:30", "punch_out": "19:15"},
    "emp_D": {"status": "ABSENT", "remark": "No show"},
}))
```

## 11. Go-live checklist

- [ ] Group created, people added from the right date, Mark given to the marker account(s).
- [ ] App connected as `TWO_WAY`; key with `sessions.issue`, `employees.read`,
      `attendance.read`; **Mark attendance groups** on; key limited to the right companies and IP
      addresses.
- [ ] Every marked person and marker linked to your ID; ID → `employment_id` map built.
- [ ] Status mapping agreed with HR. Holidays and weekly offs are not sent. One place marks.
- [ ] Tried end to end on the **testing** site with a test key; a second run reports only
      `unchanged`.
- [ ] HR has checked a week in the attendance register and the attendance report.
