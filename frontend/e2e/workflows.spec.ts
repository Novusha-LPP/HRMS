import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac, randomUUID } from "node:crypto";
const api = "http://127.0.0.1:18015";
const scan = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=", "base64");
const password = "Synthetic-test-password-123";
async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data,
    headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}
async function seed(request: APIRequestContext) {
  const adminEmail = `e2e-admin-${randomUUID()}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: "Synthetic browser company", admin_email: adminEmail, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Operator" }, token);
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Browser", legal_last_name: "Employee" }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: "BROWSER", hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: { location_id: location.id, org_unit_id: unit.id, job_id: job.id } }, token);
  const email = `e2e-employee-${randomUUID()}@example.com`;
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  for (const kind of ["LEAVE", "CORRECTION"]) {
    const flow = await call(request, "POST", "/v1/approvals/flows", { name: `Browser ${kind}`, request_type: kind, reusable: true,
      steps: [{ name: "Administrator", approver_ids: [admin.user.id] }] }, token);
    await call(request, "PUT", `/v1/approvals/employees/${employee.id}/flows/${kind}`, { flow_id: flow.id, version: 0 }, token);
  }
  await call(request, "POST", "/v1/leave/types", { name: "Annual", code: "AL", days_per_year: 120, accrual_enabled: true }, token);
  await call(request, "POST", "/v1/leave/accrual/run", {}, token);
  const login = await call(request, "POST", "/v1/auth/login", { identifier: email, password });
  await call(request, "PATCH", "/v1/kyc/me", { pan_number: "ABCDE1234F" }, login.access_token);
  const upload = await request.post(api + "/v1/kyc/me/documents", {
    headers: { Authorization: `Bearer ${login.access_token}` }, multipart: {
      document_type: "PAN_CARD", document_title: "Synthetic PAN",
      file: { name: "synthetic-pan.png", mimeType: "image/png", buffer: scan } } });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  return { email, adminEmail, employee, token };
}
async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}
test("login, punch, leave approval, correction and encrypted document view", async ({ page, request, browser }) => {
  const data = await seed(request);
  await signIn(page, data.email);
  await page.goto("/attendance");
  const punch = page.waitForResponse(r => r.url().includes("/v1/time/punch") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  expect((await punch).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "Check out", exact: true })).toBeVisible();
  await page.goto("/leave");
  await page.getByRole("button", { name: "Apply leave", exact: true }).first().click();
  const day = new Date(Date.now() + 7 * 86400_000);
  while ([0, 6].includes(day.getUTCDay())) day.setUTCDate(day.getUTCDate() + 1);
  const date = day.toISOString().slice(0, 10);
  await page.locator("#lv-from").fill(date);
  await page.locator("#lv-to").fill(date);
  const submission = page.waitForResponse(r => /\/v1\/leave\/applications\/.*\/submit/.test(r.url()));
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  expect((await submission).ok()).toBeTruthy();
  await expect(page.getByText("Leave request submitted", { exact: true })).toBeVisible();
  const adminContext = await browser.newContext({ baseURL: "http://127.0.0.1:18180" });
  const adminPage = await adminContext.newPage();
  try {
    await signIn(adminPage, data.adminEmail);
    await adminPage.goto("/approvals");
    await adminPage.getByRole("button", { name: /Review Browser Employee/ }).click();
    const decision = adminPage.waitForResponse(r => r.url().endsWith("/decision") && r.request().method() === "POST");
    await adminPage.getByRole("button", { name: "Approve stage", exact: true }).click();
    expect((await decision).ok()).toBeTruthy();
    await expect(adminPage.getByText("Request Approved", { exact: false }).first()).toBeVisible();
  } finally { await adminContext.close(); }
  await page.goto("/corrections?new=1");
  await page.locator("#cr-type").selectOption("LATE_REASON");
  await page.locator("#cr-reason").fill("Synthetic browser regression");
  const correction = page.waitForResponse(r => r.url().includes("/v1/corrections") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  expect((await correction).ok()).toBeTruthy();
  await page.goto("/profile?tab=kyc");
  await expect(page.getByText("synthetic-pan.png", { exact: true })).toBeVisible();
  const document = page.waitForResponse(r => /\/v1\/kyc\/documents\/.*\/preview/.test(r.url()) && r.request().method() === "GET");
  await page.getByRole("button", { name: "View", exact: true }).first().click();
  const downloaded = await document;
  expect(downloaded.ok()).toBeTruthy();
  expect(downloaded.headers()["content-length"]).toBe(String(scan.length));
  const image = page.locator('img[src^="blob:"]');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);
  expect(await page.evaluate(() => localStorage.getItem("hrms_token"))).toBeNull();
  expect(await page.evaluate(() => document.cookie)).not.toContain("hrms_session");
  const verified = await page.request.get(downloaded.url());
  expect((await verified.body()).equals(scan)).toBeTruthy();
});
test("a transient /me failure preserves the HttpOnly session", async ({ page, request }) => {
  const data = await seed(request);
  await signIn(page, data.email);
  const before = (await page.context().cookies()).find(c => c.name === "hrms_session");
  expect(before?.httpOnly).toBeTruthy();
  await page.route("**/v1/auth/me", route => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"unavailable"}' }));
  await page.reload();
  const after = (await page.context().cookies()).find(c => c.name === "hrms_session");
  expect(after?.value).toBe(before?.value);
  expect(await page.evaluate(() => localStorage.getItem("hrms_token"))).toBeNull();
  await page.unroute("**/v1/auth/me");
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/dashboard/);
});

// An independent test authenticator feeds codes into the real enrollment/login UI.
function authenticatorCode(secret: string, step: number) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let buffer = 0, bits = 0;
  const bytes: number[] = [];
  for (const char of secret) {
    buffer = (buffer << 5) | alphabet.indexOf(char); bits += 5;
    if (bits >= 8) { bits -= 8; bytes.push((buffer >>> bits) & 255); }
  }
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", Buffer.from(bytes)).update(counter).digest();
  const offset = digest[digest.length - 1] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}
test("authenticator enrollment revokes the old cookie and requires a code on login", async ({ page, request }) => {
  const email = `e2e-factor-${randomUUID()}@example.com`;
  await call(request, "POST", "/v1/auth/register-company", {
    company_name: "Synthetic factor company", admin_email: email, admin_password: password });
  await signIn(page, email);
  const old = (await page.context().cookies()).find(c => c.name === "hrms_session")?.value;
  await page.goto("/security/mfa");
  await page.getByLabel("Current password").fill(password);
  await page.getByRole("button", { name: "Create setup key" }).click();
  const secret = await page.locator("main code").innerText();
  await page.getByLabel("Six-digit authenticator code").fill(authenticatorCode(secret, Math.floor(Date.now() / 30_000)));
  await page.getByRole("button", { name: "Confirm authenticator" }).click();
  await expect(page).toHaveURL(/login\?mfa=enrolled/);
  expect((await page.context().cookies()).find(c => c.name === "hrms_session")).toBeUndefined();
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const missing = page.waitForResponse(r => r.url().endsWith("/v1/auth/login"));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await missing).status()).toBe(401);
  await expect(page).toHaveURL(/login/);
  // +1 is within allowed clock drift and avoids reusing the just-confirmed code.
  await page.getByLabel("Authenticator code (if enabled)").fill(authenticatorCode(secret, Math.floor(Date.now() / 30_000) + 1));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
  const current = (await page.context().cookies()).find(c => c.name === "hrms_session");
  expect(current?.httpOnly).toBeTruthy();
  expect(current?.value).not.toBe(old);
  await page.reload();
  await expect(page).toHaveURL(/dashboard/);
});
