# 1 · Platform foundations: what makes every module configurable from the UI

The requirements list about twenty modules. Under the business wording they all need the same dozen capabilities: roles, masters, custom fields, scoped rules, approvals, due dates and reminders, notifications, exceptions, documents, letters, numbering, import and history. If each module builds its own copy, HR ends up with twenty different settings screens, and some rule somewhere is still fixed in code. This file specifies each capability **once**. Every module in [02-modules.md](02-modules.md) is then built on top of them.

The target architecture is already described in [docs/architecture/06](../architecture/06-configuration-workflow-rules.md) and [05](../architecture/05-identity-access-security.md). This file is the **build specification**: for each capability, what the code has today, what to add, what the admin screens are, the guardrails, and the first module that uses it.

> **Rule from the critique (C-01):** no foundation ships alone. Each one is delivered together with its *first consumer*, a real module screen that uses it, so HR sees value in every release and the design is proven against a real case.

---

## F1 · Access control builder (roles, permissions, scopes, data classes)

**Today.** There are five system roles: `SUPER_ADMIN`, `HR_MANAGER`, `MANAGER`, `EMPLOYEE` and `ACCOUNTANT`. Their permissions are a Python dictionary (`ROLE_PERMISSIONS` in `core/authz.py`). The `roles` table has no link to permissions. That means a role created in the database gets **no permissions at all**: a tenant cannot make an "HR Executive – Plant 2" or "Admin/IT" role without a code change. Role assignments do carry scopes (`ALL`, `LEGAL_ENTITY`, `ORG_UNIT`, `SELF`, `DIRECT_REPORTS`, `ALL_REPORTS`) and an expiry. The frontend also decides navigation from role *names*: `primaryRole()` maps `HR_MANAGER` and `ACCOUNTANT` to "HR". So a custom role would also break the menu.

**Build.**

| Object | Contents |
|---|---|
| Permission catalogue (code-registered, read-only in UI) | `module.resource.action` key, module, label, description, risk level (normal / sensitive / critical), implied permissions. Each module registers its own permissions at start-up. |
| Role (tenant data) | Name, description, permissions (many), data classes granted, `is_template`, `is_system` (system roles can be copied but not deleted), status. |
| Data classes | Directory, Personal, Identity, Financial, Case, Medical. Fields declare their class; serializers trim by class (architecture 05). |
| Role assignment (exists, extended) | User, role, **scope**, effective from/to, granted by, reason. New scope types: `LOCATION`, `EMPLOYEE_GROUP` (F4) and `MULTI` (a list of entities, locations or units). |
| Segregation-of-duties rules | Pairs of permissions one person may not hold on the same record type, for example `bank.change.request` + `bank.change.approve`. Warnings appear at grant time; the block is enforced at action time. |

**Admin UI** (Settings → Access):

- **Roles.** List, copy from template, edit with a permission matrix grouped by module (checkboxes, with a "sensitive" badge), data-class toggles, and a "who has this role" tab.
- **Users and access.** Assign roles with a scope picker that shows entity, location, unit and group trees, plus a validity window and a reason.
- **"View as" preview.** Pick a user to see their menu, their visible employee count and the fields they can see. HR uses it to check access before go-live, and it does not log in as that user.
- **Access review.** A quarterly certification list (who has what), with sign-off stored. Exportable.
- **Who signs off the access matrix (D-1, decided 2026-10-09): the Admin** (tenant administrator / super admin), not HR as §33 of the requirements suggests.
  - Before A1 switches over, the default role templates are presented to the Admin as an access-matrix page (roles × permissions × scopes × data classes) and approved.
  - After that, every role or grant change and every quarterly access review is signed off by the Admin in the app. The sign-off is stored with the version.

**Guardrails.**

- The last active tenant administrator cannot be removed or downgraded.
- Granting a *critical* permission (roles, bank change approve, compensation write) requires step-up MFA and is logged. It can optionally need approval (F6, request type `ACCESS_CHANGE`).
- Tenant administrator ≠ HR. The administrator template has **no employee data classes** by default, so a tenant can split IT administration from HR.
- **No acting on your own sensitive record (C-35).** HR and admin permissions never apply to the user's own employment for Personal, Identity or Financial changes: bank, salary, grade, statutory IDs. Those go through self-service and another person's approval, whatever role the user holds.
- **Settings are scoped like data (C-49).**
  - Every configuration object carries an *owner scope*: policy assignments, flow routes, templates, reminder overrides, bypass settings.
  - Settings permissions (`settings.time.write`, `settings.leave.write`, …) are checked against that scope. A company's HR can maintain that company's attendance rules, notice periods and bypass settings, but not another company's.
  - Tenant-wide objects need tenant scope.

**Migration from today.**

1. Seed the permission catalogue from `ROLE_PERMISSIONS`.
2. Create the five system roles as database roles with identical bundles. A login must produce exactly the same permission set before and after; a test compares them.
3. Switch the frontend menu from role names to permissions only (`anyPermission`), and delete `primaryRole()`.

**First consumer.** An "Admin/IT" and an "HR Executive (location-scoped)" role created from the UI, used by the Assets module (M12) and the Daily Analysis page.

---

## F2 · Masters and lookups (picklists HR can edit)

**Today.** Many business lists are Python enums. Changing them needs a developer:

- document types (`DocumentType`, 10 values)
- employment states
- personnel action types
- onboarding item types
- report modules
- location types and unit types (free text)
- `worker_type` (free text, default `PERMANENT`)

**Build.** One generic lookup service for simple lists, plus dedicated masters for rich objects.

