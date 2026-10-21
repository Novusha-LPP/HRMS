import { test, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { appearanceFixtures } from "./fixtures/appearance";

async function settled(locator: Locator) {
  await locator.evaluate(async element => {
    await document.fonts.ready;
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    await Promise.all(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
  });
}

function verify(state: Awaited<ReturnType<typeof appearanceFixtures>>) {
  expect(state.unexpectedRequests).toEqual([]);
  expect(state.errors).toEqual([]);
}

async function snapshot(page: Page, testInfo: TestInfo, label: string) {
  await settled(page.locator("body"));
  await page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true, animations: "disabled" });
}

async function headerGeometry(page: Page) {
  return page.locator(".page-header").evaluate(header => {
    const bounds = header.getBoundingClientRect();
    const main = header.closest("main")!;
    const controls = [...header.querySelectorAll<HTMLElement>("button,a,input,select,[role='radio']")].filter(element => element.getBoundingClientRect().width > 0);
    return {
      viewport: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      mainWidth: main.clientWidth,
      mainScrollWidth: main.scrollWidth,
      header: { left: bounds.left, right: bounds.right, width: bounds.width, height: bounds.height },
      escapedControls: controls.flatMap(element => {
        const rect = element.getBoundingClientRect();
        return rect.left < bounds.left - 1 || rect.right > bounds.right + 1 || rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1
          ? [{ name: element.getAttribute("aria-label") ?? element.textContent, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }]
          : [];
      }),
    };
  });
}

for (const mode of ["light", "dark"] as const) test(`${mode}: Midnight headers fit desktop, laptop, tablet and narrow phones`, async ({ page }, testInfo) => {
  const state = await appearanceFixtures(page, mode, "midnight-blue");
  const results: Record<string, Awaited<ReturnType<typeof headerGeometry>>> = {};
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: width < 640 ? 844 : 1000 });
    for (const path of ["/dashboard", "/daily-analysis", "/attendance"]) {
      await page.goto(path);
      await expect(page.locator(".page-header h1")).toBeVisible();
      await expect(page.locator(".skeleton")).toHaveCount(0);
      await settled(page.locator(".page-header"));
      const label = `${mode}-${width}-${path.slice(1)}`;
      results[label] = await headerGeometry(page);
      await snapshot(page, testInfo, label);
    }
  }
  await writeFile(testInfo.outputPath("header-geometry.json"), JSON.stringify(results, null, 2));
  for (const [label, result] of Object.entries(results)) {
    expect.soft(result.documentWidth, `${label} must not overflow the browser`).toBeLessThanOrEqual(result.viewport);
    expect.soft(result.mainScrollWidth, `${label} must not clip content inside the workspace`).toBeLessThanOrEqual(result.mainWidth + 1);
    expect.soft(result.escapedControls, `${label} actions must remain inside their header`).toEqual([]);
  }
  verify(state);
});

for (const mode of ["light", "dark"] as const) test(`${mode}: mobile navigation traps focus, closes with Escape and restores its trigger`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 700 });
  const state = await appearanceFixtures(page, mode, "midnight-blue");
  await page.goto("/dashboard");
  await expect(page.locator(".stat-value").first()).toHaveText("24");
  const toggle = page.getByRole("button", { name: "Toggle sidebar", exact: true });
  await toggle.focus();
  await page.keyboard.press("Enter");
  const sidebar = page.locator(".app-sidebar").nth(1);
  await expect(sidebar).toBeVisible();
  await expect(sidebar).toHaveAccessibleName("Main navigation");
  await settled(sidebar);
  await snapshot(page, testInfo, `${mode}-320-sidebar`);
  const evidence = {
    role: await sidebar.getAttribute("role"),
    modal: await sidebar.getAttribute("aria-modal"),
    initialFocusInside: await sidebar.evaluate(element => element.contains(document.activeElement)),
    escapedFocus: [] as string[],
    escapedWithEscape: false,
    restoredTrigger: false,
  };
  for (let i = 0; i < 35; i++) {
    await page.keyboard.press("Tab");
    const focus = await sidebar.evaluate(element => ({ inside: element.contains(document.activeElement), label: document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.textContent?.trim().slice(0, 80) ?? "none" }));
    if (!focus.inside) evidence.escapedFocus.push(focus.label);
  }
  await page.keyboard.press("Escape");
  evidence.escapedWithEscape = await sidebar.count() === 0;
  evidence.restoredTrigger = await toggle.evaluate(element => element === document.activeElement);
  await writeFile(testInfo.outputPath("navigation-keyboard.json"), JSON.stringify(evidence, null, 2));
  expect.soft(evidence.role).toBe("dialog");
  expect.soft(evidence.modal).toBe("true");
  expect.soft(evidence.initialFocusInside).toBe(true);
  expect.soft(evidence.escapedFocus).toEqual([]);
  expect.soft(evidence.escapedWithEscape).toBe(true);
  expect.soft(evidence.restoredTrigger).toBe(true);
  // A hidden desktop drawer must release its modal hook instead of trapping invisible controls.
  await toggle.click();
  await expect(sidebar).toBeVisible();
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(sidebar).toHaveCount(0);
  await expect(toggle).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
  verify(state);
});

