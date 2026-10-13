export type UsageHelpTopic = "organization" | "departments" | "companies" | "company-departments" | "teams" | "approvals" | "payroll";

export interface UsageHelp {
  title: string;
  introduction: string;
  steps: { title: string; description: string }[];
  note: string;
}

/** Saved in-app instructions, selected by the screen's Help button. */
export const usageHelp: Record<UsageHelpTopic, UsageHelp> = {
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
