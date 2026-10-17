# HRMS Platform — Architecture & System Design Documentation

Authoritative system design and architecture specifications for the HRMS Platform, aligned with the running codebase (`backend/` and `frontend/`).

---

## Authoritative Specifications

| Document | Description |
|---|---|
| [System Design Specification](system-design/README.md) | **Primary System Design Document**: Component & container architecture, multi-tenant dual planes (Platform vs Tenant), dual-role PostgreSQL RLS security, 13 domain modules breakdown, and Alembic schema evolution (0001–0019). |
| [API documentation](API.md) | Swagger UI (`/docs`), ReDoc (`/redoc`) and the OpenAPI schema: how the frontend team and third-party integrators use them, how to export the spec, and how to keep it accurate. |
| [Technology Stack Reference](TECH_STACK.md) | Concrete inventory of frameworks, runtimes, ORMs, libraries, and dev tools across backend, frontend, database, and DevOps. |
| [Enterprise completion plan](enterprise-plan/README.md) | **Build programme** from today's code to the full requirements v2.0, with every rule configurable from the UI: platform foundations, module plans, industry coverage, roadmap, and the critique with decisions needed. |
| [Releasing](RELEASING.md) | Release PRs, versioning, verified API/web images, and production promotion. |
| [Testing CI/CD on EC2](EC2_TESTING_DEPLOYMENT_GUIDE.md) | Complete end-to-end runbook for deploying testing branch to EC2 + Docker + RDS via GitHub Actions and SSM. |
| [Frontend CI/CD on ECS Fargate](FRONTEND_ECS_CICD.md) | AWS and GitHub setup, automatic testing deployment, and manual production promotion of the same frontend image digest. |

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
| [erp-crm-integration-plan.md](erp-crm-integration-plan.md) | Enterprise ERP/CRM integration plan and implementation status: per-company settings and field ownership, API keys and OAuth, two-way employee sync, the events feed, self-service through the ERP, backlog (webhooks, file feeds, connectors, SSO, SCIM) |
| [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) | For ERP/CRM developers: keys and OAuth, the go-live order, syncing employees, the events feed, employee sessions, retries and the error codes |
| [erp-integration-plan.md](erp-integration-plan.md) | Importing the Suraj Group and Sharanga Production ERPs as tenants: field mapping, security decisions, implementation status, open decisions |
| [leave-management-design.md](leave-management-design.md) | Leave balance buckets, immutable transaction journal, monthly ledger and policy-driven entitlement rules — design, not yet implemented |

