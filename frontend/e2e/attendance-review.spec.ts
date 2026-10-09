/**
 * Attendance rules that need a person in the loop, through the real UI and API with synthetic data
 * in an isolated *_test database (see playwright.config.ts): a check-out more than 16 hours after
 * check-in must be confirmed by the employee, and the day then waits for HR to accept it.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

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

/** The calendar date of `instant` in India, as YYYY-MM-DD (the fallback policy's timezone). */
const istDate = (instant: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(instant);

test("a very long day is confirmed by the employee and accepted by HR", async ({ page, browser, request }) => {
  const tag = randomUUID().slice(0, 8);
  const adminEmail = `e2e-admin-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Review ${tag}`, admin_email: adminEmail, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Operator" }, token);
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Asha", legal_last_name: "Rao" }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: `EMP-${tag}`, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01",
    changes: { location_id: location.id, org_unit_id: unit.id, job_id: job.id } }, token);
  const email = `e2e-employee-${tag}@example.com`;
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  const employeeToken = (await call(request, "POST", "/v1/auth/login", { identifier: email, password })).access_token;

  // A check-in 17 hours ago that was never closed (entered as an approved correction).
  const checkIn = new Date(Date.now() - 17 * 3600_000);
  const workDate = istDate(checkIn);
  const correction = await call(request, "POST", "/v1/corrections", { work_date: workDate, correction_type: "PUNCH_IN",
    requested_punch_in: checkIn.toISOString(), reason: "Checked in at the gate" }, employeeToken);
  await call(request, "POST", `/v1/corrections/${correction.id}/approve`, { action: "APPROVE" }, token);

  // The employee is warned before a 17-hour day is recorded; cancelling keeps them checked in.
  await signIn(page, email);
  await page.goto("/attendance");
  const checkOut = page.getByRole("button", { name: "Check out", exact: true });
  await checkOut.click();
  const warning = page.getByRole("dialog");
  await expect(warning.getByText("Check out after a very long day?")).toBeVisible();
  await expect(warning.getByText(/records a 17-hour day, which HR will review/)).toBeVisible();
  await warning.getByRole("button", { name: "Cancel" }).click();
  await expect(checkOut).toBeVisible();
  await checkOut.click();
  await page.getByRole("dialog").getByRole("button", { name: "Check out anyway" }).click();
  await expect(page.getByText("Recorded — HR will review this day")).toBeVisible();

  // HR finds the day under "Needs review" and accepts it.
  const hrContext = await browser.newContext({ baseURL: "http://127.0.0.1:18180", timezoneId: "Asia/Kolkata" });
  const hr = await hrContext.newPage();
  await signIn(hr, adminEmail);
  await hr.goto(`/daily-analysis?date=${workDate}`);
  await hr.getByRole("tab", { name: /Needs review/ }).click();
  const row = hr.getByRole("row", { name: /Asha Rao/ });
  await expect(row.getByText("Review")).toBeVisible();
  await row.click();
  const sheet = hr.getByRole("dialog");
  await expect(sheet.getByText("Needs HR review")).toBeVisible();
  await expect(sheet.getByText(/Over 16 hours from check-in to check-out/)).toBeVisible();
  await sheet.getByRole("button", { name: "Accept as recorded" }).click();
  await expect(hr.getByText("Day reviewed")).toBeVisible();
  await expect(sheet.getByText("Reviewed by HR")).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Accept as recorded" })).toHaveCount(0);

  const days = await call(request, "GET", `/v1/time/attendance-days?employment_id=${employee.id}&from_date=${workDate}&to_date=${workDate}`, undefined, token);
  expect(days[0].review_flags).toEqual(["LONG_DAY"]);
  expect(days[0].needs_review).toBe(false);
  // The fallback policy has overtime off, so the extra time is shown only.
  expect(days[0].ot_status).toBe("INFO");
  expect(days[0].ot_minutes).toBeGreaterThan(0);
  await hrContext.close();
});
