import { useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Building2, Landmark, MapPin, Briefcase, Users, Hash, Pencil, Trash2, KeyRound, UserRoundX, UserRoundCheck, Copy, Sparkles } from "lucide-react";
import { orgApi } from "../api/org";
import type { LegalEntity, OrgUnit, EmployeeIdScheme } from "../api/org";
import { dashboardApi } from "../api/dashboard";
import { usersApi } from "../api/users";
import type { Role, ScopeType, UserAccount } from "../api/users";
import { generateTempPassword, passwordProblem } from "../lib/password";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { Sheet, ConfirmDialog } from "../components/ui/Overlay";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { format } from "date-fns";

type Tab = "overview" | "companies" | "departments" | "locations" | "jobs" | "employee-ids" | "access";

export function OrganizationPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const setTab = (t: Tab) => setParams({ tab: t }, { replace: true });

  const canCreateCompany = !!user?.isAllScope;
  const canManageAccess = !!user && (user.permissions.includes("iam.read") || user.permissions.includes("*"));

  return (
    <>
      <PageHeader
        title="Organization"
        description="Companies, departments, locations and job titles across the group."
      />
      <Tabs
        className="mb-6"
        value={tab}
        onChange={setTab}
        items={[
          { value: "overview", label: "Overview" },
          { value: "companies", label: "Companies" },
          { value: "departments", label: "Departments" },
          { value: "locations", label: "Locations" },
          { value: "jobs", label: "Job titles" },
          { value: "employee-ids", label: "Employee IDs" },
          ...(canManageAccess ? [{ value: "access" as const, label: "Users & access" }] : []),
        ]}
      />
      {tab === "overview" && <OrganizationOverviewTab onNavigateTab={setTab} />}
      {tab === "companies" && <CompaniesTab canCreate={canCreateCompany} />}
      {tab === "departments" && <DepartmentsTab />}
      {tab === "locations" && <LocationsTab />}
      {tab === "jobs" && <JobsTab />}
      {tab === "employee-ids" && <EmployeeIdSchemesTab canCreateGlobal={canCreateCompany} />}
      {tab === "access" && canManageAccess && <AccessTab />}
    </>
  );
}

/* ─────────────────────────── Summary of Organization (Overview) ─────────────────────────── */

