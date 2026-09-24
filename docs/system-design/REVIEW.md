# Design review: HRMS Platform System Design v1.0

Reviewer: Claude, reviewing its own draft · 21 Sep 2026 · Scope: [README.md](README.md) (the system design), plus the earlier architecture sections and the design system where they disagree.

**Verdict.** The foundations are right: pooled tenancy with RLS and dedicated tiers on the same schema, effective-dated personnel actions, outbox-driven thin webhooks, contract-first APIs with breaking-change gates, data classification, and the capability map. Four things would cause rework if built as written:

- the launch footprint is far too big for the team it assumes
- the identity design doesn't match how Keycloak actually works
- there is no model for customers whose employee master lives in another system
- the design breaks its own cell-isolation rule in several places

Several vendor and region claims are also unverified. None of this needs a new architecture. It needs a launch-versus-target split and about a dozen targeted fixes.

Severity: **Critical** means fix before any build starts. **High** means fix before the component it touches is built. **Medium** means fix during the phase. **Low** means clean up.

## Critical

**C1. The launch architecture is the target architecture, and it is too big.**
- **Problem:** Phase 0 stands up the following per cell or region: Aurora, MSK plus Debezium, Temporal, OpenSearch, Valkey, Svix, Kong, Keycloak, ClickHouse plus Cube, the Grafana stack, Shield Advanced, Network Firewall, and one AWS account per cell. That contradicts the stated goal, "operable by a small team", and the first-year cost is high. Shield Advanced alone is about USD 3,000 a month; Network Firewall is billed per AZ-hour before any traffic.
- **Fix:** define a **launch architecture** and a **target architecture**, with an explicit trigger for each addition:
  - At launch: one cell running Aurora, S3, Valkey and the app.
  - An outbox table relayed by the app instead of Debezium and Kafka.
  - A PostgreSQL-backed job scheduler (for example db-scheduler or JobRunr) instead of Temporal.
  - PostgreSQL full-text search instead of OpenSearch.
  - WAF without Shield Advanced.
  - No ClickHouse until Phase 5.
- Keep the interfaces (outbox, scheduler port, search port) so each component can be swapped later without touching modules.

**C2. The identity design assumes things Keycloak does not do.**
- In Keycloak, **clients belong to realms, not organisations**. "OAuth clients per tenant in the tenant organisation" and "tokens bound to one tenant" need a custom tenant attribute and a protocol mapper that we write and test.
- The **partner-app install flow** (tenant-admin consent, installation records, revocation of every token an installation issued) is not a Keycloak feature. Keycloak consent is per user and client. We would have to build that service.
- Running **thousands of organisations, each with its own external IdP**, in one realm is unproven for this design.
- **Fix:** run an identity proof of concept before Phase 0 ends:
  - 2,000 organisations with per-org SAML/OIDC
  - OTP login
  - a tenant claim on client-credentials tokens
  - an installation service that we own
- Compare Keycloak with Zitadel and one managed CIAM on the same script. Record the result as an ADR.

**C3. There is no model for "the HRMS is not the system of record".**
- **Problem:** enterprise customers often keep SAP, Oracle or Workday as the employee master and buy this platform for attendance, leave or compliance. The API forces every employment change through `POST /personnel-actions` with approval workflows. A nightly sync of 50,000 employees would create 50,000 approval workflows.
- **Fix:**
  - Add **master-data ownership per tenant and per field group**: HRMS-owned, externally owned (read-only in the UI), or shared with conflict rules.
  - Add an **integration action policy**: system-to-system actions are applied directly and audited as integration changes, with a tenant-configured approval exception.
  - Add a bulk personnel-action endpoint for reorganisations and syncs.

**C4. The design breaks its own cell-isolation rule.**
- The document says "cell data stores never shared across cells", yet Keycloak, Kong, ClickHouse and Cube are shared per region.
  - A Keycloak or Kong outage takes down every cell in the region.
  - ClickHouse holds every tenant of the region in one store.
- The control plane "holds no employee personal data", yet it counts active employees from `employee.*` events.
- **Fix:**
  - Cells send the control plane **daily aggregates only** (tenant, date, active count).
  - Either move analytics into each cell, or state explicitly that regional analytics is an accepted shared dependency, with row policies and its own blast-radius analysis.
  - Run identity and gateway as **per-region, multi-AZ, independently deployable** stacks with their own error budgets, and document them as the regional shared tier.

## High

**H1. The web app holds bearer tokens in the browser, and our own apps spend customers' API quotas.**
- **Problem:** the design has the SPA call the public API directly with access tokens. The OAuth guidance for browser apps recommends a backend-for-frontend (token handler) with httpOnly cookies. Routing our own apps through the same plans also means a busy HR team's clicks count against the tenant's API quota.
- **Fix:** add a thin BFF or token-handler for web (the earlier Architecture 7 already proposed a BFF). Register first-party apps as a separate client class with their own limits. Keep dogfooding at the level of API contracts, not quotas.

