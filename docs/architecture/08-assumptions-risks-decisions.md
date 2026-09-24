# Architecture 8 · Assumptions, risks and decisions before build

## Assumptions

Each of these shaped the design. If one is wrong, the right-hand column says what changes.

| # | Assumption | If it is wrong |
|---|---|---|
| A1 | The platform will serve **many unrelated organisations** (SaaS); SURAJ Group is the first tenant. | If it is only for SURAJ Group's companies, pooled multi-tenancy still costs little; the control plane, billing and partner scope shrink. |
| A2 | **SURAJ Group is one tenant** with several legal entities. | If each company must be a separate tenant, group dashboards, inter-company transfers and group-unique IDs need cross-tenant federation, which is expensive and risky. |
| A3 | **India first**; other countries later through packs. | If another country is near-term, country packs, currency, time zones and residency move into Phase 0–1. |
| A4 | **Cloud SaaS** on a hyperscaler with Indian regions; some tenants may need dedicated cells. | If on-premises installs are required, you need packaging (Helm, air-gapped installs, customer-run upgrades), a significant operational cost. |
| A5 | **No payroll engine in the first releases**; the HRMS holds compensation and produces payroll inputs. | If in-house payroll is chosen, the compensation model and statutory calculators join the Phase 1–2 critical path. |
| A6 | Attendance comes from **biometric devices of several vendors, mobile and web**. | A single vendor simplifies ingestion. Heavy use of offline sites needs the site gateway early. |
| A7 | **Tenant HR administrators configure rules themselves** after an initial implementation. | If not, implementation services grow linearly with tenants and margins suffer. |
| A8 | **English first**; regional languages for self-service later, with every string externalised from day one. | If regional languages are needed at launch, translation workflow and font coverage move to Phase 1. |
| A9 | Tenants range from **10 to about 200,000 employees**, with **thousands of tenants** within five years. | Much larger tenants need dedicated cells from the start, and possibly distributed PostgreSQL (for example, Citus). |
| A10 | **Government filings stay on the official portals**; the HRMS tracks work and evidence (§20). | Direct filing needs portal APIs, credentials handling and much stronger controls. |
| A11 | **Performance/KPI is out of scope** for this analysis. | The module contract accommodates it; it adds a data class and links into increment and promotion actions. |
| A12 | **No cross-tenant features** (shared candidate pools, benchmarks) in v1. | Any cross-tenant feature needs explicit consent, anonymisation and its own data model. |

