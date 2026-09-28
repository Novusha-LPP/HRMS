# HRMS Platform — Runbook

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | [python.org](https://python.org) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |
| Docker + Docker Compose | latest | [docker.com](https://docker.com) |
| PostgreSQL 16 | via Docker | included in `docker-compose.yml` |

---

## Quick Start (day-to-day — DB already provisioned)

Two terminals, no Docker rebuild needed once `db` has run once:

```bash
# Terminal 1 — backend
docker compose up -d db          # skip if Postgres is already running
cd backend && uv run uvicorn hrms.main:app --reload --port 8015

# Terminal 2 — frontend
cd frontend && npm run dev
```

App: http://localhost:5173 · API/Swagger: http://localhost:8015/docs

Sign in with your company account on the login page. A platform admin
(`/platform/login`) creates tenants — seed the first one with
`cd backend && uv run python scripts/seed_platform_admin.py`. To get the
throwaway SFPL Group demo data back for development, run
`uv run python scripts/seed_demo.py` (demo accounts use password `Passw0rd!`;
the login page no longer has one-click tiles for them — type the email in).

---

## Option A — Full Docker (recommended for first run)

Starts PostgreSQL + FastAPI API in containers. Frontend runs locally for hot-reload.

`alembic/` is baked into the `api` image at build time (only `backend/src`
is live-mounted), so after pulling new migration files you must rebuild
before applying them — otherwise you'll hit `Can't locate revision
identified by '000X'` because the container is still running old versions:

```bash
# 1. Start the database + API (add --build if migrations changed since your last build)
docker compose up -d --build

# 2. Run migrations inside the API container
docker compose exec api alembic upgrade head

# 3. Seed a demo tenant (SFPL Group + sister companies + demo logins — see below)
cd backend && uv run python scripts/seed_demo.py

# 4. Start the frontend (separate terminal)
cd frontend
npm install
npm run dev
```

App: http://localhost:5173  
API docs: http://localhost:8015/docs

---

## Option B — Local Development (no Docker)

### 1. Start PostgreSQL

Use Docker for just the database:

```bash
docker compose up -d db
```

Or point to any PostgreSQL 16 instance and update `HRMS_DATABASE_URL` below.

### 2. Backend setup

```bash
cd backend

# Install dependencies with uv
uv sync
```

Config is loaded from `backend/.env` (pydantic-settings, `env_file=".env"` —
**not** `.env.local`, so don't bother copying it; edit `.env` in place). It
already exists with working local defaults:

```env
# Superuser — migrations only, never used by the running app
HRMS_DATABASE_URL=postgresql+asyncpg://hrms:hrms@localhost:5432/hrms
# Restricted role the app actually connects as (created by migration 0005),
# so PostgreSQL row-level security is a real enforcement layer, not just the
# application's own WHERE tenant_id = ... filters.
HRMS_APP_DATABASE_URL=postgresql+asyncpg://hrms_app:hrms_app_dev_password@localhost:5432/hrms
HRMS_SECRET_KEY=dev-secret-change-before-production
HRMS_DEBUG=true
HRMS_ENVIRONMENT=development
HRMS_CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

`backend/.env.example` documents every var if you need to recreate it.

```bash
# Apply all migrations (creates the hrms_app role + login_lookup() function)
uv run alembic upgrade head

# Seed a demo tenant: SFPL Group with sister companies SRCC, Novusha and
# Alluvium IoT Solutions, and 7 logins covering every scope pattern
# (group admin, group HR, a regional HR scoped to 2 companies, a shared
# accountant scoped to 2 companies, a manager, and two plain employees in
# different companies). Prints the login table when done.
uv run python scripts/seed_demo.py

# Start the API server
uv run uvicorn hrms.main:app --reload --port 8015
```

API: http://localhost:8015  
Swagger: http://localhost:8015/docs

### 3. Frontend setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

App: http://localhost:5173

---

## Database Migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Check current revision
uv run alembic current

# Roll back one revision
uv run alembic downgrade -1

# Generate a new migration after model changes
uv run alembic revision --autogenerate -m "describe_the_change"
```

Migration files are in `backend/alembic/versions/`:

| File | What it creates |
|------|-----------------|
| `0001_initial_schema.py` | Tenants, employees, employment |
| `0002_time_onboarding_reports.py` | Attendance, onboarding, reports |
| `0003_policy_leave_corrections.py` | Policies, leave, corrections |
| `0004_auth_and_scoping.py` | Password login columns on `user_accounts`, indexes for scope resolution |
| `0005_app_role_rls_enforcement.py` | The `hrms_app` restricted role + `login_lookup()` function |

---

## Authentication

There's no more "pick a role" fake login. Every request carries a signed JWT
(`Authorization: Bearer …`) obtained from `POST /v1/auth/login`, and the
backend derives tenant + identity + scope entirely from that token — nothing
is trusted from a header or query parameter. See
`backend/src/hrms/core/authn.py` and `core/authz.py`.

### First-time tenant & data setup

Don't hand-create a tenant through the API — use the seed script, which
builds a complete, realistic multi-company tenant in one shot:

```bash
cd backend && uv run python scripts/seed_demo.py
```

This creates tenant **SFPL Group** with four legal entities (SFPL, SRCC,
Novusha, Alluvium IoT Solutions), departments, jobs, and 7 logins that each
demonstrate a different access-scope pattern — a platform admin, a group-wide
HR manager, an HR manager scoped to just two companies, a shared accountant
scoped to two companies, a manager with direct reports, and two plain
employees in different companies. Every account's password is `Passw0rd!`;
the script prints the full table on completion.

Re-run the script any time to reset the demo tenant back to this clean state
— it wipes and recreates everything for that tenant id.

### Roles and scope

Authorization lives in `backend/src/hrms/core/authz.py`. A `role_assignment`
grants a role (`SUPER_ADMIN`, `HR_MANAGER`, `MANAGER`, `EMPLOYEE`,
`ACCOUNTANT` — see `ROLE_PERMISSIONS`) with a `scope_type`:

| scope_type | Means |
|---|---|
| `ALL` | Every legal entity in the tenant |
| `LEGAL_ENTITY` | A specific set of companies (`scope_value` = JSON array of typed ids) |
| `ORG_UNIT` | A department and everything under it, resolved to its legal entities |
| `SELF` | Only the caller's own employment |
| `DIRECT_REPORTS` / `ALL_REPORTS` | The caller plus their reporting chain |

A user can hold several grants; effective access is their union. See
`scripts/seed_demo.py` for worked examples of each pattern, including the
"one employment, visibility into two companies" shared-accountant case.

---

## Org & Employee Onboarding (via the UI)

No API calls needed for day-to-day HR setup — it's all in the app now:

| Task | Where |
|---|---|
| Onboard a new company (legal entity) | Settings → Organization → Companies tab → "Add company" (requires all-scope, e.g. Super Admin) |
| Give that company a login with full access | Settings → Organization → **Users & access** tab → "Add user" — pick a role and tick the company/companies to grant it in |
| Add a department, location, or job title | Settings → Organization → Departments / Locations / Job titles tabs |
| Onboard a new employee | Workforce → Employees → "Add employee" — capturing company, department, designation, location and manager in one form places them immediately (fires a `HIRE` personnel action) and starts their onboarding checklist |
| Move an employee to a different department/designation/location/manager | Open the employee → "Transfer / change department" — prefilled with their current assignment; any field left unchanged carries forward (fires a `TRANSFER` personnel action) |

Under the hood every placement/move goes through `PersonnelAction` →
`_apply_personnel_action` (`backend/src/hrms/modules/people/router.py`), the
single write path for employment changes, scope-checked per company so a
company-scoped HR manager can't place or move someone outside their
companies.

**Granting access** (`POST /v1/users`, `backend/src/hrms/modules/kernel/users/router.py`)
has two built-in escalation guards, since granting a login is granting
authority, not just data:
- You can only grant access to companies already inside your own scope
  (checked via `scope.covers_entity`) — a company-scoped HR manager can't
  reach into a company they don't administer.
- You can only grant a role whose permissions are a subset of your own — an
  `HR_MANAGER` (no `"*"`) can never mint a `SUPER_ADMIN` account, for
  themselves or anyone else.

Only roles with `iam.write` (`SUPER_ADMIN`, `HR_MANAGER`) see the "Add user"
button at all; `GET /v1/users` is filtered the same way so a company-scoped
viewer only ever sees logins for companies they can see.

---

## Multi-Tenant vs Multi-Company — two different things

This platform has two distinct ways a "new company" gets added, and mixing
them up breaks the isolation model:

| | Sister company (legal entity) | Brand-new tenant |
|---|---|---|
| Example | SRCC under SFPL Group | An unrelated customer, e.g. Meridian Health |
| How | Signed-in admin → Organization → "Add company" | Public — no login — `/register` page or `POST /v1/auth/register-company` |
| Who can see it | Anyone granted access within the SFPL Group tenant (per their scope) | Nobody outside its own tenant, ever — not even SFPL's own SUPER_ADMIN |
| Shares roles/departments with SFPL Group? | Yes — same tenant, same `roles` table, same Organization page | No — gets its own five system roles, its own first legal entity, its own everything |

`POST /v1/auth/register-company` (`backend/src/hrms/modules/kernel/auth/router.py`)
runs on the same tenant-free anonymous session as login — there's no
existing tenant to bind to. It creates the `tenants` row, bootstraps the
five system roles (`SUPER_ADMIN`, `HR_MANAGER`, `MANAGER`, `EMPLOYEE`,
`ACCOUNTANT` — see `ROLE_DESCRIPTIONS` in `core/authz.py`), the company's
first legal entity, and a `SUPER_ADMIN` login — then signs that admin in
immediately (same `LoginResponse` shape as `/v1/auth/login`). Email must be
globally unique across every tenant (checked via the same `login_lookup()`
SECURITY DEFINER function login uses), since login resolves tenant purely
from email with no other hint.

### The Platform Console — a role above every tenant

Every `SUPER_ADMIN` above is still a `role_assignment` bound to ONE tenant —
its JWT carries that tenant's id, RLS enforces the boundary, and it can
never reach a second tenant no matter what permission it holds. Managing
the whole platform (list every tenant, register a company as a brand-new
tenant OR link it as a subsidiary of an existing one) needs a role above
that model entirely, so it's a fully separate mechanism:

- **`platform_admins`** (migration `0006`) — its own table, no `tenant_id`
  column, no RLS (same reasoning as `tenants` itself: it's part of the root
  of the isolation boundary, not a tenant living inside it).
- **A distinct JWT type** (`PLATFORM_TOKEN_TYPE` in `core/security.py`) — a
  platform token has no `tenant_id` claim at all and is rejected outright by
  every tenant-scoped endpoint, and a tenant token is equally rejected by
  every `/v1/platform/*` endpoint. Verified: cross-using either token the
  wrong way returns 401.
- **Bootstrap** (no self-serve signup — there's no chicken to lay this egg):
  ```bash
  cd backend && uv run python scripts/seed_platform_admin.py [email] [password] [name]
  # defaults to platform@hrms.internal / Passw0rd! if you pass nothing
  ```
- **Console**: sign in at `/platform/login`, lands on `/platform` with a
  sidebar across four sections. Same design system and light/dark/system
  theme as the tenant app (shared `ThemeContext`/`hrms_theme`, toggle lives
  in the sidebar footer) — built on the same `.card`/`.btn-*`/`.tbl`/
  `.badge-*`/`Sheet` components, not a bespoke one-off style:
  - **Overview** — tenant/company counts, active/suspended/archived, plan
    breakdown.
  - **Tenants** — searchable, paginated table (`GET /v1/platform/tenants?q=&limit=&offset=`).
    "Add company" lets you choose **Independent** (new tenant, own first
    admin — same code path as `/register`, via the shared
    `bootstrap_tenant()` helper in `core/tenant_provisioning.py`) or
    **Subsidiary** (pick an existing tenant from a dropdown; becomes a
    legal entity inside it immediately — that tenant's own admins see it
    appear with no further action). Clicking a row opens a detail drawer
    showing employee + company counts, plan (`STARTER`/`GROWTH`/`ENTERPRISE`),
    and two severity levels of "turn this off":
    - **Suspend/reactivate** — reversible, one click. Wired all the way
      through: `POST /v1/auth/login` checks `tenants.status`, and — this is
      the important part — so does `core/database.get_session()` on
      **every** tenant-scoped request, not just login. A tenant suspended
      mid-session immediately 403s that tenant's already-issued tokens on
      their very next request, not just new logins. Confirmed via curl:
      logged in, suspended the tenant from another session, reused the
      *same* token → 403; reactivated → same token worked again.
    - **Archive (offboard)** — sets `tenants.archived_at`, hides it from the
      default tenant list, blocks login the same way suspension does, but
      keeps all data and is undone with **Restore**. Meant for "this
      customer left," not a temporary pause.
  - **Platform admins** — list, add, and manage role + status.
    - **Role**: `ADMIN` (full) vs `VIEWER` (read-only) — resolved fresh
      from the DB on every request (`core/platform_authz.py`), never baked
      into the JWT, so a demotion takes effect on the demoted admin's very
      next request rather than waiting out their token. Every mutating
      `/v1/platform/*` endpoint requires `ADMIN`; confirmed a `VIEWER`
      gets 200 on reads and 403 on every write.
    - **Guards on `PATCH /v1/platform/admins/{id}`**: you can never modify
      your own account through this endpoint (status or role — ask another
      admin), and you can't suspend or demote the platform's last remaining
      active `ADMIN` (both would be a lockout with no recovery path, since
      there's no self-serve platform signup).
    - **Forgot password**: `/platform/forgot-password` →
      `POST /v1/platform/forgot-password` generates a single-use, 1-hour
      token (stored hashed, sha256) and always returns the same generic
      message regardless of whether the email exists, so it can't be used
      to enumerate admin accounts. There's no email provider wired up
      anywhere in this codebase — in `HRMS_DEBUG=true` (the local default)
      the response also includes the raw reset link directly, for dev use
      only; production needs a real mailer here instead.
  - **Audit log** — every mutating action above (`platform_audit_log`,
    migration `0007`), who/what/target/when, paginated, write-once. This is
    the thing a compliance-conscious buyer asks for first, and until this
    round it didn't exist at all — only implicit DB row timestamps.

Scope is still deliberately narrow: provisioning, standing (suspend/plan/
archive), and platform-admin management. Nothing under `/v1/platform/*`
queries `employments`, `persons`, `leave_applications`, or any other
tenant's actual HR data — the one exception is a bare employee **count** on
tenant detail (a usage signal, computed the same RLS-bypassing way as the
company count), not the underlying records. A platform admin can create the
shell a company operates in and control whether it's switched on, not see
inside it.

**Deliberately not built**, and why: billing/payment integration (would
need a real payment provider — faking one would be actively misleading) and
tenant impersonation/"view as" support access (cuts directly against the
isolation model the rest of this system enforces). Both are real gaps for
a production platform, just not ones to fake.

---

## Leave & Policy Bootstrap

The seed script already creates two leave types (Casual, Sick) with balances
for every seeded login. To add more, sign in via `POST /v1/auth/login` first
(Swagger's "Authorize" button accepts a bearer token), then:

```bash
# 1. Create a leave type — requires the leave.write permission (HR_MANAGER)
POST /v1/leave/types

# 2. Initialize balances for a specific employee/year
POST /v1/leave/balances/init?employment_id=<emp_id>&year=2026

# 3. Create a policy template — requires policy.write (HR_MANAGER)
POST /v1/policies/templates

# 4. Assign the policy to an employee — target must be within your scope
POST /v1/policies/assignments
```

Use http://localhost:8015/docs (Swagger UI) for all setup calls — click
"Authorize" and paste an access token from `/v1/auth/login`.

---

## Alternate Saturdays, Policy Assignment & Schedule Entry

Two gaps found together: `PolicyTemplate.work_days` was a plain weekly
Mon–Sun bitmask that could not express "2nd & 4th Saturday off," and it
was — separately — never actually consulted anywhere (no `WEEKEND` status
was ever derived, and leave's day-counting was hard-coded to `"1111100"`
regardless of what a policy said). Both are fixed as of migration `0012`;
`0013` renamed the saturday_pattern values (see below).

**Alternate Saturday**: `PolicyTemplate.saturday_pattern` (`ALL` /
`SECOND_FOURTH_OFF` / `FIRST_THIRD_OFF`) refines Saturday specifically —
it's only consulted when `work_days`' Saturday bit is `"1"`. Named by which
Saturdays are OFF (matching how this is actually described in a policy —
"2nd & 4th off"), not which are working, so a 5th Saturday in a month that
has one is never named as off by either pattern and is always a working
day — there's nothing extra to configure for it. There's no `NONE` value:
turning Saturday off entirely is the `work_days` toggle's job, not a
second, redundant control here. See `core/datetime_utils.is_working_day()`.
This now actually drives two real things: `GET /v1/time/daily-analysis`
marks an un-punched non-working day `WEEKEND` (vs. `ABSENT` for a missed
working day — including a working Saturday under an alternate pattern),
and `POST /v1/leave/applications` excludes non-working Saturdays from
`days_requested`.

**Assigning a policy to a department or a company**: `employee_policy_assignments`
can target exactly one of `employment_id`, `org_unit_id` (department) or
`legal_entity_id` (company) — enforced by a DB check constraint
(`num_nonnulls(...) = 1`, added in migration `0014`). `resolve_policy()`'s
priority: employee-specific → the employee's department (walking up the
org hierarchy for the nearest ancestor with an assignment) → the
employee's legal entity → the tenant's `is_default` template →
hard-coded system defaults. The legal-entity tier exists because
`tenant_provisioning.py` never creates an org_unit when a company is
created — only `employments.legal_entity_id` is guaranteed to exist for
every employee, so it's the only reliable "whole company" target;
org_unit_id depends on both an org_unit tree existing and the employee
having a current `Assignment` row. Assign via **Attendance policies** →
a policy's `⋯` menu → **Assign** → the **Department** / **Company**
toggle, or `POST /v1/policies/assignments` with `org_unit_id` or
`legal_entity_id` instead of `employment_id`.

**Schedule as start time + duration**: the policy form no longer asks for
an end time directly — `PolicySheet` takes **Start time** + **Total
working hours** and computes `expected_end_time` as
`start + hours + break_minutes` (shown as a read-only "Ends at HH:MM").
This is purely a frontend UX change; the API is unchanged (still stores
`expected_start_time`/`expected_end_time`, still derives `standard_minutes`
server-side via `compute_standard_minutes`). Overtime needs no separate
wiring for this — `calc_overtime()` has always compared `effective_minutes`
against `standard_minutes`, so once `standard_minutes` correctly reflects
the entered hours, OT already measures against it.

---

## Configurable Employee IDs

`employee_number` used to be a plain required string on `POST
/v1/employees` — HR typed every employee ID by hand, no generation, no
format enforced. `EmployeeIdScheme` (`org/models.py`, migration `0015`)
makes it optional and auto-generated: **prefix + separator + zero-padded
running number** (e.g. `SFPL-0001`, or `EMP_001` with a `_` separator and
3 digits — both the separator and digit-padding are configurable per
scheme, not fixed).

Two scopes, same shape as policy assignment: a scheme with
`legal_entity_id` set applies to that one company only; one with it `NULL`
applies tenant-wide. Resolution in `people/router.py:_generate_employee_number`
tries the hiring company's own scheme first, then the tenant-wide one,
then — if neither exists — falls back to today's behavior (manual entry
required). Setting the tenant-wide scheme requires `org.write` **and**
`scope.is_all` (same bar as creating a legal entity); a company's own
scheme just needs that company in the caller's scope.

The counter increment is a single `UPDATE ... RETURNING`, not a
read-modify-write, so two employees hired at the same instant still get
distinct numbers. At most one active scheme per company and at most one
active tenant-wide scheme are enforced by partial unique indexes in the
database, not application logic. `POST /v1/employees` still accepts an
explicit `employee_number` to override generation entirely — needed for
preserving historical IDs when importing from a legacy system (see
[`docs/erp-integration-plan.md`](docs/erp-integration-plan.md)).

UI: **Organization → Employee IDs** tab (list, add, edit, remove, with a
live preview of the next ID as you configure prefix/separator/digits); the
**Add employee** sheet on the Employees page shows the field as optional
with an `Auto: SFPL-0001`-style placeholder once a scheme resolves for the
selected company.

---

## Overtime

`PolicyTemplate` has always had `ot_enabled`/`ot_qualifying_minutes`/
`ot_rate`/`ot_daily_cap_minutes`, and `core/datetime_utils.compute_day()`
has always computed OT correctly from them — but until migration `0009`,
`attendance_days` had no column for it, so both places that call
`compute_day()` (a punch-out in `time/router.py`, a corrections
recompute in `corrections/router.py`) silently discarded the value. The
Daily Analysis page showed a different, hardcoded `max(0, effective - 480)`
flat-8-hour number labeled "Approved Overtime" despite no approval step
existing anywhere.

**Now real, end to end:**
1. A day's OT is computed from whichever policy resolves for that
   employee/date (`policy/engine.py:resolve_policy`) and persisted as
   `attendance_days.ot_minutes`, with `ot_status` starting at `PENDING`
   (or `NONE` if no OT was worked). See `apply_overtime()` in
   `time/models.py` — a correction that changes the minutes resets any
   prior review rather than leaving a stale `APPROVED` sitting on a
   different number.
2. `GET /v1/time/overtime/pending` — attendance days with `ot_status=PENDING`
   in the caller's scope. `PATCH /v1/time/overtime/{attendance_day_id}` —
   approve or reject. Gated on `corrections.approve` (same reviewers who
   already approve attendance corrections) rather than a new permission
   string; self-approval is blocked; re-reviewing an already-decided day
   is rejected with 400.
3. Frontend: an "Overtime awaiting review" card on the **Attendance** page
   (HR/Manager/Super Admin only, hides itself when nothing's pending), and
   Daily Analysis now shows the real number with a status-aware label
   (`Overtime — pending review` / `Approved overtime` / `Overtime — rejected`)
   instead of unconditionally claiming "Approved".

No demo tenant ships with `ot_enabled` on by default (`_DEFAULT_POLICY` in
`policy/engine.py` has it off, and `seed_demo.py` doesn't create a
`PolicyTemplate` at all) — create one with `POST /v1/policies/templates`,
`is_default: true`, `ot_enabled: true` to turn it on for the whole tenant.

---

## Leave Completeness — Holidays, Comp-off, Encashment, Accrual

Migration `0010` filled four gaps in Leave: `HOLIDAY` existed only as an
`AttendanceStatus` enum value with no calendar to ever set one; there was no
comp-off concept; no leave encashment; and balances only ever moved via the
one-time manual `POST /v1/leave/balances/init` — no ongoing accrual.

**Holiday calendar** (`time/router.py`, gated on `leave.write` — HR
maintains it the same way it maintains leave types):
- `GET/POST /v1/time/holidays`, `DELETE /v1/time/holidays/{id}`.
  `legal_entity_id` null = tenant-wide; set = specific to one company.
- Feeds two places: `GET /v1/time/daily-analysis` shows `HOLIDAY` status for
  employees who didn't punch in on a tenant-wide holiday (per-company
  holidays aren't resolved there yet — see code comment); and
  `POST /v1/leave/applications` excludes tenant-wide holidays from the
  working-day count via `working_days_between()`'s new `holidays` param.

**Comp-off** (`POST /v1/leave/comp-off`, `leave.write`): a direct HR credit
for a day worked outside the normal schedule, not a second approval chain —
one row in `comp_off_grants` (unique per employment/work_date, so re-granting
the same day 400s) plus an `allocated_days` credit to that employee's "Comp
Off" `LeaveType`, auto-created on first use (`_get_or_create_comp_off_type`
in `leave/router.py`).

**Encashment** (`POST /v1/leave/encashment`, `leave.write`): converts N days
of balance to a payout record (`leave_encashments`) and debits
`allocated_days`. Only leave types with `encashable=true` qualify — toggle it
via `PATCH /v1/leave/types/{id}`. There's no payroll module (see below), so
this is the record for payroll to act on externally; it doesn't move money.

**Accrual** (`POST /v1/leave/accrual/run?period=YYYY-MM`, `leave.write`):
credits `days_per_year / 12` to every active employment in the caller's scope
for every `LeaveType` with `accrual_enabled=true`. `last_accrued_period` on
`LeaveBalance` is a **high-water mark**, compared as a `"YYYY-MM"` string —
re-running the current or an earlier period is a safe no-op, but it does not
backfill a month that was skipped by mistake (running `2026-11` after
`2026-09` moves the mark to `2026-11`; re-running `2026-09` afterward no-ops
rather than double-crediting). There's no in-app scheduler anywhere in this
stack — trigger this from an external monthly cron in production, the same
way `seed_demo.py` is a manually-run script rather than a job.

Frontend: **Leave → Admin** tab (HR only — gated on the same role that holds
`leave.write`, not just any approver) has cards for all four: leave-type
toggles for Encashable/Accrues-monthly, the holiday calendar, a comp-off
grant form, an encashment form, and a manual "Run accrual" button.

**Payroll is intentionally not built.** `LeaveEncashment` is designed as the
handoff point for it (see its docstring), but salary/CTC/bank data doesn't
exist anywhere in this codebase yet — it's a from-scratch subsystem, not a
gap-fill. Scoping doc: [`docs/payroll-design.md`](docs/payroll-design.md).

**ERP integration (Suraj Group / Sharanga Production) is planned, not
implemented** — bringing two legacy systems in as tenants with dual login
(ERP SSO + direct email/mobile/employee-code login). Blocked on the real
legal-entity list for Suraj Group; see
[`docs/erp-integration-plan.md`](docs/erp-integration-plan.md) for what's
confirmed vs. still open. The source files
(`exim.users.json`, `Sharanga_Production.*.json`) contain real employee PII
and are gitignored — never commit them.

---

## Frontend Environment

`frontend/.env` — defaults for local dev:

```env
VITE_API_URL=http://localhost:8015
```

Change `VITE_API_URL` to point at a remote API when deploying the frontend elsewhere.

---

## Production Build

```bash
# Build the frontend
cd frontend && npm run build
# Outputs to frontend/dist/ — serve with any static host (S3 + CloudFront, nginx, etc.)

# Run API in production (no --reload)
uv run uvicorn hrms.main:app --host 0.0.0.0 --port 8015 --workers 4
```

Set these in production:
- `HRMS_SECRET_KEY` — strong random secret (never the default); JWTs are signed with this
- `HRMS_ENVIRONMENT=production`
- `HRMS_CORS_ORIGINS` — your actual frontend domain
- `HRMS_APP_DATABASE_URL` — the `hrms_app` role's password is `hrms_app_dev_password` by
  default (set in migration `0005_app_role_rls_enforcement.py` for local dev convenience).
  Rotate it in production: `ALTER ROLE hrms_app PASSWORD '<strong-random>'` and update this
  env var to match. `HRMS_DATABASE_URL` (the superuser) is only ever used for migrations.

---

## Useful Commands

```bash
# Tail API logs (Docker)
docker compose logs -f api

# Open a psql shell
docker compose exec db psql -U hrms hrms

# Run backend tests
cd backend && uv run pytest

# TypeScript type-check frontend
cd frontend && npx tsc --noEmit

# Lint backend
cd backend && uv run ruff check src/
```

---

## Ports at a Glance

| Service | Port |
|---------|------|
| Frontend (Vite) | 5173 |
| Backend (FastAPI) | 8015 |
| PostgreSQL | 5432 |
