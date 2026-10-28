import { test, expect, type APIRequestContext } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-calendar-test-123";

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, {
    method, data, headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

// The backend uses the real clock, so the month under test is always next month: every day in it is upcoming.
function targetMonth() {
  const now = new Date();
  const year = now.getUTCFullYear() + (now.getUTCMonth() === 11 ? 1 : 0);
  const month = (now.getUTCMonth() + 1) % 12;
  const pad = (n: number) => String(n).padStart(2, "0");
  const days = Array.from({ length: new Date(Date.UTC(year, month + 1, 0)).getUTCDate() }, (_, i) => i + 1);
  const dow = (d: number) => new Date(Date.UTC(year, month, d)).getUTCDay();
  const saturdays = days.filter((d) => dow(d) === 6);
  return {
    iso: (d: number) => `${year}-${pad(month + 1)}-${pad(d)}`,
    sundays: days.filter((d) => dow(d) === 0),
    saturdays,
    firstFriday: days.find((d) => dow(d) === 5)!,
    listLabel: (d: number) => `Sat, ${d} ${new Date(Date.UTC(year, month, d)).toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}`,
  };
}

test("attendance calendar shows assigned weekly offs even without punches", async ({ page, request }) => {
  const tag = randomUUID().slice(0, 8);
  const m = targetMonth();
  const [firstSat, secondSat, , fourthSat] = m.saturdays;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Calendar ${tag}`, admin_email: `calendar-admin-${tag}@example.com`,
    admin_password: password,
  });
  const token = admin.access_token;
  const person = await call(request, "POST", "/v1/persons", {
    legal_first_name: "Calendar", legal_last_name: tag,
  }, token);
  const emp = await call(request, "POST", "/v1/employees", {
    person_id: person.id, legal_entity_id: admin.user.legal_entities[0].id,
    employee_number: `CAL-${tag}`, hire_date: "2020-01-01",
  }, token);
  const email = `calendar-employee-${tag}@example.com`;
  await call(request, "POST", "/v1/users", {
    email, password, employment_id: emp.id, role: "EMPLOYEE", scope_type: "SELF",
    must_change_password: false,
  }, token);
  const policy = await call(request, "POST", "/v1/policies/templates", {
    name: "Second Saturday only", timezone: "Asia/Kolkata", work_days: "1111110",
    saturday_pattern: "SECOND_OFF", ot_enabled: false,
  }, token);
  await call(request, "POST", "/v1/policies/assignments", {
    employment_id: emp.id, policy_template_id: policy.id, effective_from: m.iso(1),
  }, token);
  await call(request, "POST", "/v1/time/holidays", {
    name: "Calendar Festival", holiday_date: m.iso(m.firstFriday),
  }, token);
  // No materialized attendance rows exist: weekly offs must come from policy resolution.
  expect(await call(request, "GET", `/v1/time/attendance-days?employment_id=${emp.id}&from_date=${m.iso(1)}&to_date=${m.iso(28)}`, undefined, token)).toEqual([]);

  await page.clock.setFixedTime(new Date(`${m.iso(6)}T06:30:00Z`));
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
  await page.goto("/attendance");
  for (const day of [...m.sundays, secondSat]) {
    await expect(page.locator(`[data-date="${m.iso(day)}"]`).getByText("Weekly off", { exact: true })).toBeVisible();
  }
  await expect(page.locator(`[data-date="${m.iso(firstSat)}"]`)).not.toContainText("Weekly off");
  await expect(page.locator(`[data-date="${m.iso(fourthSat)}"]`)).not.toContainText("Weekly off");
  await expect(page.locator(`[data-date="${m.iso(m.firstFriday)}"]`)).toContainText("Calendar Festival");
  await expect(page.locator(`[data-date="${m.iso(fourthSat)}"]`)).toContainText("upcoming");
  await page.getByRole("radio", { name: "List", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: m.listLabel(secondSat) })).toContainText("Weekly off");
  await page.getByRole("radio", { name: "Calendar", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(`[data-date="${m.iso(secondSat)}"]`).getByText("Weekly off", { exact: true })).toBeVisible();
});