- **Lookup type** (code-registered): key (`EMPLOYEE_TYPE`, `SEPARATION_REASON`, `DOCUMENT_TYPE`, …), whether tenants may add values, and which *system categories* a value may map to.
- **Lookup value** (tenant data):
  - `code` (immutable once used), label, translations, sort order, active flag, effective dates, scope (tenant / entity), colour
  - **system category**: the meaning the code relies on. Example: a tenant can call a separation reason "Left for higher studies", but it maps to category `VOLUNTARY`.
  - extra attributes, defined per lookup type (for example `EMPLOYEE_TYPE` has `counts_in_headcount`, `pf_default`, `probation_applies`)
- **Status labels.** System statuses keep fixed codes and categories (Architecture UI 3). Tenants may rename and recolour the *label* only. Logic never reads a label.
- **Usage protection.** A value in use cannot be deleted, only deactivated. Deactivated values stay readable on history.

Initial lookup types:

- employee type
- separation type
- separation reason
- rejection reasons (per process)
- relationship
- qualification
- blood group
- marital status
- document category
- asset category
- training type
- request category
- exit-interview reason
- leave reason
- correction reason
- OD purpose
- location type
- unit type
- source of hire
- rehire-ineligibility reason
- compliance obligation status reasons
- bank names (optional)

**Admin UI.** Settings → Masters lists every lookup type with search. Each type opens a table with drag-to-reorder, add, deactivate, "used by N records", and bulk import/export.

**First consumer.** Employee type and separation reason, used by Employee Master (M2) and Exit (M13).

---

## F3 · Custom fields and form layouts

**Today.** `persons.custom_fields` (JSONB) exists, and a comment says it is "validated against the tenant's field registry". **No registry and no UI exist.**

**Build.**

- **Field definition.** Fields have:
  - entity: Person, Employment, Assignment, Candidate, Job opening, Asset, Exit case, HR request, Training session, Location, Legal entity
  - key, label (translatable), type: text, long text, number, decimal, date, date-time, yes/no, lookup (F2), multi-lookup, employee reference, email, phone, URL, file
  - validation: required, regex, min/max, unique-within-tenant
  - data class (F1)
  - visibility and edit rights by permission
  - "employee can edit" and "employee edit needs approval"
  - section, order, help text
  - applicability condition (F4 condition, for example only for `employee_type = CONTRACT`)
  - searchable and reportable flags
  - effective dates and status
- **Form layout.** Sections and field order per entity and per context (HR edit, self-service, onboarding, candidate portal). Built-in fields are also placed by the layout, so HR can reorder, hide optional ones, or make them required where the model allows.
- **Storage and query.** JSONB with a GIN index. Fields marked reportable appear automatically in the report builder metadata (M18) and in import templates (F13). Heavily filtered fields can be promoted to generated columns by an engineer, invisibly to HR.
- **Required-data rules.** "For worker type X at location Y these fields are required before activation / before confirmation." The data-quality checker (M25) reports against them.

**Admin UI.** Settings → People data → Fields and Forms: a field list per entity, a field editor, and a form layout editor (drag sections and fields). The preview shows the form exactly as an employee or HR user will see it.

**Guardrails.**

- Changing a field's type after data exists is blocked. The admin creates a new field and migrates values with the bulk tool instead.
- Deleting a field archives it; the values remain in history.

**First consumer.** Employee Master profile sections (M2) and the candidate form (M5).

---

## F4 · Employee groups and the condition builder

Many rules apply to "a set of people" defined by attributes: "contract workers at Plant 2", "all drivers", "managers grade M3 and above", "employees in Maharashtra". Today scoping is only by employee, org unit or legal entity (leave and attendance policy assignments).

**Build.**

- **Condition language (JSON, not code).** For example:

  ```
  { "all": [ { "fact": "assignment.location", "op": "in", "value": ["loc_…"] },
             { "fact": "employment.employee_type", "op": "eq", "value": "CONTRACT" } ] }
  ```

  - Operators: eq, ne, in, not_in, gt, gte, lt, lte, between, is_empty, within_days, contains.
  - Groups can be nested with `all`, `any` and `not`.
- **Fact registry** (code-registered per module). Each fact has a typed path and label, and declares whether it can be compiled to SQL. Custom fields (F3) appear automatically as facts.
- **Two evaluators sharing one spec:**
  - a Python evaluator for one record (workflow conditions, notification filters)
  - a SQL compiler for sets (group membership, policy targeting, report filters, role scopes)
  - a property test keeps the two equivalent
- **Employee group.** A named, saved condition (dynamic) or an explicit list (static).
  - Membership is materialised nightly and on relevant events, **with effective dates**.
  - **Group definitions are versioned and effective-dated (C-30).** Editing "Plant 2 contract workers" today does not change who was in it last month, so past policy resolution and reports stay true.
- **Where groups are used:**
  - policy assignment (F5)
  - role scopes (F1)
  - workflow conditions (F6)
  - reminder recipients and filters (F7)
  - notification and announcement audiences (F8)
  - policy-document audiences (M17)
  - required documents (F10)
  - training requirements (M9)
  - report filters (M18)

**Admin UI.** A visual condition builder ("Add rule → Field → Operator → Value", with AND/OR groups), a live count ("matches 214 employees"), and a "show members" list. There is **no free-text expression editor in v1**, because HR users cannot be expected to write and test code-like expressions safely.

**First consumer.** Attendance policy assignment to "Plant 2 contract workers" (M6) and the leave policy for contract staff (M7).

---

## F5 · Policy framework (scoped, effective-dated, versioned, simulated, explained)

**Today.** There are good partial patterns:

