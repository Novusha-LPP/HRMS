# Architecture 3 · Tenancy, isolation and deployment

## What a tenant is

A **tenant** is one customer organisation under one contract. It is:

- the **isolation boundary** (no data crosses it),
- the **configuration root** (every setting inherits from it),
- the **identity boundary** (its own SSO, users and roles),
- the **billing account** (plan, modules, metered employees).

Inside a tenant sit one or more **legal entities** (employers), optionally grouped into **entity groups** for consolidation, plus locations, org units and the rest of Architecture 4.

**SURAJ Group is one tenant with several legal entities, not several tenants.** The requirements need group dashboards for Management (§3), inter-company transfers (§14), a group-wide unique Employee ID (§5) and consolidated reports filtered by company (§24). All of these would cross tenant boundaries if each company were its own tenant.

Use **separate tenants** only for unrelated organisations, or when a group needs hard legal separation between companies (for example, a joint venture that is a separate data controller). Cross-tenant consolidation is excluded by design. If it is ever needed, it arrives as an explicit, consented federation feature, not as shared tables.

A later **partner model** (HR outsourcing firms or resellers managing many client tenants) lives in the control plane: a partner organisation gets delegated, logged access to specific tenants. No tenant data moves.

## Isolation tiers: pooled by default, dedicated on demand

| Tier | Where the data lives | Who it suits | Isolation |
|---|---|---|---|
| **Pooled** (standard) | Shared PostgreSQL cluster in a regional cell; `tenant_id` on every row; RLS | Small and mid-size tenants, trials | Logical, enforced in the database |
| **Pooled compute, dedicated database** (premium) | Its own database in the cell's cluster, or its own cluster; shared application tier | Large tenants, heavy batch loads, stricter security reviews | Physical data separation; shared compute |
| **Dedicated cell** (enterprise, regulated) | A complete stack for one tenant, optionally in-country or in the customer's own cloud account | Very large or regulated tenants, residency commitments, private deployment | Full physical separation |

All tiers run **the same code, the same schema and the same migrations**. `tenant_id` stays on every row even in a dedicated database, so moving a tenant between tiers is a data migration (copy, verify, switch the route), not a code change. Build **tenant mobility tooling** early: it doubles as the tenant-level backup, restore and offboarding export.

Why not the alternatives as the default:

- **A schema per tenant** runs every migration thousands of times, bloats the database catalogue, and breaks connection pooling as tenants grow.
- **A database per tenant for everyone** costs too much and adds operational load at the small-tenant end, where most tenants will be.

## Isolation mechanics, in layers

1. **Edge resolution.** The tenant comes from the host (`kaveri.hrms.app` or a custom domain) and must match the tenant claim in the access token. A mismatch is rejected.
2. **Context propagation.** One tenant-context object travels from request to service to database session to outbox event to background job to log line. Code that runs without it fails.
3. **Row-level security.** Every tenant table has an RLS policy on `tenant_id = current_setting('app.tenant_id')::uuid`, with `FORCE ROW LEVEL SECURITY`. The application connects as a role that does not own the tables. The setting is made with `SET LOCAL` inside each transaction, which stays safe under transaction-mode connection pooling (PgBouncer). With no context, a query returns no rows.
4. **Keys that cannot cross.** Primary keys, unique constraints and foreign keys all include `tenant_id` (composite foreign keys), so a row in one tenant cannot reference a row in another, even through an application bug.
5. **Every other store.** Cache keys are prefixed `t:{tenant_id}:`. Search uses per-tenant routing or indices, plus a mandatory tenant filter. Object storage uses a per-tenant prefix, a per-tenant data key and short-lived signed URLs. Queue messages carry the tenant in the envelope.
6. **Background jobs** are scheduled and executed per tenant. No job iterates a whole table.
7. **Analytics** carries `tenant_id` on every fact, with row policies in the warehouse and the BI layer.
8. **Tests.** CI includes cross-tenant leakage tests: two tenant fixtures, with every API endpoint called using the other tenant's IDs. A lint rule blocks raw SQL outside the tenant-aware data layer. Penetration tests target isolation specifically.
9. **Observability.** Logs, traces and metrics are tagged with the tenant ID, and log scrubbing keeps personal data out of them.

