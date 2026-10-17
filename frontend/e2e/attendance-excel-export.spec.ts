/** Existing saved attendance reports export a full Excel register using isolated synthetic data. */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";

const api = "http://127.0.0.1:18015";
const password = "Synthetic-report-password-123";
const range = "from_date=2026-09-01&to_date=2026-09-30";

async function call(request: APIRequestContext, method: string, path: string, data?: unknown, token?: string) {
  const response = await request.fetch(api + path, {
    method, data, headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Username, Phone, or Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/dashboard/);
}

async function reportData(request: APIRequestContext) {
  const tag = randomUUID().slice(0, 8);
  const email = `attendance-report-${tag}@example.com`;
  const admin = await call(request, "POST", "/v1/auth/register-company", {
    company_name: `Report Group ${tag}`, admin_email: email, admin_password: password,
  });
  const token = admin.access_token;
  const first = admin.user.legal_entities[0];
  const second = await call(request, "POST", "/v1/org/legal-entities", { name: `Report Branch ${tag}` }, token);
  const job = await call(request, "POST", "/v1/org/jobs", { title: "Executive" }, token);
  const locations = new Map<string, string>();
  for (const company of [first, second]) {
    const location = await call(request, "POST", "/v1/org/locations", {
      name: "Report office", type: "OFFICE", legal_entity_id: company.id,
    }, token);
    locations.set(company.id, location.id);
  }
  const department = (name: string, company: string) => call(request, "POST", "/v1/org/org-units", {
    name, type: "DEPARTMENT", legal_entity_id: company, effective_from: "2020-01-01",
  }, token);
  const stores = await department("Stores", first.id);
  const accounts = await department("Accounts", first.id);
  const branchStores = await department("Stores", second.id);
  async function employee(firstName: string, number: string, company: string, unit: string) {
    const person = await call(request, "POST", "/v1/persons", {
      legal_first_name: firstName, legal_last_name: `Report${tag}`,
    }, token);
    const emp = await call(request, "POST", "/v1/employees", {
      person_id: person.id, legal_entity_id: company, employee_number: number, hire_date: "2020-01-01",
    }, token);
    await call(request, "POST", "/v1/personnel-actions", {
      employment_id: emp.id, type: "HIRE", effective_date: "2020-01-01",
      changes: { org_unit_id: unit, job_id: job.id, location_id: locations.get(company) },
    }, token);
    return { ...emp, name: `${firstName} Report${tag}` };
  }
  const meera = await employee("Meera", `SUM-MEERA-${tag}`, first.id, stores.id);
  const ravi = await employee("Ravi", `SUM-RAVI-${tag}`, first.id, accounts.id);
  const nila = await employee("Nila", `SUM-NILA-${tag}`, second.id, branchStores.id);

  const policy = await call(request, "POST", "/v1/policies/templates", {
    name: "Report shift", timezone: "Asia/Kolkata", expected_start_time: "09:30:00",
    expected_end_time: "18:30:00", work_days: "1111100", break_minutes: 60,
    break_auto_deduct: true, grace_late_minutes: 15, grace_early_departure_minutes: 15,
  }, token);
  for (const company of [first, second]) {
    await call(request, "POST", "/v1/policies/assignments", {
      legal_entity_id: company.id, policy_template_id: policy.id, effective_from: "2020-01-01",
    }, token);
  }
  for (const [day, checkIn] of [["2026-09-01", "09:30"], ["2026-09-03", "09:55"]]) {
    await call(request, "PUT", `/v1/time/register/${meera.id}/${day}`, {
      punches: [
        { punch_type: "IN", punched_at: `${day}T${checkIn}:00+05:30` },
        { punch_type: "BREAK_START", punched_at: `${day}T13:00:00+05:30` },
        { punch_type: "BREAK_END", punched_at: `${day}T14:00:00+05:30` },
        { punch_type: "OUT", punched_at: `${day}T18:30:00+05:30` },
      ], reason: "Synthetic report fixture",
    }, token);
  }
  const holiday = await call(request, "POST", "/v1/time/holiday-calendars/library", {
    holiday_date: "2026-09-02", name: "Report festival",
  }, token);
  await call(request, "POST", "/v1/time/holiday-calendars", {
    name: "Report holidays", year: 2026, holiday_ids: [holiday.id], assign_company: true,
  }, token);

  const paid = await call(request, "POST", "/v1/leave/types", {
    name: "Privilege leave", code: "PL", days_per_year: 12, is_paid: true,
    requires_approval: false, accrual_enabled: false,
  }, token);
  const unpaid = await call(request, "POST", "/v1/leave/types", {
    name: "Leave without pay", code: "LWP", days_per_year: 0, is_paid: false,
    requires_approval: false,
  }, token);
  await call(request, "POST", "/v1/leave/balances/adjust", {
    employment_id: meera.id, leave_type_id: paid.id, quantity: 10, effective_date: "2026-09-01",
    kind: "OPENING", reason: "Synthetic report opening",
  }, token);
  for (const [date, leaveType, halfDay] of [
    ["2026-09-07", paid.id, "NONE"],
    ["2026-09-08", paid.id, "FIRST_HALF"],
    ["2026-09-09", unpaid.id, "NONE"],
  ]) {
    const app = await call(request, "POST", `/v1/leave/applications?employment_id=${meera.id}`, {
      leave_type_id: leaveType, from_date: date, to_date: date, half_day_option: halfDay,
      reason: "Synthetic report leave",
    }, token);
    const submitted = await call(request, "POST", `/v1/leave/applications/${app.id}/submit`, {}, token);
    expect(submitted.status).toBe("APPROVED");
  }
  return { email, token, first, second, stores, accounts, branchStores, meera, ravi, nila };
}

interface Workbook {
  names: string[];
  sheets: Record<string, { cells: Record<string, string | number | null>; dateRows: number; freeze: string | null }>;
  tables: { ref: string; filter: string; columns: number }[];
  charts: number;
  text: string;
}

function inspectWorkbook(path: string): Workbook {
  // Inspect the real downloaded package with the already required backend Python runtime.
  return JSON.parse(execFileSync(process.env.HRMS_E2E_PYTHON || "python", ["-c", [
    "import sys, json, zipfile, posixpath, xml.etree.ElementTree as ET",
    "ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}",
    "r='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'",
    "result={'names':[], 'sheets':{}, 'tables':[], 'charts':0, 'text':''}",
    "with zipfile.ZipFile(sys.argv[1]) as z:",
    "    roots={name:ET.fromstring(z.read(name)) for name in z.namelist() if name.endswith(('.xml','.rels'))}",
    "    rels={item.get('Id'):item.get('Target') for item in roots['xl/_rels/workbook.xml.rels']}",
    "    strings=[''.join(item.itertext()) for item in roots.get('xl/sharedStrings.xml', [])]",
    "    for sheet in roots['xl/workbook.xml'].find('m:sheets', ns):",
    "        name=sheet.get('name'); target=posixpath.normpath('xl/'+rels[sheet.get(r)])",
    "        root=roots[target]; cells={}",
    "        for cell in root.findall('.//m:c', ns):",
    "            value=cell.find('m:v', ns)",
    "            if cell.get('t')=='inlineStr': value=''.join(cell.find('m:is', ns).itertext())",
    "            elif value is None: value=None",
    "            elif cell.get('t')=='s': value=strings[int(value.text)]",
    "            else: value=float(value.text)",
    "            cells[cell.get('r')]=value",
    "        pane=root.find('m:sheetViews/m:sheetView/m:pane', ns)",
    "        result['names'].append(name)",
    "        result['sheets'][name]={'cells':cells,'dateRows':sum(isinstance(v,(float,int)) and 46266<=v<=46295 for k,v in cells.items() if k.startswith('A')), 'freeze':None if pane is None else pane.get('topLeftCell')}",
    "    for name,root in roots.items():",
    "        if name.startswith('xl/tables/') and name.endswith('.xml'):",
    "            result['tables'].append({'ref':root.get('ref'),'filter':root.find('m:autoFilter', ns).get('ref'),'columns':len(root.find('m:tableColumns', ns))})",
    "        if name.startswith('xl/charts/chart') and name.endswith('.xml'): result['charts']+=1",
    "    result['text']=' '.join(' '.join(root.itertext()) for name,root in roots.items() if name.startswith(('xl/worksheets/','xl/sharedStrings','xl/charts/')))",
    "print(json.dumps(result))",
  ].join("\n"), path], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
}

test("an existing saved attendance report exports the complete Excel register without changing source records", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const s = await reportData(request);
  const registerPath = `/v1/time/register/${s.meera.id}?${range}`;
  const before = await call(request, "GET", registerPath, undefined, s.token);
  const ledgerPath = `/v1/leave/ledger?employment_id=${s.meera.id}`;
  const applicationsPath = `/v1/leave/applications?employment_id=${s.meera.id}`;
  const ledgerBefore = await call(request, "GET", ledgerPath, undefined, s.token);
  const applicationsBefore = await call(request, "GET", applicationsPath, undefined, s.token);
  const reports = await call(request, "GET", "/v1/reports?owner_type=HR", undefined, s.token);
  const report = reports.find((item: { name: string }) => item.name === "Monthly Attendance Summary");
  expect(report).toBeTruthy();
  const filters = [
    { field: "work_date", op: "gte", value: "2026-09-01" },
    { field: "work_date", op: "lte", value: "2026-09-30" },
  ];
  // The Excel export uses the chosen population and period, independently of a truncated screen result.
  const limited = await call(request, "POST", `/v1/reports/${report.id}/run`, { filters, limit: 1 }, s.token);
  expect(limited.rows).toHaveLength(1);
  expect(limited.truncated).toBe(true);
  const unbounded = await request.post(`${api}/v1/reports/${report.id}/export-attendance`, {
    data: { filters: [] }, headers: { Authorization: `Bearer ${s.token}` },
  });
  expect(unbounded.status()).toBe(422);

  await signIn(page, s.email);
  await page.getByRole("link", { name: "Reports", exact: true }).first().click();
  await expect(page.getByRole("tab", { name: "Attendance & leave" })).toHaveCount(0);
  await page.locator(".card").filter({ has: page.getByText("Monthly Attendance Summary", { exact: true }) })
    .getByRole("button", { name: "Run", exact: true }).click();
  const panel = page.locator(".card").filter({
    has: page.getByRole("heading", { name: "Run Monthly Attendance Summary", exact: true }),
  });
  await expect(panel).toBeVisible();
  await expect(panel.getByLabel("Field", { exact: true }).nth(0)).toHaveValue("work_date");
  await expect(panel.getByLabel("Operator", { exact: true }).nth(0)).toHaveValue("gte");
  await expect(panel.getByLabel("Operator", { exact: true }).nth(1)).toHaveValue("lte");
  await panel.getByLabel("Value", { exact: true }).nth(0).fill("2026-09-01");
  await panel.getByLabel("Value", { exact: true }).nth(1).fill("2026-09-30");
  let screenRuns = 0;
  page.on("request", (event) => { if (event.method() === "POST" && event.url().endsWith(`/${report.id}/run`)) screenRuns++; });
  const exportRequest = page.waitForRequest((event) => event.url().endsWith(`/${report.id}/export-attendance`));
  const downloadPromise = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Export Excel", exact: true }).click();
  expect((await exportRequest).postDataJSON()).toEqual({ filters });
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("AttendanceReport_2026-09-01_to_2026-09-30.xlsx");
  expect(await download.failure()).toBeNull();
  const file = (await download.path())!;
  expect((await readFile(file)).subarray(0, 2).toString()).toBe("PK");
  const workbook = inspectWorkbook(file);
  expect(workbook.names.slice(0, 2)).toEqual(["Overview", "Employee Summary"]);
  expect(workbook.names.slice(2).sort()).toEqual([s.first.name, s.second.name].sort());
  expect(workbook.charts).toBe(1);
  expect(workbook.tables).toEqual([{ ref: "A5:R8", filter: "A5:R8", columns: 18 }]);
  expect(workbook.sheets["Employee Summary"].freeze).toBe("C6");
  for (const name of [s.meera.name, s.ravi.name, s.nila.name, "Report festival", "Privilege leave"]) {
    expect(workbook.text).toContain(name);
  }
  // All 90 calendar rows are included, even for employees without materialized attendance days.
  expect(workbook.sheets[s.first.name].dateRows).toBe(60);
  expect(workbook.sheets[s.second.name].dateRows).toBe(30);
  const cells = workbook.sheets["Employee Summary"].cells;
  const employeeRow = Object.entries(cells).find(([address, value]) => /^B\d+$/.test(address) && value === s.meera.name)![0].slice(1);
  expect(cells[`C${employeeRow}`]).toBe(s.meera.employee_number);
  for (const [column, value] of Object.entries({
    E: 12.5, F: 2, G: 16.5, H: 1, I: 1, J: 1.5, K: 1, L: 0, M: 8, N: 1, O: 10, P: 1.5, Q: 8.5,
  })) {
    expect(cells[`${column}${employeeRow}`], `Preserved source metric ${column}`).toBe(value);
  }
  expect(cells[`R${employeeRow}`]).toBeCloseTo(7.7917 / 24, 8);
  const noLedgerRow = Object.entries(cells).find(([address, value]) => /^B\d+$/.test(address) && value === s.ravi.name)![0].slice(1);
  expect(cells[`O${noLedgerRow}`]).toBeNull();
  expect(screenRuns).toBe(0);
  await page.screenshot({ path: "/tmp/hrms-attendance-excel-export.png" });

  // Reuse the same existing filter controls to export one employee's complete month.
  await panel.getByRole("button", { name: "Add filter", exact: true }).click();
  await panel.getByLabel("Field", { exact: true }).nth(2).selectOption("employment_id");
  await panel.getByLabel("Value", { exact: true }).nth(2).fill(s.meera.id);
  const filteredDownloadPromise = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Export Excel", exact: true }).click();
  const filteredDownload = await filteredDownloadPromise;
  expect(await filteredDownload.failure()).toBeNull();
  const filtered = inspectWorkbook((await filteredDownload.path())!);
  expect(filtered.names).toEqual(["Overview", "Employee Summary", s.first.name]);
  expect(filtered.tables).toEqual([{ ref: "A5:R6", filter: "A5:R6", columns: 18 }]);
  expect(filtered.sheets[s.first.name].dateRows).toBe(30);
  expect(filtered.text).toContain(s.meera.name);
  expect(filtered.text).not.toContain(s.ravi.name);
  expect(filtered.text).not.toContain(s.nila.name);
  expect(screenRuns).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel.getByRole("button", { name: "Export Excel", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  expect(await call(request, "GET", registerPath, undefined, s.token)).toEqual(before);
  expect(await call(request, "GET", ledgerPath, undefined, s.token)).toEqual(ledgerBefore);
  expect(await call(request, "GET", applicationsPath, undefined, s.token)).toEqual(applicationsBefore);
});

