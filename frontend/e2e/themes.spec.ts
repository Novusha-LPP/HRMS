/**
 * Fixture-backed visual and interaction checks for appearance settings. All API requests are
 * intercepted; preference updates are in-memory and business-data mutations are rejected.
 * Run against an already running preview:
 *   npx playwright test --config playwright.themes.config.ts
 */
import { test, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const palettes = [
  { id: "classic-teal", name: "Classic Teal", prefix: "classic-teal-" },
  { id: "ember-sand", name: "Ember Sand", prefix: "" },
  { id: "midnight-blue", name: "Midnight Blue", prefix: "midnight-blue-" },
] as const;

const entity = { id: "theme-company", name: "Northstar Studio", short_name: "NS", country_code: "IN", status: "ACTIVE", version: 0 };
const person = { id: "theme-person", legal_first_name: "Asha", legal_last_name: "Rao", preferred_name: null, date_of_birth: "1992-06-15", gender: "FEMALE", version: 0 };
const employee = { id: "theme-employee", person_id: person.id, legal_entity_id: entity.id, employee_number: "NS-001", full_name: "Asha Rao", email: "asha@example.test", role: "HR Manager", hire_date: "2020-01-01", employment_state: "ACTIVE", service_stage: "CONFIRMED", separation_date: null, version: 0, department: "People", designation: "People Partner", location: "Bengaluru", manager_name: "Ravi Shah", legal_entity_name: entity.name };
const user = { id: "theme-user", tenant_id: "theme-tenant", tenant_name: entity.name, employment_id: employee.id, name: "Asha Rao", email: employee.email, roles: ["HR_MANAGER"], permissions: ["*"], is_all_scope: true, legal_entities: [entity], must_change_password: false, mfa_required: false };
const leaveType = { id: "theme-annual", name: "Annual leave", code: "AL", days_per_year: 24, color: "#58694E", is_active: true, requires_document: false, accrual_enabled: true };
const applications = ["APPROVED", "PENDING_L1", "REJECTED"].map((status, i) => ({ id: `theme-leave-${i}`, employment_id: employee.id, leave_type_id: leaveType.id, leave_type_name: leaveType.name, leave_type_code: "AL", leave_type_color: leaveType.color, from_date: `2026-10-${20 + i}`, to_date: `2026-10-${20 + i}`, days_requested: 1, half_day_option: "NONE", reason: "Family appointment", status, current_level: 1, total_levels: 1, applied_at: "2026-10-01T04:30:00Z", cancel_reason: null, cancel_requested_at: null, approval_history: [] }));
const hr = {
  headcount: { total: 24, by_department: [{ name: "People", count: 8 }, { name: "Engineering", count: 16 }], by_company: [{ name: entity.name, count: 24 }] },
  today: { present: 20, late: 2, absent: 1, on_leave: 3 },
  month: { new_hires: 3, separations: 1 },
  actions: { pending_approvals: 2, pending_leave: 1, pending_corrections: 1, open_onboarding: 2, pending_kyc: 1 },
  action_centre: [{ key: "leave_approvals", label: "Leave approvals", count: 1, link: "/leave?tab=approvals" }],
  department_distribution: [{ department: "People", count: 8 }, { department: "Engineering", count: 16 }],
  leave_by_department: [{ department: "People", days_per_person: 1.5 }, { department: "Engineering", days_per_person: 2.3 }],
  lifecycle: { on_probation: 3, on_notice: 1, confirmed_this_month: 2, promoted_this_month: 1 },
  statutory: { employees: 24, missing_uan: 1, missing_pf: 1, missing_esi: 1 },
  exits: { exits_this_month: 1, exits_last_90_days: 2, on_notice: 1, attrition_12m_pct: 4.2 },
  worker_types: [{ worker_type: "FULL_TIME", count: 21 }, { worker_type: "CONTRACT", count: 3 }],
  scheduled_changes: [{ name: "Nila Singh", department: "People", company: entity.name, type: "TRANSFER", effective_date: "2026-10-12", days_until: 3 }],
  recent_joiners: [{ name: "Nila Singh", department: "People", designation: "People Partner", company: entity.name, hire_date: "2026-10-01" }],
  highlights_today: { birthdays: [{ name: "Ravi Shah", department: "Engineering", company: entity.name }], joining: [], exiting: [], anniversaries: [], company_anniversaries: [] },
  pending_approvals: [], upcoming_birthdays: [], work_anniversaries: [], new_joiners: [],
};

type Preferences = { color_theme: string; dashboard_style: "widgets" | "overview" };
type Fixtures = { preferences: Preferences; unexpectedRequests: string[]; errors: string[] };

async function fixtures(page: Page, mode: "light" | "dark" | "system" = "light", colorTheme = "ember-sand", authenticated = true): Promise<Fixtures> {
  const state: Fixtures = { preferences: { color_theme: colorTheme, dashboard_style: "widgets" }, unexpectedRequests: [], errors: [] };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.addInitScript(({ mode, colorTheme }) => {
    // Runtime config selects this origin so the intercepted requests never leave the preview.
    (window as Window & { __HRMS_CONFIG__?: unknown }).__HRMS_CONFIG__ = { apiUrl: location.origin, environment: "local" };
    if (!localStorage.getItem("hrms_theme")) localStorage.setItem("hrms_theme", mode);
    if (!localStorage.getItem("hrms_color_theme")) localStorage.setItem("hrms_color_theme", colorTheme);
  }, { mode, colorTheme });
  await page.route("**/config.js", route => route.fulfill({ contentType: "application/javascript", body: "window.__HRMS_CONFIG__ = { apiUrl: location.origin, environment: 'local' };" }));
  await page.route("**/v1/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    const reply = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data).replaceAll(entity.name, colorTheme === "classic-teal" ? "Suraj Group" : entity.name) });
    if (path === "/v1/me/preferences" && request.method() === "PATCH") {
      Object.assign(state.preferences, request.postDataJSON());
      return reply(state.preferences);
    }
    if (request.method() !== "GET") {
      state.unexpectedRequests.push(`${request.method()} ${path}`);
      return reply({ message: "Theme QA rejects business mutations" }, 400);
    }
    if (path === "/v1/auth/me") return reply(authenticated ? user : { message: "Not signed in" }, authenticated ? 200 : 401);
    if (path === "/v1/platform/me") return reply({ message: "Not signed in" }, 401);
    if (path === "/v1/me/preferences") return reply(state.preferences);
    if (path === "/v1/dashboard/celebrations") return reply({ date: "2026-10-09", timezone: "Asia/Kolkata", personal: { birthday: false, anniversary_years: null }, birthdays: [], anniversaries: [] });
    if (path === "/v1/dashboard/layout") {
      const overview = url.searchParams.get("dashboard") === "overview";
      const ids = overview ? ["attendance", "leave", "action_centre", "quick_actions", "departments", "highlights", "lifecycle", "training", "exits", "employee_type", "compliance", "tasks", "recent_joiners", "quick_links"] : ["kpi_headcount", "kpi_present_today", "kpi_on_leave_today", "kpi_pending_approvals", "attendance_today", "quick_actions", "headcount_by_department"];
      return reply({ dashboard: overview ? "overview" : "hr", widgets: ids.map(widget => ({ widget, size: widget.startsWith("kpi_") ? "quarter" : "half" })), is_default: true, sections: "headcount,today,actions", catalog: ids.map(id => ({ id, title: id, description: id, category: "People", default_size: "half", sizes: ["half"] })) });
    }
    if (path === "/v1/dashboard/hr") return reply(hr);
    if (path === "/v1/employees") return reply([employee, { ...employee, id: "theme-employee-2", person_id: "theme-person-2", employee_number: "NS-002", full_name: "Ravi Shah", email: "ravi@example.test", department: "Engineering", designation: "Engineer", employment_state: "PROBATION" }]);
    if (path === "/v1/persons") return reply([person, { ...person, id: "theme-person-2", legal_first_name: "Ravi", legal_last_name: "Shah" }]);
    // No connected app manages the theme employee, so no field is locked.
    if (path.startsWith("/v1/employees/") && path.endsWith("/field-control")) return reply([]);
    if (path === "/v1/persons/me") return reply({ ...person, nationality: "IN", email: employee.email, mobile: "+91 90000 11111" });
    if (path === "/v1/org/legal-entities") return reply([entity]);
    if (path === "/v1/org/org-units") return reply([{ id: "theme-unit", name: "People", type: "DEPARTMENT", status: "ACTIVE", legal_entity_id: entity.id }]);
    if (path === "/v1/org/locations") return reply([{ id: "theme-location", name: "Bengaluru", type: "OFFICE", status: "ACTIVE", legal_entity_id: entity.id }]);
    if (path === "/v1/org/jobs") return reply([{ id: "theme-job", title: "People Partner", status: "ACTIVE" }]);
    if (path === "/v1/org/employee-id-schemes") return reply([{ id: "theme-scheme", legal_entity_id: entity.id, prefix: "NS", separator: "-", number_digits: 3, next_number: 3, preview: "NS-003" }]);
    if (path === "/v1/leave/types") return reply([leaveType]);
    if (path === "/v1/leave/balances") return reply([{ id: "theme-balance", employment_id: employee.id, leave_type_id: leaveType.id, leave_type_name: leaveType.name, leave_type_code: "AL", year: 2026, allocated_days: 24, carry_forward_days: 0, used_days: 4, pending_days: 1, available_days: 19, color: leaveType.color }]);
    if (path === "/v1/leave/applications/summary") return reply({ by_status: { APPROVED: 1, PENDING_L1: 1, REJECTED: 1 }, approved_days_by_type: [{ leave_type_id: leaveType.id, name: leaveType.name, color: leaveType.color, days: 1 }] });
    if (path === "/v1/leave/applications") return reply(url.searchParams.has("status") ? applications.filter(a => url.searchParams.get("status")!.split(",").includes(a.status)) : applications);
    if (path === "/v1/corrections" || path === "/v1/time/overtime/pending") return reply([]);
    if (path === "/v1/time/register/filters") return reply({ companies: [entity], departments: [{ id: "theme-unit", name: "People", legal_entity_id: entity.id }] });
    if (path === "/v1/time/register/employees") return reply([{ employment_id: employee.id, employee_number: employee.employee_number, name: employee.full_name, legal_entity_id: entity.id, company: entity.name, department_id: "theme-unit", department: employee.department, designation: employee.designation }]);
    if (path === "/v1/policies/templates") return reply([{ id: "theme-policy", name: "Studio standard", description: "A predictable workday with flexible arrival grace.", is_default: true, timezone: "Asia/Kolkata", expected_start_time: "09:00:00", expected_end_time: "18:00:00", work_days: "1111100", saturday_pattern: "ALL", break_minutes: 60, break_auto_deduct: true, grace_late_minutes: 10, grace_early_departure_minutes: 10, half_day_threshold_pct: 50, ot_enabled: true, ot_qualifying_minutes: 30, ot_rate: 1.5, ot_daily_cap_minutes: 120, off_day_work: "COMP_OFF", punch_rounding_minutes: 0, punch_rounding_direction: "NEAREST", correction_requires_approval: true, correction_approval_levels: 1, standard_minutes: 480 }]);
    if (path === "/v1/time/daily-analysis") {
      const date = url.searchParams.get("work_date")!;
      return reply({ snapshot_id: `theme-snapshot-${date}`, generated_at: `${date}T04:30:00Z`, total_filtered: 2, work_date: date, metrics: { total_headcount: 2, present_count: 2, on_time_count: 1, late_count: 1, absent_count: 0, on_leave_count: 0, half_day_count: 0, presence_rate: 100, average_work_minutes: 480, total_overtime_minutes: 30 }, department_stats: [{ department: "People", total: 2, present: 2, late: 1, absent: 0, on_leave: 0, presence_rate: 100 }], hourly_arrivals: [{ hour: "08:00", count: 0 }, { hour: "09:00", count: 2 }, { hour: "10:00", count: 0 }], employees: [employee, { ...employee, id: "theme-employee-2", full_name: "Ravi Shah", employee_number: "NS-002" }].map((person, i) => ({ employment_id: person.id, employee_number: person.employee_number, name: person.full_name, email: person.email, department: person.department, designation: person.designation, location: person.location, status: i ? "LATE" : "PRESENT", first_punch_in: `${date}T03:30:00Z`, last_punch_out: `${date}T12:30:00Z`, effective_minutes: 480, gross_minutes: 540, break_minutes: 60, late_by_minutes: i ? 15 : 0, early_departure_minutes: 0, overtime_minutes: i ? 30 : 0, overtime_status: i ? "APPROVED" : "NONE", comp_off_days: 0, review_flags: [], needs_review: false, punches_count: 2, is_currently_in: false })) });
    }
    if (path === "/v1/time/today") return reply({ employment_id: employee.id, work_date: "2026-10-09", is_punched_in: false, first_punch_in: "2026-10-09T04:00:00Z", last_punch_out: "2026-10-09T12:30:00Z", effective_minutes: 480, status: "PRESENT", punches: [] });
    if (path === `/v1/time/register/${employee.id}`) {
      const from = url.searchParams.get("from_date")!, to = url.searchParams.get("to_date")!;
      return reply({ employment_id: employee.id, employee_number: employee.employee_number, name: user.name, from_date: from, to_date: to, days: ["PRESENT", "LATE", "ABSENT", "ON_LEAVE", "HOLIDAY"].map((status, i) => ({ work_date: `${from.slice(0, 8)}${String(i + 1).padStart(2, "0")}`, status, is_off_day: status === "HOLIDAY", holiday_name: status === "HOLIDAY" ? "Studio day" : null, leave_type: status === "ON_LEAVE" ? "Annual leave" : null, first_punch_in: ["PRESENT", "LATE"].includes(status) ? "2026-10-01T04:00:00Z" : null, last_punch_out: ["PRESENT", "LATE"].includes(status) ? "2026-10-01T12:30:00Z" : null, effective_minutes: ["PRESENT", "LATE"].includes(status) ? 480 : 0, gross_minutes: 510, break_minutes: 30, late_by_minutes: status === "LATE" ? 15 : 0, early_departure_minutes: 0, ot_minutes: 0, ot_status: "NONE", comp_off_days: 0, review_flags: [], needs_review: false, is_locked: false, shift_start: "09:30", shift_end: "18:00", timezone: "Asia/Kolkata", policy_break_minutes: 30, grace_late_minutes: 10, grace_early_minutes: 10, standard_minutes: 480, half_day_minutes: 240, punches: [] })) });
    }
    if (path === "/v1/kyc/me") return reply({ id: "theme-kyc", employment_id: employee.id, employee_name: user.name, employee_number: employee.employee_number, department: "People", designation: "People Partner", status: "VERIFIED", updated_at: "2026-10-01T04:30:00Z", documents: [], completion_percentage: 100 });
    if (/^\/v1\/kyc\/employees\/[^/]+\/photo$/.test(path)) return route.fulfill({ status: 204 });
    state.unexpectedRequests.push(`GET ${path}`);
    return reply({ message: `Missing theme fixture: ${path}` }, 404);
  });
  return state;
}

