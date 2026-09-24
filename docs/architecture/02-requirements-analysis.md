# Architecture 2 · Requirements analysis

A module-by-module reading of the requirements. For each module, **Implies** is the hidden work behind the words, **Generalise** is what changes when the module must serve many tenants and industries, and **Open** lists questions the document leaves unanswered. KPI and performance content is excluded.

## Overall assessment

The document is strong on business behaviour: statuses, approvals, reminders, exceptions and history are specified module by module, and it states the right principles (enter once, effective dates, configurable rules, "not disconnected screens"). What it doesn't cover is the platform underneath. Every module assumes an approval engine, a reminder engine, effective-dated history, an access model and document storage, but none of these is specified as a shared capability. Built module by module, the result would be the "disconnected screens" that §43 warns against. The biggest architectural job is therefore to specify and build those shared capabilities first (Architecture 6), then build the modules on them.

Three patterns recur in almost every module and should each be built once:

| Pattern | Where the document asks for it | Build it once as |
|---|---|---|
| Change with effective date, reason, approval, history | §5, §7, §14, §17, §28 | **Personnel actions** on effective-dated records (Architecture 4) |
| "Remind at 30/15/7 days, then escalate; overdue stays visible until done or excepted" | §14, §19, §20, §21, §22, §26 | **Obligation engine** feeding the Action Centre (Architecture 6) |
| "Approved special handling outside the normal process" | §9, §19, §20, §29, §30, §39 | **Exception records**: reason, approver, validity, evidence (Architecture 6) |

## Organisation (§2, §32)

- **Implies.** Masters change over time: departments merge, branches close, designations are renamed. Historical reports (§42 "Historical report") must show the structure *as it was*, so org units, locations and jobs need effective dating, not just employee records. "HOD" is a role held on a unit, not a field on an employee.
- **Generalise.** Split the chain into dimensions (legal entity, location, org unit, job and grade, position, cost centre, reporting line, custom), each with tenant-defined types and depth (Architecture 4). Industry packs supply sensible defaults: plants, lines and shifts for manufacturing; regions and stores for retail; facilities, departments and units for healthcare.
- **Open.** Can a branch host employees of more than one company? This is common in groups with shared offices, and the model must allow it. Can a department span companies? Is "Group" only a consolidation level for reporting, or does it own policies?

## Users and access (§3, §33)

