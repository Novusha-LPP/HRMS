/**
 * Earlier service and moving a person to another company of the group, through the real UI and
 * API with synthetic data in an isolated *_test database.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = process.env.E2E_API_URL ?? "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

const daysAgo = (n: number) => new Date(Date.now() - n * 86400_000).toISOString().slice(0, 10);

type Seed = { token: string; email: string; employeeId: string; name: string; sisterId: string; leaveTypeId: string };

async function placementFor(request: APIRequestContext, token: string, le: string, label: string) {
  const location = await call(request, "POST", "/v1/org/locations", { name: `${label} Site`, type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: `${label} Ops`, type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: `${label} Operator` }, token);
  return { location_id: location.id, org_unit_id: unit.id, job_id: job.id };
}

async function seed(request: APIRequestContext): Promise<Seed> {
  const tag = randomUUID().slice(0, 8);
  const email = `e2e-xfer-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Group ${tag}`, admin_email: email, admin_password: password });
  const token = admin.access_token, first = admin.user.legal_entities[0].id;
  const sister = await call(request, "POST", "/v1/org/legal-entities", { name: `Sister ${tag}`, country: "IN" }, token);
  const placementA = await placementFor(request, token, first, "Main");
  await placementFor(request, token, sister.id, "Sister");
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Meera", legal_last_name: `Nair${tag}` }, token);
  const employee = await call(request, "POST", "/v1/employees",
    { person_id: person.id, legal_entity_id: first, employee_number: `MN-${tag}`, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: placementA }, token);
  const leaveType = await call(request, "POST", "/v1/leave/types", { name: "Annual", code: "AL", days_per_year: 12 }, token);
  await call(request, "POST", "/v1/leave/balances/adjust",
    { employment_id: employee.id, leave_type_id: leaveType.id, quantity: 10, kind: "OPENING", reason: "Test balance", effective_date: daysAgo(60) }, token);
  return { token, email, employeeId: employee.id, name: `Meera Nair${tag}`, sisterId: sister.id, leaveTypeId: leaveType.id };
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

async function openProfile(page: Page, name: string) {
  await page.goto("/employees");
  await page.getByRole("button", { name, exact: true }).click();
  await expect(page.getByText("Employee profile")).toBeVisible();
}

test.describe.configure({ mode: "serial" });
let s: Seed;
test.beforeAll(async ({ request }) => { s = await seed(request); });

test("1 · HR records earlier service and sees what it counts for", async ({ page, request }) => {
  await signIn(page, s.email);
  await openProfile(page, s.name);
  const section = page.getByTestId("prior-service");
  await expect(section).toContainText("No work for earlier employers is recorded");
  await section.getByRole("button", { name: "Add" }).click();

  // Time that overlaps their time here is refused with the reason.
  const form = page.getByRole("form", { name: "Record earlier service" });
  await form.getByLabel("Employer").fill("Overlap Ltd");
  await form.getByLabel("From", { exact: true }).fill("2019-06-01");
  await form.getByLabel("To", { exact: true }).fill("2020-03-01");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("overlaps their time here")).toBeVisible();

  await form.getByLabel("Employer").fill("Earlier Co");
  await form.getByLabel("To", { exact: true }).fill("2019-12-31");
  await form.getByLabel("Count towards the service a leave rule asks for").check();
  await form.getByLabel("Count towards service for gratuity").check();
  await form.getByRole("button", { name: "Save" }).click();
  await expect(section).toContainText("Earlier Co");
  await expect(section).toContainText("counts for leave");
  await expect(section).toContainText("counts for gratuity");

  const summary = await call(request, "GET", `/v1/persons/${(await call(request, "GET", `/v1/employees/${s.employeeId}`, undefined, s.token)).person_id}/prior-service`, undefined, s.token);
  expect(summary.recognised_leave_months).toBe(6);
});

test("2 · HR moves them to a sister company and the leave goes with them", async ({ page, request }) => {
  await signIn(page, s.email);
  await openProfile(page, s.name);
  await page.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("menuitem", { name: "Move to another company" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Department").selectOption({ label: "Sister Ops" });
  await dialog.getByLabel("Designation").selectOption({ label: "Sister Operator" });
  await dialog.getByLabel("Location").selectOption({ label: "Sister Site" });
  await dialog.getByLabel(/Employee ID in the new company/).fill("SIS-001");
  await expect(page.getByTestId("move-leave")).toContainText("Annual: 10 days carried over");
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await expect(page.getByText("Moved to the other company")).toBeVisible();

  const old = await call(request, "GET", `/v1/employees/${s.employeeId}`, undefined, s.token);
  expect(old.employment_state).toBe("SEPARATED");
  const all = await call(request, "GET", "/v1/employees?limit=50", undefined, s.token);
  const moved = all.find((e: { employee_number: string }) => e.employee_number === "SIS-001");
  expect(moved.legal_entity_id).toBe(s.sisterId);
  const balances = await call(request, "GET", `/v1/leave/balances?employment_id=${moved.id}`, undefined, s.token);
  expect(balances.find((b: { leave_type_id: string }) => b.leave_type_id === s.leaveTypeId).available_days).toBe(10);
});