## Shared resources and tenant resources

| Resource | Shared or tenant-owned | How isolation holds |
|---|---|---|
| **Platform reference data** (countries, states, currencies, bank IFSC directory, statutory pack templates, industry packs, holiday suggestions) | Shared, owned by the platform | Read-only to tenants and versioned. Tenants override through their own configuration layer, never by editing the shared copy. |
| **Compute, database clusters, caches, queues, search clusters** | Shared within a cell | Quotas per tenant, fair scheduling, and a move to a dedicated database or cell when a tenant outgrows the pool |
| **Email, SMS, WhatsApp and push gateways** | Shared providers | Per-tenant sender identity (custom email domain with SPF/DKIM/DMARC), quotas, suppression lists and delivery logs |
| **Business data, configuration, files, audit logs** | Tenant-owned | Everything in "Isolation mechanics" above |
| **Encryption keys** | Tenant-owned | A per-tenant data key under the platform KMS; bring-your-own-key for the enterprise tier later |
| **Integration credentials** (SSO, SMTP, payroll, device gateways) | Tenant-owned | A secrets vault with per-tenant paths; never stored in configuration tables |
| **Platform operators** | Shared staff | No standing access to tenant data. Support access is just-in-time, approved by the tenant, time-boxed, recorded, and visible to the tenant's administrators. |

## Control plane and cells

**Control plane** (global; holds no employee personal data):

- tenant registry: ID, slug, domains, home region, cell, tier, status
- plans, module entitlements and limits; metering of active employees for billing
- provisioning orchestration (create a tenant from packs, move a tenant, offboard)
- pack catalogue and versions; release rings; feature flags
- platform administration console; partner registry
- login discovery (email domain to tenant), holding domains only, never user records

**Cell** (regional; holds personal data): API gateway and BFF, the application, workers, PostgreSQL, cache, search, object storage, event bus, notification and integration workers, and an analytics replica.

At run time a cell depends on the control plane only through cached configuration. A control-plane outage does not stop tenants working, and a dedicated or private cell can run for long periods on its own.

## Regions and data residency

- Each tenant has a **home region**. All of its personal data stays there: database, files, backups, search, analytics and logs.
- **Start with one India region and in-country disaster recovery.** AWS (Mumbai and Hyderabad), Azure (Pune, Chennai, Mumbai) and GCP (Mumbai, Delhi) each offer two or more Indian regions.
- **Multi-location is not multi-region.** A tenant with branches across India lives in one region; latency is not an issue.
- **Tenants spanning countries** get one home region by default. If a country later requires local storage, the options are a separate tenant in that region with limited federation, or a later "satellite data" feature. Decide before selling outside India (decision D4 in Architecture 8).
- Disaster recovery replicates within the same jurisdiction. Recovery objectives are set per tier (suggested starting point: RPO 15 minutes and RTO 4 hours for pooled; tighter for dedicated).

## Tenant lifecycle

1. **Provision** from packs (country, industry, and base configuration), in minutes.
2. **Configure** in an implementation workspace: organisation, policies, workflows, templates, roles.
3. **Import** masters, employees and history with the import framework (validation, dry run, error file, idempotent re-runs).
4. **Test** in a **sandbox tenant** holding a copy of the configuration and synthetic or masked data. Promote configuration from sandbox to production as a versioned bundle.
5. **Go live**, operate, and upgrade. Configuration schemas are versioned and migrated automatically; pack updates are offered, not forced, except statutory corrections, which are flagged for HR review.
6. **Suspend** when needed (read-only, or no access).
7. **Offboard:** a full export (data, documents, audit log), then verified deletion across the database, files, search, analytics and caches. Backups expire on their retention schedule, and deleting the tenant's data key makes those copies unreadable (crypto-shredding). Issue a certificate of deletion.

## Releases without breaking tenants

- Ring-based rollout across cells: internal, then pilot tenants, then everyone. Feature flags per tenant.
- Database migrations follow expand, migrate, contract, so old and new code run side by side.
- Every configuration object carries a schema version, and each upgrade ships migrations for tenant configuration alongside database migrations.
- Canary tenants in each industry pack are tested before general rollout.
