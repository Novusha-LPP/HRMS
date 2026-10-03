import type { Employment } from "../api/people";
import type { OrgUnit } from "../api/org";

export function departmentMembers(department: OrgUnit, teams: OrgUnit[], employees: Employment[]) {
  const ids = new Set([department.id, ...teams.filter((t) => t.parent_id === department.id && t.legal_entity_id === department.legal_entity_id).map((t) => t.id)]);
  return employees.filter((e) => e.employment_state !== "SEPARATED" && e.legal_entity_id === department.legal_entity_id && e.org_unit_id && ids.has(e.org_unit_id));
}
export function employeeName(employee: Employment) {
  return employee.full_name || [employee.first_name, employee.last_name].filter(Boolean).join(" ") || employee.employee_number;
}
export function employeeMatches(employee: Employment, search: string) {
  return `${employeeName(employee)} ${employee.employee_number}`.toLowerCase().includes(search.trim().toLowerCase());
}
export async function moveTeamMembers(
  employees: Employment[], target: string, move: (employee: Employment, target: string) => Promise<unknown>,
  describeError: (error: unknown) => string, onProgress: (completed: number) => void,
) {
  const succeeded: string[] = [];
  const failed: { id: string; message: string }[] = [];
  for (const employee of employees) {
    try { await move(employee, target); succeeded.push(employee.id); }
    catch (error) { failed.push({ id: employee.id, message: describeError(error) }); }
    onProgress(succeeded.length + failed.length);
  }
  return { succeeded, failed };
}