**H2. The API does not say what an "employee" is.**
- **Problem:** `/v1/employees/{id}` sits beside `employmentId: "emp_…"`. A rehire or inter-company transfer creates a new employment, so integrators keyed on that ID lose the person.
- **Fix:** expose a stable **worker** (person-level) ID, for example `/v1/workers/{workerId}` with `/employments` and `/assignments` underneath. Document which ID survives rehire and transfer. Include both IDs in every event.

**H3. Integration apps have scopes but no data scope.**
- **Problem:** a client-credentials app with `employees:read` sees the whole tenant.
- **Fix:** give app installations the same data-scope model as roles (legal entities, locations, employee groups) and field-class limits, shown on the consent screen and enforced in the same compiled predicates.

**H4. The biometric device path assumes capabilities many devices lack.**
- **Problem:** many deployed attendance terminals push over **plain HTTP** to fixed paths and cannot present client certificates. The mTLS-everywhere ingestion design would exclude them, or tempt someone to open an unauthenticated endpoint.
- **Fix:** make the **site agent the default** for LAN devices. For direct-push devices, run a separate hardened ingest edge with a device-serial allowlist, per-device secrets where the firmware supports them, IP restrictions, and strict payload validation. List supported models per protocol once D11 is known.

**H5. Access revocation is eventually consistent.**
- **Problem:** visibility sets are refreshed "by events", so a manager removed from a team can keep seeing that team until the refresh lands.
- **Fix:** grants may propagate asynchronously, but **revocations must be synchronous**: invalidate in the same transaction, or version-stamp the caches and check the stamp on every request. Add a test that revokes access and reads immediately.

**H6. A per-tenant audit hash chain becomes a write bottleneck.**
- **Problem:** each entry hashing the previous one serialises every write for a large tenant.
- **Fix:** write audit entries freely. Seal them in short batches (for example every minute) with a Merkle root per tenant, and anchor the roots in S3 Object Lock. The evidence is equally tamper-proof and there is no hot row.

**H7. The disaster-recovery targets are optimistic for a pilot-light standby.**
- **Problem:** a 1-hour RTO needs the control plane, routing map, Keycloak, Kong, Aurora, MSK, Temporal, OpenSearch and S3 all failed over and verified. Pilot light usually takes several hours.
- **Fix:**
  - Run the control plane, identity and gateway **warm** in Hyderabad.
  - Keep cells pilot-light for pooled tenants, with an honest 4-hour RTO.
  - Offer warm standby only to Enterprise cells at a price.
  - Publish a per-component failover order and rehearse it before promising any RTO in a contract.

**H8. Bitemporal storage is harder than the document suggests.**
- **Problem:** PostgreSQL has no built-in system versioning. Transaction-time history needs triggers or application code. The temporal constraint syntax (`WITHOUT OVERLAPS`) arrived only in PostgreSQL 18, and Aurora support must be checked.
- **Fix:** specify one temporal library (application-level history writes plus gist exclusion constraints, which work today). Budget it as Phase 0 work with property-based tests. Limit transaction-time history to assignment and compensation.

**H9. The consequences of field-level encryption are missing.**
- **Problem:** decrypting salary, bank and identity fields per read will hit KMS request quotas. Encrypted salary also cannot be summed in SQL, which breaks payroll reports and compensation analytics.
- **Fix:** name the exact encrypted fields. Use envelope encryption with **cached data keys** (the AWS Encryption SDK caching pattern). Decide where compensation aggregates are computed (in the application or in a restricted analytics dataset) before building reports.

**H10. Tenant ID as a metric label will blow up metrics cardinality.**
- **Problem:** thousands of tenants × routes × status codes as label combinations is expensive and slow in Mimir or Prometheus.
- **Fix:** keep `tenantId` in traces and logs. Put it in metrics only for aggregated per-tenant SLO series, or for the top-N tenants by traffic.

**H11. Three documents now disagree.**
- **Problem:** the design system's Architecture sections, `docs/architecture/`, and this system design differ. Examples: "DB-backed scheduler first" versus Temporal as ADR-06; "BFF per surface" versus the Experience API with direct calls.
- **Fix:** make `docs/` in the repository the single source. Mark the design-system Architecture sections as superseded, with a link. Generate the published pages from the repository.

## Medium