## Architectural risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **Multi-company and multi-tenancy retrofitted later**, as the document's Phase 6 implies | High / Critical | Phase 0 foundation: `tenant_id`, legal entity and location dimensions in every relevant table from the first sprint |
| R2 | **Cross-tenant data leak** through a missed filter, cache key, search index, export, background job or file URL | Medium / Critical | Layered isolation (Architecture 3), RLS that fails closed, composite keys, leakage tests in CI, isolation-focused penetration tests |
| R3 | **Anchor-tenant capture:** SURAJ-specific logic hard-coded into the core | High / High | A "would tenant #2 want this differently?" review gate; every SURAJ rule expressed as configuration or pack data; a product owner separate from the SURAJ account |
| R4 | **Over-configurability** (the inner-platform effect): an engine so generic that HR cannot use it and engineers cannot test it | Medium / High | Typed policy objects with good defaults; a bounded expression language; simulation before publishing; templates instead of a BPMN designer |
| R5 | **Effective-dating bugs** in retro-dated and future-dated changes, producing wrong reports and payroll inputs | High / High | One temporal library; bitemporal records for assignment and compensation; database exclusion constraints; property-based tests; the as-of report tests in §42 |
| R6 | **Authorization complexity**, causing both leaks and slow pages | Medium / High | One model and one decision point; compiled predicates; precomputed visibility sets; a matrix test per role template |
| R7 | **India baked into the core** (UAN, ESIC IP and IFSC as core columns; an April–March year; Indian states as an enum) | High / High for expansion | An identifier registry and country packs; locale-driven validation; configurable fiscal and leave years |
| R8 | **Statutory churn:** the Labour Codes in force since 21 Nov 2025 and state rules still arriving | High / Medium | Versioned rule tables with source and verification status; tenant alerts on pack updates; the "not the legal authority" stance from §20 |
| R9 | **The payroll decision stays open** and blocks F&F, salary screens and inputs | Medium / High | Build the compensation model and the payroll input contract now (Architecture 7); keep the engine pluggable |
| R10 | **Attendance device variety and data quality** | High / Medium | An adapter framework, a site gateway, idempotent ingestion, device health monitoring, recomputation |
| R11 | **Tenant onboarding and migration cost** | High / High | The import framework with history and dry runs; pack-based provisioning; implementation playbooks |
| R12 | **Noisy neighbours and month-start peaks** | Medium / Medium | Quotas, fair queues, staggered jobs, tiering, moving tenants between cells |
| R13 | **Workflow edge cases:** an approver leaves, a reorganisation mid-flight, no manager | High / Medium | Re-resolution rules, fallback resolvers, administrator reassignment with reason, a monitor for stuck tasks |
| R14 | **Restricted data leaking through side channels:** exports, notifications, search, logs | Medium / High | Class-aware serialisation shared by every output; no restricted data in messages; export audit and watermarking |
| R15 | **Support access misuse or insider risk** | Low / Critical | Just-in-time, tenant-approved, time-boxed and recorded access; no standing access |
| R16 | **Upgrades breaking tenant configuration** | Medium / High | Versioned configuration schemas with migrations; canary tenants per industry pack; configuration validation in CI |
| R17 | **Phasing gaps:** approvals, notifications, audit and basic exit are needed in Phase 1 | High / Medium | The revised phasing below |
| R18 | **Residency demands** for new regions and tenants spanning countries | Medium / High | A home-region model now; a residency decision before selling outside India |
| R19 | **Blue-collar identity:** no email, shared phones, proxy punching | High / Medium | Employee code plus OTP with device binding; kiosk mode; selfie or geo-fence checks on mobile punches; anomaly reports |
| R20 | **Scope:** twenty modules at enterprise depth is a multi-year programme | High / High | Kernel first; a thin version of each module; strict phase gates; the §43 release principle (a module is done only when HR demonstrates the normal, approval and exception paths, history, reports and access rules) |

## Scalability concerns, in priority order

The full table is in Architecture 7. The five most likely to hurt first:

1. **Attendance** is the highest data volume and the most recomputation. Build ingestion as a separate service with a partitioned, append-only store before the first large tenant arrives.
2. **Month-start batch storms** across all tenants. Every batch job must be per-tenant, idempotent, resumable and fairly scheduled from the first version.
3. **Authorization on lists and search.** Get visibility sets and compiled predicates right early; retrofitting them into every query is painful.
4. **Dashboards and counts.** Event-maintained projections, not live aggregation.
5. **Tenant size spread.** Pooled for the long tail, dedicated databases or cells for the largest tenants. Build tenant mobility tooling early so you can move a tenant before it becomes a problem.

## Design now for future expansion

| Expansion | What to build now so it fits later |
|---|---|
| **Payroll engine** (India, then other countries) | Compensation model, pay groups and calendars, payroll input snapshots, a statutory calculator plugin interface |
| **New countries and regions** | Country packs, identifier registry, locale and currency handling, home-region cells, a UI built with logical CSS properties so right-to-left scripts are possible |
| **New industries** | Industry packs, custom dimensions, fields and objects, terminology, worker types, document types |
| **Contract labour and contingent workforce** | Worker types, agency (vendor) entities, principal-employer compliance obligations |
| **Rostering and workforce management** | Shift and roster model kept separate from attendance policy |
| **Timesheets and project allocation** | A "project" custom dimension; percentage allocations on assignments |
| **Performance** (excluded now) | The module contract; a reserved data class; promotion and increment actions that can reference a review |
| **Expenses, loans and advances, benefits and insurance, gratuity** | Generic "recoveries and payables" items feeding F&F and payroll inputs |
| **Grievance, POSH and disciplinary cases** | The Case data class with named access lists |
| **Partner and reseller console** | A partner entity and delegated administration in the control plane |
| **Marketplace and extensions** | Module contract, webhooks, public API, sandboxed functions later |
| **Analytics and AI assistance** | The semantic layer; tenant-isolated data; opt-in per tenant; every AI query audited like any other read |
| **White-label mobile apps and custom domains** | Runtime theming tokens (UI 1); a tenant configuration endpoint |
| **Government portal automation** | Country-pack outputs (file formats) on top of the existing evidence model |
| **Private or on-premises deployment** | The cell as the deployable unit; a cell that can run on cached control-plane data |

