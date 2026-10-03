import assert from "node:assert/strict";
import { test } from "node:test";
import { departmentMembers, employeeMatches, moveTeamMembers } from "../src/lib/teamManagement.ts";
import type { Employment } from "../src/api/people.ts";
import type { OrgUnit } from "../src/api/org.ts";
const department = { id: "sales", legal_entity_id: "company" } as OrgUnit;
const teams = [{ id: "inside", parent_id: "sales", legal_entity_id: "company" }, { id: "foreign", parent_id: "sales", legal_entity_id: "other" }] as OrgUnit[];
const employee = (id: string, unit: string, company = "company", state = "ACTIVE") => ({ id, org_unit_id: unit, legal_entity_id: company, employment_state: state, employee_number: id, full_name: "Priya Sharma" }) as Employment;
test("department members include its teams and exclude other companies, departments and leavers", () => {
  const rows = [employee("1", "sales"), employee("2", "inside"), employee("3", "foreign"), employee("4", "finance"), employee("5", "sales", "other"), employee("6", "inside", "company", "SEPARATED")];
  assert.deepEqual(departmentMembers(department, teams, rows).map((e) => e.id), ["1", "2"]);
  assert.equal(employeeMatches(rows[0], "  PRIYA "), true);
  assert.equal(employeeMatches(rows[0], "1"), true);
});
test("bulk assignment reports partial failures and retries only failed employees", async () => {
  const rows = [employee("1", "sales"), employee("2", "sales"), employee("3", "inside")];
  const calls: string[] = []; const progress: number[] = [];
  const result = await moveTeamMembers(rows, "field", async (e, target) => {
    assert.equal(target, "field"); calls.push(e.id); if (e.id === "2") throw new Error("Scheduled transfer conflicts");
  }, (e) => (e as Error).message, (n) => progress.push(n));
  assert.deepEqual(result.succeeded, ["1", "3"]);
  assert.deepEqual(result.failed, [{ id: "2", message: "Scheduled transfer conflicts" }]);
  assert.deepEqual(progress, [1, 2, 3]);
  await moveTeamMembers(rows.filter((e) => result.failed.some((f) => f.id === e.id)), "field", async (e) => { calls.push(e.id); }, String, () => {});
  assert.deepEqual(calls, ["1", "2", "3", "2"]);
});

test("companies sharing a department definition never share team members", () => {
  const shared = "shared-sales";
  const first = { id: "sales-a", legal_entity_id: "a", department_template_id: shared } as OrgUnit;
  const second = { id: "sales-b", legal_entity_id: "b", department_template_id: shared } as OrgUnit;
  const localTeams = [{ id: "inside-a", parent_id: "sales-a", legal_entity_id: "a" }, { id: "inside-b", parent_id: "sales-b", legal_entity_id: "b" }] as OrgUnit[];
  const staff = [employee("alice", "inside-a", "a"), employee("bob", "inside-b", "b")];
  assert.deepEqual(departmentMembers(first, localTeams, staff).map((e) => e.id), ["alice"]);
  assert.deepEqual(departmentMembers(second, localTeams, staff).map((e) => e.id), ["bob"]);
});
