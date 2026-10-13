# HRMS Employee Self-Service & Attendance Integration API Specification

This document provides complete, production-ready API documentation for integrating third-party applications (mobile apps, biometric kiosk systems, Slack/Teams bots, custom portals, or external ERPs) with the HRMS platform.

It covers:
1. **Authentication & Session Lifecycle**
2. **Live Attendance Punches (Punch In / Punch Out / Breaks)**
3. **Attendance Correction & Regularization Requests**
4. **Leave Management (Catalog, Balances, Application Draft & Submission, Cancellation)**
5. **Essential Employee Services (Profile, Holiday Calendar, Approval Inbox)**
6. **Standard Error Handling, Typed IDs, and Code Examples (cURL, Python, Node.js)**

---

## 1. Integration Fundamentals

### 1.1 Base URL & Environment
- **Local Development / Docker:** `http://127.0.0.1:8015`
- **Staging / Production:** `https://<hrms-api-domain>`
- **API Prefix:** All endpoints are versioned under `/v1`

### 1.2 Authentication Scheme
- **Mechanism:** HTTP Bearer token (JWT).
- **Header:** `Authorization: Bearer <access_token>`
- **Token Scope:** The JWT token encapsulates the user's tenant (`tenant_id`), account (`user_account_id`), and active employment (`employment_id`).
- **Acting Employee Resolution:**
  - When an employee calls self-service endpoints, omitting the `employment_id` query parameter defaults automatically to their own record.
  - When a third-party automated system or supervisor acts on behalf of an employee, pass `?employment_id=emp_...` (or `?employment-id=emp_...` on punch endpoints). This requires administrative permissions (e.g. `time.write`, `leave.write`).

### 1.3 Data Conventions & Formatting
- **Content-Type:** `application/json`
- **Dates:** ISO format `YYYY-MM-DD` (e.g., `2026-10-12`).
- **Date-Time / Instants:** ISO-8601 with timezone offset (e.g., `2026-10-12T09:30:00+05:30` or `2026-10-12T04:00:00Z`).
- **Typed IDs:** All exposed entity IDs use a type prefix (e.g., `emp_...` for employment, `punch_...` for attendance punches, `la_...` for leave applications, `lt_...` for leave types). Never parse or manipulate these strings.
- **Request Tracing:** Send or receive `X-Request-ID` in HTTP headers to correlate requests across systems.

---

## 2. Authentication & Identity

### 2.1 Sign In (Obtain Access Token)
Authenticates an employee or service account and yields a bearer token.

- **Method:** `POST`
- **Path:** `/v1/auth/login`
- **Authentication:** None (Public)

#### Request Body (`application/json`)
| Field | Type | Required | Description |
|---|---|---|---|
| `identifier` | string | Yes | Email address, employee code, or mobile number. (Legacy keys `email`, `username`, `phone`, `emp_id` also accepted). |
| `password` | string | Yes | Account password. |
| `tenant` | string | No | Tenant slug/code. Only required if the same employee code exists across multiple companies (returns `409 COMPANY_REQUIRED`). |
| `otp` | string | No | 6-digit TOTP code if MFA is enabled. |

#### Request Example
```bash
curl -X POST "http://127.0.0.1:8015/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "john.doe@company.com",
    "password": "SecurePassword123!"
  }'
```

#### Response Example (`200 OK`)
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "usr_01J9X1K8...",
    "email": "john.doe@company.com",
    "name": "John Doe",
    "employment_id": "emp_01J9X2M4...",
    "tenant_id": "ten_01J9W8P1...",
    "tenant_name": "Acme Group",
    "roles": ["EMPLOYEE"],
    "permissions": ["time.write", "leave.apply", "people.read"],
    "is_all_scope": false,
    "legal_entities": [
      {
        "id": "le_01J9W9A2...",
        "name": "Acme Technologies India Pvt Ltd"
      }
    ],
    "must_change_password": false,
    "mfa_required": false
  }
}
```

---

### 2.2 Get Current User Profile (`/v1/auth/me`)
Verify active session token and retrieve current permissions and company associations.

- **Method:** `GET`
- **Path:** `/v1/auth/me`
- **Authentication:** `Bearer <token>`

#### Response Example (`200 OK`)
Returns the `user` object shown above.

---

## 3. Live Attendance (Punch In / Punch Out)

### 3.1 Attendance Punch State Machine
The server enforces sequential state transitions for each business day:
```
[Start of Day] ──> IN ──> OUT ──> [Completed]
                    │       ▲
                    ▼       │
               BREAK_START  │
                    │       │
                    ▼       │
               BREAK_END ───┘