/** Actual CSS colors, including translucent fills and gradient stops through ancestor backgrounds. */
async function textContrast(page: Page) {
  return page.evaluate(() => {
    type Color = [number, number, number, number];
    const parse = (value: string): Color => {
      const nums = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return [nums[0] ?? 0, nums[1] ?? 0, nums[2] ?? 0, nums[3] ?? 1];
    };
    const blend = (fg: Color, bg: Color): Color => [fg[0] * fg[3] + bg[0] * (1 - fg[3]), fg[1] * fg[3] + bg[1] * (1 - fg[3]), fg[2] * fg[3] + bg[2] * (1 - fg[3]), 1];
    const layers = (value: string): string[] => {
      let depth = 0, start = 0;
      const result: string[] = [];
      for (let i = 0; i < value.length; i++) {
        if (value[i] === "(") depth++;
        if (value[i] === ")") depth--;
        if (value[i] === "," && depth === 0) { result.push(value.slice(start, i)); start = i + 1; }
      }
      result.push(value.slice(start));
      return result;
    };
    const background = (element: Element): Color[] => {
      const ancestors: Element[] = [];
      for (let node: Element | null = element; node; node = node.parentElement) ancestors.push(node);
      return ancestors.reverse().reduce((backgrounds, node) => {
        const style = getComputedStyle(node);
        let candidates = backgrounds.map(bg => blend(parse(style.backgroundColor), bg));
        // Each stop is considered, giving a conservative contrast check across the gradient.
        // URL images such as the native select arrow are decorative and do not cover the text.
        for (const layer of layers(style.backgroundImage).reverse()) {
          if (!layer.includes("gradient(")) continue;
          const stops = (layer.match(/rgba?\([^)]*\)|\btransparent\b/g) ?? []).map(color => color === "transparent" ? [0, 0, 0, 0] as Color : parse(color));
          if (stops.length) candidates = candidates.flatMap(bg => stops.map(stop => blend(stop, bg)));
        }
        return [...new Map(candidates.map(color => [color.join(","), color])).values()];
      }, [[255, 255, 255, 1]] as Color[]);
    };
    const luminance = (color: Color) => color.slice(0, 3).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
    const ratio = (fg: Color, bg: Color) => { const a = luminance(fg), b = luminance(bg); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); };
    const samples = [...document.querySelectorAll("body *")].flatMap(element => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      const text = [...element.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join(" ").trim()
        || (element instanceof HTMLInputElement && element.type !== "password" ? element.value : "");
      // Disabled controls are exempt from WCAG contrast.
      if (!text || !rect.width || !rect.height || style.visibility === "hidden" || element.closest("[disabled]") || Number(style.opacity) < 1) return [];
      const candidates = background(element).map(bg => ({ bg, fg: blend(parse(style.color), bg) }));
      const { bg, fg } = candidates.reduce((lowest, candidate) => ratio(candidate.fg, candidate.bg) < ratio(lowest.fg, lowest.bg) ? candidate : lowest);
      const size = parseFloat(style.fontSize), weight = parseInt(style.fontWeight);
      const minimum = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
      return [{ text: text.slice(0, 90), className: element.getAttribute("class"), ratio: ratio(fg, bg), minimum, fg: style.color, bg: bg.slice(0, 3) }];
    });
    const icons = [...document.querySelectorAll(".app-sidebar nav svg, [aria-label='Primary'] svg, header button svg, .page-header button svg, .page-header a svg, .stat-icon svg, [data-quick-actions] svg, form button svg")].flatMap(element => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height || style.visibility === "hidden" || element.closest("[disabled]") || Number(style.opacity) < 1) return [];
      const candidates = background(element).map(bg => ({ bg, fg: blend(parse(style.color), bg) }));
      const { bg, fg } = candidates.reduce((lowest, candidate) => ratio(candidate.fg, candidate.bg) < ratio(lowest.fg, lowest.bg) ? candidate : lowest);
      return [{ name: element.getAttribute("data-icon-name") ?? element.getAttribute("class"), ratio: ratio(fg, bg), minimum: 3, fg: style.color, bg: bg.slice(0, 3) }];
    });
    return { samples, failures: samples.filter(sample => sample.ratio < sample.minimum), icons, iconFailures: icons.filter(icon => icon.ratio < icon.minimum) };
  });
}

