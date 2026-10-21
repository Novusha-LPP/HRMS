import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-test-password-123";
const red = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAASwAAADICAIAAADdvUsCAAACRUlEQVR4nO3TMQ0AMAzAsCIpfyiDVRg5ZskA8mTeLhCavAA+Z0KImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGImhJgJIWZCiJkQYiaEmAkhZkKImRBiJoSYCSFmQoiZEGIH9yUXc/cR9NwAAAAASUVORK5CYII=", "base64");
const blue = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAQQAAAEECAIAAABBat1dAAACa0lEQVR4nO3TMREAIBDAMJS8fynIgqEeYMhdBHTpmtnAtZ4XwCfMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADEDxAwQM0DMADED5ABrvz/1Cyu/xQAAAABJRU5ErkJggg==", "base64");

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, { method, data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function seed(request: APIRequestContext) {
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: "Photo company", admin_email: `e2e-admin-${randomUUID()}@example.com`, admin_password: password });
  const token = admin.access_token, le = admin.user.legal_entities[0].id;
  const location = await call(request, "POST", "/v1/org/locations", { name: "HQ", type: "OFFICE", legal_entity_id: le }, token);
  const unit = await call(request, "POST", "/v1/org/org-units", { name: "Operations", type: "DEPARTMENT", legal_entity_id: le, effective_from: "2020-01-01" }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Operator" }, token);
  const person = await call(request, "POST", "/v1/persons", { legal_first_name: "Photo", legal_last_name: "Person" }, token);
  const employee = await call(request, "POST", "/v1/employees", { person_id: person.id, legal_entity_id: le, employee_number: "PHOTO1", hire_date: "2020-01-01" }, token);
  await call(request, "POST", "/v1/personnel-actions", { employment_id: employee.id, type: "HIRE", effective_date: "2020-01-01", changes: { location_id: location.id, org_unit_id: unit.id, job_id: job.id } }, token);
  const email = `e2e-photo-${randomUUID()}@example.com`;
  await call(request, "POST", "/v1/users", { email, password, role: "EMPLOYEE", scope_type: "SELF", employment_id: employee.id, must_change_password: false }, token);
  return { email, employee };
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

const photo = (page: Page) => page.locator("img.avatar");

/** Which colour the avatar actually shows, so a stale picture is caught (the address always changes). */
async function colour(page: Page) {
  return photo(page).first().evaluate((img: HTMLImageElement) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.drawImage(img, img.naturalWidth / 2, img.naturalHeight / 2, 1, 1, 0, 0, 1, 1);
    const [r, , b] = context.getImageData(0, 0, 1, 1).data;
    return r > b ? "red" : "blue";
  });
}

test("a person adds, replaces and removes their profile picture", async ({ page, request }) => {
  const { email } = await seed(request);
  await signIn(page, email);
  await page.goto("/profile");

  // No photo yet: initials, and an Add photo button.
  await expect(photo(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /View photo of/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add photo" })).toBeVisible();

  // Add one: the avatar becomes a round picture made from a small thumbnail.
  await page.getByLabel("Choose a profile photo").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: red });
  await expect(photo(page).first()).toBeVisible();
  await expect.poll(() => photo(page).first().evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(192);
  expect(await photo(page).first().evaluate((img: HTMLImageElement) => getComputedStyle(img).borderRadius)).not.toBe("0px");
  expect(await photo(page).first().getAttribute("src")).toMatch(/^blob:/);
  await expect.poll(() => colour(page)).toBe("red");
  await expect(page.getByRole("button", { name: "Change photo" })).toBeVisible();

  // Click the picture: the whole photo opens larger in a dialog (not the small avatar).
  await page.getByRole("button", { name: /View photo of/ }).first().click();
  const viewer = page.getByRole("dialog", { name: /Photo of/ });
  await expect(viewer).toBeVisible();
  const large = viewer.locator("img");
  await expect.poll(() => large.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(300);
  expect(await large.evaluate((img: HTMLImageElement) => img.naturalHeight)).toBe(200);
  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
  // And again with the close button.
  await page.getByRole("button", { name: /View photo of/ }).first().click();
  await expect(viewer).toBeVisible();
  await viewer.getByRole("button", { name: "Close photo" }).click();
  await expect(viewer).toBeHidden();

  // Replace it: a different picture appears.
  const before = await photo(page).first().getAttribute("src");
  await page.getByLabel("Choose a profile photo").setInputFiles({ name: "me2.png", mimeType: "image/png", buffer: blue });
  await expect.poll(() => photo(page).first().getAttribute("src")).not.toBe(before);
  await expect(photo(page).first()).toBeVisible();
  await expect.poll(() => colour(page)).toBe("blue");   // the new picture, not a cached old one
  await page.getByRole("button", { name: /View photo of/ }).first().click();
  const replaced = page.getByRole("dialog", { name: /Photo of/ }).locator("img");
  await expect.poll(() => replaced.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(260);
  await page.keyboard.press("Escape");

  // The picture also shows in the header menu and survives a reload.
  await page.reload();
  await expect(photo(page).first()).toBeVisible();

  // Remove it: back to initials.
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(photo(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add photo" })).toBeVisible();
});

test("a file that is not a picture is refused with a clear message", async ({ page, request }) => {
  const { email } = await seed(request);
  await signIn(page, email);
  await page.goto("/profile");
  await page.getByLabel("Choose a profile photo").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.getByText("Choose a PNG or JPEG image.")).toBeVisible();
  await expect(photo(page)).toHaveCount(0);
});