for (const mode of ["light", "dark"] as const) test(`${mode}: reduced motion disables overview quick-action lift and loading shimmer`, async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const state = await appearanceFixtures(page, mode, "midnight-blue");
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/v1/dashboard/hr?**", async route => { await gate; await route.fallback(); });
  await page.goto("/dashboard");
  await expect(page.locator(".skeleton").first()).toBeVisible();
  // Re-query on every attempt: React may swap the skeleton node, and a detached element
  // reports empty computed styles.
  let shimmer = { animation: "", duration: "", display: "" };
  await expect.poll(async () => {
    shimmer = await page.evaluate(() => {
      const element = document.querySelector(".skeleton");
      if (!element) return { animation: "", duration: "", display: "" };
      const css = getComputedStyle(element, "::after");
      return { animation: css.animationName, duration: css.animationDuration, display: css.display };
    });
    return shimmer.animation !== "";
  }).toBe(true);
  release();
  await expect(page.locator(".stat-value").first()).toHaveText("24");
  await page.getByRole("radio", { name: "Overview", exact: true }).click();
  const shortcut = page.locator("[data-quick-actions] .group").first();
  await expect(shortcut).toBeVisible();
  await shortcut.hover();
  await settled(shortcut);
  const hover = await shortcut.evaluate(element => {
    const css = getComputedStyle(element);
    return { transform: css.transform, transitionDuration: css.transitionDuration };
  });
  await writeFile(testInfo.outputPath("reduced-motion.json"), JSON.stringify({ shimmer, hover }, null, 2));
  await snapshot(page, testInfo, `${mode}-reduced-overview`);
  expect.soft(shimmer.animation).toBe("none");
  expect.soft(shimmer.display).toBe("none");
  expect.soft(hover.transform).toBe("none");
  expect.soft(hover.transitionDuration).toBe("0s");
  verify(state);
});

