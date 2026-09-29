# HRMS Platform — Architecture & System Design Documentation

Authoritative system design and architecture specifications for the HRMS Platform, aligned with the running codebase (`backend/` and `frontend/`).

---

## Authoritative Specifications

| Document | Description |
|---|---|
| [System Design Specification](system-design/README.md) | **Primary System Design Document**: Component & container architecture, multi-tenant dual planes (Platform vs Tenant), dual-role PostgreSQL RLS security, 13 domain modules breakdown, and Alembic schema evolution (0001–0019). |
| [Technology Stack Reference](TECH_STACK.md) | Concrete inventory of frameworks, runtimes, ORMs, libraries, and dev tools across backend, frontend, database, and DevOps. |

---

## Architectural Deep-Dives

| File | Contents |
|---|---|
| [architecture/01-overview.md](architecture/01-overview.md) | Architectural principles, multi-tenant foundations, and confirmed production technology stack |
| [architecture/02-requirements-analysis.md](architecture/02-requirements-analysis.md) | Domain requirements analysis, enterprise capabilities, and functional scope |
| [architecture/03-tenancy-isolation-deployment.md](architecture/03-tenancy-isolation-deployment.md) | Tenant definition, PostgreSQL RLS, dual-role least privilege (`hrms_app`), and real-time revocation |
| [architecture/04-organization-people-history.md](architecture/04-organization-people-history.md) | Entity dimensions, Person vs Employment vs UserAccount, effective dating, and personnel actions |
| [architecture/05-identity-access-security.md](architecture/05-identity-access-security.md) | Identity management, RBAC with 6 data scopes, audit logging, and data classification |
| [architecture/06-configuration-workflow-rules.md](architecture/06-configuration-workflow-rules.md) | 4-tier policy resolution, multi-level approval workflows, and business rules |
| [architecture/07-application-data-integration-scale.md](architecture/07-application-data-integration-scale.md) | FastAPI modular monolith architecture, React 19 SPA, and database schema conventions |
| [architecture/08-assumptions-risks-decisions.md](architecture/08-assumptions-risks-decisions.md) | Architectural decisions, risk mitigations, and scalability strategy |
| [payroll-design.md](payroll-design.md) | Compensation schemas, salary component structures, and payroll export interfaces |
| [erp-integration-plan.md](erp-integration-plan.md) | Importing the Suraj Group and Sharanga Production ERPs as tenants: field mapping, security decisions, implementation status, open decisions |
| [leave-management-design.md](leave-management-design.md) | Leave balance buckets, immutable transaction journal, monthly ledger and policy-driven entitlement rules — design, not yet implemented |

