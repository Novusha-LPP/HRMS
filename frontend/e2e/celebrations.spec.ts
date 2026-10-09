/** Birthday/work-anniversary popup QA. Every API response is synthetic and intercepted. */
import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

type Celebrant = { id: string; name: string; company: string; is_self: boolean };
type Celebrations = {
  date: string;
  timezone: string;
  personal: { birthday: boolean; anniversary_years: number | null };
  birthdays: Celebrant[];
  anniversaries: (Celebrant & { years: number })[];
};
const me = {
  id: "celebration-user", tenant_id: "celebration-tenant", tenant_name: "Suraj Group",
  employment_id: "celebration-employment" as string | null, name: "Asha Rao", email: "asha@example.test",
  roles: ["HR_MANAGER"], permissions: ["*"], is_all_scope: true,
  legal_entities: [{ id: "celebration-company", name: "Suraj Group" }],
  must_change_password: false, mfa_required: false,
};
const empty = (): Celebrations => ({ date: "2026-10-09", timezone: "Asia/Kolkata", personal: { birthday: false, anniversary_years: null }, birthdays: [], anniversaries: [] });
const birthday = (): Celebrations => ({ ...empty(), personal: { birthday: true, anniversary_years: null }, birthdays: [{ id: me.employment_id!, name: me.name, company: "Suraj Group", is_self: true }] });
const anniversary = (years: number): Celebrations => ({ ...empty(), personal: { birthday: false, anniversary_years: years }, anniversaries: [{ id: me.employment_id!, name: me.name, company: "Suraj Group", years, is_self: true }] });
const colleagues = (): Celebrations => ({
  ...empty(),
  birthdays: [{ id: "birthday-colleague", name: "Ravi Shah", company: "Suraj Group", is_self: false }],
  anniversaries: [{ id: "anniversary-colleague", name: "Nila Singh", company: "Suraj Group", years: 5, is_self: false }],
});

type FixtureOptions = { payload?: Celebrations; authenticated?: boolean; mode?: "light" | "dark"; palette?: string; user?: Partial<typeof me>; storageUnavailable?: boolean };
type Fixtures = { user: typeof me; payload: Celebrations; authenticated: boolean; status: number; celebrationRequests: number; celebrationReplies: number; unexpectedRequests: string[]; errors: string[] };
async function fixtures(page: Page, options: FixtureOptions = {}): Promise<Fixtures> {
  const state: Fixtures = { user: { ...me, ...options.user }, payload: options.payload ?? birthday(), authenticated: options.authenticated ?? true, status: 200, celebrationRequests: 0, celebrationReplies: 0, unexpectedRequests: [], errors: [] };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.addInitScript(({ mode, palette, storageUnavailable }) => {
    (window as Window & { __HRMS_CONFIG__?: unknown }).__HRMS_CONFIG__ = { apiUrl: location.origin, environment: "local" };
    localStorage.setItem("hrms_theme", mode);
    localStorage.setItem("hrms_color_theme", palette);
    if (storageUnavailable) {
      const getItem = Storage.prototype.getItem, setItem = Storage.prototype.setItem;
      Storage.prototype.getItem = function (key) {
        if (/celebrat/i.test(key)) throw new DOMException("Storage unavailable", "SecurityError");
        return getItem.call(this, key);
      };
      Storage.prototype.setItem = function (key, value) {
        if (/celebrat/i.test(key)) throw new DOMException("Storage unavailable", "SecurityError");
        return setItem.call(this, key, value);
      };
    }
  }, { mode: options.mode ?? "light", palette: options.palette ?? "classic-teal", storageUnavailable: options.storageUnavailable ?? false });
  await page.route("**/config.js", route => route.fulfill({ contentType: "application/javascript", body: "window.__HRMS_CONFIG__ = { apiUrl: location.origin, environment: 'local' };" }));
  await page.route("**/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const reply = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/v1/auth/login" && request.method() === "POST") {
      state.authenticated = true;
      return reply({ access_token: "synthetic-fixture-only", expires_in: 3600, user: state.user });
    }
    if (path === "/v1/auth/logout" && request.method() === "POST") { state.authenticated = false; return reply({}); }
    if (path === "/v1/auth/change-password" && request.method() === "POST") {
      state.user = { ...state.user, must_change_password: false };
      return reply({ access_token: "synthetic-fixture-only", expires_in: 3600, user: state.user });
    }
    if (request.method() !== "GET") {
      state.unexpectedRequests.push(`${request.method()} ${path}`);
      return reply({ message: "Celebration QA rejects business mutations" }, 400);
    }
    if (path === "/v1/auth/me") return reply(state.authenticated ? state.user : { message: "Not signed in" }, state.authenticated ? 200 : 401);
    if (path === "/v1/platform/me") return reply({ message: "Not signed in" }, 401);
    if (path === "/v1/dashboard/celebrations") {
      state.celebrationRequests++;
      await reply(state.status === 200 ? state.payload : { message: "Synthetic celebration lookup unavailable" }, state.status);
      state.celebrationReplies++;
      return;
    }
    if (path === "/v1/me/preferences") return reply({ color_theme: options.palette ?? "classic-teal", dashboard_style: "widgets" });
    if (path === "/v1/dashboard/layout") return reply({ dashboard: "hr", widgets: [{ widget: "kpi_headcount", size: "quarter" }], is_default: true, sections: "headcount", catalog: [{ id: "kpi_headcount", title: "Headcount", description: "People employed", category: "People", default_size: "quarter", sizes: ["quarter"] }] });
    if (path === "/v1/dashboard/hr") return reply({ headcount: { total: 24 } });
    if (["/v1/leave/applications", "/v1/corrections", "/v1/employees"].includes(path)) return reply([]);
    state.unexpectedRequests.push(`GET ${path}`);
    return reply({ message: `Missing celebration fixture: ${path}` }, 404);
  });
  return state;
}

