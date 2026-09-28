import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { differenceInMonths, format } from "date-fns";
import {
  Download, Plus, Search, X, ArrowUpDown, ArrowUp, ArrowDown, ChevronLeft, ChevronRight, Users,
  Mail, MapPin, Briefcase, Building2, CalendarDays, Hash, UserRound, SearchX, ArrowLeftRight,
  ShieldCheck, Landmark,
} from "lucide-react";
import { peopleApi, personnelActionsApi } from "../api/people";
import type { Employment } from "../api/people";
import { orgApi } from "../api/org";
import { onboardingApi } from "../api/onboarding";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { KycSection } from "../components/kyc/KycSection";

interface Row {
  id: string;
  employeeNumber: string;
  name: string;
  email?: string;
  company?: string;
  department?: string;
  designation?: string;
  location?: string;
  hireDate: string;
  type?: string;
  state: string;
  manager?: string;
  stage?: string;
  // Raw ids for the transfer form.
  legalEntityId?: string;
  orgUnitId?: string;
  jobId?: string;
  locationId?: string;
  managerEmploymentId?: string;
}

type StatusTab = "ALL" | "ACTIVE" | "PROBATION" | "ON_NOTICE" | "INACTIVE";
type SortKey = "name" | "hireDate";

const bucket = (s: string): StatusTab =>
  s === "ACTIVE" || s === "PROBATION" || s === "ON_NOTICE" ? s : "INACTIVE";

function tenure(hireDate: string) {
  const m = Math.max(differenceInMonths(new Date(), new Date(hireDate)), 0);
  const y = Math.floor(m / 12);
  return y ? `${y}y ${m % 12}m` : `${m}m`;
}

function toRow(e: Employment, name: string, company?: string): Row {
  return {
    id: e.id,
    company,
    employeeNumber: e.employee_number,
    name,
    hireDate: e.hire_date,
    state: e.employment_state,
    stage: e.service_stage ?? undefined,
    department: e.department ?? undefined,
    designation: e.designation ?? undefined,
    location: e.location ?? undefined,
    manager: e.manager_name ?? undefined,
    legalEntityId: e.legal_entity_id,
    orgUnitId: e.org_unit_id ?? undefined,
    jobId: e.job_id ?? undefined,
    locationId: e.location_id ?? undefined,
    managerEmploymentId: e.manager_employment_id ?? undefined,
  };
}

