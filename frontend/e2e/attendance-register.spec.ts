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
  await page.getByLabel("Search people").fill(`REG-${tag}`);
  await page.getByRole("option", { name: new RegExp(`Meera Iyer${tag}`) }).click();
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
  await expect(panel.getByText("8h 15m")).toBeVisible();
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
