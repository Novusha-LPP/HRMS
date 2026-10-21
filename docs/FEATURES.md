# HRMS Platform — Comprehensive Feature Catalog & Inventory

This document serves as the authoritative, comprehensive inventory of all features, capabilities, and system components in the **HRMS Platform**, spanning the backend architecture, database layer, REST APIs, and the frontend web application.

---

## 📊 Executive Summary & High-Level Metrics

| Metric | Count | Description |
| :--- | :---: | :--- |
| **Total Granular Features Cataloged** | **342** | Every distinct capability, big or small, enumerated across the platform |
| **REST API Operations** | **297** | Fully documented OpenAPI/Swagger endpoints across all HTTP verbs |
| **Functional Modules** | **20** | Domain modules spanning platform, core HR, time, leave, ATS, payroll & ops |
| **Frontend Primary Pages & Routes** | **26** | Dedicated views (`App.tsx`, lazy-loaded route tree) |
| **Interactive UI Components & Panels** | **55+** | Modals, sheets, drawers, tabs, widgets, and custom data tables |
| **Database Tables & RLS Policies** | **52** | Strict PostgreSQL Row-Level Security isolation enforced per tenant |

---

## 📑 Feature Counts by Functional Module

| # | Functional Domain | Feature Count | API Operations | Primary Scope & Interfaces |
| :---: | :--- | :---: | :---: | :--- |
| **1** | Platform Administration & Multi-Tenancy | **16** | 17 | Platform Operator Console, Tenant Provisioning, Subscriptions |
| **2** | Authentication, MFA & IAM | **18** | 13 | Secure Sign-In, TOTP MFA, RBAC, Data Scopes, Token Epochs |
| **3** | Organization Hierarchy & Master Data | **19** | 33 | Legal Entities, Locations, Departments, Grades, Cost Centers, ID Schemes |
| **4** | People & Employee Lifecycle Management | **19** | 10 | Employee Directory, Profiles, Personnel Actions, PIN Slips |
| **5** | Employee KYC & Document Compliance | **15** | 15 | Aadhaar, PAN, Bank Details, Document Verification, Access Audits |
| **6** | Time, Attendance & Daily Registers | **22** | 15 | Punches, Day Processing, Register Grid, Overtime, Daily Analysis |
| **7** | Holiday Calendars & Week-off Policies | **14** | 15 | Multi-Location Calendars, Public/Restricted Holidays, Shift Week-Offs |
| **8** | Leave Management, Balances & Comp-Off | **26** | 40 | Quotas, Monthly Accruals, Ledgers, Comp-Off, Encashment, Multi-Level |
| **9** | Attendance Regularization & Corrections | **11** | 5 | Missed Punches, On-Duty (OD), Dispute Workflows, Register Sync |
| **10** | Approval Workflows & Delegation Engine | **16** | 12 | Unified Inbox, Multi-Step Chains, Delegations, In-App Notifications |
| **11** | HR Policy Engine & Attendance Rules | **13** | 9 | Shift Rules, Grace Periods, Half-Day Thresholds, Sandwich Deductions |
| **12** | Recruitment & Applicant Tracking (ATS) | **24** | 27 | Requisitions, Kanban Board, Candidate Profiles, In-Browser Resumes |
| **13** | Employee Onboarding & Pre-boarding | **13** | 9 | Checklist Templates, Task Allocation, Progress Trackers, Welcome Emails |
| **14** | Payroll Management & Compensation | **19** | 17 | Salary Structures, CTC Breakup Preview, Component Master, Increments |
| **15** | Statutory Compliance & Benefits | **11** | (Integrated) | EPF, EPS, ESIC Gross Ceilings, Professional Tax Slabs, Gratuity |
| **16** | Reports & Business Intelligence Builder | **15** | 7 | Dynamic Column Builder, Custom Query Filters, Styled Excel/CSV Exports |
| **17** | Dashboards & Employee Self-Service | **18** | 9 | Role-Tailored Views, Drag-and-Drop Widgets, Celebrations |
| **18** | Connected Apps, ERP Sync & Integrations | **24** | 42 | Biometric Machine Ingestion, Webhooks, OAuth2, API Keys, Field Locks |
| **19** | UI Themes, Preferences & Accessibility | **13** | 2 | Teal / Midnight / Ember Themes, Dark/Light, Command Palette (`⌘K`) |
| **20** | Reliability, Observability & Migration Tools | **16** | (CLI/Ops) | Alembic Migrations, Preflights, Healthchecks, Legacy Importers |
| **TOTAL** | **Granular Features Cataloged** | **342** | **297** | **Complete platform footprint** |

---

## 1. Platform Administration & Multi-Tenancy (16 Features)
*Admin console decoupled from tenant HR data, dedicated to platform owners.*

