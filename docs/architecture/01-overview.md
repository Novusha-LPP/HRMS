# Architecture 1 · Overview and principles

This section and the seven after it turn the SURAJ Group HRMS business requirements (v2.0, 17 Sep 2026) into a platform that serves many organisations. SURAJ Group becomes the first tenant, not the shape of the product. Section numbers such as §12 refer to that requirements document. **Performance/KPI (§16, and the KPI rows elsewhere) is out of scope for this analysis, as you asked.** The module framework in Architecture 6 leaves room to add it later without changing anything here.

## The short version

1. **The requirements describe one organisation; the platform has to serve many.** Every rule in the document that is specific to SURAJ Group (leave entitlements, reminder days, approval chains, PF/ESIC handling, the org chain) becomes tenant configuration. The document already asks for this: HR must "operate routine business rules without depending on the technical team" (§43).
2. **A tenant is not a company.** A tenant is the customer and the isolation boundary. Inside it sit legal entities, locations, org units, jobs, cost centres and positions, each as its **own dimension**. The single chain in §2 (Group → Company → Branch → Department → Sub-department → Team) is one tenant's shape, not the model.
3. **Multi-company and multi-location go into the data model from the first sprint.** The document's Phase 6 ("Expansion: multi-company, multi-location") can stay a rollout step, but it cannot be a build step. Adding it later would mean rewriting every table.
4. **Four platform engines carry most of the business logic:** effective-dated personnel actions, configurable approval workflows, scoped and versioned policies, and a due-date (obligation) engine feeding one Action Centre. Every module from §7 to §26 is built on them, not beside them.
5. **Default to pooled multi-tenancy, with dedicated cells when a tenant needs them.** Most tenants share a PostgreSQL cluster, with `tenant_id` on every row enforced by row-level security. Large, regulated or residency-bound tenants get a dedicated cell. Both run the same code and the same schema.
6. **India statutory logic becomes a versioned country pack.** PF, ESIC, PT and LWF are data plus pluggable calculators, stamped with an effective date and a source, and checked by HR (§20). Other countries arrive later as further packs.
7. **Build a modular monolith per cell, not microservices on day one.** Modules have hard boundaries and talk through events. Only the high-volume parts are separate services: attendance ingestion, notifications, search, document processing and analytics.

## Design principles

| # | Principle | What it rules out |
|---|---|---|
| P1 | **Tenant context is mandatory everywhere**: requests, jobs, events, cache keys, file paths, search queries, logs, metrics. Missing context fails closed. | Any query, job or export that runs "for all rows". |
| P2 | **Configuration, not customisation.** A tenant's difference is data: settings, packs, custom fields, workflow definitions. | `if tenant == …` code paths and per-customer forks. |
| P3 | **Two clocks.** Every business fact has an effective (valid) date; every change is recorded with when, who and why. | Overwriting a department, manager or salary in place. |
| P4 | **One person, one record, many employments.** Information entered once flows through the whole journey (Business philosophy, §11, §43). | Re-keying a candidate as an employee; losing history on rejoin. |
| P5 | **Access is decided centrally and enforced in the data layer**, for rows and fields, in screens, reports, search, exports and notifications alike. | Filtering restricted data only in the UI. |
| P6 | **Complexity is opt-in.** A 20-person tenant sees one company, one location and no positions; a 50,000-person tenant turns on entity groups, positions and matrix reporting. | Forcing every tenant through enterprise setup. |
| P7 | **Country and industry specifics live in packs**, versioned and effective-dated. | PF/ESIC columns in the core employee table; Indian assumptions in core code. |
| P8 | **API-first and event-first.** Anything the UI can do, the API can do, and every state change emits an event. | Screen-only features that integrations cannot reach. |

## Your requirements, and where each is met