- **Implies.** Roles are scoped ("daily HR work *assigned to them*"), so a role alone is not enough; each assignment needs a data scope. Restrictions are field-level (salary, bank, identity, statutory, private exit data), not screen-level. "HR and Accounts access separated" is a segregation-of-duties rule.
- **Generalise.** The eight roles become default **role templates** every tenant starts from and can copy and edit. "Super Admin" splits in two: a **Tenant administrator** (the customer's configuration owner) and a **Platform operator** (your staff, with no standing access to tenant data).
- **Open.** The final access matrix (§33 says HR approves it). Get SURAJ Group's matrix signed off; it becomes the default template for all tenants.

## Statuses and definitions (§4, §39)

- **Implies.** Statuses drive logic, dashboards and reports, so each needs a stable system code and a *category* (not started, open, waiting, done-positive, done-negative, cancelled, exception) for counting across modules and tenants. Tenants may rename labels but not categories.
- **Finding.** The Employee statuses mix two dimensions: *employment state* (Active, On Notice, Exited, Hold) and *service stage* (Probation, Confirmed). As one field, "on notice during probation" cannot be represented. Model them as two fields.
- **Open.** What does "Hold" block? Payroll inputs, system access, approvals, or only reporting?

## Common rules, history and data quality (§5, §28, §30)

- **Implies.** Bitemporal storage for the records that matter (Architecture 4); reason codes per action type; attachments on any action; uniqueness scopes ("Employee ID unique": per tenant? per company?); database-enforced non-overlap for leave and effective-dated records; duplicate detection that is exact on PAN, UAN and mobile and fuzzy on name plus date of birth.
- **Generalise.** Reason codes, required-document rules by employee type, and the duplicate-match rules are tenant configuration.
- **Open.** Employee ID scope and format; what happens to the ID on inter-company transfer and on rejoin.

## Dashboard and Action Centre (§6, §31)

- **Implies.** Every number is scope-aware (the user's companies, locations and teams) and must equal the report behind it (§30 "consistent definitions"). The Action Centre is one inbox fed by three sources: workflow tasks, obligations and exceptions.
- **Generalise.** Modules contribute dashboard cards and Action Centre item types through the module contract; tenants choose which cards each role sees. Metric definitions (Active Employee, New Joiner, Vacancy, Overdue, from §39) live in one semantic layer.
- **Scale.** Counts come from event-maintained projections per scope, not live aggregation on each page load (Architecture 7).

## Employee Master and Employee 360 (§7, §8)

- **Implies.** Person, Employment and Assignment are separate records (Architecture 4). Employee 360 is a composed read model across modules, trimmed section by section by the viewer's access.
- **Generalise.** The Statutory section comes from the country pack (UAN and ESIC IP for India, other identifiers elsewhere); the Bank section validates per country (IFSC in India, IBAN elsewhere). Tenants add custom fields and sections.
- **Open.** Are concurrent employments possible (one person employed by two group companies at once)? Is dual reporting (a solid and a dotted line) needed?

## Onboarding (§9)

- **Implies.** A checklist engine with templates by company, location and employee type; a pre-joining portal for people who are not yet employees (a separate identity type); pre-joining data flowing into the employee record (§11 rule).
- **Generalise.** Onboarding templates come in industry packs: medical fitness for food and factory work, police verification for security staff, licence checks for drivers.
- **Open.** Is the employee record created at offer acceptance (a *pre-hire* employment state, recommended) or on the joining day?

## Manpower planning (§10)

- **Implies.** A headcount plan per company, location, org unit, job and period; a requisition workflow; links between vacancy, requisition and the employee being replaced. "Sanctioned vs current" is an as-of count that needs agreed definitions: do trainees and contract staff count?
- **Generalise.** Two modes per tenant: *position-based* (a seat per approved position, typical of large enterprises) and *budget-based* (N heads per unit, typical of smaller tenants). Allow FTE as well as heads, and seasonal plans for retail.
- **Open.** Who approves sanctioned strength, and how often?

## Recruitment (§11)

- **Implies.** Candidate data is personal data of people who are not employees, so it needs a notice, retention limits and deletion. Duplicate checks run within the tenant only. Interviews need calendar integration. Offers need approval, and conversion reuses everything collected.
- **Generalise.** Pipeline stages are configurable per tenant and job type: bulk blue-collar hiring and multi-round managerial hiring look different. Sources are configurable, with job-board connectors later.
- **Open.** Is a career site or candidate portal in scope? What is the retention period for rejected candidates?

## Attendance (§12)

- **Implies.** This is the highest-volume, most error-prone module. It needs ingestion from devices, mobile and web; rosters and shifts (rotational, night, split); a **deterministic, re-runnable computation** of each employee-day from punches, roster, policy, leave, holidays and approved corrections; corrections as overlays that never overwrite punches; and a period close per company or pay group (§12 rule).
- **Generalise.** Attendance policies (grace, late and early thresholds, half-day rules, overtime, missing-punch handling, WFH and OD eligibility) are policy objects assigned by scope (Architecture 6). Capture methods are set per location: biometric, geo-fenced mobile, selfie, kiosk, web. Night shifts mean the attendance date is not the punch date. Time zones come from the location.
- **Open.** Device vendors and protocols; whether contract workers use the same devices; overtime rules by state and establishment type.

## Leave (§13)

- **Implies.** Balances come from a **ledger** (credit, debit, lapse, encash, adjust), never a single mutable number, so every balance is explainable and recomputable. It also needs an accrual engine, pro-rata rules, carry-forward and expiry jobs, sandwich rules (weekends and holidays inside a leave span), half days, compensatory off, and encashment feeding F&F and payroll.
- **Generalise.** The leave year is per tenant (calendar or April–March). Statutory minimums come from packs (for example, factory and shops-and-establishments rules differ by state). Leave types and policies are scoped and effective-dated.
- **Open.** Leave year; negative-balance rules; how loss of pay reaches payroll.

## Employee Lifecycle (§14)

- **Implies.** Each event is a personnel action with approval, a letter and due-date rules. **An inter-company transfer is legally a separation from one employer and a hire by another** (new appointment letter, PF transfer, a decision on gratuity continuity), so model it as two linked employments, not an attribute change (Architecture 4).
- **Generalise.** Action types and reason codes are configurable. Due rules (probation length by grade or type, extension limits) and reminder offsets (30/15/7) are configuration with the document's values as defaults.
- **Open.** The increment cycle (annual date or work anniversary); letter templates and signatories per company.

## Training (§15)

- **Implies.** Programmes, sessions, nominations, attendance, feedback forms, certificates as documents, and effectiveness follow-ups as obligations. Many industries also need **mandatory, recurring training** with certificate validity (safety, POSH, food hygiene).
- **Generalise.** Training types, feedback forms and recurrence per tenant; external trainers and vendors. LMS integration (SCORM/xAPI) later.

## Payroll and salary (§17)

- **Implies.** A compensation model (components, formulas, CTC structure), effective-dated revisions with arrears, pay groups and pay calendars, and **locked, versioned payroll-input snapshots** per period whether payroll runs inside or outside the HRMS.
- **Decision still open** (§17, §41). Architecture 7 defines the Payroll Input contract to build now, so the decision does not block other modules.
- **Note.** Statutory wage definitions affect PF and ESIC bases. India's four Labour Codes took effect on 21 November 2025 and change how "wages" are defined; confirm the current position with your compliance owner before any calculation is built.

## Assets (§18)

- **Implies.** An asset register (catalogue, serial numbers, states: in stock, issued, in repair, lost, retired) with assignment history, not only "issued to" records. Clearance reads from it automatically (§18 rule).
- **Generalise.** Asset types and their fields per tenant and industry: vehicles, tools, uniforms, PPE, SIM cards.
- **Open.** Is this an employee-asset tracker or a full IT asset system? Larger tenants will want to integrate their existing IT asset tool instead.

## Exit (§19)

- **Implies.** An exit case with its own state machine; notice computed from policy (buy-out and waiver included); a change of last working day re-plans clearance dates (§29); clearance tasks per owner with assets pulled in; F&F inputs (salary to LWD, leave encashment, gratuity, notice recovery, loans and advances); confidential exit interview; letters; statutory exit updates; a rehire flag that recruitment reads.
- **Generalise.** Separation types (resignation, termination, retirement, death, absconding, end of contract, VRS) run different flows. Clearance templates vary by company and location.
- **Open.** Who computes F&F: the HRMS, Accounts, or a payroll system?

## Statutory Compliance, PF and ESIC (§20, §44)

- **Implies.** A compliance calendar of periodic obligations per **establishment registration** (PF and ESIC codes belong to a legal entity, and sometimes to a location as a sub-code), an evidence store, exceptions, employee statutory profiles, and rule tables with effective dates, source references and a verification status.
- **Generalise.** A **country pack** defines obligation types (for India: PF ECR monthly, ESIC monthly, Professional Tax by state, LWF by state, TDS and more), due-date rules, applicability rules, evidence checklists and official links. The links in §20 and §44 become pack data with a "last verified" date.
- **Security finding.** "Employer login" (PF and ESIC, Employer/HR) must be a **link to the portal's login page**. The HRMS should never store government portal credentials. If a tenant insists, credentials go to a vault with named access and full logging.
- **Open.** Who owns PF and ESIC, HR or Accounts? Make this per-tenant configuration.

## Documents (§21)

- **Implies.** Versioned storage where a replacement never deletes the old version (§21 rule), a verification workflow, expiry tracking, retention schedules, legal hold, generated company letters from templates, and e-signature later.
- **Generalise.** Document types per tenant, industry and country, each with required-by rules (by employee type, location, job), expiry rules and a data class. Examples: work permits, nursing council registrations, driving licences, food-handler certificates.
- **Caution.** Aadhaar numbers: collect only if legally required, and store masked unless the tenant is permitted to hold the full number.

## HR Requests and helpdesk (§22)

- **Implies.** Ticketing with SLA calendars (business hours per location and holiday calendar), assignment rules, escalations, and request types that can launch a workflow (a correction request becomes an approved change).
- **Generalise.** Categories, SLAs and assignment rules per tenant. Employee "Request correction" (§25) is a request type that ends in a personnel action.

## Policies (§23)

- **Implies.** Versioned policy documents, audience rules as dynamic employee groups, acknowledgements recorded with version, time and channel, re-acknowledgement when a version changes, and reminders.
- **Generalise.** Policies per company or location, in several languages; acknowledgement doubles as an onboarding checklist item.

## Reports (§24)

- **Implies.** As-of and period reports from effective-dated data; filters that map to dimensions; row and field trimming by access; logged exports; scheduled delivery.
- **Generalise.** The document's filters (company, branch, department) become the tenant's dimensions with the tenant's terminology. A custom report builder comes later, on the same semantic layer.

## Employee self-service and mobile (§25, §35)

- **Implies.** Many shop-floor and field employees have no corporate email and may share phones, so login needs employee code plus mobile OTP, and possibly kiosks. Mobile-first flows for the common tasks; notification preferences; regional languages.
- **Generalise.** Self-service modules can be toggled per tenant; kiosk mode per location.

## Notifications, reminders and escalation (§26)

- **Implies.** Rule-based reminders (offsets before and after due dates), recipients resolved by role within scope, escalation chains, channels, templates per language, quiet hours and digests.
- **Generalise.** The document's reminder table ships as the default configuration in the base pack; each tenant edits it.

## Approval framework and exceptions (§27, §29)

- **Implies.** Conditional chains (sequential and parallel), approver resolution by rule, alternates and delegation, segregation of duties (no self-approval, maker different from checker), SLA and escalation, a reason on reject, and full history. "No manager" (§29) becomes a data-quality check plus a fallback approver.
- **Generalise.** One engine with versioned definitions per tenant and process (Architecture 6).

## Integrations (§34)

Covered in Architecture 7. The rule "identify integration requirements now" is right: attendance devices, payroll, directory and SSO, and the email and messaging channels all shape the data model even when they are built later.

## Implementation phases (§37)

The proposed phases have dependency gaps:

- **Multi-company and multi-location (Phase 6) must move to a Phase 0 foundation.** They are data-model decisions, not features.
- **Approvals, notifications and audit (Phase 2) are prerequisites of Phase 1.** Onboarding, documents and employee changes already need them.
- **Exits happen from the first day of go-live.** Phase 1 needs at least a basic separation (resignation, LWD, exited status); full clearance and F&F can stay in Phase 4.
- **Transfer and promotion are listed as Employee Master actions (Phase 1) but Lifecycle is Phase 2.** The personnel-action framework must exist in Phase 1.

Architecture 8 proposes revised phasing.

## Gaps the document does not cover

An enterprise multi-tenant platform also needs these. They should be designed for now even where they are built later.

- **Tenant lifecycle:** provisioning, plans and module entitlements, sandboxes, data export and verified deletion at offboarding.
- **Data migration and bulk import,** including history. This is the largest single cost in onboarding a tenant.
- **Platform and support access controls:** time-boxed, tenant-approved, logged.
- **Privacy operations:** data-principal requests, retention and purge, breach support (DPDP).
- **Contract labour and contingent workers** (agency staff, apprentices, interns). This is common in manufacturing and needs compliance tracking for the principal employer.
- **Shift rostering,** separate from attendance policy.
- **Letters and templates engine** (appointment, confirmation, relieving) with e-signature.
- **Announcements** (§25 mentions "important notices" but no module owns them).
- **Loans and advances** (referenced by Accounts clearance and F&F, but with no owner).
- **Grievance, POSH and disciplinary case management,** with the strictest access class.
- **Org charts,** and later reorganisation modelling.
