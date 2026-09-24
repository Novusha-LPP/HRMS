# Architecture 7 · Application, data, integration and scale

## Application architecture: a modular monolith per cell

**Why:** the employee journey (§36) is one chain of transactions that must stay consistent. A small team ships faster with one deployable, and hard module boundaries keep the option to extract services later. Microservices from day one would add distributed transactions and heavy operations before the domain has settled.

| Area | Modules |
|---|---|
| **Platform kernel** | Tenancy context, identity integration, authorization, configuration, workflow, obligations and Action Centre, exceptions, audit, documents and letters, notifications, numbering, custom fields, terminology and i18n, search, import/export, integration hub |
| **Core HR** | Organisation (dimensions), people (person, employment, assignment), personnel actions, Employee 360 |
| **Talent** | Manpower plans and requisitions, recruitment, onboarding |
| **Time** | Shifts and rosters, attendance ingestion and computation, corrections, period close |
| **Absence** | Leave types, policies, ledger and accruals; holiday calendars |
| **Learning** | Programmes, sessions, feedback, certificates |
| **Assets** | Register, assignments, returns |
| **Separation** | Exit cases, clearance, F&F inputs, letters |
| **Compliance** | Country packs, registrations, periodic obligations, evidence, exceptions |
| **Service desk** | HR requests, SLAs |
| **Policies** | Publication, audiences, acknowledgements |
| **Compensation and payroll inputs** | Structures, revisions, payroll input snapshots; a payroll engine later |
| **Analytics** | Semantic layer, standard reports, dashboards |

**Separate services within each cell,** because their load profile differs: attendance ingestion, notification dispatch, the search indexer, document processing (scanning, previews, PDF rendering), report and export workers, and integration workers.

**Rules between modules:**

- A module owns its tables. No module reads another module's tables.
- Synchronous calls go through published module interfaces.
- State changes publish domain events through a **transactional outbox** (the row and the event commit together) to the cell's event bus.

![A personnel action is approved, applied on its effective date, and published as an event that every other module consumes.](diagrams/flow.svg)

*This is what "information entered once should flow through the employee journey" (§43) means in practice: one approved action, one transaction, one event, and every module updates itself.*

**Frontend.**

- A web SPA for the 16:9 HR desktop and a mobile app for self-service, each with its own BFF.
- **Metadata-driven** where tenants differ: forms, custom fields, terminology, navigation and entitlements come from a configuration endpoint.
- Tenant theming at runtime through this design system's CSS variables (UI 1).

## Data architecture

- **PostgreSQL per cell:** a primary with read replicas, a schema per module, `tenant_id` leading every primary key and index, UUIDv7 keys.
- **Partitioned high-volume tables:** raw punches, attendance days, audit log, notifications and outbox, partitioned by month (and hashed by tenant in large pooled clusters). Old partitions move to cheaper storage on the retention schedule.
- **Custom fields** in JSONB with GIN indexes; generated columns for fields that are filtered heavily.
- **Search:** OpenSearch, a shared index with tenant routing for small tenants and dedicated indices for large ones. Documents are indexed with precomputed visibility tags and never include restricted fields.
- **Files:** object storage with a per-tenant prefix, a per-tenant data key, versioning, and lifecycle rules for retention.
- **Analytics:** change-data capture into a columnar store or warehouse, partitioned by tenant, with row policies. A **semantic layer** holds versioned metric definitions (Active Employee, New Joiner, Vacancy, Overdue, from §39), and dashboards, standard reports and exports all use it, so the numbers agree (§30).
- **Caching:** per-tenant key prefixes, invalidated by events; never cache authorization decisions longer than their version stamp.
- **Backups:** point-in-time recovery per cluster, plus per-tenant logical snapshots (the tenant mobility tooling), so one tenant can be restored without rolling back the others.

## Payroll input contract (build this now, whatever §17 decides)

A **pay-period snapshot** per legal entity and pay group:

- **Contents:** joiners and leavers with dates; paid days, LOP days, overtime hours, shift allowances; leave encashment; arrears from retro-dated actions; variable pay and bonus inputs; deductions and recoveries (loans, advances, notice recovery); statutory applicability (PF, ESIC, PT state, LWF); the compensation structure in effect.
- **Behaviour:** locked when the attendance period closes. Versioned, so a later correction produces a *delta*, not a silent change. Exported through the API and in file formats for external payroll, or consumed by an internal payroll engine later.

## Integration architecture

An **integration hub** runs in each cell. It provides a connector framework with per-tenant configuration and secrets, field mapping, schedules, retries and a dead-letter queue, idempotency keys, and per-tenant monitoring.