function OrganizationOverviewTab({ onNavigateTab }: { onNavigateTab: (tab: Tab) => void }) {
  const { data: hrData, isPending: hrPending } = useQuery({
    queryKey: ["dash-hr"],
    queryFn: () => dashboardApi.hr(),
  });
  const { data: entities = [], isPending: entitiesPending } = useQuery({
    queryKey: ["legal-entities"],
    queryFn: () => orgApi.listLegalEntities(),
  });
  const { data: locations = [] } = useQuery({
    queryKey: ["locations"],
    queryFn: () => orgApi.listLocations(),
  });
  const { data: orgUnits = [] } = useQuery({
    queryKey: ["org-units"],
    queryFn: () => orgApi.listOrgUnits(),
  });

  const isLoading = hrPending || entitiesPending;
  const orgSummary = (hrData?.org_summary as Record<string, unknown>) ?? null;
  const entityDist = (hrData?.entity_distribution as { company: string; short_name?: string; count: number }[]) ?? [];
  const deptDist = (hrData?.department_distribution as { department: string; count: number }[]) ?? [];
  const hc = (hrData?.headcount as Record<string, unknown>) ?? {};
  const total = typeof hc.total === "number" ? hc.total : 0;

  const tenureBrackets = (orgSummary?.tenure_brackets as Record<string, number>) ?? {};
  const vets = tenureBrackets.over_10_years ?? 0;
  const established = tenureBrackets["5_to_10_years"] ?? tenureBrackets.tenure_5_to_10 ?? 0;
  const growth = tenureBrackets.under_5_years ?? tenureBrackets.tenure_under_5 ?? 0;
  const tenureTotal = vets + established + growth || total || 1;
  const vetsPct = Math.round((vets / tenureTotal) * 100);
  const establishedPct = Math.round((established / tenureTotal) * 100);
  const growthPct = Math.max(0, 100 - vetsPct - establishedPct);

  const kycCompliance = (orgSummary?.kyc_compliance as Record<string, number>) ?? {};
  const kycRate = typeof kycCompliance.rate_pct === "number" ? kycCompliance.rate_pct : 0;
  const avgTenure = typeof orgSummary?.avg_tenure_years === "number" ? orgSummary.avg_tenure_years : 0;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="card p-5 space-y-4">
          <Skeleton className="h-8 w-64" />
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 rounded-lg" />
            ))}
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton className="h-48 rounded-lg" />
            <Skeleton className="h-48 rounded-lg" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ─── Summary of Organization Card ─────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="card-title">Summary of organization</h3>
            <p className="card-desc">Group entities, operating locations, and employee seniority breakdown</p>
          </div>
          <span className="badge badge-neutral">{total} Active staff</span>
        </div>

        <div className="p-5 space-y-6">
          {/* Metric summary in standard divided box */}
          <div className="grid grid-cols-2 divide-x divide-line rounded-lg border border-line sm:grid-cols-5">
            <button
              onClick={() => onNavigateTab("companies")}
              className="p-3.5 text-center hover:bg-surface-raised transition text-left cursor-pointer"
            >
              <p className="text-2xl font-semibold tabular-nums text-fg">
                {entities.length || (orgSummary?.total_entities as number) || 0}
              </p>
              <p className="text-[11px] text-fg-subtle">Legal entities &rarr;</p>
            </button>
            <button
              onClick={() => onNavigateTab("locations")}
              className="p-3.5 text-center hover:bg-surface-raised transition text-left cursor-pointer"
            >
              <p className="text-2xl font-semibold tabular-nums text-fg">
                {locations.length || (orgSummary?.total_locations as number) || 0}
              </p>
              <p className="text-[11px] text-fg-subtle">Locations & hubs &rarr;</p>
            </button>
            <button
              onClick={() => onNavigateTab("departments")}
              className="p-3.5 text-center hover:bg-surface-raised transition text-left cursor-pointer"
            >
              <p className="text-2xl font-semibold tabular-nums text-fg">
                {orgUnits.length || (orgSummary?.total_departments as number) || 0}
              </p>
              <p className="text-[11px] text-fg-subtle">Departments &rarr;</p>
            </button>
            <div className="p-3.5 text-center">
              <p className="text-2xl font-semibold tabular-nums text-fg">{avgTenure} yrs</p>
              <p className="text-[11px] text-fg-subtle">Average tenure</p>
            </div>
            <div className="p-3.5 text-center">
              <p className="text-2xl font-semibold tabular-nums text-success">{kycRate}%</p>
              <p className="text-[11px] text-fg-subtle">KYC compliance</p>
            </div>
          </div>

          {/* Two-Column Deep Breakdown */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Left Column: Registered Companies Overview */}
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <p className="eyebrow">Group entities directory ({entityDist.length || entities.length})</p>
                <button
                  onClick={() => onNavigateTab("companies")}
                  className="link text-xs"
                >
                  Manage companies
                </button>
              </div>
              <div className="divide-y divide-line rounded-lg border border-line">
                {entityDist.length > 0 ? (
                  entityDist.map((e) => {
                    const pct = total > 0 ? Math.round((e.count / total) * 100) : 0;
                    return (
                      <div
                        key={e.company}
                        className="flex items-center justify-between px-3.5 py-2.5 text-[13px]"
                      >
                        <div className="min-w-0 pr-2">
                          <span className="font-medium text-fg block truncate">{e.company}</span>
                          {e.short_name && <span className="text-xs text-fg-subtle">{e.short_name}</span>}
                        </div>
                        <span className="shrink-0 text-right">
                          <span className="font-semibold text-fg tabular-nums">{e.count} staff</span>
                          <span className="text-xs text-fg-subtle ml-1.5">({pct}%)</span>
                        </span>
                      </div>
                    );
                  })
                ) : (
                  entities.map((e) => (
                    <div
                      key={e.id}
                      className="flex items-center justify-between px-3.5 py-2.5 text-[13px]"
                    >
                      <div className="min-w-0">
                        <span className="font-medium text-fg truncate block">{e.name}</span>
                        {e.short_name && <span className="text-xs text-fg-subtle">{e.short_name}</span>}
                      </div>
                      <span className="badge badge-neutral text-xs">{e.country_code}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Right Column: Seniority & Department Breakdown */}
            <div className="space-y-5">
              <div>
                <p className="eyebrow mb-2.5">Employee seniority & retention</p>
                <div className="space-y-3 rounded-lg border border-line p-4">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="font-medium text-fg">Veterans (10+ Years)</span>
                      <span className="tabular-nums font-semibold text-fg">{vets} staff ({vetsPct}%)</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-amber-500" style={{ width: `${vetsPct}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="font-medium text-fg">Established (5 to 10 Years)</span>
                      <span className="tabular-nums font-semibold text-fg">{established} staff ({establishedPct}%)</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-brand-500" style={{ width: `${establishedPct}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="font-medium text-fg">Growth (&lt; 5 Years)</span>
                      <span className="tabular-nums font-semibold text-fg">{growth} staff ({growthPct}%)</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-info" style={{ width: `${growthPct}%` }} />
                    </div>
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <p className="eyebrow">Functional allocation</p>
                  <button
                    onClick={() => onNavigateTab("departments")}
                    className="link text-xs"
                  >
                    All departments ({orgUnits.length})
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {deptDist.map((d) => (
                    <div key={d.department} className="rounded-lg border border-line p-2 text-center">
                      <p className="text-base font-semibold text-fg tabular-nums">{d.count}</p>
                      <p className="text-[11px] text-fg-subtle truncate">{d.department}</p>
                    </div>
                  ))}
                  {deptDist.length === 0 && (
                    <div className="col-span-full py-2 text-center text-xs text-fg-subtle">
                      {orgUnits.length} departments configured
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Companies ─────────────────────────── */

function CompaniesTab({ canCreate }: { canCreate: boolean }) {
  const [adding, setAdding] = useState(false);
  const { data, isPending, isError, refetch } = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setAdding(true)} disabled={!canCreate} title={canCreate ? undefined : "Only a group-level administrator can add a company"}>
          <Plus size={15} /> Add company
        </button>
      </div>
      {isError ? (
        <div className="card"><EmptyState icon={Building2} title="Couldn’t load companies" description="The organization API isn’t responding." action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>} /></div>
      ) : isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
      ) : !data?.length ? (
        <div className="card">
          <EmptyState
            icon={Building2}
            title="No companies yet"
            description={canCreate ? "Add your first company — this is the legal entity people are hired into." : "No companies are visible to your account yet."}
            action={canCreate ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add company</button> : undefined}
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((e) => (
            <div key={e.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-500/10 text-accent"><Building2 size={18} /></span>
                <span className="badge badge-neutral">{e.country_code}</span>
              </div>
              <p className="mt-3 text-[15px] font-semibold text-fg">{e.name}</p>
              <p className="text-xs text-fg-subtle">{e.short_name ?? "—"}</p>
              <div className="mt-3"><StatusChip status={e.status} /></div>
            </div>
          ))}
        </div>
      )}
      <AddCompanySheet open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function AddCompanySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { name: "", shortName: "", country: "IN" };
  const [form, setForm] = useState(empty);

  const create = useMutation({
    mutationFn: () => orgApi.createLegalEntity({ name: form.name.trim(), short_name: form.shortName.trim() || undefined, country_code: form.country }),
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["legal-entities"] });
      toast.success("Company added", e.name);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t add company", errorMessage(e)),
  });

  const valid = form.name.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add company"
      description="A new legal entity people can be hired into — a sister company."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="add-company" disabled={!valid || create.isPending}>
            {create.isPending ? "Adding…" : "Add company"}
          </button>
        </>
      }
    >
      <form id="add-company" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="co-name">Company name</label>
          <input id="co-name" className="input" placeholder="e.g. Novusha Industries" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="co-short">Short name</label>
            <input id="co-short" className="input" placeholder="e.g. NOVUSHA" value={form.shortName} onChange={(e) => setForm((f) => ({ ...f, shortName: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="co-country">Country</label>
            <input id="co-country" className="input" maxLength={2} value={form.country} onChange={(e) => setForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))} />
          </div>
        </div>
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Departments ─────────────────────────── */

function DepartmentsTab() {
  const [adding, setAdding] = useState(false);
  const [companyFilter, setCompanyFilter] = useState("");
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });

  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));
  const departments = (units.data ?? []).filter((o) => o.type !== "COMPANY" && (!companyFilter || o.legal_entity_id === companyFilter));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select className="input sm:w-56" value={companyFilter} onChange={(e) => setCompanyFilter(e.target.value)} aria-label="Filter by company">
          <option value="">All companies</option>
          {entities.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
        </select>
        <button className="btn-primary" onClick={() => setAdding(true)} disabled={!entities.data?.length}>
          <Plus size={15} /> Add department
        </button>
      </div>
      {units.isError ? (
        <div className="card"><EmptyState icon={Landmark} title="Couldn’t load departments" description="The organization API isn’t responding." /></div>
      ) : units.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !departments.length ? (
        <div className="card">
          <EmptyState
            icon={Landmark}
            title="No departments yet"
            description="Departments are where employees get placed — add one for each function you need (HR, Finance, Operations…)."
            action={entities.data?.length ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add department</button> : undefined}
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Department</th><th>Company</th><th className="hidden sm:table-cell">Code</th><th>Since</th></tr></thead>
            <tbody>
              {departments.map((d) => (
                <tr key={d.id}>
                  <td className="font-medium text-fg">{d.name}</td>
                  <td>{d.legal_entity_id ? entityName.get(d.legal_entity_id) ?? "—" : "—"}</td>
                  <td className="hidden font-mono text-xs sm:table-cell">{d.code ?? "—"}</td>
                  <td className="tabular-nums">{format(new Date(d.effective_from), "d MMM yyyy")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddDepartmentSheet open={adding} onClose={() => setAdding(false)} entities={entities.data ?? []} departments={units.data ?? []} />
    </div>
  );
}

function AddDepartmentSheet({ open, onClose, entities, departments }: {
  open: boolean; onClose: () => void; entities: LegalEntity[]; departments: OrgUnit[];
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { name: "", code: "", entity: entities[0]?.id ?? "", parent: "" };
  const [form, setForm] = useState(empty);
  const entityId = form.entity || entities[0]?.id || "";
  const parentOptions = departments.filter((d) => d.legal_entity_id === entityId);

  const create = useMutation({
    mutationFn: () => orgApi.createOrgUnit({
      name: form.name.trim(), type: "DEPARTMENT", code: form.code.trim() || undefined,
      legal_entity_id: entityId, parent_id: form.parent || undefined,
      effective_from: format(new Date(), "yyyy-MM-dd"),
    }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["org-units"] });
      toast.success("Department added", d.name);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t add department", errorMessage(e)),
  });

  const valid = form.name.trim().length > 0 && !!entityId;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add department"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="add-dept" disabled={!valid || create.isPending}>
            {create.isPending ? "Adding…" : "Add department"}
          </button>
        </>
      }
    >
      <form id="add-dept" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="dp-company">Company</label>
          <select id="dp-company" className="input" value={entityId} onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value, parent: "" }))}>
            {entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="dp-name">Department name</label>
          <input id="dp-name" className="input" placeholder="e.g. Finance" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="dp-code">Code <span className="font-normal text-fg-subtle">(optional)</span></label>
          <input id="dp-code" className="input font-mono" placeholder="e.g. HQ-FIN" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
        </div>
        {parentOptions.length > 0 && (
          <div>
            <label className="label" htmlFor="dp-parent">Parent department <span className="font-normal text-fg-subtle">(optional)</span></label>
            <select id="dp-parent" className="input" value={form.parent} onChange={(e) => setForm((f) => ({ ...f, parent: e.target.value }))}>
              <option value="">None — top level</option>
              {parentOptions.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
        )}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Locations ─────────────────────────── */

function LocationsTab() {
  const [adding, setAdding] = useState(false);
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const locations = useQuery({ queryKey: ["locations"], queryFn: () => orgApi.listLocations() });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setAdding(true)} disabled={!entities.data?.length}><Plus size={15} /> Add location</button>
      </div>
      {locations.isError ? (
        <div className="card"><EmptyState icon={MapPin} title="Couldn’t load locations" description="The organization API isn’t responding." /></div>
      ) : locations.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !locations.data?.length ? (
        <div className="card">
          <EmptyState icon={MapPin} title="No locations yet" description="Add an office or site — employees need one when they're placed in a department."
            action={entities.data?.length ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add location</button> : undefined} />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {locations.data.map((l) => (
            <div key={l.id} className="card p-5">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/10 text-accent"><MapPin size={18} /></span>
              <p className="mt-3 text-[15px] font-semibold text-fg">{l.name}</p>
              <p className="text-xs text-fg-subtle">{[l.city, l.legal_entity_id ? entityName.get(l.legal_entity_id) : "All companies"].filter(Boolean).join(" · ")}</p>
              <div className="mt-3 flex gap-1.5">
                <span className="badge badge-neutral">{l.type}</span>
                <StatusChip status={l.status} />
              </div>
            </div>
          ))}
        </div>
      )}
      <AddLocationSheet open={adding} onClose={() => setAdding(false)} entities={entities.data ?? []} />
    </div>
  );
}

function AddLocationSheet({ open, onClose, entities }: { open: boolean; onClose: () => void; entities: LegalEntity[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { name: "", type: "OFFICE", entity: "", city: "" };
  const [form, setForm] = useState(empty);

  const create = useMutation({
    mutationFn: () => orgApi.createLocation({
      name: form.name.trim(), type: form.type, city: form.city.trim() || undefined,
      legal_entity_id: form.entity || undefined,
    }),
    onSuccess: (l) => {
      qc.invalidateQueries({ queryKey: ["locations"] });
      toast.success("Location added", l.name);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t add location", errorMessage(e)),
  });

  const valid = form.name.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title="Add location"
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="add-loc" disabled={!valid || create.isPending}>
          {create.isPending ? "Adding…" : "Add location"}
        </button>
      </>}
    >
      <form id="add-loc" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="lo-name">Location name</label>
          <input id="lo-name" className="input" placeholder="e.g. Head Office" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="lo-type">Type</label>
            <select id="lo-type" className="input" value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}>
              {["OFFICE", "SITE", "PLANT", "REMOTE"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="lo-city">City</label>
            <input id="lo-city" className="input" value={form.city} onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="lo-entity">Company <span className="font-normal text-fg-subtle">(optional — leave blank to share across all)</span></label>
          <select id="lo-entity" className="input" value={form.entity} onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value }))}>
            <option value="">All companies</option>
            {entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Job titles ─────────────────────────── */

function JobsTab() {
  const [adding, setAdding] = useState(false);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs() });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add job title</button>
      </div>
      {jobs.isError ? (
        <div className="card"><EmptyState icon={Briefcase} title="Couldn’t load job titles" description="The organization API isn’t responding." /></div>
      ) : jobs.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : !jobs.data?.length ? (
        <div className="card">
          <EmptyState icon={Briefcase} title="No job titles yet" description="These are shared across every company — add the designations your teams use."
            action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add job title</button>} />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Title</th><th className="hidden sm:table-cell">Function</th><th>Code</th></tr></thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.id}>
                  <td className="font-medium text-fg">{j.title}</td>
                  <td className="hidden sm:table-cell">{j.function ?? "—"}</td>
                  <td className="font-mono text-xs">{j.code ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddJobSheet open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function AddJobSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { title: "", code: "", function: "" };
  const [form, setForm] = useState(empty);

  const create = useMutation({
    mutationFn: () => orgApi.createJob({ title: form.title.trim(), code: form.code.trim() || undefined, function: form.function.trim() || undefined }),
    onSuccess: (j) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      toast.success("Job title added", j.title);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t add job title", errorMessage(e)),
  });

  const valid = form.title.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title="Add job title"
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="add-job" disabled={!valid || create.isPending}>
          {create.isPending ? "Adding…" : "Add job title"}
        </button>
      </>}
    >
      <form id="add-job" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="jb-title">Title</label>
          <input id="jb-title" className="input" placeholder="e.g. Software Engineer" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="jb-code">Code <span className="font-normal text-fg-subtle">(optional)</span></label>
            <input id="jb-code" className="input font-mono" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="jb-fn">Function <span className="font-normal text-fg-subtle">(optional)</span></label>
            <input id="jb-fn" className="input" placeholder="e.g. Engineering" value={form.function} onChange={(e) => setForm((f) => ({ ...f, function: e.target.value }))} />
          </div>
        </div>
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Employee IDs ─────────────────────────── */

function EmployeeIdSchemesTab({ canCreateGlobal }: { canCreateGlobal: boolean }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<EmployeeIdScheme | null>(null);
  const [deleting, setDeleting] = useState<EmployeeIdScheme | null>(null);
  const qc = useQueryClient();
  const toast = useToast();

  const schemes = useQuery({ queryKey: ["employee-id-schemes"], queryFn: () => orgApi.listEmployeeIdSchemes() });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });

  const usedEntityIds = new Set((schemes.data ?? []).filter((s) => s.legal_entity_id).map((s) => s.legal_entity_id));
  const hasGlobal = (schemes.data ?? []).some((s) => !s.legal_entity_id);
  const availableEntities = (entities.data ?? []).filter((e) => !usedEntityIds.has(e.id));

  const remove = useMutation({
    mutationFn: (id: string) => orgApi.deleteEmployeeIdScheme(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employee-id-schemes"] });
      toast.success("Scheme removed");
      setDeleting(null);
    },
    onError: (e) => toast.error("Couldn’t remove scheme", errorMessage(e)),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <p className="max-w-lg text-[13px] text-fg-subtle">
          When set, new hires get an employee ID generated automatically — a company's own scheme
          wins over the tenant-wide one. Leave both unset to keep entering employee IDs by hand.
        </p>
        <button className="btn-primary shrink-0" onClick={() => setAdding(true)}>
          <Plus size={15} /> Add scheme
        </button>
      </div>
      {schemes.isError ? (
        <div className="card"><EmptyState icon={Hash} title="Couldn’t load employee ID schemes" description="The organization API isn’t responding." action={<button className="btn-secondary btn-sm" onClick={() => schemes.refetch()}>Retry</button>} /></div>
      ) : schemes.isPending ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : !schemes.data?.length ? (
        <div className="card">
          <EmptyState
            icon={Hash}
            title="No employee ID schemes yet"
            description="Employee IDs are entered by hand right now. Add a scheme to generate them automatically — tenant-wide, or per company."
            action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add scheme</button>}
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Scope</th><th>Format</th><th>Next ID</th><th className="w-20" /></tr></thead>
            <tbody>
              {schemes.data.map((s) => (
                <tr key={s.id}>
                  <td className="font-medium text-fg">
                    {s.legal_entity_id ? s.legal_entity_name ?? s.legal_entity_id : <span className="inline-flex items-center gap-1.5"><Building2 size={13} className="text-fg-subtle" /> Whole tenant</span>}
                  </td>
                  <td className="font-mono text-xs text-fg-subtle">{s.prefix}{s.separator}{"Y".repeat(s.number_digits)}</td>
                  <td className="font-mono font-medium text-fg">{s.preview}</td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <button className="btn-icon" onClick={() => setEditing(s)} aria-label={`Edit ${s.preview} scheme`}><Pencil size={14} /></button>
                      <button className="btn-icon hover:text-danger" onClick={() => setDeleting(s)} aria-label={`Remove ${s.preview} scheme`}><Trash2 size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <EmployeeIdSchemeSheet
        open={adding} onClose={() => setAdding(false)}
        availableEntities={availableEntities} canCreateGlobal={canCreateGlobal && !hasGlobal}
      />
      <EmployeeIdSchemeSheet
        key={editing?.id}
        open={editing !== null} onClose={() => setEditing(null)}
        initial={editing ?? undefined} availableEntities={availableEntities} canCreateGlobal={canCreateGlobal}
      />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        loading={remove.isPending}
        title={`Remove the ${deleting?.preview ?? ""} scheme?`}
        description="New hires in this scope will go back to needing an employee ID entered by hand."
        confirmLabel="Remove scheme"
      />
    </div>
  );
}

function EmployeeIdSchemeSheet({ open, onClose, initial, availableEntities, canCreateGlobal }: {
  open: boolean;
  onClose: () => void;
  initial?: EmployeeIdScheme;
  availableEntities: LegalEntity[];
  canCreateGlobal: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const [legalEntityId, setLegalEntityId] = useState(initial?.legal_entity_id ?? "");
  const [prefix, setPrefix] = useState(initial?.prefix ?? "");
  const [separator, setSeparator] = useState(initial?.separator ?? "-");
  const [numberDigits, setNumberDigits] = useState(initial?.number_digits ?? 4);
  const [nextNumber, setNextNumber] = useState(initial?.next_number ?? 1);

  const save = useMutation({
    mutationFn: () =>
      isEdit
        ? orgApi.updateEmployeeIdScheme(initial!.id, { prefix, separator, number_digits: numberDigits, next_number: nextNumber })
        : orgApi.createEmployeeIdScheme({ legal_entity_id: legalEntityId || undefined, prefix, separator, number_digits: numberDigits, next_number: nextNumber }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employee-id-schemes"] });
      toast.success(isEdit ? "Scheme updated" : "Scheme added");
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update scheme" : "Couldn’t add scheme", errorMessage(e)),
  });

  const preview = `${prefix || "…"}${separator}${String(nextNumber).padStart(numberDigits, "0")}`;
  const valid = prefix.trim().length > 0 && (isEdit || legalEntityId || canCreateGlobal);
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit employee ID scheme" : "Add employee ID scheme"}
      description={isEdit ? undefined : "Applies to new hires from now on — it doesn't renumber anyone already hired."}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="eis-form" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add scheme"}
          </button>
        </>
      }
    >
      <form id="eis-form" onSubmit={submit} className="space-y-4">
        {!isEdit && (
          <div>
            <label className="label" htmlFor="eis-scope">Scope</label>
            <select id="eis-scope" className="input" value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}>
              {canCreateGlobal ? <option value="">Whole tenant</option> : <option value="" disabled>Select a company…</option>}
              {availableEntities.map((en) => <option key={en.id} value={en.id}>{en.name}</option>)}
            </select>
            {!canCreateGlobal && !availableEntities.length && (
              <p className="hint">Every company you can administer already has its own scheme.</p>
            )}
          </div>
        )}
        <div>
          <label className="label" htmlFor="eis-prefix">Prefix</label>
          <input id="eis-prefix" className="input font-mono uppercase" placeholder="e.g. ABC" value={prefix} onChange={(e) => setPrefix(e.target.value.toUpperCase())} />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="eis-sep">Separator</label>
            <input id="eis-sep" className="input text-center font-mono" maxLength={5} value={separator} onChange={(e) => setSeparator(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="eis-digits">Digits</label>
            <input id="eis-digits" type="number" min={1} max={10} className="input" value={numberDigits} onChange={(e) => setNumberDigits(Math.max(1, Math.min(10, Number(e.target.value))))} />
          </div>
          <div>
            <label className="label" htmlFor="eis-next">Starts at</label>
            <input id="eis-next" type="number" min={1} className="input" value={nextNumber} onChange={(e) => setNextNumber(Math.max(1, Number(e.target.value)))} />
          </div>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-line bg-panel px-4 py-3 text-[13px]">
          <span className="text-fg-muted">Next employee ID will be</span>
          <span className="font-mono font-semibold tabular-nums text-fg">{preview}</span>
        </div>
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Users & access ─────────────────────────── */

const SCOPE_LABEL: Record<ScopeType, string> = {
  ALL: "All companies",
  LEGAL_ENTITY: "Specific companies",
  SELF: "Self only",
  DIRECT_REPORTS: "Direct reports",
  ALL_REPORTS: "Full reporting chain",
};

function AccessTab() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [toggling, setToggling] = useState<UserAccount | null>(null);
  const [resetting, setResetting] = useState<UserAccount | null>(null);
  const canCreate = !!user && (user.permissions.includes("iam.write") || user.permissions.includes("*"));
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => usersApi.listRoles() });
  const users = useQuery({ queryKey: ["users"], queryFn: () => usersApi.listUsers() });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));

  const setStatus = useMutation({
    mutationFn: (u: UserAccount) => usersApi.setStatus(u.id, u.status === "ACTIVE" ? "INACTIVE" : "ACTIVE"),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(u.status === "ACTIVE" ? "Login re-enabled" : "Login disabled", u.status === "ACTIVE"
        ? `${u.email ?? "The account"} can sign in again.`
        : `${u.email ?? "The account"} is signed out and can't sign in.`);
      setToggling(null);
    },
    onError: (e) => toast.error("Couldn't change the login", errorMessage(e)),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setAdding(true)} disabled={!canCreate} title={canCreate ? undefined : "You don't have permission to grant access"}>
          <Plus size={15} /> Add user
        </button>
      </div>
      {users.isError ? (
        <div className="card"><EmptyState icon={Users} title="Couldn't load users" description="The users API isn't responding." /></div>
      ) : users.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !users.data?.length ? (
        <div className="card">
          <EmptyState
            icon={Users}
            title="No logins yet"
            description={canCreate ? "Grant someone access to sign in and manage a company." : "No user accounts are visible to you yet."}
            action={canCreate ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add user</button> : undefined}
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Email</th><th>Role</th><th>Access</th><th className="hidden sm:table-cell">Linked employee</th><th>Sign-in</th>{canCreate && <th className="w-px"><span className="sr-only">Actions</span></th>}</tr></thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id + u.role}>
                  <td className="font-medium text-fg">{u.email ?? "—"}</td>
                  <td>{u.role}</td>
                  <td>
                    {u.scope_type === "LEGAL_ENTITY" && u.legal_entity_ids.length
                      ? u.legal_entity_ids.map((id) => entityName.get(id) ?? id).join(", ")
                      : SCOPE_LABEL[u.scope_type]}
                  </td>
                  <td className="hidden sm:table-cell">{u.employee_name ?? "—"}</td>
                  <td><SignInChip u={u} /></td>
                  {canCreate && (
                    <td className="whitespace-nowrap text-right">
                      {u.id !== user?.id && (
                        <>
                          <button className="btn-ghost btn-sm" onClick={() => setResetting(u)} title="Set a temporary password">
                            <KeyRound size={13} /> Reset password
                          </button>
                          <button className="btn-ghost btn-sm" onClick={() => setToggling(u)}>
                            {u.status === "ACTIVE" ? <><UserRoundX size={13} /> Disable</> : <><UserRoundCheck size={13} /> Enable</>}
                          </button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddUserSheet open={adding} onClose={() => setAdding(false)} entities={entities.data ?? []} roles={roles.data ?? []} />
      <ConfirmDialog
        open={!!toggling}
        onClose={() => setToggling(null)}
        onConfirm={() => toggling && setStatus.mutate(toggling)}
        loading={setStatus.isPending}
        title={toggling?.status === "ACTIVE" ? "Disable this login?" : "Re-enable this login?"}
        confirmLabel={toggling?.status === "ACTIVE" ? "Disable login" : "Re-enable"}
        description={toggling?.status === "ACTIVE"
          ? `${toggling?.email ?? "This person"} will be signed out immediately and won't be able to sign in until you re-enable it.`
          : `${toggling?.email ?? "This person"} will be able to sign in again.`}
      />
      <ResetPasswordSheet target={resetting} onClose={() => setResetting(null)} />
    </div>
  );
}

function ResetPasswordSheet({ target, onClose }: { target: UserAccount | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const problem = password ? passwordProblem(password) : null;

  const reset = useMutation({
    mutationFn: () => usersApi.resetPassword(target!.id, password),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("Password reset", `${u.email ?? "The account"} was signed out and must choose a new password at next sign-in.`);
      setPassword("");
      onClose();
    },
    onError: (e) => toast.error("Couldn't reset the password", errorMessage(e)),
  });

  const close = () => { setPassword(""); onClose(); };
  const submit = (e: FormEvent) => { e.preventDefault(); if (password && !problem) reset.mutate(); };

  return (
    <Sheet
      open={!!target}
      onClose={close}
      title="Reset password"
      description={target ? `Set a temporary password for ${target.email ?? "this account"}.` : undefined}
      footer={
        <>
          <button className="btn-secondary" onClick={close}>Cancel</button>
          <button className="btn-primary" type="submit" form="reset-password" disabled={!password || !!problem || reset.isPending}>
            {reset.isPending ? "Resetting…" : "Reset password"}
          </button>
        </>
      }
    >
      <form id="reset-password" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="rp-password">Temporary password</label>
          <div className="flex gap-2">
            <input id="rp-password" type="text" className="input font-mono" value={password} autoComplete="off"
              spellCheck={false} aria-invalid={!!problem} onChange={(e) => setPassword(e.target.value)} />
            <button type="button" className="btn-secondary shrink-0" onClick={() => setPassword(generateTempPassword())}>
              <Sparkles size={14} /> Generate
            </button>
            <button type="button" className="btn-secondary shrink-0" disabled={!password} aria-label="Copy password"
              onClick={() => navigator.clipboard?.writeText(password).then(() => toast.success("Copied", "Share it with them directly."))}>
              <Copy size={14} />
            </button>
          </div>
          <p className={`mt-1 text-xs ${problem ? "text-danger" : "text-fg-subtle"}`}>{problem ?? "At least 8 characters. Share it with them directly, not by email."}</p>
        </div>
        <p className="rounded-lg border border-line bg-panel px-3 py-2.5 text-[13px] text-fg-muted">
          They'll be signed out everywhere right away, and asked to choose their own password the next time they sign in.
        </p>
      </form>
    </Sheet>
  );
}

function AddUserSheet({ open, onClose, entities, roles }: {
  open: boolean; onClose: () => void; entities: LegalEntity[]; roles: Role[];
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { email: "", password: "", role: "", legalEntityIds: [] as string[], mustChange: true };
  const [form, setForm] = useState(empty);

  // Only offer roles whose permissions are a subset of the caller's own —
  // the server enforces this too, but hiding the option is better than a 403.
  // EMPLOYEE is self-service only: the API refuses it with a company scope, and employees get their
  // login when they're hired, so it isn't offered here.
  const grantableRoles = roles.filter(
    (r) => r.name !== "EMPLOYEE" &&
      (user?.permissions.includes("*") || r.permissions.every((p) => user?.permissions.includes(p)))
  );
  const roleName = form.role || grantableRoles[0]?.name || "";
  const canGrantAll = !!user?.isAllScope;

  const toggleEntity = (id: string) =>
    setForm((f) => ({
      ...f,
      legalEntityIds: f.legalEntityIds.includes(id) ? f.legalEntityIds.filter((x) => x !== id) : [...f.legalEntityIds, id],
    }));

  const create = useMutation({
    mutationFn: () =>
      usersApi.createUser({
        email: form.email.trim(),
        password: form.password,
        role: roleName,
        scope_type: "LEGAL_ENTITY",
        legal_entity_ids: form.legalEntityIds,
        must_change_password: form.mustChange,
      }),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("User created", `${u.email} can now sign in as ${u.role}`);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn't create user", errorMessage(e)),
  });

  const valid =
    /\S+@\S+\.\S+/.test(form.email) &&
    form.password.length >= 8 &&
    !!roleName &&
    form.legalEntityIds.length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add user"
      description="Grant someone a login and full access to the companies you choose."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="add-user" disabled={!valid || create.isPending}>
            {create.isPending ? "Creating…" : "Add user"}
          </button>
        </>
      }
    >
      <form id="add-user" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="us-email">Email</label>
          <input id="us-email" type="email" className="input" placeholder="e.g. admin@company.in" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="us-password">Temporary password</label>
          <input id="us-password" type="password" className="input" placeholder="At least 8 characters" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
          <label className="mt-2 flex items-center gap-2 text-[13px] text-fg">
            <input type="checkbox" className="checkbox" checked={form.mustChange}
              onChange={(e) => setForm((f) => ({ ...f, mustChange: e.target.checked }))} />
            Ask them to choose their own password when they first sign in
          </label>
          <p className="mt-1 text-xs text-fg-subtle">Share this with them directly, not by email.</p>
        </div>
        <div>
          <label className="label" htmlFor="us-role">Role</label>
          <select id="us-role" className="input" value={roleName} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
            {grantableRoles.map((r) => <option key={r.name} value={r.name}>{r.name}{r.description ? ` — ${r.description}` : ""}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Companies</label>
          {!canGrantAll && <p className="mb-2 text-xs text-fg-subtle">Only companies you have access to are shown.</p>}
          <div className="space-y-2 rounded-lg border border-line p-3">
            {entities.map((e) => (
              <label key={e.id} className="flex items-center gap-2 text-sm text-fg">
                <input type="checkbox" className="checkbox" checked={form.legalEntityIds.includes(e.id)} onChange={() => toggleEntity(e.id)} />
                {e.name}
              </label>
            ))}
            {!entities.length && <p className="text-sm text-fg-subtle">No companies available.</p>}
          </div>
        </div>
      </form>
    </Sheet>
  );
}

function StatusChip({ status }: { status: string }) {
  return <span className={`badge ${status === "ACTIVE" ? "badge-success" : "badge-neutral"}`}>{status}</span>;
}

/** What this login can actually do right now — an ACTIVE account of a separated employee can't sign in. */
function SignInChip({ u }: { u: UserAccount }) {
  if (u.status !== "ACTIVE") return <span className="badge badge-neutral">Disabled</span>;
  if (!u.can_sign_in) return <span className="badge badge-warning" title="The linked employee has left the company">Left company</span>;
  if (u.must_change_password) return <span className="badge badge-info" title="Has a temporary password">Must set password</span>;
  return <span className="badge badge-success">Active</span>;
}