```
- Allowed transitions:
  - No prior punch today: `IN`
  - Previous was `IN`: `OUT` or `BREAK_START`
  - Previous was `BREAK_START`: `BREAK_END` or `OUT`
  - Previous was `BREAK_END`: `OUT` or `BREAK_START`
  - Previous was `OUT`: `IN` (re-entry)
- Any out-of-order punch returns `409 Conflict`. Use an **Attendance Correction** instead.

---

### 3.2 Record Live Punch
Captures a real-time attendance punch. The server stamps the punch with its current UTC clock timestamp.

> [!IMPORTANT]
> **Third-Party Integration Constraints:**
> - `source` must be either `"WEB"` or `"MOBILE"`.
> - Do **not** send `punched_at`. Historical or backdated punches are rejected with `422 Unprocessable Entity` (they must go through the Attendance Correction flow).
> - Long open sessions (>16 hours) will trigger a `409 LONG_DAY_CONFIRM` error to prevent accidental overnight overtime. Resend with `"confirm_long_day": true` if intentional.

- **Method:** `POST`
- **Path:** `/v1/time/punches`
- **Authentication:** `Bearer <token>`
- **Query Parameter (Optional):** `employment-id=emp_...` (Defaults to token's own employment).

#### Request Body (`application/json`)
| Field | Type | Required | Description |
|---|---|---|---|
| `punch_type` | string | Yes | `"IN"`, `"OUT"`, `"BREAK_START"`, or `"BREAK_END"`. |
| `source` | string | No | `"WEB"` or `"MOBILE"` (Default: `"WEB"`). |
| `latitude` | float | No | GPS latitude (e.g. `19.0760`). |
| `longitude` | float | No | GPS longitude (e.g. `72.8777`). |
| `device_id` | string | No | Mobile or hardware device identifier. |
| `confirm_long_day` | boolean | No | Default `false`. Set `true` if confirming a check-out after >16 hours. |

#### Request Example (Punch In)
```bash
curl -X POST "http://127.0.0.1:8015/v1/time/punches" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "punch_type": "IN",
    "source": "MOBILE",
    "latitude": 12.9716,
    "longitude": 77.5946,
    "device_id": "Pixel-8-Pro-Device-UUID"
  }'
```

#### Response Example (`201 Created`)
```json
{
  "id": "punch_01J9Y4D2...",
  "employment_id": "emp_01J9X2M4...",
  "punch_type": "IN",
  "punched_at": "2026-10-12T09:05:14.238192Z",
  "source": "MOBILE",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "is_corrected": false
}
```

#### Request Example (Punch Out)
```bash
curl -X POST "http://127.0.0.1:8015/v1/time/punches" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "punch_type": "OUT",
    "source": "MOBILE"
  }'