- attendance `policy_templates` and `employee_policy_assignments`
- leave policy sets, bucket policies and `leave_policy_assignments` (employee, org unit or legal entity, with effective dates)
- holiday calendar assignments
- a policy explainer modal in the UI

Each module resolves its own precedence, and lifecycle, exit, document, training and SLA rules have no policy object at all.

**Build.** One framework that every rule-bearing module uses.

- **Policy type** (code-registered):
  - the typed schema of the settings (Pydantic model, which also generates the form)
  - defaults
  - validation
  - simulation hook
  - impacted-records query
- **Policy version:** values, status (draft / published / retired), effective from/to, author, approver, change note.
- **Policy assignment:** policy version → target, which is one of tenant, legal entity, location, org unit (with descendants), employee group (F4) or employee. Each assignment has a priority and effective dates.
- **Resolution order** (most specific wins): employee → employee group (by priority) → org unit (nearest ancestor) → location → legal entity → tenant → pack default. A higher layer can **lock** a value (for example a statutory minimum) so lower layers cannot override it.
- **The entity is the primary layer (D-15, D-16).** Every rule is normally set **per legal entity (company)**; the tenant value is only a default for new entities. The finer layers (unit, group, employee) exist for companies that need them, and are hidden behind "Advanced" (C-03).
- **Explain API:** "for employee X on date D, policy type T resolved to version V because of assignment A". This generalises today's `/v1/policies/employee/{id}/effective` and the policy explainer.
- **Simulation before publishing:** affected employee count, and a sample diff, for example balance before and after for 20 people, or due dates that move.
- **Conflict detector:** two assignments at the same layer and priority overlapping in time cause a publish error, not a silent pick.
- **Mandatory simulation (C-03):** a publish that affects more employees than a threshold (default 10, a tenant setting) cannot be confirmed until the simulation has been viewed. A summary of the simulation is stored with the version.
- **Progressive disclosure (C-03):** each policy form opens in **Basic** mode, showing the handful of values most tenants change, with pack defaults. **Advanced** reveals the rest. Changed-from-default values are highlighted.
- **Materialised resolution (C-29):** a table of employee × policy type × effective range → policy version, refreshed by events (assignment, group membership, employment and assignment changes). Attendance, leave and the obligation generator read ranges from it instead of walking six layers per employee per day. The explain API reads the same table, plus the reason.

Policy types covered (each detailed in its module):

| Policy type | Module |
|---|---|
| Attendance and overtime (exists; **wrap, do not migrate**) | M6 |
| Leave policy set (exists; **wrap, do not migrate**) | M7 |
| Holiday calendar (exists; keep as dedicated assignment, expose through explain) | M6/M7 |
| Lifecycle: probation, confirmation, increment cycle, contract renewal | M8 |
| Notice and exit: notice days, buy-out, clearance template | M13 |
| Document requirements and expiry | M15 |
| Training requirements and recertification | M9 |
| Request SLA | M16 |
| Statutory applicability (PF/ESIC wage ceilings and so on) | M14 |
| Self-service permissions: what employees may edit or request | M20 |

**Wrap, do not migrate (review O-1).** Attendance policies and leave policy sets already work and hold real data. They keep their own tables and assignment logic. An **adapter** registers each of them as a policy type, which gives them:

- the explain API
- the materialised resolution table
- simulation
- employee-group targets (one new nullable column on their assignment tables)

This avoids a data migration on the most sensitive calculations, and removes most of the parity testing that a migration would need. Only *new* policy types (lifecycle, notice, documents, training, SLA, statutory) are stored natively in the framework.

**Admin UI.** Each module's settings page lists its policies, with a version history, an assignment table, a "simulate" button and an "explain for employee" lookup. A cross-module **"Effective rules for an employee"** page, reachable from Employee 360, shows every resolved policy for one person and date.

**Guardrails.**

- A published version is immutable; edits create a new draft.
- Back-dating a published policy needs the `policy.backdate` permission and shows the recomputation impact (attendance and leave days that will be recalculated) before confirmation.
- A recomputation never changes **locked periods** (M6 period close). Changes there go through the post-close correction process.

**First consumer.** The lifecycle policy (probation by employee type and grade) in M8.

---

## F6 · Workflow and approvals v2

**Today.** Configurable approval flows exist (`docs/APPROVAL_WORKFLOWS.md`):

- ordered stages with **named approver accounts**
- routing by department or team, with a tenant fallback
- a version snapshot at submission
- temporary delegation
- no self-approval
- an inbox

They cover leave, leave cancellation, attendance corrections and overtime. Recruitment openings have their own decision endpoint.

**Personnel actions have no approval at all.** Anyone with `people.write` in scope applies a transfer or promotion immediately. The code sets `PENDING_APPROVAL` and clears it in the same request, so the HR dashboard's "Personnel actions to approve" count is always zero.

Another gap: stages name *people*, so when a manager leaves or a team changes, someone must edit the flows. That does not scale to factories with hundreds of supervisors, or to a group with eight companies.

**Build (extends the existing engine, keeping current flows valid).**

