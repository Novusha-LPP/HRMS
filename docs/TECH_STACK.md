# HRMS Platform — Technology Stack

This document provides a comprehensive overview of the technology stack, architectural choices, libraries, and developer tools used across the HRMS platform.

---

## High-Level Architecture Overview

The HRMS platform is structured as a **Multi-Tenant Modular Monolith** with a clear separation between the **Platform Control Plane** (tenant provisioning, subscription tiers, platform administration) and the **Tenant Plane** (HR operations, employees, attendance, leave, policy, KYC, reports).

```
                      ┌───────────────────────────────────────────┐
                      │             Frontend Client               │
                      │  React 19 + TypeScript + Vite + Tailwind  │
                      └─────────────────────┬─────────────────────┘
                                            │ HTTP / REST / JSON
                                            ▼
                      ┌───────────────────────────────────────────┐
                      │             FastAPI Backend               │
                      │  Python 3.12+ (Uvicorn, Async, SQLModel)  │
                      ├─────────────────────┬─────────────────────┤
                      │ Platform Plane      │ Tenant Plane        │
                      │ (/platform/*)       │ (/api/v1/*)         │
                      └─────────────────────┼─────────────────────┘
                                            │ asyncpg (RLS session vars)
                                            ▼
                      ┌───────────────────────────────────────────┐
                      │          PostgreSQL 16 Database           │
                      │  Row-Level Security (RLS) + Multi-Tenancy │
                      └───────────────────────────────────────────┘
```

---

## 1. Backend Stack

