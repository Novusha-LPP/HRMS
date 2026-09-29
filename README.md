# HRMS

A multi-tenant HR platform: organisation structure, people and employment history, attendance and
overtime, leave, attendance policies, employee KYC, onboarding and reporting — sold as a product to
many companies, each an isolated **tenant** that can hold several legal entities (a group with sister
companies). A separate **platform console** lets the operator create and manage tenants.

| | |
|---|---|
| Backend | Python 3.12, FastAPI, SQLModel/SQLAlchemy (async), PostgreSQL 16 with row-level security, Alembic, managed with `uv` |
| Frontend | React 19, TypeScript, Vite, Tailwind, TanStack Query |
| Tenant isolation | Every tenant table carries `tenant_id`; the API connects as a restricted `hrms_app` role so PostgreSQL itself enforces the boundary, on top of the application's own filters |
| Access control | Permissions + scope (`ALL`, `LEGAL_ENTITY`, `ORG_UNIT`, `DIRECT_REPORTS`, `SELF`) per role assignment, resolved per permission |

## Run it

The day-to-day and first-run setup, migrations, seed data, roles, policies and production notes are in
**[RUNBOOK.md](RUNBOOK.md)**. The short version:

```bash
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn hrms.main:app --reload --port 8015        # API + Swagger at http://localhost:8015/docs
cd ../frontend && npm install && npm run dev              # app at http://localhost:5173
```

Create the first platform admin with `uv run python scripts/seed_platform_admin.py you@example.com` (it prints a
generated password once, or reads `HRMS_PLATFORM_ADMIN_PASSWORD`), then create a company from `/platform/login`.
`uv run python scripts/seed_demo.py` builds a throwaway demo group for development.

## Repository layout

```
backend/            FastAPI application (src/hrms/), Alembic migrations, scripts/, tests/
  src/hrms/core/      config, database sessions + RLS context, JWT auth, scope/permission resolution,
                      sign-in throttling, security helpers
  src/hrms/modules/   kernel (auth, users, roles), org, people, time, leave, policy, kyc, onboarding,
                      reports, dashboard, platform
  alembic/versions/   hand-written migrations — the source of truth for the schema
  scripts/            seed_demo, seed_platform_admin, ERP import (migrate_tenants) and its repair tools
frontend/           React application (src/pages, src/api, src/context, src/components), unit tests in tests/
docs/               system design, architecture notes, ERP integration plan, payroll design, code review
RUNBOOK.md          how to set up, operate, and deploy
docker-compose.yml  PostgreSQL (bound to localhost) and the API
```

## Checks

CI (`.github/workflows/checks.yml`) runs the following. Run them locally before pushing:

```bash
cd backend
uv run ruff check src tests
uv run mypy src
uv run alembic upgrade head && uv run alembic check       # migrations still match the models
uv run pytest -q                                          # see the warning below

cd ../frontend
npm run lint && npm test && npm run build
```

> **The backend tests write to whatever database `HRMS_DATABASE_URL` points at** (they create tenants and
> sign in). Point them at a throwaway database whose name ends in `_test` — the recipe is under *Useful
> Commands* in the RUNBOOK. Never run them against a database that holds real employee data.

## Security notes

- Passwords are bcrypt-hashed; sign-in is throttled per identifier and per address; sessions end when a
  password is changed or an employee is separated. Imported and admin-issued passwords must be changed at
  first sign-in.
- The API refuses to start in production with a default signing secret, debug on, or the published
  development password for the `hrms_app` database role.
- Identity numbers (PAN, Aadhaar, bank) are masked for anyone without KYC permission, and every access to
  another person's KYC record is written to an append-only log. They are not yet encrypted at rest — see
  the ERP plan's open decisions.
- The legacy-system export files (`exim.users.json`, `Sharanga_Production.*.json`) and `credential.md`
  hold real people's data and credentials. They are gitignored; keep it that way.

## Documentation

| | |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Set-up, migrations, authentication and roles, onboarding, policies, leave, ERP import, production |
| [docs/README.md](docs/README.md) | Index of the architecture and system-design documents |
| [docs/erp-integration-plan.md](docs/erp-integration-plan.md) | Importing Suraj Group and Sharanga Production — plan, mapping, status, open decisions |
| [docs/CODE_REVIEW_2026-09-28.md](docs/CODE_REVIEW_2026-09-28.md) | Code review findings and what was done about them |