- **Request type registry** (code-registered by modules). Each type declares its subject employee, a summary renderer, the facts available to conditions, the allowed actions, and whether bulk approval is permitted. The new types:

  | Area | Request types |
  |---|---|
  | Personnel actions | `TRANSFER`, `PROMOTION`, `CONFIRMATION`, `PROBATION_EXTENSION`, `MANAGER_CHANGE`, `INTER_COMPANY_TRANSFER`, `REHIRE` |
  | Compensation and payroll | `SALARY_REVISION`, `PAYROLL_APPROVAL` (lock a pay run), `PAYROLL_INPUT` (one-time earnings and deductions), `SALARY_HOLD`, `TAX_PROOF_VERIFICATION` |
  | Exit | `RESIGNATION`, `LWD_CHANGE`, `TERMINATION`, `FNF_APPROVAL` |
  | Recruitment | `MANPOWER_REQUISITION` (move the opening decision here), `OFFER` |
  | Profile and bank | `PROFILE_CHANGE` (self-service correction), `BANK_CHANGE` (maker ≠ checker, step-up MFA) |
  | Documents | `DOCUMENT_CORRECTION` |
  | Attendance | `OD_REQUEST`, `WFH_REQUEST`, `HOURS_PERMISSION`, `PERIOD_REOPEN` |
  | Bypass | `BYPASS` (only for rules an entity sets to `ALLOW_WITH_APPROVAL`, F9) |
  | Assets | `ASSET_WRITE_OFF` |
  | Training | `TRAINING_NOMINATION` |
  | Policies | `POLICY_PUBLISH` |
  | Access | `ACCESS_CHANGE` |

- **Approver resolvers per stage.** Choose one or more:
  - named people (exists)
  - line manager
  - n-th level manager
  - head of the employee's unit or any ancestor unit (`org_units.head_employment_id` exists)
  - team lead / PM (exists on units)
  - **role within scope**, for example "anyone holding HR_EXECUTIVE whose scope covers this employee's location"
  - position holder
  - a group of named users
  - the requester's chosen approver from an allowed list

  The resolved people are snapshotted at submission (as today). They are **re-resolved** if a resolved approver becomes inactive, leaves, or loses the role.
- **Resolver guardrails (C-07):**
  - each stage has a completion rule (any one / all / first N)
  - a fan-out warning when a resolver returns more than a set number of people
  - an empty-result fallback
  - **approver on approved leave:** route to their active delegate, otherwise to the next resolver level (tenant setting, default on)
- **Stage conditions** (F4 condition builder): include or skip a stage. Examples: "HR stage only if leave days > 3 or employee is on probation"; "Management stage only if salary increase > 15 %".
- **Parallel stages**, completed by any one or by all (for example IT + Admin + Accounts clearance sign-offs).
- **SLA per stage.** On breach it does one of: remind (F7), escalate to the next resolver, or auto-route to the fallback. **Never auto-approve** request types marked sensitive. Auto-approve on timeout is allowed only where the request type permits it and the tenant enables it (some factories do this for OD and short leave).
- **Actions:**
  - approve
  - reject (the reason is a mandatory lookup plus a comment)
  - send back for information (the requester edits and resubmits, and the version history is kept)
  - withdraw (by the requester)
  - administrator reassignment with a reason
  - bulk approve where the type allows it
  - comment and attachment on any action
- **Quick decision from a notification (C-26):** a signed, single-use, expiring link opens a mobile-friendly approve / reject page with the request summary. It is **disabled for sensitive request types** (salary, bank, access, F&F, compliance exceptions), which always need a signed-in session.
- **Batch requests (C-50):** a bulk action produces **one** approval item containing many lines. The approver reviews the summary, can reject individual lines with a reason, and approves the rest in one step. Each line still becomes its own record and history.
- **Fallback chain:** if a resolver yields nobody (no manager, vacant head), the stage falls to the configured fallback (default: an HR role in scope). A data-quality alert is raised beforehand (M25: "12 employees have no line manager").
- **Monitoring:** a stuck-request report (no eligible approver, or older than the SLA), plus a metric and alert per tenant.

**Admin UI.** Settings → Workflows. Each request type shows its flows (routing by department or team as today, plus any employee group). There is a stage editor with a resolver picker, conditions, SLA and escalation, and a **"test route"** tool: "if Ramesh (Plant 2, grade W3) applies for 4 days of leave, who approves?"

**Migration.** The current named-person stages become resolver type `NAMED`, with no behaviour change. The legacy `PENDING_L1..L3` compatibility stays.

**First consumer.** The `PROMOTION` and `CONFIRMATION` personnel actions (M8), using line manager → HOD → HR role in scope.

---

## F7 · Obligations, reminders and the Action Centre

**Today.**

- The HR dashboard Action Centre shows counts for leave approvals, corrections, overtime, personnel actions, failed scheduled actions, KYC, onboarding, missing statutory IDs and passports expiring.
- There is no due-date engine and no reminder delivery.
- A daily job runner exists (`jobs/runner.py`: accrual, scheduled actions, missed punches), with per-tenant checkpoints and run metrics.

**Build.**

- **Obligation type** (code-registered by modules). Each type defines:
  - a key and label
  - the subject (employee, establishment, asset or case)
  - how the due date is derived (from a policy plus data)
  - the completion signal (the event that closes it)
  - the default reminder rule

  The first types are:

  | Area | Obligation types |
  |---|---|
  | Lifecycle | `PROBATION_REVIEW_DUE`, `CONFIRMATION_DUE`, `INCREMENT_DUE`, `CONTRACT_END` |
  | Documents and identity | `DOCUMENT_EXPIRY` (passport, visa, driving licence, medical fitness, professional registration), `KYC_PENDING` |
  | Exit | `NOTICE_END`, `LWD`, `CLEARANCE_ITEM`, `FNF_DUE`, `STATUTORY_EXIT_UPDATE` |
  | Compliance | `COMPLIANCE_FILING`, `ESTABLISHMENT_LICENCE_RENEWAL` |
  | Payroll | `PAY_RUN_DUE` (per pay group and pay date), `TAX_DECLARATION_WINDOW`, `TAX_PROOF_WINDOW`, `MINIMUM_WAGE_REVISION` (pack update to review), `YEAR_END_TAX_FILINGS` |
  | Training | `TRAINING_SESSION_UPCOMING`, `TRAINING_FEEDBACK`, `TRAINING_EFFECTIVENESS`, `RECERTIFICATION_DUE` |
  | Recruitment (§26) | `REQUISITION_TARGET_DATE`, `CANDIDATE_INACTIVE` (no stage movement for N days), `OFFER_EXPIRY`, `JOINING_DUE` |
  | Onboarding | `ONBOARDING_ITEM` |
  | Requests and policies | `REQUEST_SLA`, `POLICY_ACKNOWLEDGEMENT` |
  | Assets | `ASSET_RETURN` |
  | Data quality | `DATA_QUALITY` (no manager, missing required field, and so on) |

