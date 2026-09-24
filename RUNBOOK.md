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

Login with any seeded account (password `Passw0rd!` for all) — the login
page has one-click tiles. If the DB was wiped, re-seed first:
`cd backend && uv run python scripts/seed_demo.py`.

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
the script prints the full table on completion. The frontend login page has
one-click tiles for all seven.

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