| Integration (§34) | Pattern | Notes |
|---|---|---|
| **Attendance devices** | Device push over HTTP, a site gateway agent that polls LAN devices, CSV import; mobile and web punches through the API | Idempotency key = device + user + timestamp. Tolerates late and out-of-order data, and clock drift (monitored). A gateway handles offline sites. |
| **Payroll** (internal or external) | Payroll input snapshots (above), API plus files | Locked, versioned, deltas on correction |
| **Accounting and ERP** (Tally, SAP, others) | Journal or voucher export for F&F and recoveries | Ledger mapping per tenant |
| **Email and calendar** | Microsoft 365 and Google Workspace through OAuth per tenant; SMTP fallback | Interviews, training sessions, HR dates |
| **Messaging** | SMS gateway (DLT templates), WhatsApp Business provider, push | Per-tenant quotas and sender identity |
| **Directory and SSO** | SAML/OIDC; SCIM inbound and outbound | Joiner-mover-leaver automation; IT clearance on exit |
| **Recruitment sources** | Job boards, career site, email parsing | Candidate consent captured on entry |
| **Government portals** | Links plus evidence in v1; file generation (such as the PF ECR text file and ESIC contribution upload) later as country-pack outputs | No stored portal credentials |
| **Document storage** | Platform object storage; tenant-owned storage (SharePoint, Drive) later | Retention and legal hold apply either way |
| **Later** | Bank account verification (penny-drop), background verification, e-sign (Aadhaar eSign or DSC), DigiLocker | Each as a connector |

**Bulk import framework.** Onboarding a tenant depends on it:

- templates per object, generated from the tenant's configuration, so custom fields are included
- validation and a **dry run** with an error file
- idempotent upserts, safe to re-run
- **history import**, so a tenant arrives with effective-dated history rather than a snapshot
- imports run as audited jobs with tenant quotas

## Scalability

**Sizing assumptions to validate** (decision D15): tenants from 10 to 200,000 employees; hundreds of tenants at first, thousands within five years; peaks between the 1st and 5th of each month (period close, leave accrual, payroll inputs) and at shift starts (punch bursts).

| Hotspot | Why it is hard | Design response |
|---|---|---|
| **Attendance ingestion and computation** | Millions of punches a day across tenants; corrections and late data force recomputation | A separate ingestion service; an append-only partitioned punch store; incremental computation per employee-day; recompute queues with per-tenant fairness |
| **Month-start batch storms** | Every tenant closes attendance, accrues leave and generates payroll inputs at once | Jobs sharded per tenant, staggered schedules, priority queues, autoscaled workers, idempotent resumable jobs |
| **Dashboards and Action Centre counts** | Aggregating over large scopes on every page load | Event-maintained projections per scope; short-TTL caches; asynchronous refresh |
| **Authorization on lists** | Scope, hierarchy and field rules on every query | Precomputed visibility sets, closure tables, compiled predicates, indexes on `(tenant_id, org_unit_id)` and similar |
| **Reports and exports** | Large as-of queries | Read replicas and the analytics store; asynchronous exports with row limits; daily headcount snapshots |
| **Global search** | Large populations with security trimming | OpenSearch per-tenant routing; visibility tags; restricted fields not indexed |
| **Audit and event volume** | Every change and every sensitive read | Partitioned append-only storage, tiered retention, writes through the outbox |
| **Documents** | Terabytes over time | Object-storage lifecycle policies, de-duplication, retention purge |
| **Noisy neighbours** | One tenant's import or export starving the rest | Per-tenant rate limits and quotas, separate worker pools per tier, moving the tenant to a dedicated database or cell |
| **Reorganisations** | Moving a unit with thousands of employees | Batched action application; asynchronous closure recomputation; reads never block |

**Suggested performance budgets:**

- interactive API p95 under 300 ms
- dashboard under 2 s
- scoped list pages over 10,000 employees under 1 s
- exports always asynchronous
- a new tenant provisioned from packs in under 10 minutes

## Deployment and operations

- Kubernetes per cell, infrastructure as code (Terraform), GitOps (for example, Argo CD), canary releases per cell, ring rollout across cells.
- OpenTelemetry traces, metrics and logs tagged with the tenant; per-tenant SLO dashboards; alerts for anomalies that could signal a cross-tenant problem (for example, one request touching two tenant IDs).
- Regular disaster-recovery drills and **tenant-restore drills**.
- Suggested SLOs, to confirm: 99.9% availability for pooled tenants, 99.95% for dedicated cells.