1. **Isolated Platform Authentication**: Dedicated credentials table (`platform_admins`) and separate JWT token type (`PLATFORM_TOKEN_TYPE`) completely isolated from tenant accounts.
2. **Platform Admin Two-Factor Authentication (TOTP MFA)**: Enrollment QR generator, secret recovery, and code validation for platform operators.
3. **Platform Password Recovery Workflow**: Secure tokenized password reset links with configurable expiration (`RESET_TOKEN_TTL_MINUTES = 60`).
4. **Tenant Catalog & Search**: Paginated directory of all platform tenants with status and employee count filters.
5. **Tenant Detail Inspector**: Real-time tenant health, legal entity count, user counts, and subscription plan details.
6. **Self-Service Company Registration**: Public or gated multi-step registration wizard for new tenants (`/register`).
7. **Platform Company Provisioning**: Manual tenant bootstrap by platform admin without tenant self-registration (`POST /v1/platform/companies`).
8. **Sister Company Linking**: Ability to link multiple legal entities under a single tenant group.
9. **Tenant Plan Tier Management**: Assignment of subscription tiers (`STARTER`, `GROWTH`, `ENTERPRISE`).
10. **Tenant Suspension**: Immediate tenant lockout suspending all tenant user sign-ins and API requests (`PATCH /v1/platform/tenants/{tenant_id}`).
11. **Tenant Reactivation**: Instant restoration of suspended tenants with data integrity preserved.
12. **Tenant Archival**: Soft-deletion archiving inactive tenants out of operational views (`POST /v1/platform/tenants/{tenant_id}/archive`).
13. **Tenant Restoration**: Re-activation of archived tenants (`POST /v1/platform/tenants/{tenant_id}/restore`).
14. **Platform Admin User Management**: Create, promote, demote, and suspend platform administrator accounts.
15. **Append-Only Platform Audit Log**: Tamper-proof actor/action/target event trail of all platform-level changes (`GET /v1/platform/audit-log`).
16. **Tenant Data Purge Tool**: Scripted purge routine (`purge_tenant.py`) to wipe test/decommissioned tenants without affecting neighbours.

---

## 2. Authentication, MFA & Identity Access Management (IAM) (18 Features)
*Secure tenant-scoped authentication, RBAC, and session lifecycle.*

17. **Multi-Identifier Sign-in**: Sign in using work email, employee code, or registered mobile number.
18. **Bcrypt Password Encryption**: Industry-standard high-work-factor salt and hash security.
19. **Sign-In Brute Force Throttling**: Exponential backoff and account locking on repeated password failures.
20. **Token Epoch Session Invalidation**: Instant global sign-out upon password change, separation, or admin revocation via token epoch increments.
21. **Mandatory Password Change Flag**: Enforced password reset flow on first login for imported or admin-reset accounts (`must_change_password`).
22. **Tenant Employee TOTP MFA**: Authenticator app integration (Google Authenticator, Authy, etc.) for employee accounts.
23. **MFA Grace / Setup Bypass Guard**: Routing guards directing users to MFA setup before granting workspace access.
24. **Voluntary Password Change**: Self-service password updates with current password verification.
25. **Administrative Password Reset**: Admin ability to issue secure temporary passwords with forced change flag (`POST /v1/users/{user_id}/reset-password`).
26. **Sign-in Slips for Non-Email Staff**: Bulk generation of 8-digit numeric PIN slips for factory/deskless workers (`POST /v1/users/sign-in-slips`).
27. **Granular Role-Based Access Control (RBAC)**: Support for `SUPER_ADMIN`, `HR`, `MANAGER`, and `EMPLOYEE`.
28. **Fine-Grained Permission Scopes**: Permissions evaluated against `ALL`, `LEGAL_ENTITY`, `ORG_UNIT`, `DIRECT_REPORTS`, or `SELF`.
29. **Multi-Entity Scope Granting**: Ability to assign a manager access to specific sister companies or branches.
30. **Active/Inactive Login Toggle**: Instant suspension of individual user credentials without deleting employee records.
31. **Last Admin Protection Guard**: System prevents deactivating or deleting the final remaining Super Admin.
32. **PostgreSQL Row-Level Security (RLS)**: Database-level session variable (`app.tenant_id`) preventing cross-tenant data leakage.
33. **Safe Anonymous Registration Flag**: Deploy-time toggle (`HRMS_ALLOW_PUBLIC_REGISTRATION`) to close public signups.
34. **Session Cookie & Bearer Token Dual Mode**: Secure HttpOnly browser session cookies plus API Bearer headers.

---

## 3. Organization Hierarchy & Master Data (19 Features)
*Multi-entity enterprise structure and organizational taxonomy.*

35. **Multi-Company Legal Entities**: Configuration of independent registered companies under a group umbrella.
36. **Company Master Details**: CIN, PAN, GSTIN, registered office address, and statutory metadata per entity.
37. **Entity Change History**: Audit timeline tracking historical modifications to company records.
38. **Work Locations / Branches**: Management of offices, factories, warehouses, and remote sites with coordinates.
39. **Location Change History**: Versioned tracking of facility reallocations or updates.
40. **Department Tree (Org Units)**: Hierarchical departmental structures (e.g., Engineering → QA → Automation).
41. **Company-Department Mapping**: Explicit mapping associating specific departments with specific legal entities.
42. **Department Change History**: Tracking department renaming, head changes, or reorganizations.
43. **Job Catalog / Designations**: Standardized roles and job titles across the organization.
44. **Job Profile & Description**: Storing functional responsibilities and role prerequisites.
45. **Job Banding & Grades**: Salary/seniority bands (e.g., L1–L8, Band A–D) for compensation standardization.
46. **Grade Change History**: Record of changes in grade levels and salary eligibility brackets.
47. **Cost Centers**: Financial accounting units mapped to departments and personnel for payroll allocation.
48. **Cost Center Audit Trail**: History of cost center assignments and reclassifications.
49. **Positions Management**: Specific headcount positions with budget, status (Vacant, Filled), and reports-to links.
50. **Position Change History**: History of who held which position over time.
51. **Custom Employee ID Schemes**: Configurable ID generation formats (Prefix, Year, Department code, Padding).
52. **Company-Specific ID Sequences**: Separate auto-incrementing ID counters per legal entity.
53. **Scheme Retirement & Update**: Controlled update or decommissioning of historical ID schemes.