```

---

### 3.3 Get Today's Punch & Clock Status
Retrieves current attendance state for the employee's active shift/day, including timeline of all punches today and calculated effective minutes.

- **Method:** `GET`
- **Path:** `/v1/time/today`
- **Authentication:** `Bearer <token>`
- **Query Parameters:**
  - `employment_id` *(optional)*: Employee to query (defaults to caller).
  - `work_date` *(optional)*: Calendar date `YYYY-MM-DD` (defaults to current business day).

#### Response Example (`200 OK`)
```json
{
  "employment_id": "emp_01J9X2M4...",
  "work_date": "2026-10-12",
  "is_punched_in": true,
  "first_punch_in": "2026-10-12T09:05:14Z",
  "last_punch_out": null,
  "effective_minutes": 210,
  "status": "PRESENT",
  "punches": [
    {
      "id": "punch_01J9Y4D2...",
      "employment_id": "emp_01J9X2M4...",
      "punch_type": "IN",
      "punched_at": "2026-10-12T09:05:14Z",
      "source": "MOBILE",
      "latitude": 12.9716,
      "longitude": 77.5946,
      "is_corrected": false
    }
  ]
}
```

---

### 3.4 Get Attendance History / Daily Logs
Fetches calculated attendance records (status, working minutes, overtime, lateness) over a date range.

- **Method:** `GET`
- **Path:** `/v1/time/attendance-days`
- **Authentication:** `Bearer <token>`
- **Query Parameters:**
  - `from_date` *(required)*: `YYYY-MM-DD`
  - `to_date` *(required)*: `YYYY-MM-DD`
  - `employment_id` *(optional)*: Target employee (defaults to caller).

#### Response Example (`200 OK`)
```json
[
  {
    "id": "ad_01J9X9M1...",
    "employment_id": "emp_01J9X2M4...",
    "work_date": "2026-10-11",
    "first_punch_in": "2026-10-11T09:02:00Z",
    "last_punch_out": "2026-10-11T18:05:00Z",
    "effective_minutes": 512,
    "late_by_minutes": 0,
    "early_departure_minutes": 0,
    "status": "PRESENT",
    "is_locked": false,
    "ot_minutes": 32,
    "ot_status": "NONE",
    "comp_off_days": 0.0,
    "review_flags": [],
    "needs_review": false
  }
]
```
*Possible `status` values:* `PRESENT`, `ABSENT`, `HALF_DAY`, `LATE`, `EARLY_DEPARTURE`, `ON_LEAVE`, `HOLIDAY`, `WEEKEND`, `PENDING`, `MISSED_PUNCH`, `OFF_DAY_WORKED`.

---

## 4. Attendance Corrections & Regularization

When an employee forgets to punch in/out, biometric hardware fails, or attendance must be regularized, the employee submits an Attendance Correction request.

### 4.1 Correction Types & Requirements
| Correction Type (`correction_type`) | Required Fields | Use Case |
|---|---|---|
| `PUNCH_IN` | `requested_punch_in` | Missing check-in |
| `PUNCH_OUT` | `requested_punch_out` | Missing check-out |
| `MISSED_PUNCH` | `requested_punch_in` or `requested_punch_out` | Either missing event |
| `REGULARIZE` | `requested_punch_in` AND `requested_punch_out` | Replace entire day's punches |
| `MARK_PRESENT` | `requested_punch_in` AND `requested_punch_out` | Mark present for missed day |
| `MARK_ABSENT` | None (punches ignored) | Mark as absent |
| `LATE_REASON` | Reason only | Justify lateness |
| `EARLY_DEPARTURE_REASON` | Reason only | Justify early exit |

> [!NOTE]
> All requested punch timestamps **MUST include the timezone offset** (e.g. `+05:30`).

---

### 4.2 Submit a Correction Request
- **Method:** `POST`
- **Path:** `/v1/corrections`
- **Authentication:** `Bearer <token>`
- **Query Parameter (Optional):** `employment_id=emp_...` (defaults to caller).

#### Request Body (`application/json`)
```json
{
  "work_date": "2026-10-10",
  "correction_type": "REGULARIZE",
  "requested_punch_in": "2026-10-10T09:15:00+05:30",
  "requested_punch_out": "2026-10-10T18:30:00+05:30",
  "reason": "Biometric terminal was offline during morning check-in."
}
```

#### Response Example (`201 Created`)
```json
{
  "id": "cor_01J9Y7R1...",
  "employment_id": "emp_01J9X2M4...",
  "work_date": "2026-10-10",
  "correction_type": "REGULARIZE",
  "requested_punch_in": "2026-10-10T03:45:00Z",
  "requested_punch_out": "2026-10-10T13:00:00Z",
  "reason": "Biometric terminal was offline during morning check-in.",
  "status": "PENDING_L1",
  "current_level": 1,
  "total_levels": 1,
  "submitted_at": "2026-10-12T10:15:00Z",
  "approval_history": []
}
```
*Statuses:* `DRAFT`, `PENDING_L1`, `PENDING_L2`, `APPROVED`, `REJECTED`, `CANCELLED`.

---

### 4.3 List Correction Requests
Fetches correction requests raised by the employee (or subordinates if manager).

- **Method:** `GET`
- **Path:** `/v1/corrections`
- **Authentication:** `Bearer <token>`
- **Query Parameters:**
  - `employment_id` *(optional)*: Filter by employee.
  - `status` *(optional)*: Filter by status (e.g. `PENDING_L1`, `APPROVED`).

---

### 4.4 Cancel a Pending Correction Request
Withdraws a pending correction before manager review.

- **Method:** `POST`
- **Path:** `/v1/corrections/{correction_id}/cancel`
- **Authentication:** `Bearer <token>`

#### Response Example (`200 OK`)
Returns the updated `CorrectionResponse` with `"status": "CANCELLED"`.

---

### 4.5 Manager Approvals (For Manager Apps & Workflows)
- **Approve:** `POST /v1/corrections/{correction_id}/approve`
  ```json
  {
    "action": "APPROVE",
    "comments": "Verified with team lead."
  }
  ```
- **Reject:** `POST /v1/corrections/{correction_id}/reject`
  ```json
  {
    "action": "REJECT",
    "comments": "Punch times do not match client logs."
  }
  ```

---

## 5. Leave Management

### 5.1 Leave Workflow Lifecycle
```
[1. Get Catalog]       GET /v1/leave/types
       │