const popup = (page: Page) => page.getByRole("dialog");
async function opened(page: Page) {
  const dialog = popup(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(dialog).toHaveAccessibleName(/birthday|anniversary|celebrat/i);
  return dialog;
}
async function closed(page: Page) { await expect(popup(page)).toHaveCount(0); }
function verify(state: Fixtures) {
  expect(state.unexpectedRequests, "Every API request must have an explicit fixture; business writes are forbidden").toEqual([]);
  expect(state.errors, "Celebrations must not create JavaScript exceptions").toEqual([]);
}
async function settled(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations().filter(a => a.effect?.getComputedTiming().iterations !== Infinity).map(a => a.finished.catch(() => {})));
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
}
async function snapshot(page: Page, testInfo: TestInfo, label: string) {
  await settled(page);
  await page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true, animations: "disabled" });
}
async function acknowledgments(page: Page) {
  return page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => /celebrat/i.test(key))));
}
async function spaRoute(page: Page, path: string) {
  await page.evaluate(path => { history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); }, path);
  await expect(page).toHaveURL(new RegExp(`${path.replace(/[?]/g, "\\?")}$`));
}

/** Contrast is checked only on the new popup, with actual alpha-composited CSS colors. */
async function contrast(page: Page, testInfo: TestInfo, label: string) {
  const result = await popup(page).evaluate(dialog => {
    type Color = [number, number, number, number];
    const parse = (value: string): Color => {
      const n = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return [n[0] ?? 0, n[1] ?? 0, n[2] ?? 0, n[3] ?? 1];
    };
    const blend = (fg: Color, bg: Color): Color => [fg[0] * fg[3] + bg[0] * (1 - fg[3]), fg[1] * fg[3] + bg[1] * (1 - fg[3]), fg[2] * fg[3] + bg[2] * (1 - fg[3]), 1];
    const background = (el: Element) => {
      const parents: Element[] = [];
      for (let node: Element | null = el; node; node = node.parentElement) parents.push(node);
      return parents.reverse().reduce((bg, node) => blend(parse(getComputedStyle(node).backgroundColor), bg), [255, 255, 255, 1] as Color);
    };
    const luminance = (c: Color) => c.slice(0, 3).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
    const ratio = (a: Color, b: Color) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const samples = [...dialog.querySelectorAll("*")].flatMap(el => {
      const text = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(" ").trim();
      const style = getComputedStyle(el), rect = el.getBoundingClientRect();
      if (!text || !rect.width || !rect.height || style.visibility === "hidden") return [];
      const bg = background(el), fg = blend(parse(style.color), bg), size = parseFloat(style.fontSize), weight = parseInt(style.fontWeight);
      const minimum = size >= 24 || size >= 18.66 && weight >= 700 ? 3 : 4.5;
      return [{ text, ratio: ratio(fg, bg), minimum, fg: style.color, bg: bg.slice(0, 3) }];
    });
    const icons = [...dialog.querySelectorAll("svg")].map(el => {
      const style = getComputedStyle(el), bg = background(el), fg = blend(parse(style.color), bg);
      return { name: el.getAttribute("data-icon-name") ?? el.getAttribute("class"), ratio: ratio(fg, bg), minimum: 3, fg: style.color, bg: bg.slice(0, 3) };
    });
    return { samples, icons, failures: samples.filter(x => x.ratio < x.minimum), iconFailures: icons.filter(x => x.ratio < x.minimum) };
  });
  await writeFile(testInfo.outputPath(`${label}-contrast.json`), JSON.stringify(result, null, 2));
  expect(result.samples.length).toBeGreaterThan(8);
  expect.soft(result.failures, `${label} new popup text must meet AA in every palette`).toEqual([]);
  expect.soft(result.iconFailures, `${label} popup icons must reach 3:1`).toEqual([]);
}