---

## 4. People & Employee Lifecycle Management (19 Features)
*Comprehensive employee directory, personnel records, and transitions.*

54. **Employee Directory (List & Grid)**: Searchable, filterable workforce directory with status indicators.
55. **Employee Profile Hub**: Centralized view of personal, work, contact, and statutory information.
56. **New Hire Onboarding Wizard**: Multi-step flow to record personal details, position, department, and salary.
57. **Work Relations & Reporting Hierarchy**: Direct manager and functional manager assignment.
58. **Secondary Work Relations**: Matrix reporting structures for cross-functional project assignments.
59. **Personnel Actions Engine**: Structured transactions for Promotions, Transfers, Demotions, and Increments.
60. **Effective-Dated Personnel Actions**: Scheduling future-dated promotions, transfers, or salary updates.
61. **Pending Personnel Action Queue**: Inspection of scheduled actions waiting for their effective execution date.
62. **Action Cancellation**: Ability to cancel a scheduled transfer or salary change before it activates.
63. **Automated Action Execution Daemon**: Background script (`apply_scheduled_actions.py`) executing mature actions.
64. **Employment State Machine**: State tracking across `PROBATION`, `CONFIRMED`, `NOTICE_PERIOD`, and `SEPARATED`.
65. **Resignation & Separation Handling**: Recording notice period, exit reasons, and separation dates.
66. **Immediate Account Revocation on Exit**: Automatic cutoff of platform access upon reaching exit date.
67. **Emergency Contacts Management**: Recording primary and secondary emergency contacts with relationships.
68. **Personal & Family Details**: Date of birth, gender, marital status, blood group, and address records.
69. **Employee Document Vault**: Upload and categorization of appointment letters, contracts, and certificates.
70. **Quick Filter by Status/Entity**: Dynamic filtering by active status, probationers, or specific legal entity.
71. **Directory Search Bar**: Fast typeahead searching by name, email, employee code, or phone.
72. **Employee CSV Export**: One-click download of filtered employee lists with full placement attributes.

---

## 5. Employee KYC & Document Compliance (15 Features)
*Indian statutory identity management, document storage, and strict privacy.*

73. **Self-Service KYC Submission**: Employee portal to enter PAN, Aadhaar, Bank Details, and UAN.
74. **Aadhaar Number Storage & Masking**: Masked presentation (e.g., `XXXX-XXXX-1234`) for non-privileged viewers.
75. **PAN (Permanent Account Number) Validation**: Format validation and status verification.
76. **Bank Account & IFSC Verification**: Bank name, account number, branch, and IFSC code capture.
77. **UAN (Universal Account Number) Tracking**: Tracking EPFO UAN numbers for statutory filings.
78. **KYC Document Upload**: Secure upload of scanned copies (PDF, JPG, PNG) of ID proofs and cancelled cheques.
79. **Document In-Browser Preview**: Secure modal to inspect uploaded verification documents.
80. **Secure Document Download**: Token-authenticated download of compliance proofs.
81. **Document Verification Workflow**: HR approve/reject action per document with reviewer notes.
82. **Overall KYC Status Progression**: Real-time status badge (`DRAFT`, `PENDING_VERIFICATION`, `VERIFIED`, `REJECTED`).
83. **HR KYC Management Table**: Central HR workspace showing pending verifications across all companies.
84. **KYC Status Summary Counters**: Dashboard badges indicating completed vs pending verification counts.
85. **KYC Access Audit Log**: Strict append-only log tracking every time an HR user views someone's masked KYC details.
86. **HR Edit on Behalf of Employee**: Privileged HR ability to update or correct erroneous KYC details.
87. **Document Deletion Guard**: Secure deletion of superseded or unverified KYC documents.

---

## 6. Time, Attendance & Daily Registers (22 Features)
*Punch capture, attendance daily processing, register grid, and overtime.*

88. **Web Punch Clock**: Real-time Clock-In / Clock-Out widget with live time display and punch mode.
89. **Biometric Punch Ingestion API**: High-throughput endpoint (`POST /v1/time/punches`) to ingest punches from biometric machines.
90. **Today's Attendance Status Widget**: Instant visibility into current day punch status, first in, last out, and duration.
91. **Day Timeline Visualization**: Graphic bar illustrating work intervals, breaks, and out-of-office gaps.
92. **Attendance Day Record Processing**: Automated calculation of daily gross hours, effective work hours, and break time.
93. **Shift Adherence Calculation**: Automatic detection of on-time arrival, late arrival, and early departure.
94. **Half-Day vs Full-Day Thresholds**: Automatic classification based on configured work duration rules.
95. **Absenteeism Auto-Detection**: Days with zero punches flagged as absent unless covered by leave or holiday.
96. **Overtime Calculation Engine**: Automatic computation of hours worked beyond shift end time.
97. **Overtime Approval Queue**: Dedicated manager workflow to review and approve/reject claimed overtime hours.
98. **Attendance Flagging**: Automatic flagging of anomalous attendance days (single punch, short hours, odd hours).
99. **Manager Day Review / Acknowledgment**: Ability for a supervisor to review and accept a flagged day.
100. **Daily Attendance Analysis Dashboard**: High-level daily dashboard showing present, absent, on-leave, and late counts.
101. **Department-Wise Daily Attendance Breakdown**: Drill-down of daily attendance metrics by department.
102. **Daily Analysis CSV Export**: Instant export of daily presence data for management reporting.
103. **Monthly Attendance Register Grid**: Full-month calendar view with standard status codes (`P`, `A`, `HD`, `WO`, `H`, `L`).
104. **Register Multi-Filter**: Filter register by legal entity, department, employment status, and month.
105. **Register Employee Search**: Typeahead search to locate an employee inside the monthly register.
106. **HR Manual Punch Override**: HR ability to replace or adjust a day's punches directly inside the register.
107. **Register Punch History Inspector**: Inspect raw punch timestamps that produced the day's attendance status.
108. **Monthly Register Excel Export**: Download styled Excel spreadsheet formatted for payroll processing.
109. **My Team Live Presence View**: Manager page showing who on the team is currently punched in, out, on leave, or late.