for (const mode of ["light", "dark"] as const) test(`${mode}: nested dialogs keep focus in the top surface and close one at a time`, async ({ page }, testInfo) => {
  const state = await appearanceFixtures(page, mode, "midnight-blue");
  await page.goto("/dashboard");
  await expect(page.locator(".stat-value").first()).toHaveText("24");
  const originalOverflow = await page.evaluate(() => document.body.style.overflow);
  const customize = page.getByRole("button", { name: "Customize dashboard", exact: true });
  await customize.click();
  const adding = page.getByRole("button", { name: "Add widget", exact: true });
  await adding.click();
  const sheet = page.getByRole("dialog", { name: "Add a widget", exact: true });
  await expect(sheet).toBeVisible();
  const sheetLocksScroll = await page.evaluate(() => document.body.style.overflow === "hidden");
  await sheet.getByRole("button", { name: "Close", exact: true }).focus();
  await page.keyboard.press("Control+k");
  const top = page.locator(".dialog-panel");
  await expect(top).toBeVisible();
  await expect(top).toHaveAccessibleName("Search commands");
  await top.evaluate(element => {
    const probes = document.createElement("div");
    probes.dataset.focusGuardProbe = "true";
    probes.innerHTML = '<button style="display:none">Hidden modal control</button><input disabled aria-label="Disabled modal control">';
    element.append(probes);
  });
  const first = top.getByRole("textbox", { name: "Command search", exact: true });
  await first.focus();
  await page.keyboard.press("Shift+Tab");
  const backwardEdgeInside = await top.evaluate(element => element.contains(document.activeElement));
  await page.keyboard.press("Tab");
  const forwardEdgeRestoresFirst = await first.evaluate(element => element === document.activeElement);
  await page.getByRole("button", { name: "Toggle sidebar", exact: true }).focus();
  const outsideFocusRedirected = await top.evaluate(element => element.contains(document.activeElement));
  const escapedFocus: string[] = [];
  for (let i = 0; i < 35; i++) {
    await page.keyboard.press(i < 25 ? "Tab" : "Shift+Tab");
    const result = await top.evaluate(element => ({ inside: element.contains(document.activeElement), label: document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.textContent?.trim().slice(0, 70) ?? "none" }));
    if (!result.inside) escapedFocus.push(result.label);
  }
  await top.locator("[data-focus-guard-probe]").evaluate(element => element.remove());
  await snapshot(page, testInfo, `${mode}-nested-dialog`);
  await page.keyboard.press("Escape");
  await expect(top).toHaveCount(0);
  await expect(sheet).toBeVisible();
  const restoredSheet = await sheet.getByRole("button", { name: "Close", exact: true }).evaluate(element => element === document.activeElement);
  const lockRetained = await page.evaluate(() => document.body.style.overflow === "hidden");
  const escapedSheetFocus: string[] = [];
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press(i < 4 ? "Tab" : "Shift+Tab");
    const result = await sheet.evaluate(element => ({ inside: element.contains(document.activeElement), label: document.activeElement?.textContent?.trim().slice(0, 70) ?? "none" }));
    if (!result.inside) escapedSheetFocus.push(result.label);
  }
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  const overflowRestored = await page.evaluate(original => document.body.style.overflow === original, originalOverflow);
  await writeFile(testInfo.outputPath("nested-focus.json"), JSON.stringify({ backwardEdgeInside, forwardEdgeRestoresFirst, outsideFocusRedirected, escapedFocus, restoredSheet, escapedSheetFocus, sheetLocksScroll, lockRetained, overflowRestored }, null, 2));
  expect.soft(backwardEdgeInside).toBe(true);
  expect.soft(forwardEdgeRestoresFirst).toBe(true);
  expect.soft(outsideFocusRedirected).toBe(true);
  expect.soft(escapedFocus).toEqual([]);
  expect.soft(restoredSheet).toBe(true);
  expect.soft(escapedSheetFocus).toEqual([]);
  expect.soft(sheetLocksScroll).toBe(true);
  expect.soft(lockRetained).toBe(true);
  expect.soft(overflowRestored).toBe(true);
  await expect(adding).toBeFocused();
  await page.goto("/policy");
  await expect(page.getByText("Studio standard", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Actions for Studio standard", exact: true }).click();
  await page.locator(".popover").getByRole("button", { name: "Delete", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: /Delete.*Studio standard/ });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toHaveAttribute("aria-describedby", /.+/);
  await expect(confirmation).toHaveAccessibleDescription(/Employees assigned to this policy will need a new one/);
  await expect(confirmation.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await snapshot(page, testInfo, `${mode}-named-confirmation`);
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  // This form uses React autoFocus, so opener capture must happen before its mount commit.
  await page.goto("/policy?tab=leave&section=holidays");
  await page.getByRole("tab", { name: /2 · Calendars/ }).click();
  const newCalendar = page.getByRole("button", { name: "New calendar", exact: true });
  await expect(newCalendar).toBeVisible();
  for (let i = 0; i < 2; i++) {
    await newCalendar.click();
    const calendar = page.getByRole("dialog", { name: "New calendar", exact: true });
    await expect(calendar).toBeVisible();
    await expect(calendar.getByRole("textbox", { name: "Calendar name", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(calendar).toHaveCount(0);
    await expect(newCalendar).toBeFocused();
  }
  verify(state);
});

for (const mode of ["light", "dark"] as const) test(`${mode}: a long sheet and long dialog remain scrollable in short landscape`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 844, height: 320 });
  const state = await appearanceFixtures(page, mode, "midnight-blue");
  await page.goto("/dashboard");
  await expect(page.locator(".stat-value").first()).toHaveText("24");
  await page.getByRole("button", { name: "Customize dashboard", exact: true }).click();
  await page.getByRole("button", { name: "Add widget", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Add a widget", exact: true });
  await expect(sheet).toBeVisible();
  const scroll = sheet.locator(":scope > div").last();
  await scroll.evaluate(element => {
    const content = document.createElement("div");
    content.dataset.longContentProbe = "true";
    content.innerHTML = '<p>' + 'Synthetic long content for scroll testing. '.repeat(400) + '</p><button class="btn-secondary">Last sheet action</button>';
    element.append(content);
  });
  await sheet.getByRole("button", { name: "Last sheet action", exact: true }).focus();
  await expect(sheet.getByRole("button", { name: "Last sheet action", exact: true })).toBeInViewport();
  await snapshot(page, testInfo, `${mode}-landscape-sheet-end`);
  await page.keyboard.press("Control+k");
  const dialog = page.locator(".dialog-panel");
  await expect(dialog).toBeVisible();
  await settled(dialog);
  const result = await dialog.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    const scrollable = [...element.querySelectorAll<HTMLElement>("*")].filter(child => child.scrollHeight > child.clientHeight && ["auto", "scroll"].includes(getComputedStyle(child).overflowY));
    return { top: bounds.top, bottom: bounds.bottom, viewportHeight: innerHeight, scrollable: scrollable.map(child => ({ height: child.clientHeight, scrollHeight: child.scrollHeight })) };
  });
  await snapshot(page, testInfo, `${mode}-landscape-command-dialog`);
  await writeFile(testInfo.outputPath("landscape-overlay.json"), JSON.stringify(result, null, 2));
  expect.soft(result.top).toBeGreaterThanOrEqual(0);
  expect.soft(result.bottom).toBeLessThanOrEqual(result.viewportHeight);
  expect.soft(result.scrollable.length).toBeGreaterThan(0);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  verify(state);
});
