export type UsageHelpTopic =
  | "organization"
  | "org-overview"
  | "departments"
  | "companies"
  | "company-departments"
  | "teams"
  | "locations"
  | "jobs"
  | "grades"
  | "positions"
  | "cost-centres"
  | "employee-ids"
  | "company-admins"
  | "approvals"
  | "payroll"
  | "integrations-overview"
  | "integrations-keys"
  | "integrations-settings"
  | "integrations-mappings"
  | "integrations-log"
  | "integrations-review";

export interface UsageHelp {
  title: string;
  introduction: string;
  steps: { title: string; description: string }[];
  note: string;
}

/** Saved in-app instructions, selected by the screen's Help button. */
export const usageHelp: Record<UsageHelpTopic, UsageHelp> = {
  "integrations-overview": {
    title: "Understand the connection overview",
    introduction: "Check how the selected ERP, CRM or other app is connected and what information it receives.",
    steps: [
      { title: "Choose an app", description: "Select its card at the top of the page. The tabs and figures below belong to that connection." },
      { title: "Check the connection activity", description: "Linked employees have an external app ID associated with their HRMS record. Active keys are usable credentials. Last call shows the latest recorded integration operation." },
      { title: "Review what the app receives", description: "Read the Events, Data, Fields and Key permissions in the report. Use Settings to change the information it receives and Keys to change what its credentials may do." },
      { title: "Check for unread events", description: "Events not yet read are changes the app has not confirmed through the feed. If the count keeps rising, ask the app's developers to check their poller. Open the API reference for connection instructions." },
    ],
    note: "Connect an app registers it in HRMS. The app's developers must still implement the connection on their server. Pause temporarily blocks calls; Resume restores access. Disconnect permanently revokes its keys and keeps links and logs as history.",
  },
  "integrations-keys": {
    title: "Create and manage integration keys",
    introduction: "Give the selected app its own server credential and control which actions and companies it can access.",
    steps: [
      { title: "Create a named key", description: "Select Create a key and enter a name that identifies the server or purpose, such as ERP production server." },
      { title: "Choose its permissions", description: "Tick the actions the app needs. Employee sync changes employee records; employee, organisation, attendance and leave reads expose those records; events read receives changes; sessions issue enables employee self-service. Password sync is a separate permission. Receive-only and read-only apps cannot receive write or session permissions." },
      { title: "Set companies and limits", description: "Select the companies it may access. Leaving every company unticked allows all companies in this tenant. Enter the app server's allowed IP addresses or ranges, expiry in days, and requests per minute." },
      { title: "Copy and store the key", description: "Create the key, copy it, and store it in the app server's secret store. Select Done after copying or confirming it is stored. The full key is shown only once and cannot be retrieved later." },
      { title: "Replace or revoke a key", description: "For rotation or changed permissions, create a replacement and let the app switch to it before revoking the old key with a reason. An app can have two active keys." },
    ],
    note: "A key belongs on the app's server. Revoking it also stops its OAuth tokens and employee sessions. If a key is lost, create a replacement; HRMS cannot display it again.",
  },
  "integrations-settings": {
    title: "Configure integration settings",
    introduction: "Define how the selected app exchanges employee data. Two-way apps use every section below; receive-only and read-only apps use the company scope, outgoing information and publish steps.",
    steps: [
      { title: "Choose the company and start a draft", description: "In Settings for, choose All companies for the group default or a company for an override. Select Change settings. A company follows the group default except for values marked This company." },
      { title: "Choose who owns each field", description: "App means the ERP or CRM manages the field and it is normally locked in HRMS. HRMS means incoming changes are ignored or rejected. Shared lets both systems update the field, so a later accepted update can replace its value. Not synced excludes incoming updates to the field. For example, choose App for a department managed in the ERP and Shared for an email edited in either system. Ownership governs later updates; a new employee can be initialised from supplied fields." },
      { title: "Decide when HR may override", description: "Choose whether HR can change an app-owned field: Not allowed, Allowed with a reason, or Allowed with a reason after approval. Approval requires an assigned Field override workflow. Employees cannot override app-owned fields. Also choose whether incoming fields the app does not own are ignored with a warning or cause the call to be refused." },
      { title: "Choose where employee changes happen", description: "For hiring, job changes, exits and rehires, choose App only, HRMS only or Both. Use the ownership presets as a starting point, then adjust individual fields for your process." },
      { title: "Set matching and reference values", description: "Choose how existing employees are matched, whether unknown departments, locations and designations are refused for mapping or created, and a default location if the app does not send one. Possible employee matches needing confirmation appear in Needs review." },
      { title: "Configure logins and self-service", description: "Choose an app-supplied password, a default pattern or access through the app only, and whether the first direct sign-in requires a password change. Switch punching, attendance, corrections, leave, profile editing and manager approvals on or off, then set the session length." },
      { title: "Set the exit safety valve", description: "Set the exit count and percentage thresholds, then choose Hold for HR or Refuse for requests over the limit. Held exits appear in Needs review for a Release or Reject decision." },
      { title: "Choose outgoing information and timing", description: "Choose the employee events and data categories the app receives, when a new joiner becomes visible, and how long sync logs are kept. These controls are separate from field ownership. Attendance and leave API reads also depend on the key's permissions; use Keys to revoke those reads." },
      { title: "Preview and publish", description: "Save draft to keep work without activating it. Select Preview to check affected employees, field locks, event changes and warnings. Choose the From date and select Publish when ready. Versions retains earlier settings; Discard removes an unpublished draft." },
    ],
    note: "Only published settings whose effective date has arrived are in force. First name, department or other app-owned fields may appear locked on employee screens. KYC identifiers, bank details, salary and passwords are excluded from outgoing employee data.",
  },
  "integrations-mappings": {
    title: "Map the app's values to HRMS",
    introduction: "Translate company, department, location, designation and role values when the app uses different names or codes.",
    steps: [
      { title: "Check Unmapped values", description: "Values that caused requests to be refused appear with their kind, call count and last-seen time. Find the external value that needs a match." },
      { title: "Choose the HRMS value", description: "In that row, select the existing HRMS company, department, location, designation or role, then select Map. For example, map the app's Ops to HRMS's Operations department in the correct company." },
      { title: "Add a mapping in advance", description: "Use the form below: choose the kind, enter the app's exact value, select its HRMS destination and select Add mapping. Values already matching HRMS codes or names do not need a mapping." },
      { title: "Retry and check the result", description: "Ask the app to retry its refused request, then open Sync log to confirm it succeeds. Use the remove icon if a mapping is incorrect, and add the correct one." },
    ],
    note: "Adding a mapping does not replay the failed request. Match departments and locations to the right company. A role can map only to Employee or Manager.",
  },
  "integrations-log": {
    title: "Read and troubleshoot the sync log",
    introduction: "Find recorded operations from the selected app and understand their results before asking it to retry.",
    steps: [
      { title: "Find the request", description: "Filter by Outcome or Operation, or enter the employee ID used in the external app. Clear a filter to widen the results." },
      { title: "Read the outcome", description: "Created, Linked and Updated show completed changes. No change means nothing needed updating. Stale ignored means an older source update arrived after a newer one. Scheduled takes effect later; Held for review needs HR; Rejected or Failed needs investigation. Dry run previews changes without applying them." },
      { title: "Expand the row", description: "Select a row to see available old and new values, warnings, the error message, HTTP status, duration, key identifier and request reference." },
      { title: "Resolve and retry", description: "For an unknown value, add a mapping. For a duplicate or held exit, open Needs review. Share the request reference with the app's developers for other failures, then check the retry here. Select Load older for earlier entries." },
    ],
    note: "The log records integration operations rather than every raw HTTP read. Contact changes are masked and passwords are not displayed. A dry run is logged even though it does not change employee records.",
  },
  "integrations-review": {
    title: "Resolve items that need review",
    introduction: "Handle possible duplicate employees, exits held by the safety valve and hires that the app has not linked.",
    steps: [
      { title: "Compare possible duplicates", description: "Compare the external record with the HRMS employee's name, code, date of birth and email. Choose Same person: link only when they refer to the same employee, or Different person to reject that proposed match. Ask the app to retry after the decision." },
      { title: "Check held exits", description: "Confirm the employee and last working day with HR. Select Release to process that exit or Reject to refuse it. A released exit may be applied now or scheduled for its effective date." },
      { title: "Follow up on unlinked hires", description: "Hired in HRMS, not linked by the app lists hires announced over 24 hours ago without a link. Ask the app's developers to check their events poller, create or locate the matching record, and link its external ID to the HRMS employee." },
    ],
    note: "Nothing needs review means these queues are empty. Confirming a match links the records; the app's retry applies its remaining changes. Releasing a held exit authorises the employee's separation, so check the details before choosing it.",
  },
  payroll: {
    title: "Set up payroll and assign salaries",
    introduction: "Complete these steps before salaries can be assigned with confidence.",
    steps: [
      {
        title: "Load the PF and ESIC values",
        description: "Open the Statutory values tab and choose Load India defaults to populate statutory rates for Provident Fund, ESIC contribution percentages, wage caps, and minimum wages.",
      },
      {
        title: "Have them verified",
        description: "The payroll reviewer checks each statutory rule against the official government notification and verifies it. Calculations require active verified rates.",
      },
      {
        title: "Set up a salary structure",
        description: "Open the Structures tab to start from the standard structure and adjust earnings, deductions, and employer contributions to match your compensation plans.",
      },
      {
        title: "Assign salaries to employees",
        description: "Open the Salaries tab or open an employee's profile to assign their salary structure, annual CTC, and effective date. The salary breakup and deductions are calculated automatically.",
      },
    ],
    note: "Salaries require at least one active salary structure. Once configured, you can assign or revise salaries either from the Payroll Salaries tab or directly within each employee's profile. Revisions preserve complete compensation history.",
  },
  approvals: {
    title: "Set up employee approval workflows",
    introduction: "Define a workflow once, then select it for each employee. Routing is independent of teams and departments.",
    steps: [
      { title: "Create a workflow", description: "Open Approval flows → New flow. Name the workflow and choose its request type." },
      { title: "Define the stages", description: "Add approval stages in the order you need. Name each stage and select the people who can approve it. Any one selected person can approve that stage." },
      { title: "Assign employees", description: "Open Employees, select an employee, and open Approval workflow. Choose a saved workflow for each request type and select Save." },
      { title: "Set up leaders separately", description: "HODs, PMs, and leads can create workflows and assign them to employees they manage. HR/admin assigns workflows for the leaders themselves." },
    ],
    note: "Several employees can use the same workflow. Transfers do not change their selected workflows. Changes apply to new requests; submitted requests keep their original approvers. Employees cannot approve their own requests.",
  },
  organization: {
    title: "Set up and manage your group organization",
    introduction: "Structure your enterprise across legal entities, shared departments, physical locations, job titles, grades, positions, and cost centres.",
    steps: [
      { title: "Review group-wide metrics", description: "Use the Overview tab to monitor active headcount, registered entities, operating hubs, retention brackets, and workforce allocation." },
      { title: "Register legal entities & locations", description: "Add your parent and subsidiary companies under Companies. Define operating offices, factories, sites, and remote hubs under Locations." },
      { title: "Configure departments and teams", description: "Create reusable department templates under Departments, assign them to authorized companies, and organize internal teams and employee rosters." },
      { title: "Standardize jobs, grades, and positions", description: "Define universal Job titles and hierarchical career Grades. Create approved Positions with headcount caps to track budgeted seats and open vacancies." },
      { title: "Set up cost centres and employee ID schemes", description: "Add Cost centres for financial allocation and payroll booking. Configure automatic Employee ID schemes to sequentially number new hires per company or group-wide." },
    ],
    note: "Group administrators configure shared masters such as companies, global locations, job titles, and tenant ID schemes. Company administrators manage team assignments, employee placements, and company-specific workflows within their authorized entities.",
  },
  "org-overview": {
    title: "Understand organization overview & workforce analytics",
    introduction: "Get an executive snapshot of your entire enterprise structure, operating footprint, employee seniority, and workforce distribution.",
    steps: [
      { title: "Track key organizational KPIs", description: "Monitor headline numbers for total active staff, registered legal entities, operating locations/hubs, active departments, average employee tenure, and statutory KYC verification rates." },
      { title: "Analyze employee seniority and retention", description: "Review the tenure breakdown across Veterans (10+ years), Established (5 to 10 years), and Growth (< 5 years) to understand workforce stability and retention patterns." },
      { title: "Inspect operating locations & hubs", description: "Preview active office, site, and plant locations across cities. Click Manage locations to jump directly to location configuration." },
      { title: "Examine workforce allocation", description: "Toggle between By company and By department in the allocation widget to view active staff distribution and percentages across subsidiaries and business units." },
      { title: "Quick navigation to organization modules", description: "Click on any summary metric card (Legal entities, Locations & hubs, Departments) to open that module for editing." },
    ],
    note: "All overview metrics calculate automatically from active employee records and current organization settings. KYC compliance measures the percentage of active staff with verified identity and statutory records.",
  },
  companies: {
    title: "Manage group legal entities & companies",
    introduction: "Each company represents a registered legal entity or subsidiary within your enterprise group, with its own workforce, departments, and payroll.",
    steps: [
      { title: "Add a legal entity", description: "Select Add company, enter the registered legal name, short trading name or code, corporate registration/tax ID, operating currency, and registered office address." },
      { title: "Open company workspaces", description: "Find any company card and select Departments & teams to manage that company's active departments, internal teams, and assigned employee rosters." },
      { title: "Update company details", description: "Click the pencil icon on any company card to edit corporate registration information, currency, or contact addresses. Use the History icon to view audit logs." },
      { title: "Assign company-specific administrators", description: "Use Company admins (Access tab) to grant company-scoped access to HR managers or accountants who should only administer this specific entity." },
    ],
    note: "Creating or modifying legal entities requires group administrator permissions. A company cannot be deleted if active employee employments, departments, or payroll histories are attached to it.",
  },
  departments: {
    title: "Manage shared departments & company assignments",
    introduction: "Define master departments once at the group level, then assign them to the companies that operate those business functions.",
    steps: [
      { title: "Create shared department masters", description: "Select Create department, enter a name (e.g. Engineering, Human Resources, Finance) and a short code (e.g. ENG, HR, FIN). Shared departments are reusable across all companies." },
      { title: "Assign departments to companies", description: "Select Assign to company, choose the target company, tick the departments it operates, and save. Already assigned departments are marked as Assigned." },
      { title: "Build company teams & assign staff", description: "Click on an assigned company card or open Companies → Departments & teams to create internal teams and assign employees inside that department." },
      { title: "Edit master department details", description: "Select the pencil icon to update a department's name or code. Renaming updates the master definition across all assigned companies while preserving company teams." },
    ],
    note: "Shared departments ensure consistent group-wide reporting. Teams and employee memberships created inside a company's department remain strictly isolated to that company.",
  },
  "company-departments": {
    title: "Manage this company’s departments",
    introduction: "Choose which shared departments this company uses, then manage its teams.",
    steps: [
      { title: "Assign departments", description: "Select Assign departments. Tick the departments this company needs and save. Existing assignments are marked Assigned." },
      { title: "Open a department", description: "Select Manage teams & employees on its card. Employee and team counts belong to this company only." },
      { title: "Create and manage teams", description: "Create teams inside the department, then use Add employees to choose members from that department." },
    ],
    note: "Create or rename shared departments in the Departments tab. To switch companies, select All companies.",
  },
  teams: {
    title: "Manage teams and employees",
    introduction: "Use team cards to organize employees within this company’s department.",
    steps: [
      { title: "Create a team", description: "Select Create team. Enter the team name and an optional code. The company and department are already selected." },
      { title: "View members", description: "Select a team card to see its employees. Use All employees or Without a team to view other department employees. Search by name or employee number." },
      { title: "Add several employees", description: "Select a team, then Add employees. Tick the employees you want, or use Select all shown, then select Assign employees." },
      { title: "Move or remove a team assignment", description: "Select Move beside an employee and choose a destination. Choose No team to keep the employee in the department without a team." },
      { title: "Edit the team", description: "Select its card, then Edit team. The History icon shows name and code changes." },
    ],
    note: "Changes take effect today and preserve the employee’s job, location, manager, and assignment history. New employees must first be placed in this department through the Employees page. If a bulk update partly fails, successful changes stay saved and failed employees remain selected for retry.",
  },
  locations: {
    title: "Manage operating locations, offices & sites",
    introduction: "Locations represent the physical offices, manufacturing plants, customer sites, and remote hubs where employees are based.",
    steps: [
      { title: "Add a physical location or hub", description: "Select Add location, enter the location name (e.g. Corporate HQ, Tech Center, Warehouse Site 1), and select its type: Office, Site, Plant, or Remote." },
      { title: "Set geographic details & company scope", description: "Specify the city and country. Choose whether the location is restricted to a specific company or shared across All companies for multi-tenant offices." },
      { title: "Assign locations to employees", description: "When placing employees into departments or onboarding new hires, select their primary location. This drives geo-fencing, attendance rules, and state statutory compliance." },
      { title: "Edit locations & view change history", description: "Click the pencil icon to modify address or type details. Select the History icon to view timestamped audit logs of all modifications." },
    ],
    note: "Every employee must be assigned a location when placed into a department. Shared locations allow employees from different group subsidiaries to share the same physical office.",
  },
  jobs: {
    title: "Define standard job titles & designations",
    introduction: "Maintain a standardized, group-wide catalog of job designations and functional disciplines across all group companies.",
    steps: [
      { title: "Add a job title", description: "Select Add job title, enter the formal designation title (e.g. Senior Software Engineer, Accounts Manager, Plant Operator)." },
      { title: "Assign standard code and function", description: "Optionally enter a unique job code (e.g. ENG-01) and functional discipline (e.g. Technology, Operations, Finance) for categorization and ERP integration." },
      { title: "Link to positions and employments", description: "Select defined job titles when creating approved department positions or updating an employee's employment designation." },
      { title: "Review audit history", description: "Click the History icon on any job title row to view who created or modified the title, code, or functional classification." },
    ],
    note: "Job titles are universal across all companies in the tenant. They represent the professional designation, whereas Positions represent specific approved seats with headcount limits.",
  },
  grades: {
    title: "Configure grades & hierarchical levels",
    introduction: "Establish hierarchical career levels, pay bands, and seniority grades (e.g. L1–L6, M1–M3, W1–W4) across the organization.",
    steps: [
      { title: "Add a career grade", description: "Select Add grade, enter a short code (e.g. M1, L2, VP) and a descriptive level name (e.g. Associate Manager, Lead Specialist)." },
      { title: "Set hierarchy sequence order", description: "Enter an order number where lower numbers represent entry/junior levels and higher numbers represent senior leadership. Reports and sorting rely on this sequence." },
      { title: "Connect to positions and compensation", description: "Link grades to approved department positions and payroll salary structures to enforce structured pay ranges and transparent promotion paths." },
      { title: "Manage lifecycle status", description: "In edit mode, toggle status between Active (available for new positions and hires) and Inactive (retained on existing staff records but hidden from new selections)." },
    ],
    note: "Grades provide uniform career leveling across diverse subsidiaries. Inactivating a grade preserves historical compensation and promotion records without disrupting current employees.",
  },
  positions: {
    title: "Track approved positions & workforce vacancies",
    introduction: "Positions represent budgeted, approved seats within a specific company department or team (e.g. 'Shift Supervisor × 3' or 'Frontend Lead × 1').",
    steps: [
      { title: "Create an approved position", description: "Select Add position, enter an operational position title (e.g. Shift Supervisor), and select the target company department or team." },
      { title: "Map job title & grade", description: "Optionally link the position to a master Job Title and Grade to inherit leveling guidelines and compensation structure benchmarks." },
      { title: "Set approved headcount quota", description: "Enter the approved headcount quota (e.g. 3 seats) or leave blank for an unrestricted role. Positions with quotas automatically calculate open vacancies." },
      { title: "Set effective dates & lifecycle", description: "Specify the Approved from date and optional End date for contract or project roles. Active positions appear in recruitment and vacancy metrics." },
      { title: "Monitor open vacancies", description: "View filled seats versus approved quotas in the table and HR Dashboard. As employees are placed into the position, vacancies update in real time." },
    ],
    note: "Positions belong to a specific company's department or team (never the abstract shared department template). To move a seat to another department, retire the position and create a new one in the destination unit.",
  },
  "cost-centres": {
    title: "Manage accounting cost centres",
    introduction: "Cost centres define financial accounting codes where employee compensation, statutory contributions, and operational costs are booked.",
    steps: [
      { title: "Add a cost centre", description: "Select Add cost centre, enter the accounting code (e.g. CC-101, CC-OPS, CC-ENG) matching your general ledger chart of accounts, and enter a descriptive name." },
      { title: "Assign to employee records", description: "Select the cost centre when hiring or editing employee records and configuring payroll salaries to tag payroll expenses to the correct business unit." },
      { title: "Export for financial journals", description: "Group payroll summaries, bank payment advice files, and general ledger journal exports by cost centre for streamlined reconciliation in your ERP." },
      { title: "Retire obsolete cost centres", description: "When an accounting unit is discontinued, edit the cost centre and set its status to Inactive. Existing historical payroll records remain intact." },
    ],
    note: "Cost centres are shared across the tenant. Inactive cost centres are preserved for past payroll audits and accounting reports, but cannot be assigned to new employee records.",
  },
  "employee-ids": {
    title: "Configure automatic employee ID numbering",
    introduction: "Employee ID schemes generate consistent, sequential identification codes for new hires automatically upon onboarding.",
    steps: [
      { title: "Add an ID numbering scheme", description: "Select Add scheme. Choose the Scope: 'Whole tenant' for a global group pattern, or select a specific company for subsidiary-specific numbering." },
      { title: "Define prefix and separator", description: "Enter an uppercase prefix (e.g. ACME, NOV, EMP) and an optional separator character (such as '-', '/', or leave empty)." },
      { title: "Set digit padding & starting number", description: "Choose digit padding (e.g. 4 digits generates 0001) and enter the starting sequence number (e.g. 1 or 1001). Check the live Next ID preview." },
      { title: "Automatic assignment during onboarding", description: "When hiring a new employee, HRMS suggests the next sequential ID automatically. A company-specific scheme always overrides the whole-tenant scheme." },
      { title: "Edit or remove schemes", description: "Edit a scheme to update formatting or advance the sequence. Removing a scheme returns that scope to manual employee ID entry." },
    ],
    note: "ID schemes apply only to new hires created after the scheme is configured; existing employees are never renumbered. If no scheme is configured, employee IDs must be entered manually.",
  },
  "company-admins": {
    title: "Manage company administrators & access permissions",
    introduction: "Configure company-wide administrative accounts for HR managers, accountants, and auditors who manage records across legal entities.",
    steps: [
      { title: "Add an administrative user", description: "Select Add admin, enter their full name, official work email address, and an initial secure password." },
      { title: "Assign an administrative role", description: "Select the role matching their duties, such as Company Admin, HR Manager, Payroll Officer, or Super Admin." },
      { title: "Define company access scope", description: "Select the specific company they are authorized to manage, or grant All companies scope for group-level administrators." },
      { title: "Toggle account status & access", description: "Temporarily disable an administrator's sign-in by switching their status to Inactive. Inactive users cannot sign in, but their audit trail is preserved." },
      { title: "Reset administrator credentials", description: "Use Reset password to generate a secure temporary password when an administrator needs credentials restored." },
    ],
    note: "This panel is strictly for administrative logins. Ordinary employee self-service logins (mobile/web portal attendance, leave, payslips) are managed directly on the employee's personal profile under Employees → select employee → Access.",
  },
};