---

## 7. Holiday Calendars & Week-off Policies (14 Features)
*Multi-region holiday management and complex week-off schedules.*

110. **Central Holiday Library**: Master pool of recognized national, regional, and company holidays.
111. **Holiday Classification**: Mandatory/Public vs Optional/Restricted holiday categorization.
112. **Multi-Location Holiday Calendars**: Custom holiday calendars tailored to distinct office branches or states.
113. **Yearly Calendar Builder**: Quick assignment of holidays to specific yearly calendars.
114. **Calendar Day Customization**: Overriding holiday names or dates for specific location calendars.
115. **Calendar Assignment by Location/Entity**: Automated mapping of calendars to employees based on office location.
116. **Calendar Coverage Inspector**: Verification view ensuring every active employee has an assigned holiday calendar.
117. **Standard 5-Day Week-off Rule**: Default Saturday-Sunday weekly off policy.
118. **6-Day Work Week Rule**: Single-day (Sunday) weekly off configuration for manufacturing/operations units.
119. **Alternate Saturday Rules**: Configurable 2nd & 4th Saturday off policies.
120. **Rotational Week-off Rules**: Custom week-off days for shift workers on rolling rosters.
121. **Holiday Calendar Archival**: Archiving historical calendars while maintaining past attendance accuracy.
122. **Holiday Display on ESS Calendar**: Upcoming company holidays highlighted on employee home dashboard.
123. **Holiday Collision Detection with Leave**: Automatic prevention of overlapping leave deduction on public holidays.

---

## 8. Leave Management, Balances & Comp-Off (26 Features)
*Comprehensive leave types, quotas, monthly accruals, ledgers, and comp-offs.*

124. **Custom Leave Types**: Configurable leave categories (Casual Leave, Sick Leave, Earned Leave, Maternity, Paternity, Unpaid).
125. **Paid vs Unpaid Leave Flags**: Specifying whether leave days deduct from salary during payroll.
126. **Gender-Specific Leave Applicability**: Restricting leave types (e.g., Maternity, Paternity) by employee gender.
127. **Leave Balance Buckets**: Organizing leave types into balance quota groups.
128. **Leave Bucket Mapping**: Flexible mapping connecting leave types to statutory balance buckets.
129. **Annual Leave Quota Allocation**: Assigning yearly day allowances per leave category.
130. **Monthly Leave Accrual Engine**: Prorated monthly accrual run calculating monthly increments.
131. **Automated Monthly Accrual Trigger**: API and scheduled job to run monthly balance accruals across all tenants.
132. **Year-End Leave Closure**: Automated rollover processing with carry-forward limits and lapsing.
133. **Leave Carry-Forward Rules**: Configurable limits on maximum days carried forward into the new year.
134. **Leave Encashment Processing**: Workflow to encash accumulated earned leave into payroll earnings.
135. **Compensatory Off (Comp-Off) Granting**: HR/Manager grant of comp-off credits for weekend/holiday work.
136. **Comp-Off Validity Window**: Configurable expiry days for compensatory leave balances.
137. **Manual Balance Adjustments**: Audited HR ability to credit or debit employee leave balances with remarks.
138. **Self-Service Leave Application**: Employee portal to apply for leave with date range and reason.
139. **Half-Day Leave Option**: Support for First Half / Second Half partial day leave requests.
140. **Leave Attachment Upload**: Supporting document upload (e.g., medical certificates for sick leave).
141. **Real-Time Leave Balance Validation**: System prevents applying for leave exceeding available quota.
142. **Leave Application Summary Stats**: Real-time counter of total leaves taken, pending, and remaining by type.
143. **Multi-Level Leave Approval Flow**: Routing leave applications to direct supervisor and HR.
144. **Leave Rejection with Comments**: Approver ability to reject requests with mandatory explanation.
145. **Leave Withdrawal by Employee**: Ability to withdraw pending leave applications before approval.
146. **Leave Cancellation Flow**: Submitting a cancellation request for already approved future leave.
147. **Cancellation Approval Workflow**: Manager review and approval of leave cancellation requests.
148. **Monthly Leave Ledger View**: Visual month-by-month debit/credit transaction statement for any employee.
149. **Leave Audit Transactions Feed**: Complete historical trail of every balance grant, deduction, and adjustment.

---

## 9. Attendance Regularization & Corrections (11 Features)
*Self-service correction of missed punches, on-duty visits, and dispute resolution.*