function downloadCsv(rows: Row[]) {
  const cols: [string, (r: Row) => string][] = [
    ["Employee ID", (r) => r.employeeNumber],
    ["Name", (r) => r.name],
    ["Email", (r) => r.email ?? ""],
    ["Company", (r) => r.company ?? ""],
    ["Department", (r) => r.department ?? ""],
    ["Designation", (r) => r.designation ?? ""],
    ["Location", (r) => r.location ?? ""],
    ["Date of joining", (r) => r.hireDate],
    ["Type", (r) => r.type ?? ""],
    ["Status", (r) => r.state],
  ];
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const csv = [cols.map(([h]) => h), ...rows.map((r) => cols.map(([, f]) => esc(f(r))))].map((l) => l.join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `employees-${format(new Date(), "yyyy-MM-dd")}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function EmployeePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<StatusTab>("ALL");
  const [company, setCompany] = useState("");
  const [dept, setDept] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [perPage, setPerPage] = useState(10);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<Row | null>(null);
  const [adding, setAdding] = useState(false);
  const [transferring, setTransferring] = useState<Row | null>(null);

  const canPlace = !!user && (user.permissions.includes("people.write") || user.permissions.includes("*"));

  const search = params.get("q") ?? "";
  const setSearch = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("q", v); else next.delete("q");
    setParams(next, { replace: true });
  };

  const filterKey = `${status}|${company}|${dept}|${type}|${search}|${perPage}`;
  const [pageState, setPageState] = useState({ n: 1, key: filterKey });
  const page = pageState.key === filterKey ? pageState.n : 1;
  const setPage = (n: number) => setPageState({ n, key: filterKey });

  const emps = useQuery({ queryKey: ["employees"], queryFn: () => peopleApi.listAllEmployees() });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => peopleApi.listAllPersons(), enabled: !!emps.data?.length });

  const rows = useMemo<Row[]>(() => {
    const byId = new Map((persons.data ?? []).map((p) => [p.id, p]));
    // Resolved from the signed-in user's companies so it shows even for people not yet placed in a department.
    const companyById = new Map((user?.legalEntities ?? []).map((l) => [l.id, l.name]));
    return (emps.data ?? []).map((e) => {
      const p = byId.get(e.person_id);
      const name = p ? `${p.preferred_name || p.legal_first_name} ${p.legal_last_name}` : e.employee_number;
      return toRow(e, name, companyById.get(e.legal_entity_id) ?? e.legal_entity_name ?? undefined);
    });
  }, [emps.data, persons.data, user?.legalEntities]);

  const counts = useMemo(() => {
    const c: Record<StatusTab, number> = { ALL: rows.length, ACTIVE: 0, PROBATION: 0, ON_NOTICE: 0, INACTIVE: 0 };
    for (const r of rows) c[bucket(r.state)]++;
    return c;
  }, [rows]);

  const companies = useMemo(() => [...new Set(rows.map((r) => r.company).filter(Boolean))].sort() as string[], [rows]);
  const departments = useMemo(() => [...new Set(rows.map((r) => r.department).filter(Boolean))].sort() as string[], [rows]);
  const types = useMemo(() => [...new Set(rows.map((r) => r.type).filter(Boolean))].sort() as string[], [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const out = rows.filter((r) =>
      (status === "ALL" || bucket(r.state) === status) &&
      (!company || r.company === company) &&
      (!dept || r.department === dept) &&
      (!type || r.type === type) &&
      (!q || [r.name, r.employeeNumber, r.email, r.designation, r.company].some((v) => v?.toLowerCase().includes(q))),
    );
    out.sort((a, b) => {
      const cmp = sort.key === "name" ? a.name.localeCompare(b.name) : a.hireDate.localeCompare(b.hireDate);
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, status, company, dept, type, search, sort]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
  const current = Math.min(page, totalPages);
  const pageRows = filtered.slice((current - 1) * perPage, current * perPage);
  const hasFilters = !!(company || dept || type || search || status !== "ALL");
  const allOnPage = pageRows.length > 0 && pageRows.every((r) => selected.has(r.id));

  const resetFilters = () => { setStatus("ALL"); setCompany(""); setDept(""); setType(""); setSearch(""); };
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "hireDate" ? "desc" : "asc" }));
  const toggleRow = (id: string) =>
    setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const togglePage = () =>
    setSelected((s) => {
      const n = new Set(s);
      for (const r of pageRows) { if (allOnPage) n.delete(r.id); else n.add(r.id); }
      return n;
    });

  const sortIcon = (k: SortKey) =>
    sort.key !== k ? <ArrowUpDown size={12} className="opacity-50" /> : sort.dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />;

  return (
    <>
      <PageHeader
        title="Employees"
        description={(user?.legalEntities.length ?? 0) > 1 ? `Everyone employed across ${user?.tenantName} companies.` : "Everyone employed here."}
        actions={
          <>
            <button className="btn-secondary" onClick={() => downloadCsv(filtered)} disabled={!filtered.length}>
              <Download size={15} /> Export
            </button>
            {canPlace && (
              <button className="btn-primary" onClick={() => setAdding(true)}>
                <Plus size={15} /> Add employee
              </button>
            )}
          </>
        }
      />

      {emps.isError && (
        <div className="mb-4">
          <Notice
            title="Couldn’t load employees"
            action={<button className="btn-secondary btn-sm shrink-0" onClick={() => emps.refetch()}>Retry</button>}
          >
            The employee API isn’t responding, so no records can be shown right now.
          </Notice>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-5 pt-1">
          <Tabs
            value={status}
            onChange={setStatus}
            items={[
              { value: "ALL", label: "All", count: emps.isPending ? undefined : counts.ALL },
              { value: "ACTIVE", label: "Active", count: emps.isPending ? undefined : counts.ACTIVE },
              { value: "PROBATION", label: "Probation", count: emps.isPending ? undefined : counts.PROBATION },
              { value: "ON_NOTICE", label: "On notice", count: emps.isPending ? undefined : counts.ON_NOTICE },
              { value: "INACTIVE", label: "Inactive", count: emps.isPending ? undefined : counts.INACTIVE },
            ]}
          />
        </div>

        <div className="flex flex-col gap-2 border-b border-line px-5 py-3 sm:flex-row sm:items-center">
          <div className="relative flex-1 sm:max-w-xs">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input
              className="input pl-9"
              placeholder="Search name, ID or company"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search employees"
            />
          </div>
          {companies.length > 1 && (
            <select className="input sm:w-56" value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company">
              <option value="">All companies</option>
              {companies.map((c) => <option key={c}>{c}</option>)}
            </select>
          )}
          {departments.length > 0 && (
            <select className="input sm:w-44" value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Department">
              <option value="">All departments</option>
              {departments.map((d) => <option key={d}>{d}</option>)}
            </select>
          )}
          {types.length > 0 && (
            <select className="input sm:w-40" value={type} onChange={(e) => setType(e.target.value)} aria-label="Employment type">
              <option value="">All types</option>
              {types.map((t) => <option key={t}>{t}</option>)}
            </select>
          )}
          {hasFilters && (
            <button className="btn-ghost btn-sm" onClick={resetFilters}><X size={13} /> Clear</button>
          )}
          <span className="text-xs text-fg-subtle sm:ml-auto">{filtered.length} {filtered.length === 1 ? "person" : "people"}</span>
        </div>

        {selected.size > 0 && (
          <div className="flex items-center gap-3 border-b border-line bg-brand-500/[0.06] px-5 py-2 text-[13px] animate-fade-in">
            <span className="font-medium text-fg">{selected.size} selected</span>
            <button className="btn-secondary btn-sm" onClick={() => downloadCsv(rows.filter((r) => selected.has(r.id)))}>
              <Download size={13} /> Export selected
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Clear selection</button>
          </div>
        )}

        {emps.isPending ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="h-8 w-8 rounded-full" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="hidden h-4 w-32 sm:block" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No employees yet"
            description="Add your first employee to start tracking attendance, leave and onboarding."
            action={canPlace ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add employee</button> : undefined}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={SearchX}
            title="No matching employees"
            description="Try a different search term or clear the filters."
            action={<button className="btn-secondary" onClick={resetFilters}>Clear filters</button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-10"><input type="checkbox" className="checkbox" checked={allOnPage} onChange={togglePage} aria-label="Select page" /></th>
                  <th>
                    <button className="inline-flex items-center gap-1.5 hover:text-fg" onClick={() => toggleSort("name")}>Employee {sortIcon("name")}</button>
                  </th>
                  {companies.length > 1 && <th className="hidden lg:table-cell">Company</th>}
                  <th className="hidden md:table-cell">Department</th>
                  <th className="hidden lg:table-cell">Designation</th>
                  <th>
                    <button className="inline-flex items-center gap-1.5 hover:text-fg" onClick={() => toggleSort("hireDate")}>Joined {sortIcon("hireDate")}</button>
                  </th>
                  {types.length > 0 && <th className="hidden xl:table-cell">Type</th>}
                  <th>Status</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r) => (
                  <tr key={r.id} onClick={() => setDetail(r)} className={`group cursor-pointer ${selected.has(r.id) ? "bg-brand-500/[0.04]" : ""}`}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" className="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)} aria-label={`Select ${r.name}`} />
                    </td>
                    <td>
                      <div className="flex items-center gap-3">
                        <Avatar name={r.name} size="md" />
                        <div className="min-w-0 leading-tight">
                          <button
                            className="truncate font-medium text-fg hover:underline"
                            onClick={(e) => { e.stopPropagation(); setDetail(r); }}
                          >
                            {r.name}
                          </button>
                          <p className="truncate font-mono text-[11px] text-fg-subtle">{r.employeeNumber}</p>
                        </div>
                      </div>
                    </td>
                    {companies.length > 1 && <td className="hidden max-w-[14rem] truncate lg:table-cell" title={r.company}>{r.company ?? "—"}</td>}
                    <td className="hidden md:table-cell">
                      {r.department ?? (r.legalEntityId !== undefined
                        ? <span className="text-warning">Not placed</span>
                        : "—")}
                    </td>
                    <td className="hidden lg:table-cell">{r.designation ?? "—"}</td>
                    <td className="whitespace-nowrap tabular-nums">{format(new Date(r.hireDate), "d MMM yyyy")}</td>
                    {types.length > 0 && <td className="hidden xl:table-cell">{r.type ?? "—"}</td>}
                    <td><StatusBadge status={r.state} /></td>
                    <td><ChevronRight size={15} className="text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="flex flex-col gap-3 border-t border-line px-5 py-3 text-xs text-fg-subtle sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <span>Rows per page</span>
              <select
                className="input h-8 w-[72px] text-xs"
                value={perPage}
                onChange={(e) => setPerPage(Number(e.target.value))}
                aria-label="Rows per page"
              >
                {[10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-3">
              <span className="tabular-nums">
                {(current - 1) * perPage + 1}–{Math.min(current * perPage, filtered.length)} of {filtered.length}
              </span>
              <div className="flex gap-1">
                <button className="btn-icon border border-line" onClick={() => setPage(current - 1)} disabled={current === 1} aria-label="Previous page">
                  <ChevronLeft size={15} />
                </button>
                <button className="btn-icon border border-line" onClick={() => setPage(current + 1)} disabled={current === totalPages} aria-label="Next page">
                  <ChevronRight size={15} />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <EmployeeSheet
        key={detail?.id ?? "none"}
        row={detail}
        canPlace={canPlace}
        onClose={() => setDetail(null)}
        onTransfer={() => { if (detail) { setTransferring(detail); setDetail(null); } }}
      />
      <AddEmployeeSheet open={adding} onClose={() => setAdding(false)} />
      <TransferSheet row={transferring} onClose={() => setTransferring(null)} />
    </>
  );
}

type EmployeeSheetTab = "overview" | "kyc";

function EmployeeSheet({ row, canPlace, onClose, onTransfer }: {
  row: Row | null; canPlace: boolean; onClose: () => void; onTransfer: () => void;
}) {
  const [activeTab, setActiveTab] = useState<EmployeeSheetTab>("overview");

  const fields = row
    ? [
        { icon: Hash, label: "Employee ID", value: row.employeeNumber },
        { icon: Landmark, label: "Company", value: row.company },
        { icon: Building2, label: "Department", value: row.department },
        { icon: Briefcase, label: "Designation", value: row.designation },
        { icon: UserRound, label: "Reports to", value: row.manager },
        { icon: MapPin, label: "Location", value: row.location },
        { icon: CalendarDays, label: "Joined", value: `${format(new Date(row.hireDate), "d MMM yyyy")} · ${tenure(row.hireDate)}` },
        // Only shown when known — the employee list doesn't carry login emails.
        ...(row.email ? [{ icon: Mail, label: "Email", value: row.email }] : []),
      ]
    : [];
  const isPlaced = !!row?.department;

  return (
    <Sheet
      open={!!row}
      onClose={onClose}
      title="Employee profile"
      className="max-w-4xl"
      footer={row ? (
        <div className="flex items-center justify-between w-full">
          {activeTab === "overview" ? (
            <button type="button" className="btn-secondary btn-sm" onClick={() => setActiveTab("kyc")}>
              <ShieldCheck size={13} /> View KYC & Documents
            </button>
          ) : (
            <button type="button" className="btn-secondary btn-sm" onClick={() => setActiveTab("overview")}>
              Back to Overview
            </button>
          )}
          {canPlace && activeTab === "overview" && (
            <button className="btn-primary btn-sm" onClick={onTransfer}>
              <ArrowLeftRight size={14} /> {isPlaced ? "Transfer" : "Place in a department"}
            </button>
          )}
        </div>
      ) : undefined}
    >
      {row && (
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <Avatar name={row.name} size="xl" />
            <div className="min-w-0">
              <p className="truncate text-lg font-semibold tracking-tight text-fg">{row.name}</p>
              <p className="truncate text-[13px] text-fg-muted">{row.designation ?? row.stage ?? "—"}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <StatusBadge status={row.state} />
                {row.type && <span className="badge badge-neutral">{row.type}</span>}
              </div>
            </div>
          </div>

          <Tabs<EmployeeSheetTab>
            className="border-b border-line"
            value={activeTab}
            onChange={setActiveTab}
            items={[
              { value: "overview", label: "Employment overview" },
              { value: "kyc", label: "KYC & Documents" },
            ]}
          />

          {activeTab === "overview" ? (
            <>
              {!isPlaced && row.legalEntityId !== undefined && (
                <Notice title="Not yet placed in a department" tone="warning">
                  This employee was hired but hasn’t been assigned a department, job title or location yet.
                </Notice>
              )}
              <div>
                <p className="eyebrow mb-2">Employment</p>
                <dl className="divide-y divide-line rounded-xl border border-line">
                  {fields.map(({ icon: Icon, label, value }) => (
                    <div key={label} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
                      <Icon size={14} className="shrink-0 text-fg-subtle" />
                      <dt className="w-28 shrink-0 text-fg-subtle">{label}</dt>
                      <dd className="min-w-0 truncate font-medium text-fg">{value ?? "—"}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </>
          ) : (
            <KycSection
              employmentId={row.id}
              employeeName={row.name}
              isHR={true}
            />
          )}
        </div>
      )}
    </Sheet>
  );
}

/** Shared department/designation/location/manager picker used by both hiring and transferring. */
function PlacementFields({ legalEntityId, values, onChange, excludeEmploymentId }: {
  legalEntityId: string;
  values: { orgUnitId: string; jobId: string; locationId: string; managerEmploymentId: string };
  onChange: (v: Partial<typeof values>) => void;
  excludeEmploymentId?: string;
}) {
  const orgUnits = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });
  const locations = useQuery({ queryKey: ["locations"], queryFn: () => orgApi.listLocations() });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs() });
  const employees = useQuery({ queryKey: ["employees"], queryFn: () => peopleApi.listAllEmployees() });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => peopleApi.listAllPersons(), enabled: !!employees.data?.length });
  const personName = new Map((persons.data ?? []).map((p) => [p.id, `${p.preferred_name || p.legal_first_name} ${p.legal_last_name}`]));

  const departments = (orgUnits.data ?? []).filter((o) => o.type === "DEPARTMENT" && o.legal_entity_id === legalEntityId);
  const entityLocations = (locations.data ?? []).filter((l) => !l.legal_entity_id || l.legal_entity_id === legalEntityId);
  const managers = (employees.data ?? []).filter((e) => e.legal_entity_id === legalEntityId && e.id !== excludeEmploymentId);

  const loading = orgUnits.isPending || locations.isPending || jobs.isPending;
  if (loading) return <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>;

  return (
    <>
      <div>
        <label className="label" htmlFor="pl-dept">Department</label>
        <select id="pl-dept" className="input" value={values.orgUnitId} onChange={(e) => onChange({ orgUnitId: e.target.value })}>
          <option value="">{departments.length ? "Choose department…" : "No departments yet for this company"}</option>
          {departments.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="pl-job">Designation</label>
          <select id="pl-job" className="input" value={values.jobId} onChange={(e) => onChange({ jobId: e.target.value })}>
            <option value="">{jobs.data?.length ? "Choose…" : "No jobs yet"}</option>
            {jobs.data?.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="pl-loc">Location</label>
          <select id="pl-loc" className="input" value={values.locationId} onChange={(e) => onChange({ locationId: e.target.value })}>
            <option value="">{entityLocations.length ? "Choose…" : "No locations yet"}</option>
            {entityLocations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="pl-mgr">Reports to <span className="font-normal text-fg-subtle">(optional)</span></label>
        <select id="pl-mgr" className="input" value={values.managerEmploymentId} onChange={(e) => onChange({ managerEmploymentId: e.target.value })}>
          <option value="">No manager</option>
          {managers.map((m) => <option key={m.id} value={m.id}>{personName.has(m.person_id) ? `${personName.get(m.person_id)} · ${m.employee_number}` : m.employee_number}</option>)}
        </select>
      </div>
    </>
  );
}

function AddEmployeeSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = {
    first: "", last: "", number: "", hireDate: format(new Date(), "yyyy-MM-dd"), entity: "",
    orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "",
  };
  const [form, setForm] = useState(empty);
  const set = (k: "first" | "last" | "number" | "hireDate" | "entity") => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities(), enabled: open });
  const entityId = form.entity || entities.data?.[0]?.id || "";
  const idSchemes = useQuery({ queryKey: ["employee-id-schemes"], queryFn: () => orgApi.listEmployeeIdSchemes(), enabled: open });
  const resolvedScheme = (idSchemes.data ?? []).find((s) => s.legal_entity_id === entityId)
    ?? (idSchemes.data ?? []).find((s) => !s.legal_entity_id);

  const hire = useMutation({
    mutationFn: async () => {
      const person = await peopleApi.createPerson({ legal_first_name: form.first.trim(), legal_last_name: form.last.trim() });
      const employment = await peopleApi.createEmployment({
        person_id: person.id,
        legal_entity_id: entityId,
        employee_number: form.number.trim() || undefined,
        hire_date: form.hireDate,
      });
      if (form.orgUnitId && form.jobId && form.locationId) {
        await personnelActionsApi.create({
          employment_id: employment.id,
          type: "HIRE",
          effective_date: form.hireDate,
          changes: {
            org_unit_id: form.orgUnitId,
            job_id: form.jobId,
            location_id: form.locationId,
            manager_employment_id: form.managerEmploymentId || undefined,
          },
        });
        await onboardingApi.createCase(employment.id, form.hireDate).catch(() => {
          // Non-fatal — HR can start onboarding manually from the Onboarding page.
        });
      }
      return employment;
    },
    onSuccess: (emp) => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["persons"] });
      qc.invalidateQueries({ queryKey: ["onboarding-cases-all"] });
      const placed = form.orgUnitId && form.jobId && form.locationId;
      toast.success(
        placed ? "Employee hired and placed" : "Employee added — not yet placed",
        placed ? `${form.first} ${form.last} · ${emp.employee_number}` : "Open their profile to assign a department",
      );
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t add employee", errorMessage(e)),
  });

  const valid = form.first.trim() && form.last.trim() && (form.number.trim() || resolvedScheme) && form.hireDate && entityId;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) hire.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add employee"
      description="Creates their record and places them in a department."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="add-employee" disabled={!valid || hire.isPending}>
            {hire.isPending ? "Adding…" : "Add employee"}
          </button>
        </>
      }
    >
      <form id="add-employee" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="ae-first">First name</label>
            <input id="ae-first" className="input" value={form.first} onChange={set("first")} autoComplete="off" />
          </div>
          <div>
            <label className="label" htmlFor="ae-last">Last name</label>
            <input id="ae-last" className="input" value={form.last} onChange={set("last")} autoComplete="off" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="ae-num">
              Employee ID {resolvedScheme && <span className="font-normal text-fg-subtle">(optional — auto-generated)</span>}
            </label>
            <input
              id="ae-num" className="input font-mono"
              placeholder={resolvedScheme ? `Auto: ${resolvedScheme.preview}` : "Enter employee ID"}
              value={form.number} onChange={set("number")}
            />
          </div>
          <div>
            <label className="label" htmlFor="ae-date">Date of joining</label>
            <input id="ae-date" type="date" className="input" value={form.hireDate} onChange={set("hireDate")} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="ae-entity">Company</label>
          <select
            id="ae-entity" className="input" value={entityId} disabled={!entities.data?.length}
            onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value, orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "" }))}
          >
            {!entities.data?.length && <option value="">{entities.isLoading ? "Loading…" : "No companies found"}</option>}
            {entities.data?.map((le) => <option key={le.id} value={le.id}>{le.name}</option>)}
          </select>
          {entities.isError && <p className="hint text-danger">Couldn’t load companies — is the API running?</p>}
          {entities.data && !entities.data.length && <p className="hint">No companies yet — add one from Organization first.</p>}
        </div>

        {entityId && (
          <PlacementFields
            legalEntityId={entityId}
            values={{ orgUnitId: form.orgUnitId, jobId: form.jobId, locationId: form.locationId, managerEmploymentId: form.managerEmploymentId }}
            onChange={(v) => setForm((f) => ({ ...f, ...v }))}
          />
        )}
        <p className="hint">
          Leaving department, designation or location blank adds the employee without placing them — you can place them later from their profile.
        </p>
      </form>
    </Sheet>
  );
}

function TransferSheet({ row, onClose }: { row: Row | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "", effectiveDate: format(new Date(), "yyyy-MM-dd") });

  // Reset/prefill whenever a different employee is opened.
  const key = row?.id ?? "";
  const [lastKey, setLastKey] = useState(key);
  if (key !== lastKey) {
    setLastKey(key);
    setForm({
      orgUnitId: row?.orgUnitId ?? "", jobId: row?.jobId ?? "", locationId: row?.locationId ?? "",
      managerEmploymentId: row?.managerEmploymentId ?? "", effectiveDate: format(new Date(), "yyyy-MM-dd"),
    });
  }

  const transfer = useMutation({
    mutationFn: async () => {
      if (!row) return;
      await personnelActionsApi.create({
        employment_id: row.id,
        type: "TRANSFER",
        effective_date: form.effectiveDate,
        changes: {
          org_unit_id: form.orgUnitId || undefined,
          job_id: form.jobId || undefined,
          location_id: form.locationId || undefined,
          manager_employment_id: form.managerEmploymentId || undefined,
        },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success("Employee moved", row?.name);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t move employee", errorMessage(e)),
  });

  const valid = !!(row && form.orgUnitId && form.jobId && form.locationId && form.effectiveDate);
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) transfer.mutate(); };

  return (
    <Sheet
      open={!!row}
      onClose={onClose}
      title={row ? `Move ${row.name}` : "Move employee"}
      description="Creates a new effective-dated assignment — full history is kept."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="transfer-employee" disabled={!valid || transfer.isPending}>
            {transfer.isPending ? "Moving…" : "Move employee"}
          </button>
        </>
      }
    >
      {row && (
        <form id="transfer-employee" onSubmit={submit} className="space-y-4">
          <div>
            <label className="label" htmlFor="tr-date">Effective from</label>
            <input
              id="tr-date" type="date" className="input" value={form.effectiveDate}
              onChange={(e) => setForm((f) => ({ ...f, effectiveDate: e.target.value }))}
            />
          </div>
          <PlacementFields
            legalEntityId={row.legalEntityId ?? ""}
            values={form}
            onChange={(v) => setForm((f) => ({ ...f, ...v }))}
            excludeEmploymentId={row.id}
          />
        </form>
      )}
    </Sheet>
  );
}
