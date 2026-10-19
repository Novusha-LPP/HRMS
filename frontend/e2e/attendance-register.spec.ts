/**
 * HR's attendance register, through the real UI and API with synthetic data in an isolated *_test
 * database: find an employee, read their days, and correct a day directly — no approval step.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { format } from "date-fns";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

const istDate = (instant: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(instant);

test("HR finds an employee and corrects a day directly", async ({ page, request }) => {
  const tag = randomUUID().slice(0, 8);
  const adminEmail = `e2e-admin-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Register ${tag}`, admin_email: adminEmail, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Stores", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Storekeeper" }, token);
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Meera", legal_last_name: `Iyer${tag}` }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: `REG-${tag}`, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01",
    changes: { location_id: location.id, org_unit_id: unit.id, job_id: job.id } }, token);
  const email = `e2e-employee-${tag}@example.com`;
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  const employeeToken = (await call(request, "POST", "/v1/auth/login", { identifier: email, password })).access_token;
  await call(request, "POST", "/v1/time/punches", { punch_type: "IN" }, employeeToken);
  const today = istDate(new Date());
  const yesterday = istDate(new Date(Date.now() - 86_400_000));

  await signIn(page, adminEmail);
  await page.getByRole("link", { name: "Attendance register" }).first().click();
  await expect(page).toHaveURL(/attendance\/register/);
  await expect(page.getByText("Choose a person")).toBeVisible();
  await page.getByLabel("Company", { exact: true }).selectOption(le);
  await page.getByLabel("Department", { exact: true }).selectOption(unit.id);
  await page.getByLabel("Search people").fill(`REG-${tag}`);
  await page.getByRole("option", { name: new RegExp(`Meera Iyer${tag}`) }).click();
  await expect(page).toHaveURL(new RegExp(`company=${le}.*department=${unit.id}.*employee=${employee.id}`));
  await expect(page.getByText(`REG-${tag} · Stores · Storekeeper`)).toBeVisible();
  await expect(page.getByText("Shift 09:30–18:30")).toBeVisible();
  if (today.slice(0, 7) === yesterday.slice(0, 7)) {
    // Today's check-in shows as still in.
    await expect(page.getByText("Still in")).toBeVisible();
  }

  // Yesterday had no punches: open it, then fill it in.
  await page.goto(`/attendance/register?employee=${employee.id}&month=${yesterday.slice(0, 7)}`);
  const longDate = format(new Date(`${yesterday}T00:00:00`), "EEEE d MMMM");
  await page.getByRole("button", { name: new RegExp(`^${longDate}`) }).click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByText("No punches on this day.")).toBeVisible();
  await panel.getByRole("button", { name: "Edit attendance" }).click();
  await expect(panel.getByRole("heading", { name: "Edit attendance" })).toBeVisible();
  await panel.getByRole("button", { name: /Full shift/ }).click();
  await expect(panel.getByLabel("Check in", { exact: true })).toHaveValue("09:30");
  await expect(panel.getByLabel("Check out", { exact: true })).toHaveValue("18:30");
  await panel.getByRole("button", { name: "Add break" }).click();
  await panel.getByLabel("From", { exact: true }).fill("13:00");
  await panel.getByLabel("To", { exact: true }).fill("13:45");
  // exact: the "8h 15m beyond shift" badge also contains this text.
  await expect(panel.getByText("8h 15m", { exact: true })).toBeVisible();
  // An incomplete entry is explained and blocks saving.
  await panel.getByRole("button", { name: "Add time out" }).click();
  await expect(panel.getByText(/needs both times/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await panel.getByRole("button", { name: "Remove" }).last().click();
  await panel.getByRole("button", { name: "Biometric / device problem" }).click();
  await panel.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Attendance updated")).toBeVisible();
  // Back on the day's details, showing the correction.
  await expect(panel.getByText("Corrected — Biometric / device problem").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  const row = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: new RegExp(`^${longDate}`) }) });
  await expect(row.getByText("Edited")).toBeVisible();
  await expect(row.getByText("8h 15m")).toBeVisible();

  // The same register is a tab of the employee's profile; Escape closes only the day on top.
  if (today.slice(0, 7) === yesterday.slice(0, 7)) {
    await page.goto("/employees");
    await page.getByRole("row", { name: new RegExp(`Meera Iyer${tag}`) }).click();
    const profile = page.getByRole("dialog");
    await profile.getByRole("tab", { name: "Attendance" }).click();
    await profile.getByRole("button", { name: new RegExp(`^${longDate}`) }).click();
    await expect(page.getByRole("dialog")).toHaveCount(2);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(page.getByRole("dialog").getByRole("tab", { name: "Attendance" })).toBeVisible();
  }

  // The employee sees the change and the reason in their corrections.
  const corrections = await call(request, "GET", "/v1/corrections", undefined, employeeToken);
  expect(corrections.map((c: { correction_type: string; reason: string }) => [c.correction_type, c.reason])).toEqual([
    ["DIRECT_EDIT", "Biometric / device problem"],
  ]);
});

test("company and department filters stay in sync with the chosen person's register", async ({ page, request }) => {
  const tag = randomUUID().slice(0, 8);
  const adminEmail = `e2e-register-filters-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Register Group ${tag}`, admin_email: adminEmail, admin_password: password,
  });
  const token = admin.access_token;
  const first = admin.user.legal_entities[0];
  const second = await call(request, "POST", "/v1/org/legal-entities", { name: `Sister Company ${tag}` }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Executive" }, token);
  const firstLocation = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: first.id }, token);
  const secondLocation = await call(request, "POST", "/v1/org/locations", { name: "Branch", type: "OFFICE", legal_entity_id: second.id }, token);
  const department = (name: string, company: string) => call(request, "POST", "/v1/org/org-units", {
    name, type: "DEPARTMENT", legal_entity_id: company, effective_from: "2020-01-01",
  }, token);
  const stores = await department("Stores", first.id);
  const accounts = await department("Accounts", first.id);
  const sisterStores = await department("Stores", second.id);
  async function employee(name: string, number: string, company: string, unit: string, location: string) {
    const person = await call(request, "POST", "/v1/persons", { legal_first_name: name, legal_last_name: "Test" }, token);
    const emp = await call(request, "POST", "/v1/employees", {
      person_id: person.id, legal_entity_id: company, employee_number: number, hire_date: "2020-01-01",
    }, token);
    await call(request, "POST", "/v1/personnel-actions", { employment_id: emp.id, type: "HIRE", effective_date: "2020-01-01",
      changes: { location_id: location, org_unit_id: unit, job_id: job.id } }, token);
    return emp;
  }
  const meera = await employee("Meera", "REG-STORES", first.id, stores.id, firstLocation.id);
  await employee("Ravi", "REG-ACCOUNTS", first.id, accounts.id, firstLocation.id);
  await employee("Nila", "REG-SISTER", second.id, sisterStores.id, secondLocation.id);
  // More than one API page: Meera sorts after these people and must still be selectable.
  for (let i = 0; i < 101; i++) {
    const number = String(i).padStart(3, "0");
    await employee(`Extra${number}`, `REG-EXTRA-${number}`, first.id, stores.id, firstLocation.id);
  }

  await signIn(page, adminEmail);
  await page.goto("/attendance/register?month=2026-08");
  const companySelect = page.getByLabel("Company", { exact: true });
  const departmentSelect = page.getByLabel("Department", { exact: true });
  const people = page.getByRole("listbox", { name: "People" });
  await expect(people.getByRole("option")).toHaveCount(104);
  await expect(page.getByRole("status").filter({ hasText: /^104 employees$/ })).toBeVisible();
  await expect(page.getByText(/Showing the first 50/)).toHaveCount(0);
  await expect(departmentSelect.getByRole("option", { name: `Stores · ${second.name}`, exact: true })).toHaveCount(1);

  await companySelect.selectOption(first.id);
  await expect(people.getByRole("option")).toHaveCount(103);
  await expect(departmentSelect.getByRole("option")).toHaveCount(3);
  await expect(departmentSelect.locator(`option[value="${sisterStores.id}"]`)).toHaveCount(0);
  await departmentSelect.selectOption(stores.id);
  await expect(people.getByRole("option")).toHaveCount(102);
  await people.getByRole("option", { name: /Meera Test/ }).click();
  await expect(page.getByText("August 2026", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`month=2026-08.*company=${first.id}.*department=${stores.id}.*employee=${meera.id}`));
  await page.reload();
  await expect(companySelect).toHaveValue(first.id);
  await expect(departmentSelect).toHaveValue(stores.id);
  await expect(page.getByText("August 2026", { exact: true })).toBeVisible();

  await departmentSelect.selectOption(accounts.id);
  await expect(page.getByText("Choose a person", { exact: true })).toBeVisible();
  await expect(people.getByRole("option", { name: /Ravi Test/ })).toBeVisible();
  await expect(page).not.toHaveURL(/employee=/);
  await people.getByRole("option", { name: /Ravi Test/ }).click();
  await companySelect.selectOption(second.id);
  await expect(departmentSelect).toHaveValue("");
  await expect(departmentSelect.getByRole("option")).toHaveCount(2);
  await expect(page.getByText("Choose a person", { exact: true })).toBeVisible();
  await expect(people.getByRole("option")).toHaveCount(1);
  await expect(people.getByRole("option", { name: /Nila Test/ })).toBeVisible();
  await page.getByLabel("Search people").fill("REG-STORES");
  await expect(people.getByText(/No one matches/)).toBeVisible();
  await page.getByLabel("Search people").clear();
  await expect(people.getByRole("option")).toHaveCount(1);

  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(companySelect).toHaveValue("");
  await expect(departmentSelect).toHaveValue("");
  await expect(people.getByRole("option")).toHaveCount(104);
  await departmentSelect.selectOption(sisterStores.id);
  await expect(people.getByRole("option")).toHaveCount(1);
  await expect(people.getByRole("option", { name: /Nila Test/ })).toBeVisible();
  await page.screenshot({ path: "/tmp/hrms-attendance-register-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(companySelect).toBeVisible();
  await expect(departmentSelect).toBeVisible();
  await expect(people.getByRole("option", { name: /Nila Test/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "/tmp/hrms-attendance-register-mobile.png", fullPage: true });
});
