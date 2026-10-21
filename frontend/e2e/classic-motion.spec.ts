/** Scoped Classic Teal motion contracts, using synthetic fixtures only. */
import { test, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const entity = { id: "motion-company", name: "Suraj Group", status: "ACTIVE", version: 0 };
const person = { id: "motion-person", legal_first_name: "Asha", legal_last_name: "Rao", preferred_name: null, date_of_birth: "1992-06-15", gender: "FEMALE", version: 0 };
const employee = { id: "motion-employee", person_id: person.id, legal_entity_id: entity.id, employee_number: "SG-001", full_name: "Asha Rao", email: "asha@example.test", hire_date: "2020-01-01", employment_state: "ACTIVE", service_stage: "CONFIRMED", separation_date: null, department: "People", designation: "People Partner", location: "Bengaluru", legal_entity_name: entity.name, version: 0 };
const user = { id: "motion-user", tenant_id: "motion-tenant", tenant_name: entity.name, employment_id: employee.id, name: "Asha Rao", email: employee.email, roles: ["HR_MANAGER"], permissions: ["*"], is_all_scope: true, legal_entities: [entity], must_change_password: false, mfa_required: false };
const widgetIds = ["kpi_headcount", "kpi_present_today", "kpi_on_leave_today", "kpi_pending_approvals", "quick_actions"];
const layout = { dashboard: "hr", widgets: widgetIds.map(widget => ({ widget, size: widget.startsWith("kpi_") ? "quarter" : "half" })), is_default: true, sections: "headcount,today,actions", catalog: widgetIds.map(id => ({ id, title: id, description: id, category: "People", default_size: "half", sizes: ["half"] })) };

type FixtureOptions = { mode?: "light" | "dark"; palette?: string; celebration?: boolean; holdLayout?: boolean };
async function fixtures(page: Page, options: FixtureOptions = {}) {
  const state = { preferences: { color_theme: options.palette ?? "classic-teal", dashboard_style: "widgets" }, errors: [] as string[], unexpectedRequests: [] as string[], releaseLayout: () => {} };
  const layoutGate = options.holdLayout ? new Promise<void>(resolve => { state.releaseLayout = resolve; }) : Promise.resolve();
  page.on("pageerror", error => state.errors.push(error.message));
  await page.addInitScript(({ mode, palette }) => {
    (window as Window & { __HRMS_CONFIG__?: unknown }).__HRMS_CONFIG__ = { apiUrl: location.origin, environment: "local" };
    localStorage.setItem("hrms_theme", mode);
    localStorage.setItem("hrms_color_theme", palette);
  }, { mode: options.mode ?? "light", palette: options.palette ?? "classic-teal" });
  await page.route("**/config.js", route => route.fulfill({ contentType: "application/javascript", body: "window.__HRMS_CONFIG__ = { apiUrl: location.origin, environment: 'local' };" }));
  await page.route("**/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const reply = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/v1/me/preferences" && request.method() === "PATCH") {
      Object.assign(state.preferences, request.postDataJSON());
      return reply(state.preferences);
    }
    if (request.method() !== "GET") {
      state.unexpectedRequests.push(`${request.method()} ${path}`);
      return reply({ message: "Motion QA rejects business mutations" }, 400);
    }
    if (path === "/v1/auth/me") return reply(user);
    if (path === "/v1/platform/me") return reply({ message: "Not signed in" }, 401);
    if (path === "/v1/me/preferences") return reply(state.preferences);
    if (path === "/v1/dashboard/celebrations") return reply({ date: "2026-10-09", timezone: "Asia/Kolkata", personal: { birthday: options.celebration ?? false, anniversary_years: null }, birthdays: options.celebration ? [{ id: employee.id, name: user.name, company: entity.name, is_self: true }] : [], anniversaries: [] });
    if (path === "/v1/dashboard/layout") { await layoutGate; return reply(layout); }
    if (path === "/v1/dashboard/hr") return reply({ headcount: { total: 24 }, today: { present: 20, on_leave: 3 }, actions: { pending_approvals: 2 } });
    if (path === "/v1/employees") return reply([employee]);
    if (path === "/v1/persons") return reply([person]);
    if (["/v1/leave/applications", "/v1/corrections"].includes(path)) return reply([]);
    if (/^\/v1\/kyc\/employees\/[^/]+\/photo$/.test(path)) return route.fulfill({ status: 204 });
    state.unexpectedRequests.push(`GET ${path}`);
    return reply({ message: `Missing motion fixture: ${path}` }, 404);
  });
  return state;
}

