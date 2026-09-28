# Architecture 5 · Identity, access, security and compliance

## Identity

- **Tenant-scoped user directories.** Each tenant has its own realm (or organisation) with its own login methods and SSO. A person who works for two tenants has two accounts. That is simpler and safer than a global identity, and tenant A never learns that someone is also in tenant B.
- **A user is not an employee.** User types: employee, candidate (pre-joining portal), contingent worker, external approver (optional), partner user (delegated, later), and platform operator (a separate realm entirely).
- **Login methods, set per tenant:**
  - SSO through SAML 2.0 or OIDC (Microsoft Entra ID, Google Workspace, Okta), with just-in-time account creation
  - password plus MFA (TOTP, WebAuthn and passkeys)
  - **employee code plus mobile OTP** for staff without corporate email, rate-limited and bound to a device
  - **kiosk mode** for the shop floor later (shared device; badge or PIN)
- **Provisioning.** SCIM 2.0 in both directions. Inbound, a tenant's IdP can create HRMS users. Outbound, the HRMS is the source of truth for joiners, movers and leavers and pushes them to the tenant's directory: this is the "company directory" integration in §34, and it automates IT clearance on exit.
- **Sessions.** Short-lived access tokens carrying tenant and user; rotating refresh tokens; step-up MFA before sensitive acts (revealing bank details, approving a salary revision, changing roles).

## Authorization: five layers

| Layer | Question | Mechanism |
|---|---|---|
| 1. Entitlement | Has this tenant licensed the module? | Control-plane plan, turned into feature flags |
| 2. Permission | May this role perform this action? | A permission catalogue `module.resource.action`, contributed by each module; roles bundle permissions |
| 3. Data scope | On which people and records? | Each role assignment carries scopes: self, direct reports, all reports, org unit (with or without descendants), locations, legal entities, entity group, a dynamic employee group, or everything |
| 4. Data class | Which fields? | Every field has a classification (below); roles are granted classes |
| 5. Conditions | In what circumstances? | Attribute rules: not your own request (segregation of duties), edit only while Draft, not in a closed period, time-bound delegation |

**Default role templates from §3**, which each tenant copies and adjusts:

| Template | Typical scope | Data classes |
|---|---|---|
| Management | Entity group or legal entities | Directory, aggregates; Financial only in aggregate |
| HR Head / Manager | Legal entities | Directory, Personal, Identity, Financial (read), Case (as named) |
| HR Executive | Assigned locations or org units | Directory, Personal, Identity |
| Department Manager | All reports (hierarchy) | Directory, limited Personal |
| Employee | Self | All of their own classes, read; corrections by request |
| Accounts / Payroll | Legal entities or pay groups | Directory, Financial, Identity (statutory numbers) |
| Admin / IT | Locations | Directory; assets and clearance items only |
| Tenant administrator | Tenant configuration | Configuration and users; **no employee data by default** |

**How it is enforced at scale:**

- One **authorization module** makes decisions for single records and **compiles scopes into SQL predicates** for lists, search, reports and exports. Nothing fetches rows first and filters afterwards.
- **Visibility sets** for hierarchical scopes (all reports of a manager) are precomputed from the closure table and refreshed by events when assignments or managers change. They are cached with a version stamp.
- **Field trimming** happens in the serialisation layer, which API responses, exports, notification templates and the search indexer all share. Restricted fields are simply not indexed for search.
- **Delegation** (§27 "alternate approver") grants time-bound approval rights. Both names are recorded on every decision.
- **Access reviews:** a quarterly certification report per tenant listing who holds which role and scope, with sign-off.
- **The access matrix is tenant data.** §33 says HR approves it, so every change to roles or grants is itself an audited, approvable change.

![Multi-Tenant Isolation Architecture & Dual-Role RLS Enforcement](diagrams/tenancy.svg)

*Figure 1: Data access enforcement — JWT Principal decoding, real-time status revocation, and PostgreSQL 16 RLS policy execution.*