| Category | Technology | Version | Purpose / Description |
|---|---|---|---|
| **Runtime / Language** | [Python](https://www.python.org/) | `^3.12` | Modern asynchronous Python runtime with strict typing support. |
| **API Framework** | [FastAPI](https://fastapi.tiangolo.com/) | `>= 0.115.0` | High-performance asynchronous REST API framework with native OpenAPI/Swagger generation. |
| **ASGI Server** | [Uvicorn](https://www.uvicorn.org/) | Standard bundle | Lightning-fast ASGI web server with auto-reload capabilities for development. |
| **ORM / Data Modeling** | [SQLModel](https://sqlmodel.tiangolo.com/) & [SQLAlchemy](https://www.sqlalchemy.org/) | `sqlmodel >= 0.0.21`, `sqlalchemy >= 2.0.36` | Blends Pydantic validation with SQLAlchemy 2.0 async engine and query capabilities. |
| **PostgreSQL Driver** | [asyncpg](https://github.com/MagicStack/asyncpg) | `>= 0.30.0` | Ultra-fast async PostgreSQL database driver for non-blocking I/O. |
| **Schema Migrations** | [Alembic](https://alembic.sqlalchemy.org/) | `>= 1.13.0` | Database schema migrations with revision tracking and programmatic DDL scripts. |
| **Data Validation** | [Pydantic v2](https://docs.pydantic.dev/) & `pydantic-settings` | `>= 2.9.0` | High-speed Rust-backed data validation and environment variable parsing. |
| **Authentication & Crypto** | [python-jose](https://github.com/mpdavis/python-jose) & [passlib](https://passlib.readthedocs.io/) | `python-jose >= 3.3.0`, `passlib[bcrypt] >= 1.7.4` | JWT token encoding/decoding and secure password hashing (bcrypt). |
| **Identifiers** | `uuid` (stdlib) & `uuid7` | `uuid7 >= 0.1.0` (imported as `uuid_extensions`) | Random UUIDv4 for rows today; `core/ids.new_id()` can mint time-sortable UUIDv7 typed public IDs. (`python-ulid` was listed here but never used, and has been removed.) |
| **Logging** | [structlog](https://www.structlog.org/) | `>= 24.4.0` | Structured JSON and contextual logging. |
| **HTTP Client** | [httpx](https://www.python-httpx.org/) | `>= 0.27.0` | Asynchronous HTTP client for external integrations and test requests. |
| **Package Management** | [uv](https://github.com/astral-sh/uv) | Latest | Extremely fast Rust-based Python package manager and environment resolver. |
| **Build System** | [Hatchling](https://hatch.pypa.io/) | Latest | PEP 517/621-compliant build backend. |
| **Testing** | [pytest](https://docs.pytest.org/), `pytest-asyncio`, `pytest-httpx` | `pytest >= 8.3.0` | Async unit and integration test framework. |
| **Test DB Containers** | [testcontainers[postgres]](https://testcontainers-python.readthedocs.io/) | `>= 4.8.0` | Spin up ephemeral PostgreSQL containers for realistic integration tests. |
| **Linter & Formatter** | [Ruff](https://astral.sh/ruff) | `>= 0.6.0` | Extremely fast Python linter and code formatter. |
| **Type Checking** | [mypy](https://mypy-lang.org/) | `>= 1.11.0` | Strict static type checker with Pydantic plugin. |

---

## 2. Frontend Stack

| Category | Technology | Version | Purpose / Description |
|---|---|---|---|
| **Runtime / Node** | [Node.js](https://nodejs.org/) | `18+` | JavaScript/TypeScript execution environment. |
| **Language** | [TypeScript](https://www.typescriptlang.org/) | `~6.0.2` | Static typing across components, models, API contracts, and routes. |
| **UI Library** | [React](https://react.dev/) & React DOM | `^19.2.8` | Component-based UI library with the React 19 rendering engine. |
| **Build Tool / Bundler** | [Vite](https://vite.dev/) | `^8.3.0` | Next-generation frontend tooling with instant HMR and optimized production builds. |
| **Routing** | [React Router DOM](https://reactrouter.com/) | `^7.18.4` | Declarative client-side routing, protected routes, and navigation layouts. |
| **Server State & Caching** | [TanStack Query (React Query)](https://tanstack.com/query/latest) | `^5.103.2` | Async data fetching, server state synchronization, cache invalidation, and optimistic UI updates. |
| **Styling & CSS** | [Tailwind CSS](https://tailwindcss.com/) | `^3.4.19` | Utility-first CSS framework with custom theme variables, PostCSS, and Autoprefixer. |
| **Icons** | [Lucide React](https://lucide.dev/) | `^1.47.0` | Consistent, accessible icon library. |
| **Date Utilities** | [date-fns](https://date-fns.org/) | `^4.4.0` | Lightweight modular date manipulation and formatting library. |
| **Linter** | [oxlint](https://oxc-project.github.io/) | `^1.81.0` | Ultra-fast Rust-based JavaScript/TypeScript linter. |

---

## 3. Database & Multi-Tenancy Architecture

| Component | Choice | Details |
|---|---|---|
| **Primary Database** | **PostgreSQL 16** (`postgres:16-alpine`) | Relational database supporting advanced constraints, JSONB attributes, and Row-Level Security. |
| **Multi-Tenancy Isolation** | **PostgreSQL Row-Level Security (RLS)** | Tenancy is enforced at the database layer via `tenant_id` columns and RLS policies on tables. |
| **Database Connection Roles** | **Dual-Role Model**: | 1. **Migration / Superuser Role** (`hrms`): Used only by Alembic for schema migrations and DDL operations.<br>2. **Application Role** (`hrms_app`): Connects as `NOSUPERUSER` and `NOBYPASSRLS`. Each request sets `SET LOCAL app.current_tenant_id = '...'` to ensure data isolation. |
| **Key Generation Strategy** | **UUIDv4 (rows), UUIDv7 available** | Composite `(tenant_id, id)` keys. Moving row IDs to time-ordered UUIDv7 is a possible future optimisation for index locality; it is not done today. |

---

## 4. Infrastructure, DevOps & Containerization

| Tool | Purpose |
|---|---|
| **Docker & Docker Compose** | Orchestration for local development and staging (`docker-compose.yml` configures `db` and `api` containers). |
| **Container Volumes** | `postgres_data` persistent volume for database durability. |
| **Port Allocations** | • `5173`: Vite Frontend Client<br>• `8015`: FastAPI Backend Server (`/docs` for Swagger UI)<br>• `5432`: PostgreSQL Database |

---

## 5. Key Modules & Functional Boundaries

- **Core / Platform Plane**:
  - Multi-tenant isolation & context injection (`core/tenancy.py`, `core/authz.py`)
  - Platform administrator management (`modules/platform`)
  - Tenant provisioning & lifecycle management (`core/tenant_provisioning.py`)
  - Audit logging (`core/audit.py`)
- **Tenant HR Operations Plane**:
  - **Organization**: Legal entities, business units, departments, locations, cost centers (`modules/org`)
  - **People & Identity**: Employees, employment contracts, identity, access control (`modules/people`)
  - **Employee KYC**: Identity verification, statutory document uploads, verification workflow (`modules/kyc`)
  - **Time & Attendance**: Clock in/out, biometric sync, daily analysis, overtime, shift policies (`modules/time`, `modules/absence`)
  - **Leave Management**: Leave types, policies, accruals, applications, manager approval workflow (`modules/leave`)
  - **Attendance Corrections**: Correction requests, missing punches, regularizations (`modules/corrections`)
  - **Payroll Interface**: Payroll design, salary components, export contracts (`modules/payroll`)
  - **Policy Engine**: Configurable departmental and legal entity policies (`modules/policy`)
  - **Reports & Analytics**: Daily attendance, headcount, leave balances, audit reports (`modules/reports`)

---

## 6. Development Workflow Quick Reference

```bash
# Start PostgreSQL Database
docker compose up -d db

# Run Backend (Python 3.12 + uv)
cd backend
uv run uvicorn hrms.main:app --reload --port 8015

# Run Database Migrations
cd backend
uv run alembic upgrade head

# Run Frontend (Vite + React + TypeScript)
cd frontend
npm install
npm run dev
```