function verify(state: Awaited<ReturnType<typeof fixtures>>) {
  expect(state.errors, "Motion must not cause JavaScript exceptions").toEqual([]);
  expect(state.unexpectedRequests, "Every API request must use an explicit synthetic fixture").toEqual([]);
}

async function styles(locator: Locator) {
  return locator.evaluate(element => {
    const css = getComputedStyle(element);
    return { animationName: css.animationName, animationDuration: css.animationDuration, animationIterationCount: css.animationIterationCount, animationDelay: css.animationDelay, transitionDuration: css.transitionDuration, transitionProperty: css.transitionProperty, transform: css.transform, outlineWidth: css.outlineWidth, outlineStyle: css.outlineStyle, width: css.width };
  });
}

function seconds(value: string) { return value.split(",").map(duration => parseFloat(duration) * (duration.trim().endsWith("ms") ? .001 : 1)); }

async function finiteEntry(locator: Locator, maxSeconds = .35, expectedName = "classic-") {
  const motion = await styles(locator);
  expect(motion.animationName).toContain(expectedName);
  expect(motion.animationIterationCount).toBe("1");
  expect(seconds(motion.animationDuration).every(value => value > 0 && value <= maxSeconds)).toBe(true);
  return motion;
}

async function settled(locator: Locator) {
  await locator.evaluate(async element => {
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    await Promise.all(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
  });
}

async function reducedAudit(page: Page) {
  const result = await page.evaluate(() => {
    const nodes = [document.body, ...document.body.querySelectorAll("*")];
    const failures = nodes.flatMap(element => [null, "::before", "::after"].flatMap(pseudo => {
      const css = getComputedStyle(element, pseudo);
      const hasDuration = (value: string) => value.split(",").some(part => parseFloat(part) > 0);
      if (css.animationName === "none" && !hasDuration(css.transitionDuration)) return [];
      return [{ element: `${element.tagName.toLowerCase()}.${element.className}`, pseudo, animation: css.animationName, transition: css.transitionDuration }];
    }));
    return { failures, activeAnimations: document.getAnimations().length, scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior };
  });
  expect(result.failures, "Classic reduced motion must suppress animations and transitions including pseudos").toEqual([]);
  expect(result.activeAnimations).toBe(0);
  expect(result.scrollBehavior).toBe("auto");
  return result;
}

async function snapshot(page: Page, testInfo: TestInfo, label: string) {
  await page.evaluate(() => document.fonts.ready);
  await settled(page.locator("body"));
  await page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true, animations: "disabled" });
}

async function interactionGuards(page: Page, enabled: Locator, reduce: boolean) {
  await enabled.hover();
  await page.mouse.down();
  await settled(enabled);
  const press = await styles(enabled);
  if (reduce) expect(press.transform).toBe("none");
  else {
    const scale = await enabled.evaluate(element => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(element).transform);
      return { x: matrix.m11, y: matrix.m22, translation: matrix.m42 };
    });
    expect(scale.x).toBeCloseTo(.98, 2);
    expect(scale.y).toBeCloseTo(.98, 2);
    expect(scale.translation, "Press feedback takes precedence over hover lift").toBe(0);
  }
  // Release outside the button so measuring press feedback does not activate the action.
  await page.mouse.move(1400, 970);
  await page.mouse.up();
  await page.evaluate(() => {
    const probes = document.createElement("div");
    probes.id = "motion-guard-probes";
    probes.style.cssText = "position:fixed;left:320px;bottom:24px;display:flex;gap:12px;z-index:99999";
    probes.innerHTML = '<button class="btn-secondary" disabled>Disabled motion probe</button><button class="btn-secondary" aria-disabled="true">Unavailable motion probe</button>';
    document.body.append(probes);
  });
  const disabled: Record<string, unknown> = {};
  for (const label of ["Disabled motion probe", "Unavailable motion probe"]) {
    const button = page.getByRole("button", { name: label, exact: true });
    const rect = await button.boundingBox();
    await page.mouse.move(rect!.x + rect!.width / 2, rect!.y + rect!.height / 2);
    await settled(button);
    disabled[label] = await styles(button);
    await expect(button).toHaveCSS("transform", "none");
  }
  await page.locator("#motion-guard-probes").evaluate(element => element.remove());
  return { press, disabled };
}

