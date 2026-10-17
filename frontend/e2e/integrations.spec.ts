/**
 * Settings → Integrations through the real UI, with synthetic data in an isolated *_test
 * database: connect the ERP, create its key (shown once), see a call the ERP makes refused for a
 * value HRMS doesn't know, map the value, and see the retry succeed in the sync log.
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

test("the administrator connects the ERP, maps a value it sends and reads the sync log", async ({ page, request }) => {
  const tag = randomUUID().slice(0, 8);
  const email = `e2e-admin-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Integrations ${tag}`, admin_email: email, admin_password: password });
  const company = admin.user.legal_entities[0];
  const token = admin.access_token;
  await call(request, "POST", "/v1/org/org-units", {
    name: "Operations", type: "DEPARTMENT", legal_entity_id: company.id, effective_from: "2020-01-01" }, token);
  await call(request, "POST", "/v1/org/locations", { name: "Head office", type: "OFFICE", legal_entity_id: company.id }, token);
  await call(request, "POST", "/v1/org/jobs", { title: "Executive" }, token);

  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
  await page.goto("/integrations");

  // 1. Connect the ERP.
  await expect(page.getByText("No apps connected yet")).toBeVisible();
  await page.getByRole("button", { name: "Connect an app" }).first().click();
  let sheet = page.getByRole("dialog");
  await sheet.getByLabel("Code").fill("ERP");
  await sheet.getByLabel("Name").fill("EXIM ERP");
  await sheet.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("App connected")).toBeVisible();

  // Every tab's help opens independently, without selecting that tab or changing app data.
  const helpTitles = [
    "Understand the connection overview", "Create and manage integration keys",
    "Configure integration settings", "Map the app's values to HRMS",
    "Read and troubleshoot the sync log", "Resolve items that need review",
  ];
  await expect(page.getByRole("button", { name: /^Help:/ })).toHaveCount(6);
  const keysUrl = page.url();
  for (const title of helpTitles) {
    const helpButton = page.getByRole("button", { name: `Help: ${title}`, exact: true });
    await helpButton.click();
    const help = page.getByRole("dialog", { name: title, exact: true });
    await expect(help).toBeVisible();
    expect(await help.getByRole("listitem").count()).toBeGreaterThanOrEqual(3);
    if (title === "Configure integration settings") {
      await expect(help.getByText(/App means the ERP or CRM manages the field/)).toBeVisible();
      await expect(help.getByText(/Choose whether HR can change an app-owned field/)).toBeVisible();
      if (shots) await page.screenshot({ path: `${shots}/int-help-settings.png`, animations: "disabled" });
    }
    await expect(page.getByRole("tab", { name: "Keys", exact: true })).toHaveAttribute("aria-selected", "true");
    expect(page.url()).toBe(keysUrl);
    await page.keyboard.press("Escape");
    await expect(help).toHaveCount(0);
    await expect(helpButton).toBeFocused();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Help: Resolve items that need review", exact: true }).click();
  const mobileHelp = page.getByRole("dialog", { name: "Resolve items that need review", exact: true });
  await expect(mobileHelp).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  if (shots) await page.screenshot({ path: `${shots}/int-help-mobile.png`, animations: "disabled" });
  await mobileHelp.getByRole("button", { name: "Got it", exact: true }).click();
  await expect(mobileHelp).toHaveCount(0);
  await page.setViewportSize({ width: 1280, height: 720 });

  // 2. Its key, shown once.
  await page.getByRole("button", { name: "Create a key" }).click();
  sheet = page.getByRole("dialog");
  await sheet.getByRole("button", { name: "Create key" }).click();
  const shown = page.getByRole("dialog").filter({ hasText: "Copy the key now" });
  await expect(shown).toBeVisible();
  const key = (await shown.locator("code").first().innerText()).trim();
  expect(key).toMatch(/^hrms_test_/);
  if (shots) await page.screenshot({ path: `${shots}/int-1-key.png` });
  await shown.getByLabel("I've stored the key somewhere safe").check();
  await shown.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("App server")).toBeVisible();

  // 3. The ERP sends a department HRMS doesn't know: refused, and listed for mapping.
  const hire = {
    first_name: "Asha", last_name: "Kale", company: company.name, department: "Ops Team",
    location: "Head office", designation: "Executive", hire_date: "2026-10-01", employee_code: `E2E${tag}`,
  };
  const refused = await request.fetch(`${api}/v1/integrations/employees/EMP-1`, {
    method: "PUT", data: hire, headers: { "X-API-Key": key } });
  expect(refused.status()).toBe(422);
  expect((await refused.json()).code).toBe("UNKNOWN_DEPARTMENT");

  await page.getByRole("tab", { name: "Mappings" }).click();
  await expect(page.getByText("Unmapped values")).toBeVisible();
  await page.getByLabel("Map Ops Team to").selectOption({ label: `Operations · ${company.name}` });
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.getByText("Mapped")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/int-2-mapped.png` });

  // 4. The ERP's retry goes through; the sync log shows both calls.
  const created = await request.fetch(`${api}/v1/integrations/employees/EMP-1`, {
    method: "PUT", data: hire, headers: { "X-API-Key": key } });
  expect(created.status()).toBe(201);
  await page.getByRole("tab", { name: "Sync log" }).click();
  await expect(page.getByText("Created", { exact: true })).toBeVisible();
  await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
  await expect(page.getByText("UNKNOWN_DEPARTMENT")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/int-3-log.png` });

  // Apps with fewer tabs have help only for their available sections.
  await call(request, "POST", "/v1/admin/integrations/apps", {
    code: "BI", name: "Insight BI", kind: "READ_ONLY",
  }, token);
  await page.reload();
  await page.getByRole("button", { name: /^Insight BI/ }).click();
  await expect(page.getByRole("button", { name: /^Help:/ })).toHaveCount(4);
  await expect(page.getByRole("tab", { name: "Mappings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Needs review", exact: true })).toHaveCount(0);
});