- **Obligation record:**
  - tenant, type, subject, due date, owner (resolved like an approver)
  - status: `OPEN`, `DONE`, `EXCEPTED` (linked to an F9 exception), `CANCELLED` (for example the subject separated)
  - source reference
  - `last_reminded_at` and `escalation_level`
- **Generator.** A daily job, idempotent per tenant and per obligation key, plus **event-driven recompute**:
  - an LWD change moves the clearance due dates
  - a probation extension moves `CONFIRMATION_DUE`
  - a separation cancels open lifecycle obligations
- **Reminder rule** (UI-editable per obligation type, scope-able by F5):
  - offsets: before due (−30, −15, −7), on due, and after due ("every N days")
  - recipients: subject employee, owner, line manager, HOD, role within scope, named users
  - channels
  - escalation after M days overdue, to a resolver
  - quiet hours, and a digest option (one email a day listing everything)

  The §26 table of the requirements ships as the default.
- **Volume control (C-08):**
  - managers and HR receive a **daily digest by default**; immediate messages are opt-in per type
  - a per-user daily cap per channel
  - the generator is **incremental**: events recompute only affected subjects, and the nightly job reconciles only subjects that changed since the checkpoint
  - completed obligations older than the retention window move to an archive table
- **Which clock (C-14):** employee obligations fall due in the employee's **location time zone**; establishment obligations in the establishment's location time zone. Reminder sending respects the recipient's quiet hours.
- **Action Centre v2.** A per-user union of:
  - workflow tasks awaiting me
  - obligations I own or must act on
  - exceptions awaiting me
  - data-quality alerts in my scope

  It has counts per category, overdue first, filters, and a deep link to the exact record. Dashboard cards read the same counts (one definition, §30).
- **Rule from the requirements:** overdue items never disappear. An item leaves the Action Centre only when it is completed, or closed by an approved exception.

**Admin UI.**

- Settings → Reminders and escalation: a table of obligation types with their reminder rules and a per-scope override.
- A **calendar view** of due work, by month, filterable by type and scope.

**First consumer.** Probation and confirmation reminders (M8) and document expiry (M15).

---

## F8 · Notifications and announcements

**Today.**

- Email exists only for platform-admin password reset, through an SES outbox (`core/mail.py`).
- The bell in the app shell is derived from pending approvals; nothing is stored.
- There are no templates, no preferences and no delivery log.

**Build.**

- **Event catalogue** (code-registered). Each event declares its merge fields and their data classes. Examples: leave submitted, approved or rejected; correction decided; obligation reminder; request updated; letter issued; announcement published; account created; password reset.
- **Templates:**
  - one per event × channel × language, with a tenant override of the platform default
  - a rich-text editor with merge-field chips
  - preview with a real record
  - **merge fields restricted by data class:** Financial, Identity and Case fields are never allowed in email, SMS or WhatsApp. The message links into the app instead.
- **Channels:**
  - phase 1: in-app (persisted inbox, read/unread, mark all) and email (SES, using the existing outbox pattern with retries)
  - phase 2: SMS (India needs DLT-registered templates, so a template ID field is required) and WhatsApp Business (pre-approved templates)
  - later: mobile push

  **SMS and WhatsApp are Upcoming (decision D-3, deferred 2026-10-09).** They appear in Settings as "Upcoming" and are not built now. When they are picked up, DLT registration of the sender and templates comes first: it takes weeks and needs the tenant's own documents (C-09). Until then, in-app and email carry every notification, and login uses email, employee number or mobile with a password.
- **Recipient rules** use the same resolvers as F6 and F7.
- **User preferences:** per category and channel, plus quiet hours. Mandatory categories (security, statutory) cannot be switched off.
- **Delivery log:** status per message and bounce handling. Visible to admins with a "resend" action.
- **Announcements** ("important notices" in §25): title, body, attachments, audience (F4 group or entity/location), publish and expiry dates, pin, optional acknowledgement, and multi-language. They appear on employee home and in mobile.

**Admin UI.**

- Settings → Notifications: events, templates, channels and sender settings (from-name, reply-to, custom domain later).
- Communications → Announcements.

**First consumer.** Leave decision email and in-app notifications (M7), and probation reminders (M8).

---

## F9 · Bypass and exceptions: the entity decides (D-16)

**Decision (2026-10-09):** every rule can be bypassed **if the entity wants it**. The platform does not force an approval. Each company decides, rule by rule, how much control it wants.

**Today.** Bypasses are ad hoc. The only one is the long-day confirmation in punches. There is no record type.

**Build.**

- **Bypass setting per rule, per entity** (a policy value, F5; finer overrides optional):

  | Mode | What happens |
  |---|---|
  | `BLOCK` | The rule cannot be bypassed |
  | `ALLOW` | Authorised users bypass directly |
  | `ALLOW_WITH_REASON` | Bypass directly, but a reason (lookup or text) is required |
  | `ALLOW_WITH_APPROVAL` | A bypass request goes through F6 |

  The **pack default is `ALLOW_WITH_REASON`**. Each entity changes it per rule; for example one company may set notice-period bypass to `ALLOW` and another to `ALLOW_WITH_APPROVAL`.