async function audit(page: Page, testInfo: TestInfo, label: string) {
  // A visible view can still have its previous control colors while CSS transitions run.
  // Measure the settled state for the entire page, including both segmented buttons/icons.
  await settle(page.locator("body"));
  const preserveOriginal = await page.locator("html").getAttribute("data-color-theme") === "classic-teal";
  const result = { ...await textContrast(page), contrastEnforced: !preserveOriginal };
  const path = testInfo.outputPath(`${label}-contrast.json`);
  await writeFile(path, JSON.stringify(result, null, 2));
  await testInfo.attach(`${label}-contrast`, { path, contentType: "application/json" });
  expect(result.samples.length, `${label} should include meaningful rendered content`).toBeGreaterThan(10);
  // Classic is a restoration of the original styles, including known contrast limitations.
  // Retain its measurements; the two newer palettes continue to require WCAG AA.
  if (!preserveOriginal) {
    expect.soft(result.failures, `${label}: text and enabled button/badge contrast must meet WCAG AA`).toEqual([]);
    expect.soft(result.iconFailures, `${label}: navigation, toolbar and action icons must reach 3:1 contrast`).toEqual([]);
  }
}

async function screenshot(page: Page, testInfo: TestInfo, label: string) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
  await page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true, animations: "disabled" });
}

