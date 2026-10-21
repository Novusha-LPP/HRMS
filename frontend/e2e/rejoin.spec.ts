/**
 * Leavers and rejoining through the real UI and API, with synthetic data in an isolated
 * *_test database: company rules for unused leave and rejoining, the settlement shown when
 * someone is separated, the Continue / Start fresh choice on rehire, and the warning when
 * someone who already has a record is added again.
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

function daysAgo(n: number) {
  return new Date(Date.now() - n * 86400_000).toISOString().slice(0, 10);
}

type Seed = { token: string; email: string; employeeId: string; name: string; leaveTypeId: string };

async function seed(request: APIRequestContext): Promise<Seed> {
  const tag = randomUUID().slice(0, 8);
  const email = `e2e-rejoin-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Rejoin ${tag}`, admin_email: email, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Operator" }, token);
  const placement = { location_id: location.id, org_unit_id: unit.id, job_id: job.id };
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Binu", legal_last_name: `Singh${tag}` }, token);
  const employee = await call(request, "POST", "/v1/employees",
    { person_id: person.id, legal_entity_id: le, employee_number: `RJ-${tag}`, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: placement }, token);
  const leaveType = await call(request, "POST", "/v1/leave/types", { name: "Annual", code: "AL", days_per_year: 12, encashable: true }, token);
  await call(request, "POST", "/v1/leave/balances/adjust",
    { employment_id: employee.id, leave_type_id: leaveType.id, quantity: 10, kind: "OPENING", reason: "Test balance", effective_date: daysAgo(150) }, token);
  return { token, email, employeeId: employee.id, name: `Binu Singh${tag}`, leaveTypeId: leaveType.id };
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

async function chooseAction(page: Page, label: string) {
  await page.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("menuitem", { name: label }).click();
}

test.describe.configure({ mode: "serial" });
let s: Seed;
test.beforeAll(async ({ request }) => { s = await seed(request); });

test("1 · HR sets the company rules for leavers and rejoining", async ({ page }) => {
  await signIn(page, s.email);
  await page.goto("/policy?tab=leave&section=leavers");
  await expect(page.getByTestId("no-separation-rules")).toBeVisible();
  await expect(page.getByTestId("no-rejoin-policies")).toBeVisible();

  const rule = page.getByRole("form", { name: "Add a rule for leavers" });
  await rule.getByLabel("What happens").selectOption("LAPSE");
  await rule.getByLabel("Starts on").fill("2020-01-01");
  await rule.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByTestId("separation-rules")).toContainText("Lapse");

  const policy = page.getByRole("form", { name: "Add a rejoin policy" });
  await policy.getByLabel("Longest break to continue (days)").fill("30");
  await policy.getByLabel("Starts on").fill("2020-01-01");
  await policy.getByRole("button", { name: "Add policy" }).click();
  await expect(page.getByTestId("rejoin-policies")).toContainText("a break over 30 days must start fresh");
});

test("2 · recording a separation shows what happens to the unused leave", async ({ page, request }) => {
  await signIn(page, s.email);
  await openProfile(page, s.name);
  await chooseAction(page, "Record separation");
  await page.getByLabel("Last working day").fill(daysAgo(101));
  await page.getByLabel("Reason").selectOption("RESIGNATION");
  const notice = page.getByTestId("separation-leave");
  await expect(notice).toContainText("Annual");
  await expect(notice).toContainText("10 days lapses");
  await page.getByRole("button", { name: "Record separation" }).last().click();
  await expect(page.getByText("Separation recorded")).toBeVisible();

  const settlements = await call(request, "GET", `/v1/leave/separation-settlements?employment_id=${s.employeeId}`, undefined, s.token);
  expect(settlements[0]).toMatchObject({ action: "LAPSE", lapsed_days: 10 });
});

test("3 · a long break can only start fresh, and the history keeps both stints", async ({ page, request }) => {
  await signIn(page, s.email);
  await openProfile(page, s.name);
  await chooseAction(page, "Rehire");
  const panel = page.getByTestId("rejoin-panel");
  await expect(panel).toContainText("break of 100 days");
  await expect(panel).toContainText("company limit for continuing: 30 days");

  // Continuing after a break this long is refused until it is accepted with a reason.
  await panel.getByRole("radio", { name: /^Continue earlier service/ }).check();
  await expect(page.getByText("The break is longer than 30 days")).toBeVisible();

  await panel.getByRole("radio", { name: /^Start fresh/ }).check();
  await panel.getByLabel("Reason for this choice").fill("New contract");

  await page.getByLabel("Department").selectOption({ label: "Operations" });
  await page.getByLabel("Designation").selectOption({ label: "Operator" });
  await page.getByLabel("Location").selectOption({ label: "HQ" });
  await page.getByRole("button", { name: "Rehire employee" }).click();
  await expect(page.getByText("Employee rehired")).toBeVisible();

  const history = await call(request, "GET", `/v1/employees/${s.employeeId}/employment-history`, undefined, s.token);
  expect(history.spells).toHaveLength(2);
  expect(history.spells[0].rejoin).toMatchObject({ mode: "FRESH", reason: "New contract" });
  expect(history.continuity_start_date).toBe(new Date().toISOString().slice(0, 10));
  const balances = await call(request, "GET", `/v1/leave/balances?employment_id=${s.employeeId}`, undefined, s.token);
  expect(balances.find((b: { leave_type_id: string }) => b.leave_type_id === s.leaveTypeId).available_days).toBe(0);

  await openProfile(page, s.name);
  await expect(page.getByTestId("employment-stints")).toContainText("Rejoined");
});

test("4 · adding someone who already has a record asks first", async ({ page }) => {
  await signIn(page, s.email);
  await page.goto("/employees");
  await page.getByRole("button", { name: "Add employee" }).first().click();
  const [first, ...rest] = s.name.split(" ");
  await page.getByLabel("First name").fill(first);
  await page.getByLabel("Last name").fill(rest.join(" "));
  await expect(page.getByTestId("hire-lookalikes")).toContainText(s.name);
  await expect(page.getByText("choose Rehire")).toBeVisible();
  const submit = page.getByRole("button", { name: "Add employee" }).last();
  await expect(submit).toBeDisabled();
  await page.getByLabel(/Employee ID/).fill("RJ-NEW-1");
  await expect(submit).toBeDisabled(); // still waiting for the answer about the lookalike
  await page.getByLabel("This is a different person").check();
  await expect(submit).toBeEnabled();
});

test("5 · the reports list who rejoined and how, and download as a file", async ({ page }) => {
  await signIn(page, s.email);
  await page.goto("/policy?tab=leave&section=leavers");
  const report = page.getByTestId("lifecycle-report");
  await expect(report).toContainText(s.name);
  await expect(report).toContainText("Started fresh");
  await expect(report).toContainText("New contract");
  await page.locator("#lr-from").fill(daysAgo(200)); // the leave was settled 100 days ago
  await page.locator("#lr-kind").selectOption("separation-settlements");
  await expect(report).toContainText("Annual");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^separation-settlements-\d{4}-\d{2}-\d{2}\.csv$/);
});