- **M1. Moving a tenant between tiers "freezes writes".** A large tenant would be down for hours. Use logical replication, then a short cutover, for tenants above a size threshold.
- **M2. Search visibility tags force reindex storms on reorganisations.** Filter by the allowed org-unit and location IDs at query time instead of stamping every document.
- **M3. Custom fields (JSONB) are not solved in analytics, CDC or search.** Define how tenant-defined fields reach ClickHouse and Cube (per-tenant views, or a typed side table) and which are searchable.
- **M4. The API has no durable change feed and no erasure event.** Add `/v1/changes?since=<cursor>` per resource family for polling integrators, and a `person.erased` event so connected systems delete data when a DPDP erasure runs.
- **M5. Thin-only webhooks push work onto customers.** Allow opt-in inclusion of Directory-class fields per endpoint; keep restricted classes out.
- **M6. Names are inconsistent.** Examples: `personnel_action.*` versus `leave.request.*`, and `absence.leave-request.v1` versus `leave.request.approved`. The path `/v1/org/org-units` repeats itself. Fix the naming guide before the first public endpoint ships.
- **M7. "New enum values are additive" breaks strictly typed SDKs.** Generate SDKs that tolerate unknown enum values, and say so in the versioning policy.
- **M8. Most Kong features the design relies on are Enterprise or Konnect.** Rate limiting by tenant claim, OpenAPI request validation, and tenant-to-cell routing need custom plugins or a paid tier. Cost it, or prototype on Kong OSS or Envoy with our own plugin (D18).
- **M9. "Embedded Svix portal" is unverified for self-hosted Svix.** The consumer portal may be a cloud-only feature. Verify it, or plan our own endpoint-management UI.
- **M10. Region and vendor availability is assumed, not checked.** MSK Serverless, Temporal Cloud and ClickHouse Cloud in Mumbai; Aurora Global Database and the full service list in Hyderabad; AWS Marketplace in INR. Verify before the ADRs are accepted.
- **M11. Support access needs a break-glass path.** "Tenant-approved" access blocks a 3 a.m. incident. Add break-glass with two-person approval on our side, automatic tenant notification and post-incident review.
- **M12. There is no configuration explainability and no configuration regression testing.** HR will ask "why did this employee get 5 minutes' grace?". Add a "trace this value" view and API over the configuration layers. Before each release, replay every tenant's published configuration through policy tests.
- **M13. Mobile and site-agent integrity is thin.** Device clock spoofing on offline punches (use server receive time plus a monotonic device clock and attestation). The site agent needs code signing, automatic updates and certificate rotation.
- **M14. Custom domains at scale need a plan.** Per-tenant hostnames and certificates hit CloudFront distribution limits. Use CloudFront's multi-tenant (SaaS) distribution features, or a shared wildcard domain plus opt-in custom domains.
- **M15. Some subprocessors sit outside India** (Sentry SaaS, Chargebee, PagerDuty, the GRC tool, docs hosting). This is allowed under DPDP unless the destination is restricted, but enterprise contracts may promise in-country processing. Keep a subprocessor register and self-host where a promise is made.
- **M16. One Temporal workflow per request gets expensive at scale.** Millions of leave, correction and approval workflows a month on usage-priced Temporal Cloud will cost real money. Model the cost, or keep simple approvals in the database-backed engine.
- **M17. Setting the tenant per transaction has sharp edges.** Reads in autocommit mode, or any session-level `SET`, bypass or leak the setting across pooled connections. Enforce "every statement inside a transaction that sets the tenant" in the data layer, and make RLS fail loudly (not silently empty) when the setting is missing. The document's "returns no rows" is the wrong failure mode to aim for.

## Low

- **L1.** Ten teams from Phase 0 is not a startup org chart. Start with three (platform and core HR; API and integrations; experience) plus shared SRE and security, and split as the headcount allows.
- **L2.** The API plans, limits and four SDK languages are guesses. Validate them with two or three design partners; start with TypeScript and Python SDKs.
- **L3.** The ADRs are one-line rows. Each needs context, the options considered, consequences and a revisit trigger (MADR format).
- **L4.** Diagram fixes:
  - AWS: the replication arrow leaves the Aurora reader instead of the writer.
  - Containers: the edges from satellites to Kafka and Temporal are missing.
  - The ERD is dense; split it per module.
- **L5.** The design system is plain CSS while the stack is React. Add "React component library from the design system" to Phase 0.
- **L6.** The licence stack (Kong Enterprise, Temporal Cloud, Speakeasy or Stainless, Redocly, Vanta or Drata, PagerDuty, Sentry, Statuspage, Carbone, e-sign) isn't budgeted. Early on it could cost more than the infrastructure.
- **L7.** The roadmap has no durations or effort estimates, so it can't be planned against.

## Recommended fixes, in order

1. Split the document into a launch architecture and a target architecture, with triggers (C1, L6, M16).
2. Run the identity proof of concept and decide the CIAM (C2).
3. Add system-of-record ownership and integration action policy (C3).
4. Fix the API identity model, app data scopes, first-party client class and web BFF (H1–H3).
5. Resolve the isolation contradictions and make the control plane aggregate-only (C4).
6. Make revocation synchronous and fix the tenant-setting failure mode (H5, M17).
7. Specify the temporal storage, audit sealing and field encryption (H6, H8, H9).
8. Rework DR tiers and set honest RTOs (H7).
9. Make `docs/` the single source of truth (H11).
10. Verify vendor and region availability before accepting the ADRs (M8–M10).