## Data classification

| Class | Examples | Default visibility | Protection |
|---|---|---|---|
| **Directory** | Name, photo, designation, department, official email, work location | Everyone in the tenant (tenant can narrow it) | Standard |
| **Personal** | Personal contacts, address, date of birth, family, emergency contact | Self, HR; managers limited | Changes audited |
| **Financial** | Salary, CTC, revisions, bank account, loans, F&F amounts | Self (read), Payroll/Accounts, HR Head | Field-level encryption; masked by default; reveals logged; step-up MFA |
| **Identity** | PAN, UAN, ESIC IP, passport; Aadhaar masked only | Self, HR compliance, Payroll | Vault; blind index; masked display |
| **Case** | Exit-interview notes, grievance and POSH cases, disciplinary records, medical information | Named case roles only | Separate access lists; never inherited through the manager hierarchy; excluded from general search and exports; section hidden rather than shown as restricted |

Retention is set per class, per tenant (Privacy, below). The performance class is reserved for the excluded KPI module.

## Audit and history

- **Business history** (§28) is the effective-dated data plus the personnel-action records: what changed, from when, why, and who approved it.
- **The audit log** is the forensic layer beneath it: append-only, **tamper-evident** (a hash chain per tenant, anchored daily to write-once storage). It records who (user, on-behalf-of, support session), what (entity, fields before and after, with restricted values tokenised), when, where (IP, device, channel: UI, API, import, integration or system job) and why (reason, action ID).
- **Sensitive-read log**: every view or reveal of Financial, Identity or Case data, and every export.
- Tenant administrators can search the audit log, and it can be streamed to a tenant's SIEM (syslog or webhook).

## Security baseline

- TLS 1.2 or later in transit (1.3 preferred); KMS encryption at rest; envelope encryption with per-tenant data keys for Financial and Identity fields; bring-your-own-key for the enterprise tier later.
- Secrets in a vault. **No government portal passwords stored** (§20 "Employer login" is a link).
- Files: malware scanning, content-type checks, size limits, private buckets, short-lived signed URLs, optional watermarking on exports of restricted documents.
- Application: OWASP ASVS level 2 (level 3 for authentication and cryptography), SAST, DAST and dependency scanning, SBOMs, container scanning, WAF, rate limits per tenant and per user, abuse protection on OTP endpoints.
- Operations: least privilege, just-in-time production access through a bastion, every session recorded.
- Certifications enterprise buyers will ask for early: **ISO/IEC 27001** (with 27701 for privacy) and **SOC 2 Type II**.

## Privacy and regulation (India first, ready for more regions)

This is architectural guidance, not legal advice. Confirm obligations and dates with counsel.

- **India's DPDP Act 2023** and the **DPDP Rules notified in November 2025** phase obligations in over roughly 18 months. The **tenant is the Data Fiduciary; the platform is the Data Processor.** The platform must provide:
  - privacy notices and employee acknowledgement (reusing the Policies module)
  - purpose tags on data categories
  - retention schedules with automated purge or anonymisation, overridden by legal hold
  - data-principal requests (access, correction, erasure, grievance) as a workflow with deadlines
  - breach detection and notification support
  - processing records, a subprocessor list, and a data processing agreement with each tenant
- **Candidates** are not employees: recruitment data needs its own notice and a shorter retention period (§11).
- **Aadhaar**: do not collect the full number unless the tenant has a legal basis to. Store it masked (last four digits) or through a compliant vault; prefer DigiLocker-style verification later.
- **Deletion reaches everywhere**: database, files, search, caches, analytics; backups by expiry plus crypto-shredding at tenant offboarding.
- **Other regions** (GDPR, UK GDPR, UAE, Saudi Arabia, Singapore) are handled through regional cells, per-region retention defaults, data-subject request tooling and transfer mechanisms, when the business expands.