test("a personal birthday welcomes the person after a real fixture sign-in", async ({ page }, testInfo) => {
  const state = await fixtures(page, { authenticated: false });
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  expect(state.celebrationRequests).toBe(0);
  await page.getByLabel(/email|employee id|identifier/i).fill("asha@example.test");
  await page.getByLabel("Password", { exact: true }).fill("FixturePassword1!");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  const dialog = await opened(page);
  await expect(dialog).toContainText(/happy birthday/i);
  await expect(dialog).toContainText("Asha");
  await expect(dialog).not.toContainText(/work anniversary/i);
  await snapshot(page, testInfo, "personal-birthday");
  verify(state);
});

for (const years of [1, 7]) test(`personal anniversary shows ${years} completed service year${years === 1 ? "" : "s"}`, async ({ page }, testInfo) => {
  const state = await fixtures(page, { payload: anniversary(years) });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect(dialog).toContainText(/anniversary/i);
  await expect(dialog).toContainText(new RegExp(`${years} year${years === 1 ? "(?!s)" : "s"}`));
  await expect(dialog).not.toContainText(/happy birthday/i);
  await snapshot(page, testInfo, `personal-anniversary-${years}`);
  verify(state);
});

test("simultaneous birthday and anniversary appear in one dialog", async ({ page }, testInfo) => {
  const state = await fixtures(page, { payload: { ...birthday(), personal: { birthday: true, anniversary_years: 6 }, anniversaries: anniversary(6).anniversaries } });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect(dialog).toContainText(/birthday/i);
  await expect(dialog).toContainText(/anniversar/i);
  await expect(dialog).toContainText(/6 years/);
  await expect(popup(page)).toHaveCount(1);
  await snapshot(page, testInfo, "personal-combined");
  verify(state);
});

test("colleague-only list works for an employed account", async ({ page }, testInfo) => {
  const state = await fixtures(page, { payload: colleagues() });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect(dialog).toContainText("Ravi Shah");
  await expect(dialog).toContainText("Nila Singh");
  await expect(dialog).toContainText("Suraj Group");
  await expect(dialog).toContainText(/5 years/);
  await expect(dialog).not.toContainText(/happy birthday,? Asha/i);
  await snapshot(page, testInfo, "colleagues");
  verify(state);
});

test("an account without employment makes no celebration request", async ({ page }) => {
  const state = await fixtures(page, { payload: colleagues(), user: { employment_id: null } });
  await page.goto("/dashboard");
  await expect(page.locator(".stat-value")).toHaveText("24");
  await settled(page);
  await closed(page);
  expect(state.celebrationRequests).toBe(0);
  expect(await acknowledgments(page)).toEqual({});
  verify(state);
});

for (const status of [200, 503]) test(status === 200 ? "an empty celebration day leaves the app uninterrupted" : "celebration API failure is silent and nonblocking", async ({ page }) => {
  const state = await fixtures(page, { payload: empty() });
  state.status = status;
  await page.goto("/dashboard");
  await expect.poll(() => state.celebrationReplies).toBeGreaterThan(0);
  await expect(page.locator(".stat-value")).toHaveText("24");
  await settled(page);
  await closed(page);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await acknowledgments(page)).toEqual({});
  verify(state);
});