for (const phone of [false, true]) for (const mode of ["light", "dark"] as const) {
  test.describe(`${phone ? "phone" : "desktop"} ${mode}`, () => {
    test.use({ viewport: phone ? { width: 390, height: 844 } : { width: 1440, height: 1000 }, isMobile: phone, hasTouch: phone });

    for (const reducedMotion of ["no-preference", "reduce"] as const) test(`${reducedMotion}: popup, drawer, navigation and feedback`, async ({ page }, testInfo) => {
      await page.emulateMedia({ reducedMotion });
      const reduce = reducedMotion === "reduce";
      const state = await fixtures(page, { mode, celebration: true, holdLayout: reduce });
      const evidence: Record<string, unknown> = {};
      await page.goto("/dashboard");
      const popup = page.getByRole("dialog", { name: /happy birthday/i });
      await expect(popup).toBeVisible();
      await expect(popup.getByRole("button", { name: "Continue to work" })).toBeFocused();
      if (reduce) {
        await expect(page.locator(".skeleton").first()).toBeAttached();
        evidence.popupAndSkeleton = await reducedAudit(page);
        const shimmer = await page.locator(".skeleton").first().evaluate(element => getComputedStyle(element, "::after").display);
        expect(shimmer).toBe("none");
      } else {
        evidence.popup = await finiteEntry(popup);
        evidence.badge = await finiteEntry(popup.locator(".celebration-mark"), .5);
      }
      await snapshot(page, testInfo, "celebration");
      await page.keyboard.press("Tab");
      await expect(popup.getByRole("region", { name: "Today's celebrations" })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(popup.getByRole("button", { name: "Close celebrations" })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(popup).toHaveCount(0);
      state.releaseLayout();
      await expect(page.locator("[data-widget='kpi_headcount'] .stat-value")).toHaveText("24");

      const customize = page.getByRole("button", { name: "Customize dashboard", exact: true });
      if (!phone) evidence.interactionGuards = await interactionGuards(page, customize, reduce);
      if (!phone && !reduce) {
        await customize.hover();
        await settled(customize);
        evidence.buttonHover = await styles(customize);
        const buttonY = await customize.evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).m42);
        expect(buttonY, "Button hover gives a small lift").toBeLessThan(0);
        expect(buttonY).toBeGreaterThanOrEqual(-2);
        await page.locator(".stat-card").first().hover();
        await settled(page.locator(".stat-icon").first());
        evidence.statIconHover = await styles(page.locator(".stat-icon").first());
        expect((evidence.statIconHover as Awaited<ReturnType<typeof styles>>).transform).not.toBe("none");
      }
      await customize.click();
      await page.getByRole("button", { name: "Add widget", exact: true }).click();
      const drawer = page.getByRole("dialog", { name: "Add a widget", exact: true });
      await expect(drawer).toBeVisible();
      if (reduce) evidence.drawer = await reducedAudit(page);
      else evidence.drawer = await finiteEntry(drawer, .35, "slide-in-right");
      await settled(drawer);
      const rect = await drawer.boundingBox();
      expect(rect!.x).toBeGreaterThanOrEqual(0);
      expect(rect!.x + rect!.width).toBeLessThanOrEqual((phone ? 390 : 1440) + 1);
      await snapshot(page, testInfo, "drawer");
      await page.keyboard.press("Escape");
      await expect(drawer).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Add widget", exact: true })).toBeFocused();
      await page.keyboard.press("Tab");
      const cancel = page.getByRole("button", { name: "Cancel", exact: true });
      await expect(cancel).toBeFocused();
      await expect(cancel).toHaveCSS("outline-style", "solid");
      await expect(cancel).toHaveCSS("outline-width", "2px");
      await cancel.click();

      const toggle = page.getByRole("button", { name: "Toggle sidebar", exact: true });
      await toggle.click();
      if (phone) {
        const sidebar = page.locator(".app-sidebar").nth(1);
        await expect(sidebar).toBeVisible();
        if (reduce) evidence.sidebar = await reducedAudit(page);
        else evidence.sidebar = await finiteEntry(sidebar, .35, "slide-in-left");
      } else {
        const sidebar = page.locator(".app-sidebar").first();
        await expect(sidebar).toHaveCSS("width", "68px");
        evidence.sidebar = await styles(sidebar);
        if (!reduce) expect(seconds((evidence.sidebar as Awaited<ReturnType<typeof styles>>).transitionDuration).every(value => value > 0 && value <= .3)).toBe(true);
        expect(await page.evaluate(() => localStorage.getItem("hrms_sidebar"))).toBe("collapsed");
        await toggle.click();
        await expect(sidebar).toHaveCSS("width", "240px");
      }
      await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("link", { name: "Employees", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Employees", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Asha Rao", exact: true })).toBeVisible();
      if (phone) await expect(page.locator(".app-sidebar").nth(1)).toHaveCount(0);
      if (reduce) evidence.finalPage = await reducedAudit(page);
      await snapshot(page, testInfo, "employees");
      await writeFile(testInfo.outputPath("motion-evidence.json"), JSON.stringify(evidence, null, 2));
      verify(state);
    });
  });
}