- **Who may bypass:** a permission per rule family (`bypass.attendance`, `bypass.leave`, `bypass.exit`, `bypass.payroll`, …), granted through roles (F1) and scoped to entities (C-49).
- **Bypass record.** It is created automatically on every bypass, whatever the mode. It holds:
  - subject (employee, case, establishment, period)
  - the rule bypassed and its normal result
  - mode, actor, time, reason if given, evidence if attached
  - approval if required
  - an optional validity window

  **This record cannot be switched off.** It costs the user nothing (no extra step in `ALLOW` mode), and it keeps the history the requirements need (§5, §28) and protects the company in audits. It is the only part of F9 that is not optional.
- **Rules that can be bypassed** (each module registers its own):
  - notice-period shortfall
  - LWD before resignation date
  - exit without clearance of an item
  - onboarding with pending items
  - negative leave balance
  - leave rules (back-dating, maximum days)
  - correction limits
  - correction after period close
  - OT caps
  - probation beyond the policy maximum
  - joining without bank details
  - PF/ESIC applicability
  - compliance payment delayed
  - payroll checks (minimum wage, variance threshold)
- **Statutory checks.** Where a rule protects a legal obligation (minimum wage, PF/ESIC applicability, statutory payment deadlines), the bypass screen shows a plain warning that the legal responsibility stays with the company. The entity still decides the mode.
- **Reporting:** one Bypass report across modules (who bypassed what, how often, by entity), with reminders (F7) for time-bound bypasses.

**Admin UI.**

- Settings → Bypass rules: a table of rules × entities with the mode per cell, and who may bypass.
- Daily users bypass from the blocked screen itself: "This normally isn't allowed because… → Bypass (reason)" or "→ Request bypass", depending on the mode.

**First consumer.** Notice-period shortfall (M13) and correction after period close (M6).

---

## F10 · Documents: types, versions, verification, expiry, retention

**Today.**

- KYC documents have a fixed `DocumentType` enum, `PENDING` / `VERIFIED` / `REJECTED` status, and encrypted storage (local or S3).
- Only `passport_expiry` tracks expiry.
- Replacing a document is not versioned.

**Build.**

- **Document type master** (F2-backed, with attributes):
  - category, data class
  - allowed file types and size, multiple allowed
  - has expiry (and reminder offsets), has a number field (encrypted)
  - verification required, and by whom (role)
  - who may upload: self, HR or manager
  - retention period after separation
  - visible to the employee
  - **required-by rule** (F4 condition: worker type, location, job) and the stage it is required by: before joining, within N days, or before confirmation
- **Document record:** versions (replace creates version n+1; the previous is marked `REPLACED`, never deleted, as §21 requires). Statuses: `UPLOADED`, `PENDING_VERIFICATION`, `VERIFIED`, `REJECTED` (with reason), `EXPIRED`, `REPLACED`.
- **Owner types:** employee, candidate, legal entity or establishment (licences, registrations), asset, case.
- **Retention:**
  - a nightly job flags documents past retention
  - purge happens only after HR confirmation, and never under **legal hold**
  - purge removes the file and leaves a tombstone record
- **Malware scan and content-type check on upload,** with short-lived download links. The access log already exists for KYC; extend it to all restricted classes.

**Admin UI.**

- Settings → Documents: types, required-documents matrix (rows are document types, columns are worker types and locations), retention.
- HR → Documents: verification queue, expiring list, missing-documents list.
- Employee → My documents.

**Migration.** The current enum values become seeded document types with the same codes. `EmployeeKycDocument` rows map to version 1.

---

## F11 · Letters and templates

**Today.** Nothing.

**Build.**

- **Letter template:**
  - type: appointment, offer, confirmation, probation extension, promotion, transfer, increment, warning, show-cause, relieving, experience, address proof, salary certificate, NOC, custom
  - legal entity (letterhead, footer, logo)
  - language
  - rich-text body with merge fields (F8 rules, plus Financial fields allowed **only** inside letters, which are themselves restricted documents)
  - signatory (from a signatory master: name, designation, signature image, entity)
  - numbering series (F12)
  - version and status
- **Generation:**
  - triggered by a personnel action, exit or request, or manually
  - preview, edit-before-issue (if permitted), and approval if the type requires it
  - the PDF is stored as a document (F10) on the employee
  - delivered by notification
  - bulk generation (for example 300 increment letters)
- **E-sign:** later (Aadhaar e-sign or DSC providers); the interface is reserved.

**Admin UI.** Settings → Letters: template editor with live preview against a chosen employee, and the signatory master.

**First consumer.** The confirmation letter (M8) and the relieving and experience letters (M13).

---

## F12 · Numbering series

**Today.** `employee_id_schemes` produces employee numbers (prefix plus zero-padded sequence, using a concurrency-safe `UPDATE … RETURNING`).

**Build.** Generalise it to `numbering_series`:

- **document kind:** employee ID, request reference, letter number, exit case, asset tag, requisition, offer, ticket
- **scope:** tenant, entity or location
- **pattern tokens:** `{ENTITY}`, `{LOC}`, `{YYYY}`, `{YY}`, `{FY}`, `{MM}`, `{SEQ:n}`
- **reset:** never, yearly, financial-yearly or monthly
- **preview** of the next number

The concurrency-safe increment is kept, and issued numbers are never reused. The current employee-ID schemes migrate in unchanged.

**Admin UI.** Settings → Numbering, alongside the existing Organisation → Employee IDs tab, which moves here.