150. **Missed Punch Regularization Request**: Employee portal to report forgotten clock-in or clock-out.
151. **Correction Type Selection**: Categorizing corrections into Check-In, Check-Out, Both, or Shift Error.
152. **On-Duty (OD) Official Duty Application**: Regularization request for client visits, field work, or outdoor duty.
153. **Work Date & Time Correction Picker**: Selecting specific date and target timestamps for adjustment.
154. **Reason & Justification Entry**: Mandatory text explanation for the attendance anomaly.
155. **Evidence Attachment**: Uploading travel receipts, client emails, or approvals supporting the correction.
156. **Self-Service Correction History**: Personal tracking table showing submitted correction statuses.
157. **Correction Withdrawal**: Ability for an employee to cancel a pending correction request.
158. **Manager Regularization Approval**: Manager inbox to review, approve, or reject attendance corrections.
159. **Automated Attendance Day Recalculation**: Instant recalculation of work hours upon correction approval.
160. **Direct Register Synchronization**: Approved corrections immediately reflect in the Monthly Attendance Register.

---

## 10. Approval Workflows & Delegation Engine (16 Features)
*Unified multi-step approval orchestrator, delegation, and routing rules.*

161. **Unified Approvals Inbox**: Single dashboard aggregating all pending Leave, Attendance, Overtime, and ATS requests.
162. **Request Type Filter**: Fast filtering of pending tasks by Leave, Correction, Overtime, or Requisition.
163. **Multi-Step Approval Chains**: Configurable multi-level workflows (e.g., Level 1: Manager → Level 2: HR Head).
164. **Dynamic Approver Roles**: Steps routed to `REPORTING_MANAGER`, `DEPARTMENT_HEAD`, or specific named users.
165. **Employee-Specific Flow Assignments**: Assigning customized approval workflows to specific employees or groups.
166. **Approval Flow Visualizer / Builder**: Admin interface to create and reorder sequential approval steps.
167. **Auto-Approval Rules**: Configurable conditions under which certain requests are approved automatically.
168. **One-Click Batch Approval**: Approving multiple pending tasks in bulk from the inbox.
169. **Decision Comments & Audit History**: Detailed timeline recording each approver's action, timestamp, and notes.
170. **Temporary Cover / Delegation Rules**: Out-of-office delegation redirecting approval tasks to an acting colleague.
171. **Delegation Date Windows**: Scheduling start and end dates for approval delegation coverage.
172. **Active Delegations Inspector**: Viewing currently active delegation rules across the organization.
173. **Immediate Delegation Revocation**: Revoking active delegations when returning early from absence.
174. **In-App Notification Badges**: Real-time counter of pending approval tasks displayed on sidebar and top bar.
175. **Email Approval Notifications**: Background email dispatch alerting approvers of newly submitted requests.
176. **Stale Request Escalation**: Detection and reporting of requests lingering beyond defined SLA windows.

---

## 11. HR Policy Engine & Attendance Rules (13 Features)
*Configurable attendance rules, shift definitions, and enforcement.*

177. **Attendance Policy Templates**: Defining modular attendance rule profiles for different worker categories.
178. **Shift Definition & Hours**: Configurable shift start time, shift end time, and nominal duration.
179. **Grace Period Configuration**: Allowed late arrival buffer (e.g., 15 minutes) before marking late flag.
180. **Half-Day Minimum Hours Threshold**: Configurable minimum working hours required to qualify for half-day credit.
181. **Full-Day Minimum Hours Threshold**: Configurable minimum working hours required to qualify for full-day credit.
182. **Late Arrival Penalties**: Policy rule flagging chronic tardiness (e.g., 3 late marks = 0.5 day leave deduction).
183. **Early Departure Rules**: Configurable threshold for leaving early before shift completion.
184. **Strict Punch Pairing Option**: Toggle requiring balanced In/Out pairs vs first-in/last-out calculation.
185. **Overtime Eligibility Rules**: Minimum excess hours required before overtime accrual begins.
186. **Sandwich Rule Enforcement**: Policy deducting weekend/holidays if preceded and followed by unpaid leave.
187. **Policy Assignment by Entity / Dept**: Assigning attendance policy templates across departments or companies.
188. **Individual Employee Policy Override**: Ability to assign a specialized attendance policy to an individual worker.
189. **Effective Policy Resolver**: High-speed engine resolving the exact policy hierarchy for any employee date.

---

## 12. Recruitment & Applicant Tracking System (ATS) (24 Features)
*End-to-end talent acquisition, job requisitions, candidate pipeline, and hiring.*

190. **Job Requisition Creation**: Raising job openings with title, department, vacancies, experience, and budget.
191. **Requisition Approval Workflow**: Submitting job openings through management approval before publishing.
192. **Requisition Status Lifecycle**: Managing opening states (`DRAFT`, `PENDING_APPROVAL`, `OPEN`, `ON_HOLD`, `CLOSED`).
193. **Requisition Withdrawal**: Allowing hiring managers to withdraw open requisitions.
194. **Opening Change History**: Comprehensive event log of opening updates, status changes, and approvals.
195. **Configurable Pipeline Stages**: Customizable recruitment stages (e.g., Applied → Screened → Tech Interview → HR → Offer).
196. **Recruitment Pipeline Kanban Board**: Visual drag-and-drop board moving candidates across stages.
197. **Candidate Talent Pool Directory**: Central repository of all historical applicants across all openings.
198. **Candidate Profile Sheet**: Detailed applicant drawer with contact info, current employer, CTC, and notice period.
199. **Resume Upload (PDF / Docx)**: Direct resume file attachment to candidate profile.
200. **In-Browser Resume Viewer**: Embedded document viewer to inspect candidate CVs without downloading.
201. **Resume File Replacement / Deletion**: Updating or removing outdated resumes from the talent pool.
202. **Candidate Tagging & Skills**: Adding custom tags (e.g., `React`, `Python`, `High-Priority`) to candidates.
203. **Interviewer Evaluation Rating**: 1-to-5 star rating and feedback submission for candidate interviews.
204. **Interview Notes & Feedback Feed**: Chronological feedback timeline contributed by multiple interviewers.
205. **Stage Movement History**: Audit trail showing date, time, and user who transitioned a candidate's stage.
206. **Hiring Decision Action**: Marking candidate as `HIRED` or `REJECTED` with rejection reason categorization.
207. **Convert Candidate to Employee**: One-click action linking a hired candidate into the New Hire Onboarding flow.
208. **Duplicate Candidate Detection**: Automatic flagging of applicants with matching email or phone number.
209. **Recruitment Access Control**: Fine-grained permissions (`recruitment.request`, `recruitment.read`, `recruitment.manage`).
210. **Opening Link Sharing**: Generating direct internal links to specific job openings.
211. **Recruitment Analytics Counters**: Real-time counts of active openings, total candidates, and pending evaluations.
212. **Candidate Deletion Guard**: Secure deletion of accidental or spam applicant submissions.
213. **Recruitment Demo Seeder**: Development and testing script (`seed_recruitment_demo.py`) populating sample pipelines.