[2. Check Balance]     GET /v1/leave/balances
       │
[3. Create Draft]      POST /v1/leave/applications  ──> Status: DRAFT
       │
[4. Submit for Review] POST /v1/leave/applications/{id}/submit  ──> Status: PENDING_L1 (Balance held)
       │
       ├──> [Approved] Status: APPROVED (Balance deducted)
       └──> [Rejected] Status: REJECTED (Held balance released)
```

---

### 5.2 List Active Leave Types
Returns the catalog of available leave types (Casual Leave, Sick Leave, Earned Leave, Comp-off) and policy limits.

- **Method:** `GET`
- **Path:** `/v1/leave/types`
- **Authentication:** `Bearer <token>`

#### Response Example (`200 OK`)
```json
[
  {
    "id": "lt_01J9V1C2...",
    "name": "Casual Leave",
    "code": "CL",
    "days_per_year": 12.0,
    "carry_forward": false,
    "max_carry_forward_days": null,
    "requires_approval": true,
    "approval_levels": 1,
    "min_days_per_application": 0.5,
    "max_days_per_application": 3.0,
    "advance_notice_days": 2,
    "requires_document": false,
    "is_paid": true,
    "color": "#3B82F6",
    "is_comp_off": false,
    "is_active": true
  },
  {
    "id": "lt_01J9V1S8...",
    "name": "Sick Leave",
    "code": "SL",
    "days_per_year": 10.0,
    "carry_forward": true,
    "requires_approval": true,
    "requires_document": true,
    "is_paid": true,
    "color": "#EF4444",
    "is_active": true
  }
]
```

---

### 5.3 Get Leave Balances
Returns current financial year balance quotas, days used, pending holds, and available days.

- **Method:** `GET`
- **Path:** `/v1/leave/balances`
- **Authentication:** `Bearer <token>`
- **Query Parameters:**
  - `employment_id` *(optional)*: Employee to query (defaults to caller).
  - `year` *(optional)*: Financial year start year (e.g. `2026` for FY 2026-27). Defaults to current FY.

#### Response Example (`200 OK`)
```json
[
  {
    "id": "lb_01J9W2A1...",
    "employment_id": "emp_01J9X2M4...",
    "leave_type_id": "lt_01J9V1C2...",
    "leave_type_name": "Casual Leave",
    "leave_type_code": "CL",
    "year": 2026,
    "allocated_days": 12.0,
    "carry_forward_days": 0.0,
    "used_days": 2.0,
    "pending_days": 1.0,
    "available_days": 9.0,
    "color": "#3B82F6"
  }
]
```

---

### 5.4 Apply for Leave (Step 1: Create Draft Application)
Creates a leave application in `DRAFT` status. The system validates:
- Non-working days and holidays are automatically excluded from `days_requested`.
- Notice period and max/min limits according to leave type rules.
- Overlapping active leaves.

- **Method:** `POST`
- **Path:** `/v1/leave/applications`
- **Authentication:** `Bearer <token>`
- **Query Parameter (Optional):** `employment_id=emp_...`

#### Request Body (`application/json`)
| Field | Type | Required | Description |
|---|---|---|---|
| `leave_type_id` | string | Yes | Typed ID from `GET /v1/leave/types`. |
| `from_date` | string | Yes | Start date `YYYY-MM-DD`. |
| `to_date` | string | Yes | End date `YYYY-MM-DD`. |
| `half_day_option` | string | No | `"NONE"`, `"FIRST_HALF"`, or `"SECOND_HALF"` (Default: `"NONE"`). |
| `reason` | string | No | Reason for leave. |
| `document_id` | string | No | KYC/medical certificate attachment UUID (if required). |

```json
{
  "leave_type_id": "lt_01J9V1C2...",
  "from_date": "2026-10-20",
  "to_date": "2026-10-21",
  "half_day_option": "NONE",
  "reason": "Personal family event"
}
```

#### Response Example (`201 Created`)
```json
{
  "id": "la_01J9Z5K9...",
  "employment_id": "emp_01J9X2M4...",
  "leave_type_id": "lt_01J9V1C2...",
  "leave_type_name": "Casual Leave",
  "leave_type_code": "CL",
  "leave_type_color": "#3B82F6",
  "from_date": "2026-10-20",
  "to_date": "2026-10-21",
  "days_requested": 2.0,
  "half_day_option": "NONE",
  "reason": "Personal family event",
  "status": "DRAFT",
  "current_level": 0,
  "total_levels": 1,
  "applied_at": null,
  "cancel_reason": null,
  "approval_history": []
}
```

---

### 5.5 Submit Leave Application (Step 2: Send for Approval)
Submits the `DRAFT` application into the approval flow. This places a **hold** on the employee's available balance and advances the status to `PENDING_L1` (or `APPROVED` if auto-approved).

- **Method:** `POST`
- **Path:** `/v1/leave/applications/{app_id}/submit`
- **Authentication:** `Bearer <token>`

#### Response Example (`200 OK`)
```json
{
  "id": "la_01J9Z5K9...",
  "employment_id": "emp_01J9X2M4...",
  "status": "PENDING_L1",
  "current_level": 1,
  "total_levels": 1,
  "applied_at": "2026-10-12T10:25:31Z",
  "days_requested": 2.0
}
```

---

### 5.6 List Leave Applications
Retrieves past and current leave applications.

- **Method:** `GET`
- **Path:** `/v1/leave/applications`
- **Authentication:** `Bearer <token>`
- **Query Parameters:**
  - `employment_id` *(optional)*: Filter by employee.
  - `status` *(optional)*: Filter by status (e.g. `APPROVED`, `PENDING_L1,PENDING_L2`).
  - `limit` *(optional)*: Page size (1 to 200, default 100).
  - `after` *(optional)*: Keyset cursor (pass `id` of last item).

---

### 5.7 Cancel a Leave Application
Cancels an application.
- If `DRAFT` or pending approval: Cancelled immediately and held balance is released.
- If `APPROVED`: If policy requires cancellation approval, moves to `CANCEL_PENDING_L1`; otherwise cancelled and days refunded immediately.

- **Method:** `POST`
- **Path:** `/v1/leave/applications/{app_id}/cancel`
- **Authentication:** `Bearer <token>`

#### Request Body (`application/json`)
```json
{
  "cancel_reason": "Change of travel plans."
}
```

---

## 6. Additional Employee Services

### 6.1 Tenant Holiday Calendar
List declared company holidays for the current year.

- **Method:** `GET`
- **Path:** `/v1/time/holidays`
- **Authentication:** `Bearer <token>`
- **Query Parameter:** `year=2026` *(optional)*

#### Response Example (`200 OK`)
```json
[
  {
    "id": "hday_01J9...",
    "holiday_date": "2026-10-24",
    "name": "Diwali",
    "is_optional": false,
    "calendar_name": "Standard India Holidays"
  },
  {
    "id": "hday_01J9...",
    "holiday_date": "2026-12-25",
    "name": "Christmas",
    "is_optional": false,
    "calendar_name": "Standard India Holidays"
  }
]
```

---

### 6.2 View Personal Profile (`/v1/persons/me`)
Retrieve current employee profile details.

- **Method:** `GET`
- **Path:** `/v1/persons/me`
- **Authentication:** `Bearer <token>`

#### Response Example (`200 OK`)
```json
{
  "id": "per_01J9X1N8...",
  "legal_first_name": "John",
  "legal_last_name": "Doe",
  "preferred_name": "Johnny",
  "date_of_birth": "1994-05-18",
  "gender": "MALE",
  "nationality": "IN",
  "email": "john.doe@company.com",
  "mobile": "+919876543210",
  "version": 1
}
```

---

### 6.3 Update Personal Profile
Update self-service personal fields (e.g., preferred name, mobile number).

- **Method:** `PATCH`
- **Path:** `/v1/persons/me`
- **Authentication:** `Bearer <token>`

#### Request Body (`application/json`)
```json
{
  "preferred_name": "Johnny",
  "mobile": "+919812345678"
}
```

---

### 6.4 Approvals Inbox
Returns approval tasks pending the caller's action or raised by the caller.

- **Method:** `GET`
- **Path:** `/v1/approvals/inbox`
- **Authentication:** `Bearer <token>`

---

## 7. Standard Error Responses

All API errors return a standard envelope format:

```json
{
  "detail": "Invalid punch sequence; use a correction for missing events",
  "code": "INVALID_PUNCH_SEQUENCE",
  "request_id": "req_01J9ABC...",
  "error": {
    "code": "INVALID_PUNCH_SEQUENCE",
    "message": "Invalid punch sequence; use a correction for missing events",
    "details": [],
    "request_id": "req_01J9ABC...",
    "timestamp": "2026-10-12T10:30:00Z"
  }
}
```

### Common HTTP Status Codes & Error Codes
| HTTP Status | Error Code | Explanation |
|---|---|---|
| `400 Bad Request` | `BAD_REQUEST` | Action invalid for current entity status (e.g. submitting already submitted leave). |
| `401 Unauthorized` | `UNAUTHORIZED` | Token missing, expired, or invalid. |
| `401 Unauthorized` | `MFA_REQUIRED` | Two-factor sign-in required. Pass `otp` with login. |
| `403 Forbidden` | `FORBIDDEN` | Missing permission or outside employee's access scope. |
| `403 Forbidden` | `PASSWORD_CHANGE_REQUIRED` | Temporary password must be changed via `/v1/auth/change-password`. |
| `404 Not Found` | `NOT_FOUND` | Resource does not exist or outside visible scope. |
| `409 Conflict` | `COMPANY_REQUIRED` | Sign-in identifier belongs to multiple tenants. Pass `tenant` slug. |
| `409 Conflict` | `LONG_DAY_CONFIRM` | Punch out after >16 hrs. Resend with `"confirm_long_day": true`. |
| `409 Conflict` | `RESOURCE_CONFLICT` | Overlapping leave application or conflicting punch state. |
| `422 Unprocessable`| `VALIDATION_ERROR` | Schema validation error (e.g. invalid date, bare timestamp lacking timezone offset). |
| `429 Too Many Req`| `RATE_LIMITED` | Throttled. Inspect `Retry-After` header for seconds to wait. |

---

## 8. Integration Code Examples

### 8.1 Python Integration Client
```python
import os
import requests