## Decisions required before implementation

These add platform decisions to the business decisions in §41, which all still stand.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Business model: SaaS for many organisations, or a group-internal platform | Build SaaS-ready (A1); it costs little extra now |
| D2 | What a tenant is | One customer organisation; SURAJ Group = one tenant with N legal entities |
| D3 | Isolation tiers offered, and their pricing | Pooled, pooled compute with dedicated database, dedicated cell |
| D4 | Cloud provider, regions and residency commitments | One India region with in-country DR; decide residency before selling abroad |
| D5 | Identity provider (build or buy) and login methods | A managed or self-hosted CIAM with per-tenant SSO and SCIM, plus mobile OTP |
| D6 | Authorization: in-house or an engine (OpenFGA, SpiceDB, Cedar) | An in-house model; optionally a relationship engine for hierarchy checks |
| D7 | Workflow runtime | A DB-backed scheduler first; Temporal if orchestration grows |
| D8 | Tech stack and team topology | Decided by team skills; one team owns the platform kernel |
| D9 | Employee number: scope, and behaviour on inter-company transfer and rejoin | Unique per tenant; configurable per tenant |
| D10 | Payroll inside or outside the HRMS (§17) | Build the payroll input contract now in either case |
| D11 | Attendance sources and device vendors (§41) | List SURAJ Group's devices now; design the adapter framework for more |
| D12 | Retention and deletion defaults per data class; DPDP roles (§41 "document retention") | Defaults per class, overridable per tenant; legal hold |
| D13 | Default role templates and access matrix (§33) | SURAJ Group's signed-off matrix becomes the default template |
| D14 | Languages at launch | English, with externalised strings; regional languages for self-service next |
| D15 | Scale targets and service levels (largest tenant, tenant count, RPO and RTO) | Confirm A9 and the suggested budgets in Architecture 7 |
| D16 | Certifications and timeline | ISO 27001 then SOC 2 Type II, planned from Phase 0 |
| D17 | Pricing metric, which drives metering | Per active employee per month, per module bundle |

## Revised phasing

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 · Platform foundation** | Tenancy and a minimal control plane; identity (SSO, OTP); authorization (roles, scopes, data classes); organisation dimensions; person, employment, assignment and personnel actions; configuration framework; workflow, obligations and the Action Centre; exceptions; audit; notifications (in-app and email); documents and letters; numbering; custom fields; import framework; terminology and i18n; this design system and the app shell; CI/CD; observability; isolation tests | Two synthetic tenants from different industry packs provisioned from packs, running the same build, with zero cross-tenant failures in the leakage suite |
| **1 · Core HR** | Organisation, Employee Master and 360, onboarding, documents, self-service, transfers and promotions through actions, **basic separation** (resignation, LWD, exited) | SURAJ Group data migrated with history; UAT items for employee creation, department change and access (§42) pass |
| **2 · Daily HR** | Attendance (ingestion, rules, corrections, period close), leave (ledger, accruals), lifecycle due dates, HR requests, SMS and WhatsApp channels, mobile self-service | A month closed end to end, with payroll inputs produced |
| **3 · Workforce** | Manpower, recruitment (with candidate-to-employee conversion), training, assets | A vacancy runs through to a joined employee with no re-entry |
| **4 · Exit and compliance** | Full exit, clearance and F&F inputs; the India compliance pack (PF, ESIC, PT, LWF) with evidence and exceptions; compliance dashboards | Monthly compliance checklist and evidence complete for one period |
| **5 · Payroll and analytics** | Payroll engine or integration; analytics store and semantic layer; management dashboards | Dashboard and report counts agree for the same scope and date |
| **6 · Expansion** | New countries and regions, further industry packs, partner console, marketplace, dedicated and private cells | Driven by the business |

Multi-company and multi-location, the document's Phase 6, are now part of Phase 0.