---

## 13. Employee Onboarding & Pre-boarding (13 Features)
*Checklist templates, cross-department task allocation, and progress tracking.*

214. **Onboarding Checklist Templates**: Defining reusable onboarding task lists by role, department, or location.
215. **Standard India Checklist Seed**: One-click loader adding industry-standard IT, HR, and Admin onboarding tasks.
216. **Versioned Checklist Templates**: Saving new versions of onboarding templates without breaking in-flight cases.
217. **Template Deactivation**: Retiring obsolete onboarding checklists.
218. **Onboarding Case Initiation**: Launching an onboarding checklist instance for newly hired employees.
219. **Onboarding Directory**: Overview of all active, completed, and overdue onboarding cases.
220. **Task Assignment to Stakeholders**: Assigning individual tasks to IT (Laptop), HR (Documents), or Manager (Training).
221. **Due Date & SLA Assignment**: Setting relative due dates (e.g., Day -3, Day 1, Day 30) for each task.
222. **Checklist Task Status Progression**: Updating items across `PENDING`, `IN_PROGRESS`, `COMPLETED`, and `BLOCKED`.
223. **Task Completion Notes**: Adding verification remarks or serial numbers (e.g., asset tag) upon completion.
224. **Visual Progress Tracker**: Percentage-based progress bar showing overall onboarding case completion.
225. **Document Collection Tracking**: Specific checklist tasks monitoring submission of signed agreements.
226. **Automated Welcome Communication**: Triggering welcome notifications with sign-in instructions for the new hire.

---

## 14. Payroll Management & Compensation (19 Features)
*Salary structures, components, CTC calculation, and revision tracking.*

227. **Pay Component Catalog**: Master list of salary earnings, deductions, allowances, and reimbursements.
228. **Component Calculation Types**: Support for Fixed amounts, Percentage of Basic, or Calculated formulas.
229. **Taxable vs Exempt Flags**: Marking components as taxable earnings, tax-exempt allowances, or pre-tax deductions.
230. **Standard India Pay Components Loader**: Pre-configured setup for Basic, HRA, Conveyance, Special Allowance, PF, and PT.
231. **Salary Structure Templates**: Grouping components into reusable grade-based compensation packages.
232. **Live CTC Breakup Calculator / Previewer**: Interactive tool computing monthly/annual breakup for any entered CTC.
233. **Standard India Structure Seed**: Default statutory structure factoring PF, ESI, and standard allowances.
234. **Versioned Salary Structures**: Modifying structures by creating new active versions while preserving historical payroll.
235. **Structure Deactivation**: Retiring compensation structures no longer offered to new hires.
236. **Employee Compensation Assignment**: Assigning a tailored salary structure and CTC to an employee.
237. **Salary Revision History**: Complete versioned timeline of an employee's historical CTCs and revisions.
238. **Effective-Dated Salary Increments**: Scheduling compensation increments to take effect on a future pay cycle.
239. **Employee Compensation Breakup Inspector**: Detailed view of an employee's exact monthly earning and deduction lines.
240. **Active Salaries Register**: Paginated overview of all current employee salaries across the company.
241. **Statutory Parameter Rules**: Configurable statutory limits (e.g., PF wage ceiling ₹15,000, ESI threshold ₹21,000).
242. **Effective-Dated Statutory Slabs**: Scheduling new statutory contribution rates starting from a designated fiscal date.
243. **Statutory Rule Verification**: Administrative review and verification step before activating revised statutory rules.
244. **Standard India Statutory Defaults Loader**: Auto-population of current statutory EPF, EPS, EDLI, and ESIC slabs.
245. **Restricted Payroll Permission Gate**: Explicit permission boundary (`payroll.read`, `payroll.write`) isolating salaries from general HR.

---

## 15. Statutory Compliance & Benefits (11 Features)
*Indian statutory adherence for PF, ESIC, Professional Tax, and Gratuity.*