BASE_URL = os.getenv("HRMS_API_URL", "http://127.0.0.1:8015")

class HRMSClient:
    def __init__(self, identifier: str, password: str, tenant: str | None = None):
        self.session = requests.Session()
        self.token = self._login(identifier, password, tenant)
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        })

    def _login(self, identifier: str, password: str, tenant: str | None) -> str:
        payload = {"identifier": identifier, "password": password}
        if tenant:
            payload["tenant"] = tenant
        res = requests.post(f"{BASE_URL}/v1/auth/login", json=payload)
        res.raise_for_status()
        return res.json()["access_token"]

    def punch_in(self, lat: float | None = None, lon: float | None = None):
        payload = {"punch_type": "IN", "source": "MOBILE"}
        if lat and lon:
            payload["latitude"] = lat
            payload["longitude"] = lon
        res = self.session.post(f"{BASE_URL}/v1/time/punches", json=payload)
        res.raise_for_status()
        return res.json()

    def punch_out(self, confirm_long_day: bool = False):
        payload = {
            "punch_type": "OUT",
            "source": "MOBILE",
            "confirm_long_day": confirm_long_day
        }
        res = self.session.post(f"{BASE_URL}/v1/time/punches", json=payload)
        res.raise_for_status()
        return res.json()

    def apply_leave(self, leave_type_id: str, from_date: str, to_date: str, reason: str):
        # 1. Create draft
        draft_res = self.session.post(f"{BASE_URL}/v1/leave/applications", json={
            "leave_type_id": leave_type_id,
            "from_date": from_date,
            "to_date": to_date,
            "reason": reason
        })
        draft_res.raise_for_status()
        app_id = draft_res.json()["id"]

        # 2. Submit for approval
        sub_res = self.session.post(f"{BASE_URL}/v1/leave/applications/{app_id}/submit")
        sub_res.raise_for_status()
        return sub_res.json()

    def request_attendance_correction(self, work_date: str, punch_in: str, punch_out: str, reason: str):
        res = self.session.post(f"{BASE_URL}/v1/corrections", json={
            "work_date": work_date,
            "correction_type": "REGULARIZE",
            "requested_punch_in": punch_in,
            "requested_punch_out": punch_out,
            "reason": reason
        })
        res.raise_for_status()
        return res.json()