test("dismissal is stored only on acknowledgment, then routes and reload stay closed", async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  await opened(page);
  expect(await acknowledgments(page)).toEqual({});
  await page.keyboard.press("Escape");
  await closed(page);
  const saved = await acknowledgments(page);
  expect(Object.keys(saved)).toHaveLength(1);
  expect(Object.values(saved).join(" ")).toContain(state.payload.date);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("link", { name: "Employees", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Employees" })).toBeVisible();
  await closed(page);
  await page.reload();
  await expect.poll(() => state.celebrationReplies).toBeGreaterThan(1);
  await settled(page);
  await closed(page);
  expect(await acknowledgments(page)).toEqual(saved);
  verify(state);
});

test("reloading before dismissal shows the celebration again", async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  await opened(page);
  await page.reload();
  await opened(page);
  expect(state.celebrationRequests).toBeGreaterThan(1);
  expect(await acknowledgments(page)).toEqual({});
  verify(state);
});

test("a changed server business date reopens the next nonempty day", async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  await opened(page);
  await page.keyboard.press("Escape");
  await closed(page);
  state.payload = { ...birthday(), date: "2026-10-10" };
  await page.reload();
  await opened(page);
  await page.keyboard.press("Escape");
  await closed(page);
  expect(Object.values(await acknowledgments(page)).join(" ")).toContain("2026-10-10");
  verify(state);
});

for (const identity of ["id", "tenant_id", "employment_id"] as const) test(`daily dismissal is isolated by ${identity}`, async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  await opened(page);
  await page.keyboard.press("Escape");
  await closed(page);
  const original = { ...state.user };
  state.user = { ...original, [identity]: `different-${identity}`, name: "Maya Desai" };
  state.payload = { ...birthday(), birthdays: [{ id: state.user.employment_id!, name: state.user.name, company: "Suraj Group", is_self: true }] };
  await page.reload();
  const second = await opened(page);
  await expect(second).toContainText("Maya");
  await page.keyboard.press("Escape");
  await closed(page);
  expect(Object.keys(await acknowledgments(page))).toHaveLength(2);
  state.user = original;
  state.payload = birthday();
  await page.reload();
  await expect.poll(() => state.celebrationReplies).toBeGreaterThan(2);
  await settled(page);
  await closed(page);
  verify(state);
});

test("keyboard focus stays inside the popup and Escape dismisses it", async ({ page }) => {
  const state = await fixtures(page, { payload: colleagues() });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect.poll(() => dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  }
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await closed(page);
  expect(await page.evaluate(() => document.activeElement?.isConnected)).toBe(true);
  verify(state);
});

test("the close button acknowledges the day", async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await dialog.getByRole("button", { name: /close/i }).click();
  await closed(page);
  expect(Object.values(await acknowledgments(page)).join(" ")).toContain(state.payload.date);
  verify(state);
});

test("Continue to work acknowledges the day and leaves the dashboard usable", async ({ page }) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await dialog.getByRole("button", { name: "Continue to work", exact: true }).click();
  await closed(page);
  expect(Object.values(await acknowledgments(page)).join(" ")).toContain(state.payload.date);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("link", { name: "Employees", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Employees" })).toBeVisible();
  verify(state);
});

test("server date supplies the displayed date and acknowledgment independently of browser today", async ({ page }) => {
  const state = await fixtures(page, { payload: { ...birthday(), date: "2000-01-01" } });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect(dialog).toContainText("Saturday, 1 January");
  await page.keyboard.press("Escape");
  await closed(page);
  expect(Object.values(await acknowledgments(page))).toEqual(["2000-01-01"]);
  verify(state);
});

test("blocked celebration storage falls back to memory during shell remounts", async ({ page }) => {
  const state = await fixtures(page, { storageUnavailable: true });
  await page.goto("/dashboard");
  await opened(page);
  await page.keyboard.press("Escape");
  await closed(page);
  await spaRoute(page, "/change-password");
  await expect(page.getByRole("heading", { name: "Change password", exact: true })).toBeVisible();
  await spaRoute(page, "/dashboard");
  await expect(page.locator(".stat-value")).toHaveText("24");
  await settled(page);
  await closed(page);
  verify(state);
});

for (const gate of ["password", "mfa"] as const) test(`${gate} requirement prevents celebration requests until authentication gate clears`, async ({ page }) => {
  const state = await fixtures(page, { user: { must_change_password: gate === "password", mfa_required: gate === "mfa" } });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: gate === "password" ? "Choose a new password" : "Set up your authenticator" })).toBeVisible();
  await closed(page);
  expect(state.celebrationRequests).toBe(0);
  state.user = { ...state.user, must_change_password: false, mfa_required: false };
  await page.goto("/dashboard");
  await opened(page);
  verify(state);
});