246. **Employees' Provident Fund (EPF / EPS)**: Employee (12%) and Employer (12% split into EPF and EPS) calculation.
247. **EPF Wage Ceiling Configuration**: Handling PF capped at ₹15,000 vs actual Basic wage contributions.
248. **Employee State Insurance (ESIC)**: Employee (0.75%) and Employer (3.25%) calculation for eligible staff.
249. **ESIC Gross Wage Threshold**: Automatic inclusion/exclusion based on the ₹21,000 gross monthly wage ceiling.
250. **State-Wise Professional Tax (PT) Slabs**: Configurable monthly tax deduction slabs according to state regulations.
251. **Labor Welfare Fund (LWF)**: Support for state-mandated periodic employee and employer welfare deductions.
252. **Payment of Gratuity Rules**: 15 days of last drawn basic salary per year of completed service computation.
253. **Statutory Data Export**: Generating data formats required for Monthly ECR (Electronic Challan cum Return) filing.
254. **Form 16 / TDS Integration Fields**: Storage and export of income tax deduction metadata.
255. **Statutory Overview Dashboard Tab**: Dedicated compliance dashboard showing contributions across entities.
256. **Statutory Audit Checklist**: Automated audit flagging employees missing mandatory UAN, ESIC, or PAN details.

---

## 16. Reports & Business Intelligence Builder (15 Features)
*Customizable ad-hoc reporting, dynamic pivots, and styled spreadsheet exports.*

257. **Ad-Hoc Report Builder UI**: Flexible interactive builder to generate custom organizational reports.
258. **Multi-Module Reporting**: Run reports across Attendance, Leave, Employee Directory, and Attrition.
259. **Dynamic Column Selector**: Choose exactly which fields (from dozens of available attributes) appear in the report.
260. **Module Column Metadata Engine**: Backend registry describing available fields, data types, and display labels.
261. **Filter Query Builder**: Add multiple chained filter criteria (e.g., Entity = X AND Department = Y AND Status = Active).
262. **Date Range Scoping**: Filter records by custom start and end dates or relative periods (This Month, Last Month).
263. **Saved Custom Report Definitions**: Save report queries and configurations for repeat one-click execution.
264. **Saved Reports Directory**: Manage, browse, and execute team-wide or personal saved reports.
265. **Custom Report Deletion**: Clean up obsolete or duplicate report definitions.
266. **Interactive On-Screen Result Table**: Paginated, sortable preview of report output directly in the browser.
267. **Styled Attendance & Leave Excel Exporter**: Proprietary openpyxl generator outputting color-coded attendance grids.
268. **Excel Summary Cards**: Exported spreadsheets include top-level statistics (Present%, Absent count, Leaves taken).
269. **CSV Data Export**: High-speed export of raw tabular report results for external data analysis.
270. **Strict Report Scope Enforcement**: Data exported is strictly bounded by the requesting user's RLS and scope permissions.
271. **Column Alignment & Formatting Rules**: Automated numeric right-align, date formatting, and status pill rendering.

---

## 17. Dashboards & Employee Self-Service (ESS/MSS) (18 Features)
*Personalized workspaces, role-based metrics, widgets, and celebrations.*

272. **Role-Tailored Dashboard Views**: Automatically customized views for `EMPLOYEE`, `MANAGER`, `HR`, and `SUPER_ADMIN`.
273. **Employee Self-Service (ESS) Home**: Personal hub showing daily punch, leave balance cards, and quick actions.
274. **Manager Self-Service (MSS) Workspace**: Team overview showing daily attendance rates and pending team approvals.
275. **HR Executive Dashboard**: Company-wide workforce health metrics (headcount, attendance %, leave volume).
276. **Super Admin Dashboard**: Multi-company high-level standing, active logins, and compliance indicators.
277. **Customizable Dashboard Layouts**: Drag-and-drop grid reordering and arranging dashboard widgets.
278. **Persistent User Layout Preferences**: Dashboard widget coordinates and arrangements saved per user account.
279. **Reset Dashboard Layout**: One-click action to restore default factory widget layout.
280. **Modular Widget Registry**: Extensible widget architecture allowing new widgets to be plugged in seamlessly.
281. **Quick Clock-In / Out Widget**: One-click punch trigger directly from the dashboard header.
282. **Leave Balance Quick Cards**: At-a-glance cards showing remaining Casual, Sick, and Earned leave balances.
283. **Pending Approvals Queue Widget**: Immediate cards alerting managers to requests awaiting their signature.
284. **Upcoming Holidays Widget**: Chronological list of upcoming official holidays over the next 30 days.
285. **Who Is Away Today Widget**: Visibility into colleagues or team members currently on approved leave.
286. **Team Attendance Rate Stat Card**: Visual percentage indicator and trend comparing today's attendance to last week.
287. **Birthday Celebration Cards**: Visual cards celebrating employee birthdays occurring today.
288. **Work Anniversary Celebrations**: Recognition cards highlighting employee work anniversaries and tenure milestones.
289. **Confetti & Celebration Animations**: Dynamic micro-animations greeting employees on milestone login days.

---

## 18. Connected Apps, External ERP/CRM & Integrations (24 Features)
*REST APIs, Webhooks, API keys, and robust bidirectional ERP sync.*