---

## F13 · Import, export and bulk actions

**Today.**

- One-off Python scripts per source (`backend/scripts/migrate_*.py`), run by engineers.
- `import_batches` records runs.
- Report exports exist.

**Build.**

- **Import wizard:**
  1. Choose an entity.
  2. Download a template generated from the current form layout, including custom fields.
  3. Upload CSV or XLSX.
  4. Map columns.
  5. **Validate:** every row shows errors in plain words; nothing is written yet.
  6. **Dry-run summary:** create / update / skip counts.
  7. Commit, as a background job with progress.
  8. Download a result file.
  9. **Undo** within a window, for creates only.
  10. History.
- **Importable entities:**
  - org masters and lookups
  - employees with history (hire, then dated transfers)
  - opening leave balances
  - punches (CSV or Excel from devices)
  - holidays
  - assets
  - statutory profiles
  - bank details (restricted permission, maker-checker)
  - training records
  - candidates
  - compensation (restricted)
- **Bulk actions from lists:**
  - assign policy
  - change manager
  - transfer by upload
  - send document request
  - send policy for acknowledgement
  - generate letters
  - deactivate accounts

  Each bulk action creates the normal records (personnel actions, assignments) and **runs through approvals where the request type requires it**, as **one batch request** (F6, C-50).
- **Migration playbook (C-15)** for every new tenant and legacy source:
  1. import masters
  2. import people with history (hire, then dated transfers)
  3. opening balances
  4. reconciliation reports: counts per entity and location, balance totals per leave bucket, and 20 sampled employee timelines
  5. HR sign-off on those reports
  6. data-quality rules (M25) run immediately after the import, with the results attached to the sign-off

  The EXIM and Sharanga imports showed why: duplicates and inconsistent company IDs in source data.
- **Export:**
  - permission-gated, logged (the export audit exists for KYC; generalise it)
  - restricted classes are masked unless the exporter holds the class
  - optional watermark on PDFs

**Admin UI.** Settings → Data import and HR list screens (a bulk-action bar).

---

## F14 · Terminology, language and branding

**Today.**

- Theme tokens and theme names exist (UI 1 doc, migration 0028).
- Labels are hard-coded English.

**Build.**

- **Terminology overrides** per tenant, for a fixed list of nouns:
  - Department → Section / Division
  - Branch → Plant / Site / Store
  - Employee → Associate / Staff
  - Manager → Supervisor / In-charge
  - Grade → Level / Band

  The frontend resolves labels through `t()` with a tenant dictionary. Statutory screens keep legal names.
- **Language:** all UI strings externalised (start with self-service and attendance screens). Regional languages for self-service are chosen per employee. **Which languages come first is decision D-9**, based on where each tenant's plants and depots are (C-44).
- **Formats:** date and number formats, and the financial year start (exists per legal entity).
- **Branding:** logo, colour (contrast-guarded), login page message, email sender name.

**Admin UI.** Settings → Terminology and language, and Settings → Branding.

---

## F15 · Configuration governance

**Today.**

- `entity_change_log` keeps org history.
- The approval-flow version check prevents lost updates.
- There is no audit of policy or setting changes in one place, no sandbox, and no export of configuration.

**Build.**

- **Configuration audit.** Every settings change records who, when, before/after, a reason (optional or mandatory per area) and the version. It is visible under Settings → Change history, filterable by area.
- **Draft → publish** for policies, workflows, templates and reminder rules. Optionally, **approval of configuration changes** (`POLICY_PUBLISH`, `ACCESS_CHANGE`) for tenants that want four-eyes control.
- **Configuration bundles.** Export and import a JSON bundle of masters, policies, workflows, templates and reminder rules. Uses:
  - copy a set-up from one legal entity to another
  - move a tested configuration from the **sandbox tenant** to production
  - build industry packs (F16)

  Import shows a diff and applies as drafts.
- **Copy and compare between entities (review E-6).** Every rule is per entity (D-16), so a group with 8 companies has 8 sets. HR can:
  - **copy** one company's settings (any area, or all) to another, as drafts
  - see a **side-by-side comparison** of any two or more companies, area by area, with differences highlighted
- **Sandbox tenant.** The platform console can clone a tenant's configuration (no employee data) into a sandbox where HR rehearses changes.
- **Setup health page.** Live checks with a fix link for each:
  - employees without a manager, attendance policy, holiday calendar or leave policy
  - flows with no eligible approver
  - templates with missing merge fields
  - reminder rules with no recipients
  - expired statutory rule values

**First consumer.** Attendance and leave policy changes (already the riskiest settings).

---

## F16 · Packs and the setup wizard

**Build.**

- **Pack** = a versioned configuration bundle (F15) maintained by the platform team. It holds:
  - lookups
  - document types
  - policy defaults
  - obligation types and reminder rules
  - workflow templates
  - letter templates
  - compliance obligations and official links
  - terminology
  - employee groups
  - dashboard layouts
- **Pack layers:**
  - **base** (every tenant)
  - **country**: India first, holding PF, ESIC, PT and LWF by state, statutory leave types, labour-code notes and official links (with a "last verified" date)
  - **industry**: Manufacturing/Factory, Logistics & Freight, IT & Services, Retail, Healthcare, Construction (see [03](03-industry-coverage.md))
- **Pack application.** Applied at tenant set-up, or later per legal entity, as drafts that HR reviews and publishes. Pack updates (for example a new PF ceiling) arrive as **proposed changes** with source and effective date. They are never silently applied to a tenant.
- **Setup wizard** for a new tenant or a new legal entity:
  1. industry and country packs
  2. company details and statutory registrations
  3. locations
  4. departments
  5. employee types
  6. attendance rules (duration thresholds, OT, weekly offs)
  7. leave policy
  8. holidays
  9. approval defaults
  10. roles and first users
  11. import employees
  12. go-live checklist (setup health, F15)

  Every step can be skipped and resumed.