| Your requirement | The mechanism | Section |
|---|---|---|
| Multiple tenants with strict data isolation | Tenant resolution at the edge; `tenant_id` on every row and in every key; PostgreSQL RLS that fails closed; composite foreign keys; per-tenant encryption keys; cross-tenant leakage tests in CI | 3 |
| Different industries and business models | Industry packs, tenant-defined org dimensions, worker types, custom fields and objects, a terminology layer | 4, 6, UI 2 |
| Multiple locations, branches, offices, sites | Location as its own dimension with type, jurisdiction, time zone, holiday calendar and statutory registrations | 4 |
| Different hierarchies and departments | Tenant-defined org unit types and depth; separate reporting, cost-centre and custom hierarchies; optional positions; effective-dated reorganisations | 4 |
| Enterprise-scale users, roles, permissions | Tenant-scoped identity with SSO, SCIM and OTP; roles × data scopes × data classes × conditions; delegation; access reviews | 5 |
| Configurable workflows and business rules | Versioned approval definitions; typed policy objects; a sandboxed expression language; layered, scoped, effective-dated configuration; simulation before publishing | 6 |
| Small organisations to large enterprises | Pooled and dedicated cells; partitioning; asynchronous heavy work; opt-in complexity; quotas and fair scheduling | 3, 7 |
| Security, auditing, compliance | Data classification; field encryption; tamper-evident audit log; sensitive-read logging; DPDP-ready retention and data-principal requests; controlled support access | 5 |
| Tenant-specific configuration and customisation | Configuration layers from platform to employee group; branding with contrast guards; terminology; templates; sandbox tenants with configuration promotion | 6, UI 1 |
| Multi-location and multi-region deployment | Regional cells; a home region per tenant; in-country disaster recovery; residency decisions before expanding | 3 |
| Extensibility for new industries, modules, capabilities | A module contract, packs, events and webhooks, a public API, custom objects, and later sandboxed extensions | 6, 7 |
| Shared resources with tenant isolation | Platform reference data (read-only, versioned), shared infrastructure with quotas, shared gateways with per-tenant identity, and no standing operator access | 3 |

## Target architecture at a glance

![A request is resolved to one tenant at the edge, routed to that tenant's home cell, and carries the tenant context into every store.](diagrams/tenancy.svg)

*A request is resolved to one tenant at the edge, routed to the tenant's home cell, and carries the tenant context into every store. Pooled and dedicated cells run the same code and schema (details in Architecture 3).*

## Suggested reference stack (to be confirmed)

The architecture does not depend on these choices. They are sensible defaults to confirm against your team's skills (decision D8 in Architecture 8).

| Concern | Suggested default | Why |
|---|---|---|
| Operational database | PostgreSQL 16 or later (managed) | Row-level security, range types and exclusion constraints for effective dating, JSONB for custom fields, partitioning |
| Application | One modular monolith per cell, in TypeScript (NestJS), Kotlin/Java (Spring Boot) or C# (.NET) | Transactions that span the employee journey; one deployable unit per cell |
| Web | React with TypeScript, consuming this design system's tokens and classes | Tenant theming through CSS variables at runtime |
| Mobile self-service | React Native or Flutter; a PWA is acceptable for Phase 1 | One app with tenant discovery; white-label builds later |
| Events | Transactional outbox, then Kafka/Redpanda or a managed equivalent per cell | Reliable fan-out without distributed transactions |
| Durable timers and workflows | A DB-backed scheduler to start; Temporal if orchestration grows | Reminders, escalations, scheduled effective dates |
| Search | OpenSearch with per-tenant routing | Global employee search with security trimming |
| Identity | Keycloak (realm or organisation per tenant) or a managed CIAM with per-tenant SAML/OIDC and SCIM | Enterprise SSO per tenant |
| Authorization | An in-house model (Architecture 5), optionally backed by OpenFGA or SpiceDB for relationships | Hierarchy-based access at scale |
| Analytics | CDC (Debezium) into ClickHouse or a cloud warehouse, with a semantic layer | Consistent metric definitions (§30) |
| Platform | Kubernetes, Terraform, GitOps, OpenTelemetry | Repeatable cells; per-tenant observability |