290. **Connected Apps Management Console**: Administrative dashboard to register and monitor external enterprise systems.
291. **Integration App Catalog**: Pre-configured integration profiles for custom ERP, CRM, and biometric platforms.
292. **App Lifecycle Controls**: Ability to Connect, Rename, Pause, Resume, or Disconnect an external application.
293. **Scoped API Key Generation**: Generating high-security API keys with explicit granular permission boundaries.
294. **API Key Revocation**: Immediate termination of compromised or decommissioned integration keys.
295. **API Rate Limiting & Retry-After Headers**: Dedicated rate limiting per integration key returning HTTP 429.
296. **OAuth 2.0 Client Credentials Flow**: Modern machine-to-machine authentication issuing scoped integration tokens.
297. **Settings Profiles & Versioning**: Multi-version draft/publish workflow for managing integration sync parameters.
298. **Settings Draft Preview**: Dry-run simulation previewing what changes publishing a draft profile will cause.
299. **Value Mapping Engine**: Translating external ERP codes to HRMS entities (e.g., ERP Branch `BR01` → HRMS Location ID).
300. **Unmapped Values Inspector**: Dedicated view highlighting external records that failed to sync due to missing mappings.
301. **Managed Fields Control**: Explicitly defining which platform (HRMS vs ERP) is authoritative for specific employee fields.
302. **External Single Employee Upsert API**: REST endpoint creating or updating an employee using external system IDs.
303. **Bulk Employee Sync API**: High-capacity endpoint accepting up to 200 employee upsert records in a single payload.
304. **External Employee Exit API**: Triggering employee separation directly from an external enterprise system.
305. **External Employee Rehire API**: Reactivating separated employees via integration endpoints.
306. **Employee Account Reconciliation Tool**: Comparing active employee lists between ERP and HRMS to identify discrepancies.
307. **Duplicate Detection Safety Valve**: Detecting duplicate employee imports and holding them for manual HR resolution.
308. **Mass Exit Safety Valve**: Halting automated imports when exit volume exceeds safety threshold to prevent accidental wipes.
309. **Held Exits Release / Reject**: Administrative dashboard to inspect and approve or reject held separation actions.
310. **Events Feed API**: Change Data Capture (CDC) events feed enabling downstream systems to poll recent changes.
311. **Integration Sync Logs**: Detailed request and response payload audit trail tracking every sync transaction.
312. **Reference Data Discovery Endpoints**: API listing valid companies, departments, locations, and designations for sync tools.
313. **External Daily Attendance & Leave Pull**: Endpoints allowing external ERPs to query daily attendance and leave data.

---

## 19. UI Themes, Preferences & Accessibility (13 Features)
*Modern design system, curated color palettes, dark mode, and keyboard ergonomics.*

314. **Curated Color Theme Switcher**: Instant switching between 3 design themes:
    - **Classic Teal**: Clean, enterprise modern teal palette.
    - **Midnight Blue**: Deep, immersive navy executive aesthetic.
    - **Ember Sand**: Warm, organic, high-contrast earth tones.
315. **Light / Dark Mode Toggle**: Full dual-mode support across every page, card, popover, and data table.
316. **User Preferences Persistence**: Saving color theme, dark/light mode, and display choices to the backend database.
317. **Global Command Palette (`Ctrl+K` / `⌘K`)**: Fast keyboard-driven launcher to navigate pages and search records.
318. **Collapsible Responsive Sidebar**: Compact icon-only rail or full 240px drawer with memory of collapsed state.
319. **Mobile Navigation Sheet**: Touch-optimized slide-in navigation drawer for smartphones and tablets.
320. **Dynamic Breadcrumb Navigation**: Contextual header breadcrumbs updating with current section and active page.
321. **Environment Watermark Badge**: Colored badge clearly indicating `LOCAL`, `TESTING`, or `PRODUCTION`.
322. **Interactive Notification Dropdown**: Top bar bell popover displaying actionable pending approvals and alerts.
323. **Toast Notification System**: Fluid toast alerts for successful operations, warnings, and network errors.
324. **Multi-Level Error Boundaries**: Isolated card and full-screen React error boundaries preventing total app crashes.
325. **Optimistic Version Conflict Reloading**: Automatic cache invalidation handling HTTP 409 stale version collisions.
326. **Accessibility & Screen Reader Standards**: Semantic HTML5 tags, ARIA attributes, and keyboard focus states.

---

## 20. System Reliability, Ops, Backups & Migration Tools (16 Features)
*DevOps scripts, database integrity preflights, and legacy data migration.*

327. **Alembic Database Migration Pipeline**: Sequential, hand-written, reversible database schema migrations.
328. **Database Preflight Script (`db_preflight.py`)**: Strict sanity checker validating database connection, roles, and schema.
329. **Schema Drift Detection (`alembic check`)**: Automated verification ensuring SQLModel classes match database schema.
330. **Runtime RLS Bypass Guard**: Application refuses to start if running as database superuser or role with RLS bypass.
331. **Production Secret Enforcement**: Server fails to start in production if using default secrets or debug flags.
332. **Automated Docker Compose Stack**: Complete local/staging setup running PostgreSQL 16 and the FastAPI application.
333. **Prometheus Metrics Middleware**: Detailed metrics endpoint tracking request timings, status codes, and latency.
334. **Database Query Performance Instrumentation**: SQL query tallying and slow query logging via custom middleware.
335. **Health Check Endpoints**: Liveness and readiness endpoints (`/v1/health`) for AWS ECS / Kubernetes load balancers.
336. **Structured JSON Logging**: Standardized JSON-formatted application logs with correlation request IDs (`X-Request-ID`).
337. **Demo Group Data Seeder (`seed_demo.py`)**: Script generating a complete demo group with employees, punches, and leaves.
338. **Initial Platform Admin Seeder (`seed_platform_admin.py`)**: Secure bootstrap generator for the first platform admin.
339. **Legacy MongoDB Exim Importer (`migrate_tenants.py`)**: Large-scale migration script importing legacy company databases.
340. **Punch History Migration Script (`migrate_exim_punch_history.py`)**: Migrating multi-year historical biometric punches.
341. **Leave History Migration Script (`migrate_exim_leave_history.py`)**: Migrating historical leave applications and balances.
342. **Automated AWS EC2 / ECS Deployment Scripts**: Shell scripts (`deploy.sh`) automating zero-downtime rolling deploys.

---

*Document generated and synchronized with codebase version 1.1.*