# Usage Example:
# client = HRMSClient("john.doe@company.com", "MyPassword123")
# client.punch_in(lat=12.9716, lon=77.5946)
```

---

### 8.2 Node.js / TypeScript Integration Client
```typescript
interface LoginResponse {
  access_token: string;
  user: {
    employment_id: string;
    email: string;
  };
}

export class HRMSIntegration {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl = 'http://127.0.0.1:8015') {
    this.baseUrl = baseUrl;
  }

  async login(identifier: string, password: string, tenant?: string): Promise<string> {
    const res = await fetch(`${this.baseUrl}/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier, password, tenant })
    });
    if (!res.ok) throw new Error(`Login failed: ${await res.text()}`);
    const data = (await res.json()) as LoginResponse;
    this.token = data.access_token;
    return this.token;
  }

  private authHeaders(): HeadersInit {
    if (!this.token) throw new Error('Not authenticated. Call login() first.');
    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json'
    };
  }

  // Punch In / Out
  async recordPunch(punchType: 'IN' | 'OUT' | 'BREAK_START' | 'BREAK_END', lat?: number, lon?: number) {
    const res = await fetch(`${this.baseUrl}/v1/time/punches`, {
      method: 'POST',
      headers: this.authHeaders(),
      body: JSON.stringify({
        punch_type: punchType,
        source: 'MOBILE',
        latitude: lat,
        longitude: lon
      })
    });
    if (!res.ok) throw new Error(`Punch failed: ${await res.text()}`);
    return res.json();
  }

  // Regularize Attendance / Correction
  async submitCorrection(workDate: string, inIsoWithTz: string, outIsoWithTz: string, reason: string) {
    const res = await fetch(`${this.baseUrl}/v1/corrections`, {
      method: 'POST',
      headers: this.authHeaders(),
      body: JSON.stringify({
        work_date: workDate,
        correction_type: 'REGULARIZE',
        requested_punch_in: inIsoWithTz,
        requested_punch_out: outIsoWithTz,
        reason
      })
    });
    if (!res.ok) throw new Error(`Correction failed: ${await res.text()}`);
    return res.json();
  }

  // Apply Leave (Draft + Submit)
  async applyLeave(leaveTypeId: string, fromDate: string, toDate: string, reason: string) {
    // 1. Create Draft
    const draftRes = await fetch(`${this.baseUrl}/v1/leave/applications`, {
      method: 'POST',
      headers: this.authHeaders(),
      body: JSON.stringify({
        leave_type_id: leaveTypeId,
        from_date: fromDate,
        to_date: toDate,
        reason
      })
    });
    if (!draftRes.ok) throw new Error(`Create leave draft failed: ${await draftRes.text()}`);
    const draft = await draftRes.json();

    // 2. Submit Draft
    const submitRes = await fetch(`${this.baseUrl}/v1/leave/applications/${draft.id}/submit`, {
      method: 'POST',
      headers: this.authHeaders()
    });
    if (!submitRes.ok) throw new Error(`Submit leave failed: ${await submitRes.text()}`);
    return submitRes.json();
  }
}
```