---

## F17 · Global search, navigation and the Employee 360 shell

**Today.**

- No global search.
- Employee details open in a side sheet with Overview, Attendance, KYC, Access and Workflow tabs.
- The menu does not follow the requirements' main sequence (§38).

**Build.**

- **Global search:**
  - top bar plus a command palette (Ctrl/⌘+K)
  - searches employee ID, name, mobile and official email
  - scope- and class-trimmed in SQL (F1)
  - also finds requests and cases by reference number
  - offers quick actions ("Apply leave for…", "Start exit for…")
- **Employee 360 page** (a full route, `/people/{id}`):
  - header card with status, key dates and the pending-items count
  - **module-contributed tabs** registered by each module and shown only when the module is enabled and the viewer holds the permission: Profile, Employment, Attendance, Leave, Compensation, PF/ESIC, Documents, Training, Assets, Requests, Policies, Lifecycle, Exit, History
  - Case-class tabs are hidden entirely, not shown as "restricted"
- **History timeline:** personnel actions, field changes (with old → new), documents, letters and approvals, filterable.
- **Navigation:** reorganised to the requirements' main sequence, grouped by persona. Every module has its own route (§31), and modules disabled for the tenant disappear (F18).

---

## F18 · Module entitlements and feature switches

**Build.**

- **Per tenant (platform console):** which modules are licensed.
- **Per tenant and legal entity (tenant admin):** which licensed modules are switched on. For example, Training is on for the factory entity and off for the trading entity.
- **Feature switches** inside modules: geo-fenced mobile punch, selfie punch, kiosk, WFH requests, self-service bank change, payslip view.
- **Enforcement:**
  - backend dependencies check entitlement and return a consistent `MODULE_DISABLED` error
  - frontend menus and 360 tabs hide disabled modules
  - jobs skip disabled modules

---

## F19 · Integration framework

**Build.**

- **Attendance device adapters:**
  - a device registry per location (vendor, serial, gate, direction, time zone)
  - push endpoint (signed) and pull connectors for common vendors (eSSL/ZKTeco-compatible, Matrix, Realtime), plus CSV import
  - **Deferred until the device list arrives (D-12, 2026-10-09)**, as WP C7. Until then, punches come from web, mobile and kiosk, and device data arrives through the punch import wizard (F13). Everything else here (idempotency, late punches, the no-biometrics rule) applies to imported punches too.
  - idempotent punch ingestion, keyed by device ID + device timestamp + employee
  - **late-arriving punches accepted (C-18):** days are recomputed until the period close; after the close a late punch becomes a post-close adjustment (M6)
  - a device health dashboard (last seen, punches today, clock drift)
  - an **offline site gateway** later
  - **no biometric templates are ever stored or transferred into the HRMS (C-43)**, only punch events. Device enrolment stays on the device or the vendor's software.
- **Webhooks:** the tenant subscribes to events (employee hired, separated, leave approved…). Deliveries are signed, retried and logged.
- **API keys** (exist): extended with scopes per module and an IP allow-list UI.
- **Payroll export contract:** a versioned "payroll input" file per period and pay group, with a column mapper UI so each payroll vendor's format is configuration (M11).
- **Directory and SSO:** OIDC/SAML per tenant, and later SCIM provisioning. Account deactivation on LWD feeds IT clearance.
- **Calendar:** ICS invites for interviews and training. Later, a Google or Microsoft calendar sync.

**Admin UI.** Settings → Integrations: devices, webhooks, API keys, payroll export formats, SSO.

---

## Settings console: one place for every rule

All of the above appears under a single **Settings** area. It is grouped for the person who maintains it, and every page shows "last changed by / when" and links to Change history (F15).

| Group | Pages |
|---|---|
| Organisation | Companies and registrations · Locations · Units and unit types · Designations (jobs) · Grades · Positions · Cost centres · Org chart |
| People data | Fields and forms · Masters (lookups) · Employee types · Employee groups · Data-quality rules |
| Time | Attendance rules (per entity) · Overtime · Weekly offs · Holiday calendars · Capture methods and devices · Pay calendars and period close |
| Leave | Leave types · Policy sets · Accrual and year-end · Comp-off · Encashment |
| Lifecycle and exit | Lifecycle policies · Notice and exit policies · Separation types and reasons · Clearance templates · Exit interview forms |
| Workflows | Approval flows · Bypass rules · Delegations |
| Communication | Notification templates · Reminders and escalation · Announcements |
| Documents and letters | Document types · Required documents · Retention · Letter templates · Signatories |
| Recruitment and onboarding | Stages · Sources · Interview feedback forms · Offer templates · Onboarding checklists |
| Training | Programmes · Training types · Feedback forms · Requirements matrix |
| Assets | Asset types · Asset fields |
| Requests | Categories · SLAs and business-hours calendars · Assignment rules |
| Compliance | Establishments · Statutory rules (rates, ceilings, due dates) · Obligation calendar · Official links |
| Payroll (restricted) | Components and calculation types · Structures · Pay groups and calendars · Statutory rule values · Minimum wages · Tax regimes and declaration windows · Bank file formats · GL mapping · Payslip template · Variance thresholds |
| Access | Roles · Users and access · Segregation of duties · Access review |
| Platform for this tenant | Modules on/off · Numbering · Terminology and language · Branding · Integrations · Data import · Configuration bundles · Setup health · Change history |
