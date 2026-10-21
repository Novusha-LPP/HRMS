/**
 * The employee's day-to-day journey, end to end through the real UI and API, with synthetic data
 * in an isolated *_test database (see playwright.config.ts). Covers what an employee can do and,
 * as importantly, what they can't see.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";
const newPassword = "Synthetic-new-password-456";
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=", "base64");
const jpeg = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/" +
  "2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCABkAGQDASIAAhEBAxEB/" +
  "8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2Jy" +
  "ggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLD" +
  "xMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3" +
  "AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6" +
  "goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDCooor" +
  "706wooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo" +
  "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii" +
  "igAooooAKKKKACiiigD/9k=",
  "base64"
);

type Seed = {
  adminToken: string; adminId: string;
  email: string; employeeId: string; colleagueId: string;
  firstName: string; lastName: string; colleagueName: string;
};

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function status(request: APIRequestContext, method: string, path: string, token: string, data?: unknown) {
  return (await request.fetch(api + path, { method, data, headers: { Authorization: `Bearer ${token}` } })).status();
}

async function hire(request: APIRequestContext, token: string, le: string, placement: Record<string, string>, first: string, last: string, number: string) {
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: first, legal_last_name: last }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: number, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: placement }, token);
  return employee;
}

/** A fresh company with an employee, a colleague, a leave type and approval flows routed to the admin. */
async function seed(request: APIRequestContext): Promise<Seed> {
  const tag = randomUUID().slice(0, 8);
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Journey ${tag}`, admin_email: `e2e-admin-${tag}@example.com`, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Operator" }, token);
  const placement = { location_id: location.id, org_unit_id: unit.id, job_id: job.id };
  const employee = await hire(request, token, le, placement, "Asha", "Rao", `EMP-${tag}`);
  const colleague = await hire(request, token, le, placement, "Ravi", "Colleague", `COL-${tag}`);
  const email = `e2e-employee-${tag}@example.com`;
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  for (const kind of ["LEAVE", "LEAVE_CANCELLATION", "CORRECTION"]) {
    const flow = await call(request, "POST", "/v1/approvals/flows", { name: `Journey ${kind}`, request_type: kind, reusable: true,
      steps: [{ name: "HR", approver_ids: [admin.user.id] }] }, token);
    await call(request, "PUT", `/v1/approvals/employees/${employee.id}/flows/${kind}`, { flow_id: flow.id, version: 0 }, token);
  }
  await call(request, "POST", "/v1/leave/types", { name: "Annual", code: "AL", days_per_year: 120, accrual_enabled: true }, token);
  await call(request, "POST", "/v1/leave/accrual/run", {}, token);
  return { adminToken: token, adminId: admin.user.id, email, employeeId: employee.id, colleagueId: colleague.id,
    firstName: "Asha", lastName: "Rao", colleagueName: "Ravi Colleague" };
}

async function signIn(page: Page, email: string, pw = password) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(pw);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

async function employeeToken(request: APIRequestContext, email: string, pw = password) {
  return (await call(request, "POST", "/v1/auth/login", { identifier: email, password: pw })).access_token as string;
}

/** A weekday at least `days` ahead, as YYYY-MM-DD. */
function weekday(days: number) {
  const d = new Date(Date.now() + days * 86400_000);
  while ([0, 6].includes(d.getUTCDay())) d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** A weekday at least `days` ago, as YYYY-MM-DD. */
function pastWeekday(days: number) {
  const d = new Date(Date.now() - days * 86400_000);
  while ([0, 6].includes(d.getUTCDay())) d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** Approve everything pending for this employee in the admin's approvals inbox. */
async function approveAll(request: APIRequestContext, s: Seed, type: string) {
  const inbox = await call(request, "GET", "/v1/approvals/inbox", undefined, s.adminToken);
  const mine = inbox.filter((r: { employment_id: string; request_type: string }) => r.employment_id === s.employeeId && r.request_type === type);
  expect(mine.length, `pending ${type} requests`).toBeGreaterThan(0);
  for (const r of mine) await call(request, "POST", `/v1/approvals/requests/${r.id}/decision`, { action: "APPROVE", comments: "OK" }, s.adminToken);
}

test.describe.configure({ mode: "serial" });
let s: Seed;
test.beforeAll(async ({ request }) => { s = await seed(request); });

test("1 · signs in to a self-service workspace and sees only their own data", async ({ page, request }) => {
  await signIn(page, s.email);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(s.firstName);

  const nav = page.locator("aside nav, nav").first();
  for (const allowed of ["Dashboard", "Attendance", "Leave", "Corrections", "Approvals"]) {
    await expect(nav.getByRole("link", { name: allowed, exact: true })).toBeVisible();
  }
  for (const hidden of ["Employees", "Organization", "Policies", "Approval flows", "Recruitment", "Onboarding", "Daily Analysis"]) {
    await expect(page.getByRole("link", { name: hidden, exact: true })).toHaveCount(0);
  }

  // Typing an admin URL directly doesn't reveal colleagues.
  await page.goto("/employees");
  await expect(page.getByText(s.colleagueName)).toHaveCount(0);

  // The API enforces the same boundaries.
  const token = await employeeToken(request, s.email);
  const people = await call(request, "GET", "/v1/employees?limit=200", undefined, token);
  const visible = (Array.isArray(people) ? people : people.items ?? []).map((e: { id: string }) => e.id);
  expect(visible).not.toContain(s.colleagueId);
  expect(await status(request, "GET", `/v1/kyc/employees/${s.colleagueId}`, token)).toBe(403);
  expect(await status(request, "GET", "/v1/users", token)).toBe(403);
  expect(await status(request, "POST", "/v1/org/org-units", token, { name: "X", type: "DEPARTMENT", effective_from: "2020-01-01" })).toBe(403);
  expect(await status(request, "POST", "/v1/recruitment/openings", token, { title: "Nope", org_unit_id: "ou_x", description: "Should be refused" })).toBe(403);
  const access = await call(request, "GET", "/v1/recruitment/access", undefined, token);
  expect(access.can_request).toBe(false);
});

test("2 · checks in and out from the attendance page", async ({ page }) => {
  await signIn(page, s.email);
  await page.goto("/attendance");
  const checkIn = page.waitForResponse((r) => r.url().includes("/v1/time/punch") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  expect((await checkIn).ok()).toBeTruthy();
  const checkOutButton = page.getByRole("button", { name: "Check out", exact: true });
  await expect(checkOutButton).toBeVisible();
  const checkOut = page.waitForResponse((r) => r.url().includes("/v1/time/punch") && r.request().method() === "POST");
  await checkOutButton.click();
  expect((await checkOut).ok()).toBeTruthy();
  await expect(page.getByText("Checked out").first()).toBeVisible();
});

test("3 · applies for leave, sees it approved, and withdraws a second request", async ({ page, request }) => {
  await signIn(page, s.email);
  const apply = async (date: string) => {
    await page.goto("/leave");
    await page.getByRole("button", { name: "Apply leave", exact: true }).first().click();
    await page.locator("#lv-from").fill(date);
    await page.locator("#lv-to").fill(date);
    await page.locator("#lv-reason").fill("Family function");
    const submitted = page.waitForResponse((r) => /\/v1\/leave\/applications\/.*\/submit/.test(r.url()));
    await page.getByRole("button", { name: "Submit request", exact: true }).click();
    expect((await submitted).ok()).toBeTruthy();
    await expect(page.getByText("Leave request submitted", { exact: true })).toBeVisible();
  };

  await apply(weekday(10));
  await approveAll(request, s, "LEAVE");
  await page.reload();
  await expect(page.getByText("Approved").first()).toBeVisible();

  await apply(weekday(20));
  await page.getByRole("button", { name: /Annual/ }).filter({ hasText: /Pending/ }).first().click();
  const withdrawn = page.waitForResponse((r) => r.url().includes("/v1/leave/applications/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Withdraw request", exact: true }).click();
  expect((await withdrawn).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/Withdrawn|Cancelled/).first()).toBeVisible();
});

test("4 · requests an attendance correction and withdraws it", async ({ page }) => {
  await signIn(page, s.email);
  await page.goto("/corrections");
  await page.getByRole("button", { name: "Request correction", exact: true }).first().click();
  await page.locator("#cr-type").selectOption("REGULARIZE");
  await page.locator("#cr-date").fill(pastWeekday(7));
  await page.locator("#cr-in").fill("09:30");
  await page.locator("#cr-out").fill("18:30");
  await page.locator("#cr-reason").fill("Biometric device was offline at the gate");
  const created = page.waitForResponse((r) => r.url().includes("/v1/corrections") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await expect(page.getByText(/Pending/).first()).toBeVisible();

  await page.getByText(/Pending/).first().click();
  const withdrawn = page.waitForResponse((r) => r.url().includes("/v1/corrections/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Withdraw request", exact: true }).click();
  expect((await withdrawn).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/Cancelled|Withdrawn/).first()).toBeVisible();
});

test("5 · keeps personal details and KYC up to date, and HR verifies them", async ({ page, request }) => {
  await signIn(page, s.email);
  await page.goto("/profile");

  // Personal details: view first, edit on purpose, persists across reloads.
  const personal = page.locator("section, form").filter({ hasText: "Personal information" }).first();
  await personal.getByRole("button", { name: "Edit" }).click();
  await page.locator("#pf-preferred").fill("Ash");
  await page.locator("#pf-mobile").fill("+91 90000 22222");
  await page.locator("#pf-nationality").fill("IN");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByText("Profile updated")).toBeVisible();
  await page.reload();
  await expect(page.getByText("+91 90000 22222").first()).toBeVisible();
  await expect(page.getByText("India (IN)")).toBeVisible();
  await expect(page.getByText(`Legal name: ${s.firstName} ${s.lastName}`)).toBeVisible();

  // KYC: fill identity, bank, address and emergency details section by section.
  await page.getByRole("tab", { name: "KYC & Documents" }).click();
  await expect(page).toHaveURL(/tab=kyc/);
  const editSection = async (title: string, fill: () => Promise<void>) => {
    const section = page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: true }) }).first();
    await section.getByRole("button", { name: "Edit" }).click();
    await fill();
    const saved = page.waitForResponse((r) => r.url().endsWith("/v1/kyc/me") && r.request().method() === "PATCH");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
    await expect(page.getByRole("button", { name: "Save changes", exact: true })).toHaveCount(0);
  };
  // A malformed PAN is caught before it is saved.
  const identity = page.locator("section, form").filter({ has: page.getByRole("heading", { name: "Identity & tax", exact: true }) }).first();
  await identity.getByRole("button", { name: "Edit" }).click();
  await page.locator("#kyc-pan_number").fill("ABC123");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByText("A PAN is 5 letters, 4 digits and a letter, e.g. ABCDE1234F")).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();

  // Pasted with spaces, the Aadhaar number keeps all 12 digits.
  await editSection("Identity & tax", async () => {
    await page.locator("#kyc-pan_number").fill("abcde1234f");
    await page.locator("#kyc-aadhaar_number").fill("1234 5678 9012");
  });
  await expect(page.getByText("ABCDE1234F")).toBeVisible();
  await expect(page.getByText("•••• 9012")).toBeVisible();
  await page.getByRole("button", { name: "Show Aadhaar number" }).click();
  await expect(page.getByText("1234 5678 9012")).toBeVisible();

  await editSection("Bank account", async () => {
    await page.locator("#kyc-bank_name").fill("State Bank of India");
    await page.locator("#kyc-account_number").fill("12345678901");
    await page.locator("#kyc-ifsc_code").fill("sbin0001234");
  });
  await editSection("Family & emergency contact", async () => {
    await page.locator("#kyc-emergency_contact_name").fill("Meena Rao");
    await page.locator("#kyc-emergency_contact_phone").fill("+91 90000 33333");
  });
  await editSection("Addresses", async () => {
    await page.locator("#kyc-current_address").fill("Flat 4, Green Park, Pune 411001");
    await page.getByRole("button", { name: "Same as current" }).click();
  });

  // Documents: upload the three required proofs, then view one.
  for (const label of ["PAN card", "Aadhaar card", "Bank proof"]) {
    const row = page.locator("li").filter({ hasText: label }).first();
    await row.getByRole("button", { name: "Upload" }).click();
    await page.locator("[role=dialog] input[type=file]").setInputFiles({ name: `${label}.png`, mimeType: "image/png", buffer: png });
    const uploaded = page.waitForResponse((r) => r.url().includes("/v1/kyc/me/documents") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Upload document", exact: true }).click();
    expect((await uploaded).ok()).toBeTruthy();
    await expect(row.getByText("Pending")).toBeVisible();
  }
  await expect(page.getByText("3 / 3")).toBeVisible();
  await page.locator("li").filter({ hasText: "PAN card" }).first().getByRole("button", { name: "View", exact: true }).click();
  await expect(page.locator('[role=dialog] img[src^="blob:"]')).toBeVisible();
  await page.keyboard.press("Escape");

  // Submit, then HR verifies; the employee sees the outcome.
  const submitted = page.waitForResponse((r) => r.url().endsWith("/v1/kyc/me/submit"));
  await page.getByRole("button", { name: "Submit for verification", exact: true }).click();
  expect((await submitted).ok()).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Under HR review" })).toBeVisible();
  await call(request, "POST", `/v1/kyc/employees/${s.employeeId}/verify`, { status: "VERIFIED" }, s.adminToken);
  await page.reload();
  await expect(page.getByRole("heading", { name: "KYC verified" })).toBeVisible();
  await expect(page.getByText("100%", { exact: true }).first()).toBeVisible();
});

test("6 · changes their password, signs out, and only the new password works", async ({ page, request }) => {
  await signIn(page, s.email);
  await page.goto("/change-password");
  await page.locator("#cp-current").fill(password);
  await page.locator("#cp-new").fill(newPassword);
  await page.locator("#cp-confirm").fill(newPassword);
  const changed = page.waitForResponse((r) => r.url().includes("password") && r.request().method() === "POST");
  await page.getByRole("button", { name: /Change password|Update password|Save/ }).click();
  expect((await changed).ok()).toBeTruthy();

  await page.goto("/dashboard");
  if (page.url().includes("/login")) {
    // Changing the password ended every session, including this one.
  } else {
    // The account menu shows the preferred name set in test 5 ("Ash Rao").
    const account = page.getByRole("button", { name: "Account menu", exact: true });
    await expect(account).toContainText(s.lastName);
    await account.click();
    await page.getByRole("button", { name: "Sign out" }).click();
  }
  await expect(page).toHaveURL(/login/);

  const old = await request.post(api + "/v1/auth/login", { data: { identifier: s.email, password } });
  expect(old.status()).toBe(401);
  await signIn(page, s.email, newPassword);
});

test("7 · uploads a profile photo and sees it rendered as a round avatar", async ({ page }) => {
  await page.route("**/photo*", (route) => route.continue());
  await signIn(page, s.email, newPassword);
  await page.goto("/profile");

  // Before uploading a photo, the profile and account menu show initials
  const asideAvatar = page.locator("aside .avatar").first();
  await expect(asideAvatar).toBeVisible();
  await expect(page.locator("aside img.avatar")).toHaveCount(0);

  // Upload a real photograph document
  await page.getByRole("tab", { name: "KYC & Documents" }).click();
  await expect(page).toHaveURL(/tab=kyc/);
  const photoRow = page.locator("li").filter({ hasText: "Photograph" }).first();
  await photoRow.getByRole("button", { name: "Upload" }).click();
  await page.locator("[role=dialog] input[type=file]").setInputFiles({
    name: "portrait.jpg",
    mimeType: "image/jpeg",
    buffer: jpeg,
  });
  const uploaded = page.waitForResponse((r) => r.url().includes("/v1/kyc/me/documents") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Upload document", exact: true }).click();
  expect((await uploaded).ok()).toBeTruthy();
  await expect(photoRow.getByText("Pending")).toBeVisible();

  // On the profile page, the round avatar now shows the real photo
  await page.reload();
  const avatarImg = page.locator("aside img.avatar").first();
  await expect(avatarImg).toBeVisible();
  await expect(avatarImg).toHaveClass(/rounded-full/);
  await expect(avatarImg).toHaveAttribute("src", /^blob:/);

  // The image successfully decoded in the browser
  const naturalWidth = await avatarImg.evaluate((img: HTMLImageElement) => img.naturalWidth);
  expect(naturalWidth).toBeGreaterThan(0);

  // The account menu in the sidebar also displays the round photo avatar
  const accountAvatar = page.getByRole("button", { name: "Account menu", exact: true }).locator("img.avatar");
  await expect(accountAvatar).toBeVisible();
  await expect(accountAvatar).toHaveClass(/rounded-full/);
});

