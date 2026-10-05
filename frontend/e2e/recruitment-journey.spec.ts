/**
 * Recruitment end to end through the real UI: a department head raises an opening, HR approves
 * it, sources candidates (links + resume), works the pipeline board, rejects one with a reason
 * and turns another into an employee; the head follows along read-only and leaves feedback.
 * Synthetic data in an isolated *_test database (see playwright.config.ts).
 */
import { test, expect, type APIRequestContext, type Page, type Locator } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";
const pdf = Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n");

type Seed = { adminEmail: string; hodEmail: string; employeeEmail: string; tag: string };

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function hireWithLogin(request: APIRequestContext, token: string, le: string, placement: Record<string, string>,
  first: string, last: string, number: string, email: string) {
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: first, legal_last_name: last }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: number, hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: placement }, token);
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  return employee;
}

/** A company whose Engineering department is headed by an ordinary employee account. */
async function seed(request: APIRequestContext): Promise<Seed> {
  const tag = randomUUID().slice(0, 8);
  const adminEmail = `e2e-hr-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", { company_name: `Hiring ${tag}`, admin_email: adminEmail, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Engineering", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Software Engineer" }, token);
  const placement = { location_id: location.id, org_unit_id: unit.id, job_id: job.id };
  const hodEmail = `e2e-hod-${tag}@example.com`, employeeEmail = `e2e-emp-${tag}@example.com`;
  const hod = await hireWithLogin(request, token, le, placement, "Hema", "Head", `HOD-${tag}`, hodEmail);
  await hireWithLogin(request, token, le, placement, "Eli", "Engineer", `EMP-${tag}`, employeeEmail);
  await call(request, "PATCH", `/v1/org/org-units/${unit.id}`, { head_employment_id: hod.id }, token);
  return { adminEmail, hodEmail, employeeEmail, tag };
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

/** Drag a pipeline card onto a stage column with the mouse, as a recruiter would. */
async function dragTo(page: Page, card: Locator, stage: string) {
  const column = page.getByRole("group", { name: new RegExp(`^${stage} stage`) });
  await column.scrollIntoViewIfNeeded();
  const from = (await card.boundingBox())!;
  const to = (await column.boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2, { steps: 3 });
  await page.mouse.move(to.x + to.width / 2, to.y + 80, { steps: 12 });
  const moved = page.waitForResponse((r) => r.url().endsWith("/move") && r.request().method() === "POST");
  await page.mouse.up();
  expect((await moved).ok()).toBeTruthy();
}

async function addCandidate(page: Page, c: { first: string; last: string; email: string; links: string[]; resume?: boolean }) {
  await page.getByRole("button", { name: "Add candidate", exact: true }).first().click();
  await page.locator("#cf-first").fill(c.first);
  await page.locator("#cf-last").fill(c.last);
  await page.locator("#cf-email").fill(c.email);
  await page.locator("#cf-company").fill("Acme Software");
  await page.locator("#cf-title").fill("Backend Engineer");
  await page.locator("#cf-exp").fill("4");
  await page.locator("#cf-cctc").fill("1200000");
  await page.locator("#cf-ectc").fill("1600000");
  for (let i = 0; i < c.links.length; i++) {
    if (i > 0) await page.getByRole("button", { name: "Add link" }).click();
    await page.getByLabel("Link address").nth(i).fill(c.links[i]);
  }
  await page.locator("#cf-skills").fill("Python, PostgreSQL");
  await page.locator("#cf-skills").press("Enter");
  if (c.resume) {
    await page.locator("[role=dialog] input[type=file]").setInputFiles({ name: `${c.first}_Resume.pdf`, mimeType: "application/pdf", buffer: pdf });
  }
  const added = page.waitForResponse((r) => r.url().endsWith("/applications") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Add to pipeline", exact: true }).click();
  expect((await added).ok()).toBeTruthy();
  await expect(page.getByText(`${c.first} ${c.last} added to the pipeline`)).toBeVisible();
}

test.describe.configure({ mode: "serial" });
let s: Seed;
let openingUrl = "";
const title = "Senior Backend Engineer";

test.beforeAll(async ({ request }) => { s = await seed(request); });

test("1 · a department head raises an opening; a regular employee can't", async ({ page, browser }) => {
  await signIn(page, s.hodEmail);
  await page.getByRole("link", { name: "Recruitment", exact: true }).click();
  await page.getByRole("button", { name: "Raise opening", exact: true }).first().click();
  await page.locator("#op-title").fill(title);
  await expect(page.locator("#op-unit")).toHaveValue(/ou_/); // their one department is preselected
  await page.locator("#op-pos").fill("2");
  await page.locator("#op-priority").selectOption("HIGH");
  await page.locator("#op-desc").fill("Own the payments platform end to end, from schema to API.");
  await page.locator("#op-skills").fill("Python, FastAPI");
  await page.locator("#op-skills").press("Enter");
  await page.getByRole("button", { name: "Submit for approval", exact: true }).click();
  await expect(page).toHaveURL(/\/recruitment\/openings\/jopn_/);
  openingUrl = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Awaiting approval")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0); // can't approve their own

  const other = await browser.newContext({ baseURL: "http://127.0.0.1:18180" });
  const employee = await other.newPage();
  try {
    await signIn(employee, s.employeeEmail);
    await expect(employee.getByRole("link", { name: "Recruitment", exact: true })).toHaveCount(0);
    await employee.goto(openingUrl);
    await expect(employee.getByText("Opening not found")).toBeVisible();
  } finally {
    await other.close();
  }
});

test("2 · HR approves, sources candidates, works the board and hires", async ({ page }) => {
  await signIn(page, s.adminEmail);
  await page.goto("/recruitment?filter=approval");
  await page.getByRole("link", { name: title }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Open", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("No candidates yet")).toBeVisible();

  await addCandidate(page, { first: "Kavya", last: "Nair", email: `kavya-${s.tag}@example.com`, resume: true,
    links: ["linkedin.com/in/kavya-demo", "https://github.com/kavya-demo"] });
  await addCandidate(page, { first: "Rohan", last: "Mehta", email: `rohan-${s.tag}@example.com`, links: ["https://rohan.example.dev"] });

  // Drag Kavya from Applied to Shortlisted on the board.
  const kavya = page.getByRole("button", { name: /^Kavya Nair, Applied/ });
  await dragTo(page, kavya, "Shortlisted");
  await expect(page.getByRole("group", { name: /^Shortlisted stage, 1 candidate$/ })).toBeVisible();

  // Stage filter chips narrow the board.
  await page.getByRole("group", { name: "Filter by stage" }).getByRole("button", { name: /^Shortlisted/ }).click();
  await expect(page.getByText("Showing 1 of 2 candidates")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Rohan Mehta/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Clear filters" }).first().click();

  // Reject Rohan: a reason is required and recorded.
  await page.getByRole("button", { name: /^Rohan Mehta, Applied/ }).click();
  await page.getByLabel("Move to stage").selectOption({ label: "Move to Rejected" });
  await page.getByRole("dialog").last().locator("textarea").fill("Not enough distributed systems experience");
  await page.getByRole("button", { name: "Move candidate", exact: true }).click();
  await expect(page.getByText("Reason:")).toBeVisible();
  await page.keyboard.press("Escape");

  // Kavya: view the resume, then move to Onboarding and create the employee record.
  await page.getByRole("button", { name: /^Kavya Nair, Shortlisted/ }).click();
  await expect(page.getByRole("link", { name: "LinkedIn" })).toHaveAttribute("href", "https://linkedin.com/in/kavya-demo");
  await expect(page.getByRole("link", { name: "GitHub" })).toBeVisible();
  await expect(page.getByText("₹16,00,000")).toBeVisible(); // recruiters see expected CTC
  await page.getByRole("button", { name: "View", exact: true }).click();
  await expect(page.locator('[role=dialog] object[type="application/pdf"]')).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).last().click();

  await page.getByLabel("Move to stage").selectOption({ label: "Move to Onboarding" });
  await expect(page.getByText("Moved to Onboarding")).toBeVisible();
  await page.getByRole("button", { name: "Create employee", exact: true }).click();
  await expect(page.locator("#ae-first")).toHaveValue("Kavya");
  await expect(page.locator("#ae-last")).toHaveValue("Nair");
  await page.locator("#ae-num").fill(`NEW-${s.tag}`);
  const linked = page.waitForResponse((r) => r.url().endsWith("/hire") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Add employee", exact: true }).click();
  expect((await linked).ok()).toBeTruthy();
  await expect(page.getByText("Employee record created")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open employee" })).toBeVisible();
});

test("3 · the department head follows along read-only and leaves feedback", async ({ page }) => {
  await signIn(page, s.hodEmail);
  await page.goto(openingUrl);
  const card = page.getByRole("button", { name: /^Kavya Nair, Onboarding$/ }); // not draggable for them
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.getByText("Employee record created")).toBeVisible();
  await expect(page.getByText("Expected CTC")).toHaveCount(0);
  await expect(page.getByLabel("Move to stage")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open employee" })).toHaveCount(0);
  await page.getByLabel("Feedback").fill("Great culture fit — looking forward to having her on the team.");
  await page.getByRole("button", { name: "Add feedback", exact: true }).click();
  await expect(page.getByText("Feedback added")).toBeVisible();
  await expect(page.getByText("Great culture fit — looking forward to having her on the team.")).toBeVisible();

  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "Activity" }).click();
  for (const entry of ["submitted it for HR approval", "approved the opening", "moved Rohan Mehta from Applied to Rejected", "created the employee record for Kavya Nair"]) {
    await expect(page.getByText(entry, { exact: false }).first()).toBeVisible();
  }
});
