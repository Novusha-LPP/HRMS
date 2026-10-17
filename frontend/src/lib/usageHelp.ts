export type UsageHelpTopic = "organization" | "departments" | "companies" | "company-departments" | "teams" | "approvals" | "payroll"
  | "integrations-overview" | "integrations-keys" | "integrations-settings" | "integrations-mappings" | "integrations-log" | "integrations-review";

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
    title: "Set up your organization",
    introduction: "Define departments once, then organize each company’s teams and employees.",
    steps: [
      { title: "Create the department list", description: "Open Departments and create Sales, HR, Finance, or other departments. No company selection is needed yet." },
      { title: "Assign departments to companies", description: "Select Assign to company, choose a company, tick the departments it needs, then select Assign departments. Repeat for other companies." },
      { title: "Manage teams within each company", description: "Open Companies → Departments & teams. Choose a department to create teams and assign employees." },
    ],
    note: "The same department can belong to several companies. Their teams and employees remain separate.",
  },
  departments: {
    title: "Use the shared department list",
    introduction: "Create a reusable list of departments before assigning companies.",
    steps: [
      { title: "Create a department", description: "Select Create department. Enter a name and an optional code, then save. Add each department your organization needs." },
      { title: "Assign one or several departments", description: "Select Assign to company. Choose the company, tick the departments, then select Assign departments. Departments already assigned are marked Assigned." },
      { title: "Open a company’s departments", description: "Select a company name on a department card, or go to Companies → Departments & teams. Manage teams and employees there." },
      { title: "Edit a shared department", description: "Select its pencil icon to change the name or code. The change updates that department in every assigned company." },
    ],
    note: "A group administrator creates and edits shared departments. Company administrators can assign existing departments within their authorized companies.",
  },
  companies: {
    title: "Manage companies and their teams",
    introduction: "Each company has its own departments, teams, and employee assignments.",
    steps: [
      { title: "Open the company", description: "Find its card and select Departments & teams." },
      { title: "Assign its departments", description: "Select Assign departments, choose departments from the shared list, then save." },
      { title: "Manage teams and employees", description: "On a department card, select Manage teams & employees. Create teams, view members, and assign employees." },
    ],
    note: "To add or edit a company, use Add company or the pencil icon. Company details are managed by a group administrator.",
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
};
