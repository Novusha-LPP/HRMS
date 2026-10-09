/**
 * Setting up holidays the way HR thinks about it, through the real UI with synthetic data in an
 * isolated *_test database: 1) list the year's holidays, 2) build named calendars by ticking
 * holidays from that list, 3) give each calendar to the whole company or a department.
 */
import { test, expect, type APIRequestContext } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";
const shots = process.env.SHOTS;

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

test("HR lists holidays, groups them into calendars and assigns them", async ({ page, request }) => {
  const tag = randomUUID().slice(0, 8);
  const email = `e2e-admin-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Holidays ${tag}`, admin_email: email, admin_password: password });
  const le = admin.user.legal_entities[0].id;
  await call(request, "POST", "/v1/org/org-units", {
    name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, admin.access_token);
  const year = new Date().getFullYear();

  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
  await page.goto("/policy?tab=leave&section=holidays");

  // 1. The holiday list.
  await expect(page.getByText(`No holidays for ${year} yet`)).toBeVisible();
  for (const [day, name] of [["01-26", "Republic Day"], ["03-04", "Holi"], ["11-08", "Diwali"]]) {
    await page.getByLabel("Date", { exact: true }).first().fill(`${year}-${day}`);
    await page.getByLabel("Holiday", { exact: true }).first().fill(name);
    await page.getByRole("button", { name: "Add holiday" }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(page.getByText("Not in a calendar yet")).toHaveCount(3);
  if (shots) await page.screenshot({ path: `${shots}/hol-1-list.png` });

  // 2. Calendars, ticked from the list.
  await page.getByRole("button", { name: "Next: calendars" }).click();
  await page.getByRole("button", { name: "New calendar" }).click();
  let sheet = page.getByRole("dialog");
  await sheet.getByLabel("Calendar name").fill("HO");
  await sheet.getByRole("checkbox", { name: "Republic Day" }).check();
  await sheet.getByRole("checkbox", { name: "Diwali" }).check();
  await expect(sheet.getByText("Holidays · 2 of 3 ticked")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/hol-2-tick.png` });
  await sheet.getByRole("button", { name: "Create calendar" }).click();
  await expect(page.getByText("HO created")).toBeVisible();

  await page.getByRole("button", { name: "New calendar" }).click();
  sheet = page.getByRole("dialog");
  await sheet.getByLabel("Calendar name").fill("Operations");
  await sheet.getByRole("button", { name: "Tick all" }).click();
  await sheet.getByRole("button", { name: "Create calendar" }).click();
  await expect(page.getByText("Operations created")).toBeVisible();
  await expect(page.getByText("Not given to anyone yet — see step 3.")).toHaveCount(2);
  if (shots) await page.screenshot({ path: `${shots}/hol-3-calendars.png` });

  // 3. Who gets which.
  await page.getByRole("button", { name: "Next: who gets which" }).click();
  await page.getByLabel("Gets calendar", { exact: true }).selectOption({ label: "HO (2)" });
  await page.getByRole("button", { name: "Assign" }).click();
  await expect(page.getByText("HO assigned")).toBeVisible();
  await page.getByLabel("Who", { exact: true }).selectOption("DEPARTMENT");
  await page.getByLabel("Department", { exact: true }).selectOption({ index: 1 });
  await page.getByLabel("Gets calendar", { exact: true }).selectOption({ label: "Operations (3)" });
  await page.getByRole("button", { name: "Assign" }).click();
  await expect(page.getByText("Operations assigned")).toBeVisible();
  const rules = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: /^Remove / }) });
  await expect(rules).toHaveCount(2);
  await expect(rules.first()).toContainText("Whole company");
  await expect(rules.first()).toContainText("HO");
  await expect(rules.nth(1)).toContainText("Operations");

  // Re-pointing the whole company asks before switching.
  await page.getByLabel("Who", { exact: true }).selectOption("COMPANY");
  await page.getByLabel("Gets calendar", { exact: true }).selectOption({ label: "Operations (3)" });
  await page.getByRole("button", { name: "Assign" }).click();
  await expect(page.getByRole("dialog").getByText("Switch calendar?")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  if (shots) await page.screenshot({ path: `${shots}/hol-4-assign.png` });

  // The list shows where each holiday is used.
  await page.getByRole("tab", { name: /Holiday list/ }).click();
  const diwali = page.getByRole("listitem").filter({ hasText: "Diwali" });
  await expect(diwali).toContainText("HO");
  await expect(diwali).toContainText("Operations");
});
