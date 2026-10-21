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
  | "payroll-salaries"
  | "payroll-structures"
  | "payroll-components"
  | "payroll-statutory"
  | "leavers"
  | "rejoin"
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
  /** How the numbers are worked out, in the order the calculation does it. */
  calculation?: { title: string; items: { name: string; text: string }[] };
  /** Worked examples with real figures: label on the left, amount on the right. */
  examples?: { title: string; intro: string; rows: [string, string][] }[];
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
  "payroll-salaries": {
    title: "Understand salaries and the breakup",
    introduction: "Each person has one annual CTC (cost to company) and a salary structure. Payroll splits the CTC into the monthly components on their payslip.",
    steps: [
      { title: "See who has a salary", description: "The list shows every current employee with their annual CTC and the date it starts. People with no salary are counted in the notice at the top. Search or filter to find someone, then open them." },
      { title: "Assign the first salary", description: "Choose Assign salary. Enter the annual CTC, the date it starts, and the structure that splits it. Add the reason and, if you like, a note. The breakup is shown before you save so you can check it." },
      { title: "Revise it later", description: "Choose Revise salary for a raise or a change of structure. The revision starts on the date you set, and the earlier salary stays in the history with the dates it applied. A salary that starts in the future shows a Starts badge." },
      { title: "If the breakup cannot be worked out", description: "The page says why, for example the CTC is too low for the fixed amounts in the structure, or a PF or ESIC value has not been loaded. Fix that cause and open the person again." },
    ],
    note: "Previews never change anything. A salary only takes effect from the date you save it with, and people keep the structure version they were given until you revise them.",
    calculation: {
      title: "How the breakup is worked out",
      items: [
        { name: "Monthly CTC", text: "Annual CTC divided by 12." },
        { name: "Earnings", text: "Each earning in the structure is worked out from the monthly CTC, or from a component listed above it, in the structure's order." },
        { name: "Employer cost", text: "Employer PF and employer ESIC are added to the earnings and count inside the CTC, so they are not extra." },
        { name: "The balance", text: "The balancing component (usually Special allowance) takes whatever is left, so earnings plus employer PF, employer ESIC and reimbursements always add up to the monthly CTC." },
        { name: "Gross and net", text: "Gross pay is all the earnings. Net before tax is gross pay minus employee PF, employee ESIC and any other deductions." },
        { name: "Not included yet", text: "Professional tax and income tax (TDS) are not calculated yet, so net pay is before them." },
        { name: "Provisional", text: "If any PF or ESIC value used has not been verified by the payroll reviewer, the breakup is marked provisional." },
      ],
    },
    examples: [
      {
        title: "Example: annual CTC of ₹6,00,000 (ESIC does not apply)",
        intro: "Standard structure, India default values. Monthly CTC = 6,00,000 ÷ 12.",
        rows: [
          ["Monthly CTC", "₹50,000"],
          ["Basic = 50% of CTC", "₹25,000"],
          ["House rent allowance = 40% of Basic", "₹10,000"],
          ["PF wages = Basic ₹25,000, limited to the ₹15,000 ceiling", "₹15,000"],
          ["Employer PF = 12% of ₹15,000", "₹1,800"],
          ["ESIC wages ₹48,200 are over the ₹21,000 ceiling, so employer ESIC", "₹0"],
          ["Special allowance (balance) = 50,000 − 25,000 − 10,000 − 1,800", "₹13,200"],
          ["Gross pay = 25,000 + 10,000 + 13,200", "₹48,200"],
          ["Employee PF = 12% of ₹15,000", "₹1,800"],
          ["Net before tax = 48,200 − 1,800", "₹46,400"],
        ],
      },
    ],
  },
  "payroll-structures": {
    title: "Understand salary structures",
    introduction: "A salary structure is the recipe that turns one number, the annual CTC, into the monthly components on a payslip.",
    steps: [
      { title: "Start from the standard structure", description: "It has Basic at 50% of CTC, House rent allowance at 40% of Basic, Special allowance as the balance, and the PF and ESIC lines. Adjust it to match how you pay." },
      { title: "Choose how each component is worked out", description: "Fixed amount: the same rupees every month. Percentage: a share of the CTC or of a component listed above it. Balance of CTC: whatever is left, and exactly one earning must take it. By law: PF and ESIC, taken from the Statutory values tab." },
      { title: "Mind the order", description: "A percentage can only be of a component that is listed above it. You can also set a minimum and a maximum on a fixed or percentage line, and the result is held between them." },
      { title: "Try a CTC", description: "Enter any annual CTC to see the breakup. It appears once every component is filled in and one takes the balance. If the CTC is too low for the fixed parts, the message says so." },
      { title: "Saving makes a new version", description: "People already on the structure keep their version until their salary is revised, so a change never alters pay that was already set." },
    ],
    note: "The examples use the standard structure and the India default values. Your structure and verified values may differ, so use Try a CTC to see your own numbers.",
    calculation: {
      title: "How a CTC is split, in order",
      items: [
        { name: "1. Monthly CTC", text: "Annual CTC ÷ 12, rounded to the paisa." },
        { name: "2. Fixed lines", text: "The amount you entered, held between the minimum and maximum if you set them." },
        { name: "3. Percentage lines", text: "The percentage × the monthly CTC, or × the earlier component it is based on, then held between the minimum and maximum." },
        { name: "4. Employer PF", text: "The PF employer rate (12%) × PF wages, rounded to the nearest rupee. PF wages are the earnings marked as counting towards PF wages, usually Basic. When the limit is on, PF wages stop at the PF wage ceiling (₹15,000)." },
        { name: "5. Employer ESIC", text: "The ESIC employer rate (3.25%) × ESIC wages, rounded up to the next rupee, and only while ESIC wages are at or under the ESIC ceiling (₹21,000). Above it, ESIC does not apply at all." },
        { name: "6. The balance", text: "Monthly CTC − fixed and percentage lines − employer PF − employer ESIC. Employer ESIC depends on the balance when the balance counts towards ESIC wages, so the system repeats the sum until the figures settle." },
        { name: "7. Employee deductions", text: "Employee PF = PF employee rate (12%) × the same PF wages, rounded to the nearest rupee. Employee ESIC = the ESIC employee rate (0.75%) × ESIC wages, rounded up, when ESIC applies. Other deductions are added as set." },
        { name: "8. Totals", text: "Gross pay = all earnings. Net before tax = gross pay − deductions. Professional tax and TDS are not included yet." },
      ],
    },
    examples: [
      {
        title: "Example: annual CTC of ₹6,00,000 (ESIC does not apply)",
        intro: "Standard structure, India default values. Monthly CTC = 6,00,000 ÷ 12.",
        rows: [
          ["Monthly CTC", "₹50,000"],
          ["Basic = 50% of CTC", "₹25,000"],
          ["House rent allowance = 40% of Basic", "₹10,000"],
          ["PF wages = Basic ₹25,000, limited to the ₹15,000 ceiling", "₹15,000"],
          ["Employer PF = 12% of ₹15,000", "₹1,800"],
          ["ESIC wages ₹48,200 are over the ₹21,000 ceiling, so employer ESIC", "₹0"],
          ["Special allowance (balance) = 50,000 − 25,000 − 10,000 − 1,800", "₹13,200"],
          ["Gross pay = 25,000 + 10,000 + 13,200", "₹48,200"],
          ["Employee PF = 12% of ₹15,000", "₹1,800"],
          ["Net before tax = 48,200 − 1,800", "₹46,400"],
        ],
      },
      {
        title: "Example: annual CTC of ₹2,40,000 (ESIC applies)",
        intro: "The same structure with a lower CTC. Monthly CTC = 2,40,000 ÷ 12.",
        rows: [
          ["Monthly CTC", "₹20,000"],
          ["Basic = 50% of CTC", "₹10,000"],
          ["House rent allowance = 40% of Basic", "₹4,000"],
          ["Employer PF = 12% of ₹10,000 (under the ₹15,000 ceiling)", "₹1,200"],
          ["Special allowance (balance), found so the total equals the CTC", "₹4,208"],
          ["ESIC wages = 10,000 + 4,000 + 4,208 (under the ₹21,000 ceiling, so ESIC applies)", "₹18,208"],
          ["Employer ESIC = 3.25% of 18,208 = 591.76, rounded up", "₹592"],
          ["Check: 10,000 + 4,000 + 4,208 + 1,200 + 592", "₹20,000"],
          ["Gross pay = 10,000 + 4,000 + 4,208", "₹18,208"],
          ["Employee PF = 12% of ₹10,000", "₹1,200"],
          ["Employee ESIC = 0.75% of 18,208 = 136.56, rounded up", "₹137"],
          ["Net before tax = 18,208 − 1,200 − 137", "₹16,871"],
        ],
      },
    ],
  },
  "payroll-components": {
    title: "Understand pay components",
    introduction: "A component is one line on a payslip, such as Basic, an allowance, a deduction or an employer contribution. Salary structures are built by choosing from these components.",
    steps: [
      { title: "Pick the kind", description: "Earning: part of the pay the employee receives. Deduction: taken from the employee's pay. Employer contribution: a cost to the company that sits inside the CTC but is not paid to the employee. Reimbursement: paid back against bills and also counted in the CTC. Information only: shown but never added up." },
      { title: "Say what an earning counts towards", description: "Counts towards PF wages: usually only Basic (and DA). Counts towards ESIC wages: most earnings do, but reimbursements and annual bonus do not. Is taxable. Is reduced for unpaid days: turn it off for fixed monthly amounts." },
      { title: "Code, name and payslip order", description: "The code cannot change after the component is created, and neither can its kind. You can rename it and change its payslip order. Changes apply to breakups worked out from then on." },
      { title: "PF and ESIC are calculated by law", description: "Those components do not take an amount from the structure. They always use the PF and ESIC values on the Statutory values tab." },
    ],
    note: "A component does nothing until a salary structure uses it. Marking it for PF or ESIC wages only matters for earnings, and those marks decide what the PF and ESIC percentages are worked out on.",
    calculation: {
      title: "How the marks change the numbers",
      items: [
        { name: "PF wages", text: "The total of the earnings marked as counting towards PF wages. Employer and employee PF are percentages of this total, limited to the ceiling when the limit is on." },
        { name: "ESIC wages", text: "The total of the earnings marked as counting towards ESIC wages. ESIC is a percentage of this total, and applies only while it is at or under the ESIC ceiling." },
        { name: "Why it matters", text: "Marking House rent allowance as PF wages would raise PF; leaving it unmarked means PF is worked out on Basic alone. Marking a reimbursement as ESIC wages could push someone over the ESIC ceiling and switch ESIC off." },
      ],
    },
    examples: [
      {
        title: "Example: what a mark changes",
        intro: "Monthly Basic ₹10,000, House rent allowance ₹4,000, India default PF values (12%, ceiling ₹15,000).",
        rows: [
          ["Only Basic counts towards PF wages: PF wages", "₹10,000"],
          ["Employee PF = 12% of ₹10,000", "₹1,200"],
          ["Basic and House rent allowance both count: PF wages", "₹14,000"],
          ["Employee PF = 12% of ₹14,000", "₹1,680"],
        ],
      },
    ],
  },
  "payroll-statutory": {
    title: "Understand the PF and ESIC values",
    introduction: "These are the legal rates and wage limits payroll uses for Provident Fund (PF) and Employees' State Insurance (ESIC). Each value has a start date, a source, and a verification.",
    steps: [
      { title: "Load the India defaults", description: "Choose Load India defaults to fill in the PF and ESIC rates and wage ceilings, each with the date it took effect. They load unverified, because the law changes and a person must check them." },
      { title: "Have each value verified", description: "The payroll reviewer checks each value against the current official EPFO and ESIC notification and verifies it. It must be someone other than whoever entered the value. Until then, any breakup that uses it is marked provisional." },
      { title: "Read the three lists", description: "In force today are the values being used now. Coming up are values that start on a later date. Earlier values are history. Calculations use the value that is in force on the day." },
      { title: "When the law changes", description: "Add a new value with its start date instead of editing the old one. The current value ends the day before the new one starts, and the new value needs verifying." },
    ],
    note: "A missing value stops the breakup, and the message names the one that is missing. Loading the defaults first avoids that.",
    calculation: {
      title: "What each value does (India default shown)",
      items: [
        { name: "PF wage ceiling · ₹15,000", text: "The most monthly wages PF is worked out on, when the limit below is on." },
        { name: "Limit PF to the ceiling · 1", text: "1 means PF stops at the ceiling. 0 means PF is worked out on the actual PF wages, however high." },
        { name: "PF employee · 12%", text: "Deducted from the employee: 12% of PF wages (up to the ceiling), rounded to the nearest rupee." },
        { name: "PF employer · 12%", text: "Paid by the company: 12% of PF wages, rounded to the nearest rupee. It covers both EPF and the pension (EPS)." },
        { name: "EPS rate · 8.33% and EPS ceiling · ₹15,000", text: "The pension part of the employer's 12%, worked out on wages up to ₹15,000. The rest of the 12% goes to EPF." },
        { name: "ESIC wage ceiling · ₹21,000", text: "ESIC applies only while monthly ESIC wages are at or under this. Above it, nobody pays ESIC on that salary." },
        { name: "ESIC employee · 0.75%", text: "Deducted from the employee: 0.75% of ESIC wages, rounded up to the next rupee." },
        { name: "ESIC employer · 3.25%", text: "Paid by the company: 3.25% of ESIC wages, rounded up to the next rupee." },
      ],
    },
    examples: [
      {
        title: "Example: PF on Basic of ₹25,000 a month",
        intro: "India defaults: 12% and a ₹15,000 ceiling, with the limit on.",
        rows: [
          ["Wages for PF, limited to the ceiling", "₹15,000"],
          ["Employee PF = 12% × 15,000", "₹1,800"],
          ["Employer PF = 12% × 15,000", "₹1,800"],
        ],
      },
      {
        title: "Example: ESIC for two salaries",
        intro: "India defaults: ceiling ₹21,000, employee 0.75%, employer 3.25%.",
        rows: [
          ["ESIC wages ₹18,208: employee 0.75% = 136.56, rounded up", "₹137"],
          ["ESIC wages ₹18,208: employer 3.25% = 591.76, rounded up", "₹592"],
          ["ESIC wages ₹48,200: over the ceiling, so ESIC", "does not apply"],
        ],
      },
    ],
  },
  leavers: {
    title: "Leavers and rejoining",
    introduction: "Two company rules for people who leave: what happens to their unused leave, and how a rejoin treats their earlier service. With neither set, nothing changes: leave stays as it is and a rejoin continues earlier service.",
    steps: [
      { title: "Decide what happens to unused leave", description: "Add a rule under Unused leave when someone leaves. Lapse removes the balance. Pay it out (encash) pays it, only for leave types marked encashable, and can be capped. Hold keeps it, for a number of days or until they rejoin." },
      { title: "Pick who the rule covers", description: "Choose a company and a leave type, or leave either on Every. When more than one rule fits, the most specific one in force on the last working day wins." },
      { title: "Set how a rejoin starts", description: "Under When someone rejoins choose whether a rejoin continues earlier service or starts fresh by default, and the longest break that may still continue." },
      { title: "See what will happen first", description: "When you record a separation, the sheet lists each unused balance and what the rule does with it. When you rehire someone, it shows the break, the choices and what happens to their leave before you save." },
    ],
    note: "Every outcome is a leave-history entry, so nothing is deleted. If gratuity was paid when someone left, a rejoin always starts fresh. Check any legal point, such as paying out leave on exit, with your labour adviser: the rules here are your company's choices.",
    calculation: {
      title: "How the choices work",
      items: [
        { name: "Lapse", text: "The whole unused balance is removed on the last working day." },
        { name: "Pay out (encash)", text: "Up to the cap (or all of it with no cap) is paid out and recorded as an encashment. Anything above the cap lapses." },
        { name: "Hold", text: "The balance stays. After the hold days, if the person has not rejoined, it lapses. If they rejoin and continue, it is restored." },
        { name: "Continue on rejoin", text: "Earlier service counts and any held leave carries on. Leave that was paid out or lapsed at exit stays gone." },
        { name: "Start fresh on rejoin", text: "Unused leave lapses and service for leave eligibility starts again from the rejoin date." },
        { name: "Long breaks", text: "A break longer than the company limit can only continue if HR records that the break is accepted, with a reason." },
        { name: "The months away", text: "Leave is not credited for the months someone was away, whichever choice is made." },
      ],
    },
    examples: [
      {
        title: "Example: a rule that pays out up to 4 days",
        intro: "Annual leave, 10 days unused on the last working day. Rule: pay out at most 4 days.",
        rows: [
          ["Unused balance", "10 days"],
          ["Paid out (the cap)", "4 days"],
          ["Lapses (the rest)", "6 days"],
          ["Balance after leaving", "0 days"],
        ],
      },
      {
        title: "Example: rejoining after 100 days",
        intro: "Company policy: continue by default, but a break over 30 days must start fresh. 10 days of leave were still held.",
        rows: [
          ["Break", "100 days"],
          ["Choice offered", "Start fresh"],
          ["Held leave", "10 days lapse"],
          ["Service for leave counts from", "The rejoin date"],
          ["To continue anyway", "Accept the break and give a reason"],
        ],
      },
    ],
  },
  rejoin: {
    title: "Rehire someone who left",
    introduction: "Bring a former employee back on the same record. Their history stays together, and you decide whether their earlier service and leave carry on or start again.",
    steps: [
      { title: "Choose the rejoin date and placement", description: "The date they rejoin, and the department, designation and location they return to." },
      { title: "Choose what happens to service and leave", description: "Follow the company default, continue earlier service, or start fresh. The sheet shows the length of the break and what happens to each unused leave balance." },
      { title: "Say if gratuity was paid", description: "If gratuity was paid when they left, their service restarts, so only Start fresh is allowed." },
      { title: "Give a reason where one is needed", description: "Starting fresh needs a reason. Continuing after a break longer than your company allows needs you to accept the break and give a reason." },
    ],
    note: "A returning person has one record, one set of identity numbers and one leave history. If you are about to add someone who has worked here before, rehire them instead of adding them again.",
    calculation: {
      title: "What each choice does",
      items: [
        { name: "Continue", text: "Earlier service counts. Held leave is restored. Leave paid out or lapsed at exit does not come back." },
        { name: "Start fresh", text: "Unused leave lapses as leave-history entries. Service for leave eligibility starts from the rejoin date." },
        { name: "Company default", text: "Set under Leave policies, Leavers and Rejoining. Without one, a rejoin continues." },
      ],
    },
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