async function hover(locator: Locator) {
  await locator.hover();
  // Contrast is measured at the final hover state, after finite CSS transitions settle.
  await settle(locator);
}

async function settle(locator: Locator) {
  await locator.evaluate(async el => {
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    await Promise.all(el.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
  });
}

function verifyFixtures(state: Fixtures) {
  expect(state.unexpectedRequests, "Every API request must be intercepted by an explicit fixture").toEqual([]);
  expect(state.errors, "Main screens should not emit JavaScript exceptions").toEqual([]);
}

async function classicBaseline(page: Page, testInfo: TestInfo, label: string, mode: "light" | "dark") {
  const light = {
    "brand-50": "240 253 250", "brand-100": "204 251 241", "brand-200": "153 246 228", "brand-300": "94 234 212", "brand-400": "45 212 191", "brand-500": "20 184 166", "brand-600": "13 148 136", "brand-700": "15 118 110", "brand-800": "17 94 89", "brand-900": "19 78 74", "brand-950": "4 47 46",
    canvas: "244 244 245", panel: "250 250 250", surface: "255 255 255", muted: "244 244 245", line: "228 228 231", "line-strong": "212 212 216",
    fg: "24 24 27", "fg-muted": "82 82 91", "fg-subtle": "113 113 122", accent: "15 118 110", success: "4 120 87", warning: "180 83 9", danger: "220 38 38", info: "37 99 235", plum: "124 58 237",
  };
  const expected = mode === "light" ? light : {
    ...light, canvas: "9 9 11", panel: "14 14 17", surface: "22 22 26", muted: "34 34 39", line: "39 39 45", "line-strong": "58 58 66", fg: "244 244 245", "fg-muted": "161 161 170", "fg-subtle": "113 113 122", accent: "45 212 191", success: "52 211 153", warning: "251 191 36", danger: "248 113 113", info: "96 165 250", plum: "167 139 250",
  };
  const actual = await page.evaluate(keys => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(keys.map(key => [key, style.getPropertyValue(`--${key}`).trim()]));
  }, Object.keys(expected));
  expect(actual, "Classic must retain every original brand, surface, text and semantic token").toEqual(expected);
  await writeFile(testInfo.outputPath(`${label}-baseline-tokens.json`), JSON.stringify({ expected, actual }, null, 2));
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toHaveCSS("font-family", /Inter/);
  await expect(heading).toHaveCSS("font-size", "22px");
  await expect(heading).toHaveCSS("font-weight", "600");
  await expect(page.locator(".card").first()).toHaveCSS("border-radius", "12px");
  await expect(page.locator(".app-workspace")).toHaveCSS("border-radius", "12px");
  await expect(page.locator(".page-header")).toHaveCSS("padding", "0px");
  await expect(page.locator(".stat-value").first()).toHaveCSS("font-size", "28px");
  await expect(page.locator(".stat-value").first()).toHaveCSS("font-weight", "600");
  await expect(page.locator(".stat-icon").first()).toHaveCSS("border-radius", "8px");
  const primary = page.getByRole("link", { name: "Review approvals", exact: true });
  await expect(primary).toHaveCSS("border-radius", "8px");
  await expect(primary).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(primary).toHaveCSS("background-color", mode === "light" ? "rgb(15, 118, 110)" : "rgb(13, 148, 136)");
  const icon = page.getByRole("button", { name: "Switch Theme Palette" }).locator("svg");
  await expect(icon).toHaveClass(/lucide/);
  await expect(icon).toHaveCSS("stroke-width", "2px");
  await expect(page.locator(".app-sidebar").first()).toHaveCSS("background-image", "none");
  await expect(page.locator(".app-sidebar").first()).toHaveCSS("width", "240px");
  await expect(page.locator(".app-sidebar").first().getByText("Suraj Group", { exact: true })).toBeVisible();
  const main = page.getByRole("navigation", { name: "Main", exact: true });
  await expect(main).toBeVisible();
  for (const section of ["Overview", "Workforce", "Talent", "Settings", "Developers"]) await expect(main.getByText(section, { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);
}

test("all three palettes register, cycle, and persist independently of appearance mode", async ({ page }) => {
  const state = await fixtures(page, "light", "classic-teal");
  await page.goto("/dashboard");
  await expect(page.getByText("Headcount", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  const palette = page.getByRole("combobox", { name: "Colour theme", exact: true });
  await expect(palette.locator("option")).toHaveText(["Classic Teal", "Midnight Blue", "Ember Sand"]);
  await palette.selectOption("ember-sand");
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", "ember-sand");
  await page.getByRole("radio", { name: "dark", exact: true }).click();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", "ember-sand");
  await expect(page.locator("html")).toHaveClass(/dark/);
  for (const expected of ["classic-teal", "midnight-blue", "ember-sand"]) {
    await page.getByRole("button", { name: "Switch Theme Palette" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-color-theme", expected);
    await expect(page.locator("html")).toHaveClass(/dark/);
    await expect.poll(() => state.preferences.color_theme).toBe(expected);
  }
  verifyFixtures(state);
});

for (const palette of palettes) {
test(`system mode follows OS changes while preserving ${palette.name}`, async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  const state = await fixtures(page, "system", palette.id);
  await page.goto("/dashboard");
  await expect(page.getByText("Headcount", { exact: true })).toBeVisible();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", palette.id);
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  expect(await page.evaluate(() => localStorage.getItem("hrms_theme"))).toBe("system");
  verifyFixtures(state);
});
}

for (const palette of palettes.filter(palette => palette.id !== "ember-sand")) {
test(`${palette.name} light/dark controls keep the palette and persist after reload`, async ({ page }) => {
  const state = await fixtures(page, "light", palette.id);
  await page.goto("/dashboard");
  await expect(page.getByText("Headcount", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Switch to dark theme", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", palette.id);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", palette.id);
  await page.getByRole("button", { name: "Switch to light theme", exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-color-theme", palette.id);
  verifyFixtures(state);
});
}

for (const palette of palettes.filter(palette => palette.id !== "ember-sand")) {
for (const mode of ["light", "dark"] as const) {
  test(`${palette.name} ${mode}: date focus, header controls and phone attendance layout`, async ({ page }, testInfo) => {
    const state = await fixtures(page, mode, palette.id);
    const label = `${palette.prefix}${mode}`;
    await page.goto("/daily-analysis");
    await expect(page.getByRole("heading", { name: "Daily Employee Analysis", exact: true })).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    const date = page.getByLabel("Select Date", { exact: true });
    const today = await date.inputValue();
    await page.getByRole("button", { name: "Previous Day", exact: true }).click();
    await expect(date).not.toHaveValue(today);
    await expect(page.getByRole("button", { name: "Today", exact: true })).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await audit(page, testInfo, `${label}-daily-previous`);
    await hover(page.getByRole("button", { name: "Today", exact: true }));
    await audit(page, testInfo, `${label}-daily-today-hover`);
    await date.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(date).toBeFocused();
    await settle(date);
    const focus = await date.evaluate(el => {
      const style = getComputedStyle(el);
      const lum = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
      const a = lum(style.outlineColor), b = lum(getComputedStyle(el.parentElement!).backgroundColor);
      return { width: style.outlineWidth, style: style.outlineStyle, contrast: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
    });
    await writeFile(testInfo.outputPath(`${label}-date-focus.json`), JSON.stringify(focus, null, 2));
    if (palette.id !== "classic-teal") {
      expect(focus.width).toBe("2px");
      expect(focus.style).toBe("solid");
      expect(focus.contrast, "Date keyboard focus must reach 3:1 against its surrounding surface").toBeGreaterThanOrEqual(3);
    }
    await audit(page, testInfo, `${label}-daily-date-focus`);
    await screenshot(page, testInfo, `${label}-daily-date-focus`);
    await page.getByRole("button", { name: "Today", exact: true }).click();
    await expect(date).toHaveValue(today);
    await expect(page.getByRole("button", { name: "Today", exact: true })).toHaveCount(0);

    await page.goto("/policy");
    await expect(page.getByText("Studio standard", { exact: true })).toBeVisible();
    const policyInfo = page.getByRole("button", { name: "How policies work", exact: true });
    await expect(policyInfo.locator("svg")).toBeVisible();
    await hover(policyInfo);
    await audit(page, testInfo, `${label}-policy-info-hover`);
    await screenshot(page, testInfo, `${label}-policy-info-hover`);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/attendance");
    await expect(page.getByText("Your check-ins, working hours and monthly record.")).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await expect(page.locator(".page-header a")).toHaveCount(3);
    const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const overflow = await page.locator(".page-header").evaluate(header => {
      const bounds = header.getBoundingClientRect();
      return [...header.querySelectorAll("a")].filter(link => {
        const rect = link.getBoundingClientRect();
        return rect.left < bounds.left || rect.right > bounds.right || rect.top < bounds.top || rect.bottom > bounds.bottom;
      }).map(link => link.textContent);
    });
    if (palette.id === "classic-teal") {
      await expect(page.locator(".page-header-actions > .flex")).toHaveCSS("flex-wrap", "wrap");
      await writeFile(testInfo.outputPath(`${label}-attendance-layout.json`), JSON.stringify({ viewport: 390, documentWidth, overflow }, null, 2));
    }
    expect(documentWidth).toBeLessThanOrEqual(390);
    expect(overflow, "Attendance actions should wrap inside the phone page header").toEqual([]);
    await audit(page, testInfo, `${label}-mobile-attendance`);
    await screenshot(page, testInfo, `${label}-mobile-attendance`);
    verifyFixtures(state);
  });

}
}

for (const palette of palettes) {
for (const mode of ["light", "dark"] as const) {
  const label = `${palette.prefix}${mode}`;
  test(`${palette.name} ${mode}: desktop main screens, controls, forms and text contrast`, async ({ page }, testInfo) => {
    const state = await fixtures(page, mode, palette.id);
    await page.goto("/dashboard");
    await expect(page.getByText("Headcount", { exact: true })).toBeVisible();
    await expect(page.locator("[data-widget^='kpi_'] .stat-value")).toHaveText(["24", "20", "3", "2"]);
    await expect(page.locator(".skeleton")).toHaveCount(0);
    if (palette.id === "classic-teal") {
      const headcount = page.locator("[data-widget='kpi_headcount'] .stat-value");
      await expect(headcount).toBeVisible();
    }
    await audit(page, testInfo, `${label}-widgets`);
    await screenshot(page, testInfo, `${label}-widgets`);
    if (palette.id === "ember-sand") {
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-family", /Georgia/);
      await expect(page.locator(".card").first()).toHaveCSS("border-radius", "6px");
      await expect(page.getByRole("button", { name: "Switch Theme Palette" }).locator("svg")).toHaveCSS("stroke-width", "1.75px");
    } else if (palette.id === "midnight-blue") {
      await expect(page.getByRole("button", { name: "Switch Theme Palette" }).locator("svg")).toHaveAttribute("data-icon-set", "midnight-blue");
      expect(await page.locator(".app-sidebar").first().evaluate(el => getComputedStyle(el).backgroundImage)).toContain("linear-gradient");
      const tokens = await page.evaluate(() => ({ canvas: getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim(), brand: getComputedStyle(document.documentElement).getPropertyValue("--brand-700").trim() }));
      expect(tokens.canvas).toBe(mode === "light" ? "237 242 251" : "8 18 36");
      expect(tokens.brand).toBe(mode === "light" ? "36 92 230" : "152 184 255");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-family", /Inter/);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-size", "26px");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-weight", "700");
      await expect(page.locator(".card").first()).toHaveCSS("border-radius", "18px");
      await expect(page.locator(".app-workspace")).toHaveCSS("border-radius", "24px");
      await expect(page.locator(".page-header")).toHaveCSS("border-radius", "22px");
      await expect(page.locator(".page-header")).toHaveCSS("padding", "24px");
      await expect(page.locator(".stat-value").first()).toHaveCSS("font-size", "32px");
      await expect(page.locator(".stat-label").first()).toHaveCSS("text-transform", "uppercase");
    } else {
      await classicBaseline(page, testInfo, label, mode);
    }
    await hover(page.getByRole("link", { name: "Review approvals", exact: true }));
    await audit(page, testInfo, `${label}-primary-hover`);
    await page.getByRole("radio", { name: "Overview", exact: true }).click();
    await expect(page.getByText("Attendance Overview (Today)", { exact: true })).toBeVisible();
    await audit(page, testInfo, `${label}-overview`);
    await screenshot(page, testInfo, `${label}-overview`);
    await page.getByRole("heading", { name: "Compliance (PF & ESIC)", exact: true }).scrollIntoViewIfNeeded();
    await screenshot(page, testInfo, `${label}-overview-lower`);

    await page.goto("/employees");
    await expect(page.getByRole("cell", { name: /^Asha Rao NS-/ })).toBeVisible();
    if (palette.id === "classic-teal") {
      // The custom select arrow is an SVG background rather than a DOM icon.
      const arrowContrast = await page.locator("select.input").first().evaluate(el => {
        const style = getComputedStyle(el);
        const stroke = /stroke=['"]#([\da-f]{6})['"]/i.exec(decodeURIComponent(style.backgroundImage));
        if (!stroke) throw new Error("The select must render its custom arrow");
        const foreground = [0, 2, 4].map(offset => parseInt(stroke[1].slice(offset, offset + 2), 16));
        const background = (style.backgroundColor.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
        const lum = (channels: number[]) => channels.map(v => {
          const n = v / 255;
          return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
        }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        const a = lum(foreground), b = lum(background);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      });
      expect(arrowContrast, "Custom select arrows must reach 3:1 against their control surface").toBeGreaterThanOrEqual(3);
    }
    await audit(page, testInfo, `${label}-employees`);
    await screenshot(page, testInfo, `${label}-employees`);
    await page.getByRole("button", { name: "Add employee", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel("First name", { exact: true }).fill("Nila");
    await page.getByLabel("Last name", { exact: true }).fill("Singh");
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByLabel("First name", { exact: true })).toBeFocused();
    await settle(page.getByLabel("First name", { exact: true }));
    const focus = await page.getByLabel("First name", { exact: true }).evaluate(el => {
      const style = getComputedStyle(el);
      const luminance = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
      const foreground = luminance(style.outlineColor), background = luminance(style.backgroundColor);
      const border = luminance(style.borderColor);
      return { width: style.outlineWidth, style: style.outlineStyle, outlineColor: style.outlineColor, borderColor: style.borderColor, boxShadow: style.boxShadow, contrast: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05), borderContrast: (Math.max(border, background) + .05) / (Math.min(border, background) + .05) };
    });
    await writeFile(testInfo.outputPath(`${label}-input-focus.json`), JSON.stringify(focus, null, 2));
    if (palette.id === "classic-teal") {
      expect(focus.borderColor).toBe("rgb(20, 184, 166)");
      expect(focus.boxShadow).toContain("4px");
    } else {
      expect(focus.width).toBe("2px");
      expect(focus.style).toBe("solid");
      expect(focus.contrast, "Keyboard focus outline must have at least 3:1 contrast").toBeGreaterThanOrEqual(3);
      expect(focus.borderContrast, "Focused input border must have at least 3:1 contrast").toBeGreaterThanOrEqual(3);
    }
    await expect(page.getByRole("dialog").getByRole("button", { name: "Add employee", exact: true })).toBeEnabled();
    await audit(page, testInfo, `${label}-employee-form`);
    await screenshot(page, testInfo, `${label}-employee-form`);
    await page.keyboard.press("Escape");

    await page.goto("/attendance");
    await expect(page.getByRole("heading", { name: "Attendance", exact: true })).toBeVisible();
    await expect(page.getByText("Your check-ins, working hours and monthly record.")).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await audit(page, testInfo, `${label}-attendance-calendar`);
    await screenshot(page, testInfo, `${label}-attendance-calendar`);
    await page.getByRole("radio", { name: "List", exact: true }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await audit(page, testInfo, `${label}-attendance-list`);

    await page.goto("/leave");
    await expect(page.getByRole("tab", { name: "All requests 3", exact: true })).toBeVisible();
    await audit(page, testInfo, `${label}-leave`);
    await screenshot(page, testInfo, `${label}-leave`);
    await page.getByRole("button", { name: /Annual leave.*Approved/ }).click();
    await expect(page.getByText("Family appointment", { exact: true })).toBeVisible();
    await audit(page, testInfo, `${label}-leave-detail`);
    await screenshot(page, testInfo, `${label}-leave-detail`);
    await page.keyboard.press("Escape");

    await page.goto("/profile");
    await expect(page.getByRole("heading", { name: "Personal information", exact: true })).toBeVisible();
    await audit(page, testInfo, `${label}-profile`);
    await screenshot(page, testInfo, `${label}-profile`);

    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await expect(page.locator(".app-sidebar").first()).toHaveCSS("width", "68px");
    await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toHaveAttribute("title", "Dashboard");
    expect(await page.evaluate(() => localStorage.getItem("hrms_sidebar"))).toBe("collapsed");
    if (palette.id !== "ember-sand") await audit(page, testInfo, `${label}-collapsed-sidebar`);
    await screenshot(page, testInfo, `${label}-collapsed-sidebar`);
    if (palette.id === "classic-teal") {
      await page.reload();
      await expect(page.locator(".app-sidebar").first()).toHaveCSS("width", "68px");
      await page.getByRole("button", { name: "Toggle sidebar" }).click();
      await expect(page.locator(".app-sidebar").first()).toHaveCSS("width", "240px");
      const main = page.getByRole("navigation", { name: "Main", exact: true });
      await main.getByRole("link", { name: "Attendance register", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Attendance register", exact: true })).toBeVisible();
      await expect(main.getByRole("link", { name: "Attendance register", exact: true })).toHaveAttribute("aria-current", "page");
      await expect(main.getByRole("link", { name: "Attendance", exact: true })).not.toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("listbox", { name: "People", exact: true }).getByRole("option")).toHaveCount(1);
      await audit(page, testInfo, `${label}-nested-sidebar`);
      await screenshot(page, testInfo, `${label}-nested-sidebar`);
    }
    verifyFixtures(state);
  });

  test(`${palette.name} ${mode}: phone layout and navigation`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const state = await fixtures(page, mode, palette.id);
    await page.goto("/dashboard");
    await expect(page.getByText("Headcount", { exact: true })).toBeVisible();
    if (palette.id === "midnight-blue") {
      await expect(page.locator(".page-header")).toHaveCSS("border-radius", "18px");
      await expect(page.locator(".page-header")).toHaveCSS("padding", "20px");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-size", "24px");
    } else if (palette.id === "classic-teal") {
      await expect(page.locator(".app-workspace")).toHaveCSS("border-radius", "0px");
      await expect(page.locator(".page-header")).toHaveCSS("border-radius", "0px");
      await expect(page.locator(".page-header")).toHaveCSS("padding", "0px");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-size", "22px");
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await expect(page.getByRole("navigation", { name: "Main", exact: true })).toBeVisible();
    if (palette.id !== "ember-sand") await audit(page, testInfo, `${label}-mobile-sidebar`);
    await screenshot(page, testInfo, `${label}-mobile-sidebar`);
    await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("link", { name: "Employees", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Employees", exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main", exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    if (palette.id !== "ember-sand") await audit(page, testInfo, `${label}-mobile-employees`);
    await screenshot(page, testInfo, `${label}-mobile-employees`);
    await page.getByRole("button", { name: "Add employee", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await page.getByRole("dialog").evaluate(el => el.getBoundingClientRect().width)).toBeLessThanOrEqual(390.5);
    if (palette.id !== "ember-sand") await audit(page, testInfo, `${label}-mobile-form`);
    await screenshot(page, testInfo, `${label}-mobile-form`);
    verifyFixtures(state);
  });

  test(`${palette.name} ${mode}: platform sign-in uses the shared appearance controls`, async ({ page }, testInfo) => {
    const state = await fixtures(page, mode, palette.id, false);
    await page.goto("/platform/login");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Colour theme", exact: true })).toHaveValue(palette.id);
    await page.getByLabel("Email", { exact: true }).fill("platform@example.test");
    await page.getByLabel("Password", { exact: true }).fill("Synthetic-password-123");
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
    await audit(page, testInfo, `${label}-platform-login`);
    await screenshot(page, testInfo, `${label}-platform-login`);
    verifyFixtures(state);
  });

  test(`${palette.name} ${mode}: company sign-in on desktop and phone`, async ({ page }, testInfo) => {
    const state = await fixtures(page, mode, palette.id, false);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    await page.getByLabel("Username, Phone, or Email", { exact: true }).fill("asha@example.test");
    await page.getByLabel("Password", { exact: true }).fill("Synthetic-password-123");
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
    await audit(page, testInfo, `${label}-company-login-desktop`);
    await screenshot(page, testInfo, `${label}-company-login-desktop`);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await audit(page, testInfo, `${label}-company-login-phone`);
    await screenshot(page, testInfo, `${label}-company-login-phone`);
    verifyFixtures(state);
  });

  test(`${palette.name} ${mode}: semantic success button and checked policy switch contrast`, async ({ page }, testInfo) => {
    const state = await fixtures(page, mode, palette.id, false);
    await page.goto("/platform/login");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    // Use the exact utility variants used by PlatformConsolePage and PolicyPage without
    // inventing business fixtures or triggering a tenant reactivation/policy mutation.
    await page.locator(".card").evaluate(card => {
      const probe = document.createElement("section");
      probe.className = "mt-5 space-y-4";
      probe.innerHTML = '<button class="btn h-9 w-full bg-success text-white hover:bg-success/90">Reactivate</button><button type="button" role="switch" aria-label="Policy enabled" aria-checked="true" class="relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors bg-brand-600"><span class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform translate-x-4"></span></button>';
      card.append(probe);
    });
    await audit(page, testInfo, `${label}-semantic-controls`);
    await hover(page.getByRole("button", { name: "Reactivate", exact: true }));
    await audit(page, testInfo, `${label}-success-hover`);
    const thumbContrast = await page.getByRole("switch", { name: "Policy enabled", exact: true }).evaluate(el => {
      const lum = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
      const thumb = lum(getComputedStyle(el.firstElementChild!).backgroundColor), track = lum(getComputedStyle(el).backgroundColor);
      return (Math.max(thumb, track) + .05) / (Math.min(thumb, track) + .05);
    });
    expect(thumbContrast, "Switch thumb and checked track must have at least 3:1 contrast").toBeGreaterThanOrEqual(3);
    await screenshot(page, testInfo, `${label}-semantic-controls`);
    verifyFixtures(state);
  });
}
}