test("password takes precedence and remaining MFA keeps celebrations gated", async ({ page }) => {
  const state = await fixtures(page, { user: { must_change_password: true, mfa_required: true } });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
  await page.locator("#cp-current").fill("TemporaryFixture1!");
  await page.locator("#cp-new").fill("ReplacementFixture2!");
  await page.locator("#cp-confirm").fill("ReplacementFixture2!");
  await page.getByRole("button", { name: "Set password and continue" }).click();
  await expect(page.getByRole("heading", { name: "Set up your authenticator" })).toBeVisible();
  expect(state.celebrationRequests).toBe(0);
  await closed(page);
  verify(state);
});

for (const palette of ["classic-teal", "midnight-blue", "ember-sand"]) for (const mode of ["light", "dark"] as const) test(`${palette} ${mode}: combined wishes and colleague list fit desktop and phone`, async ({ page }, testInfo) => {
  const state = await fixtures(page, { palette, mode, payload: { ...colleagues(), personal: { birthday: true, anniversary_years: 6 } } });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  await expect(dialog).toContainText("Ravi Shah");
  await expect(dialog).toContainText("Nila Singh");
  await expect(dialog).toContainText(/6 years/);
  await contrast(page, testInfo, `${palette}-${mode}`);
  await snapshot(page, testInfo, `${palette}-${mode}-desktop`);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(dialog.getByRole("button", { name: /close/i })).toBeInViewport();
  await snapshot(page, testInfo, `${palette}-${mode}-phone`);
  await writeFile(testInfo.outputPath(`${palette}-${mode}-geometry.json`), JSON.stringify({ viewport: { width: 390, height: 844 }, dialog: bounds }, null, 2));
  verify(state);
});

test("a long colleague roster can be scrolled by keyboard while dismissal stays visible", async ({ page }, testInfo) => {
  const payload = { ...colleagues(), birthdays: Array.from({ length: 24 }, (_, i) => ({ id: `colleague-${i}`, name: `Colleague ${i + 1} with a long family name`, company: "Suraj Group", is_self: false })) };
  const state = await fixtures(page, { payload, mode: "dark" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  const dialog = await opened(page), region = dialog.getByRole("region", { name: "Today's colleagues", exact: true });
  await expect(region).toHaveAttribute("tabindex", "0");
  await region.focus();
  await page.keyboard.press("End");
  await expect.poll(() => region.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await expect(dialog.getByRole("button", { name: "Continue to work", exact: true })).toBeInViewport();
  await snapshot(page, testInfo, "long-roster-phone");
  verify(state);
});

test("long personal names retain reachable dismissal controls in a short landscape viewport", async ({ page }, testInfo) => {
  const state = await fixtures(page, { user: { name: "Asha Priyadarshini Venkataraman Subramanian Rao" }, payload: { ...colleagues(), personal: { birthday: true, anniversary_years: 12 } } });
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto("/dashboard");
  const dialog = await opened(page);
  const region = dialog.getByRole("region", { name: "Today's colleagues", exact: true });
  const person = region.locator("li").first().locator(":scope > div").last();
  await person.scrollIntoViewIfNeeded();
  await settled(page);
  const regionBounds = await region.boundingBox(), personBounds = await person.boundingBox();
  await writeFile(testInfo.outputPath("long-name-landscape-geometry.json"), JSON.stringify({ viewport: { width: 844, height: 390 }, region: regionBounds, celebrant: personBounds }, null, 2));
  await snapshot(page, testInfo, "long-name-landscape");
  expect(regionBounds).not.toBeNull();
  expect(personBounds).not.toBeNull();
  expect(personBounds!.y, "The colleague name must be readable inside the roster after scrolling").toBeGreaterThanOrEqual(regionBounds!.y);
  expect(personBounds!.y + personBounds!.height, "The colleague name and detail must fit together in the visible roster").toBeLessThanOrEqual(regionBounds!.y + regionBounds!.height);
  const button = dialog.getByRole("button", { name: "Continue to work", exact: true });
  await expect(button).toBeInViewport();
  const buttonBounds = await button.boundingBox();
  expect(buttonBounds!.y + buttonBounds!.height).toBeLessThanOrEqual(390);
  await button.click();
  await closed(page);
  verify(state);
});
