/** Synthetic appearance fixtures copied without changing the existing theme suite. */
import type { Page } from "@playwright/test";

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

export async function appearanceFixtures(page: Page, mode: "light" | "dark" | "system" = "light", colorTheme = "midnight-blue", authenticated = true): Promise<Fixtures> {
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
    if (path === "/v1/time/register/employees") return reply([{ employment_id: employee.id, employee_number: employee.employee_number, name: employee.full_name, department: employee.department, designation: employee.designation }]);
    if (path === "/v1/time/holiday-calendars/library") return reply([{ id: "theme-holiday", holiday_date: `${url.searchParams.get("year") ?? "2026"}-11-01`, name: "Studio day", holiday_type: null, calendars: [] }]);
    if (path === "/v1/time/holiday-calendars") return reply([]);
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
    state.unexpectedRequests.push(`GET ${path}`);
    return reply({ message: `Missing theme fixture: ${path}` }, 404);
  });
  return state;
}