test("switching palettes restores their original motion and does not retain Classic feedback", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const state = await fixtures(page, { palette: "midnight-blue" });
  await page.goto("/dashboard");
  await expect(page.locator(".stat-value").first()).toHaveText("24");
  const evidence: Record<string, unknown> = {};
  const account = page.getByRole("button", { name: "Account menu", exact: true });
  await account.click();
  const palette = page.getByRole("combobox", { name: "Colour theme", exact: true });
  for (const id of ["midnight-blue", "ember-sand"]) {
    await palette.selectOption(id);
    await expect(page.locator("html")).toHaveAttribute("data-color-theme", id);
    await settled(page.locator(".popover"));
    const before = { sidebar: await styles(page.locator(".app-sidebar").first()), popover: await styles(page.locator(".popover")), button: await styles(page.getByRole("button", { name: "Customize dashboard" })) };
    expect(JSON.stringify(before)).not.toContain("classic-");
    await palette.selectOption("classic-teal");
    await expect(page.locator("html")).toHaveAttribute("data-color-theme", "classic-teal");
    expect((await styles(page.locator(".app-sidebar").first())).transitionDuration).not.toBe(before.sidebar.transitionDuration);
    await palette.selectOption(id);
    await expect(page.locator("html")).toHaveAttribute("data-color-theme", id);
    await settled(page.locator(".popover"));
    const after = { sidebar: await styles(page.locator(".app-sidebar").first()), popover: await styles(page.locator(".popover")), button: await styles(page.getByRole("button", { name: "Customize dashboard" })) };
    expect(after).toEqual(before);
    await account.click();
    const customize = page.getByRole("button", { name: "Customize dashboard", exact: true });
    await customize.hover();
    await settled(customize);
    await expect(customize).toHaveCSS("transform", "none");
    await page.locator(".stat-card").first().hover();
    await settled(page.locator(".stat-icon").first());
    await expect(page.locator(".stat-icon").first()).toHaveCSS("transform", "none");
    evidence[id] = { before, after };
    await account.click();
  }
  await writeFile(testInfo.outputPath("palette-motion-isolation.json"), JSON.stringify(evidence, null, 2));
  verify(state);
});

test("a pending dashboard uses a gentle shimmer that disappears when data arrives", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const state = await fixtures(page, { holdLayout: true });
  await page.goto("/dashboard");
  const skeleton = page.locator(".skeleton").first();
  await expect(skeleton).toBeVisible();
  const shimmer = await skeleton.evaluate(element => {
    const css = getComputedStyle(element, "::after");
    return { name: css.animationName, duration: css.animationDuration, iterations: css.animationIterationCount };
  });
  expect(shimmer.name).toBe("shimmer");
  expect(seconds(shimmer.duration).every(value => value >= 1 && value <= 3)).toBe(true);
  await writeFile(testInfo.outputPath("skeleton-motion.json"), JSON.stringify(shimmer, null, 2));
  state.releaseLayout();
  await expect(page.locator("[data-widget='kpi_headcount'] .stat-value")).toHaveText("24");
  await expect(page.locator(".skeleton")).toHaveCount(0);
  verify(state);
});
