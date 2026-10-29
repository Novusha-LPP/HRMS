import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Building2, Landmark, MapPin, Briefcase, Users, Hash, Pencil, Trash2, KeyRound, UserRoundX, UserRoundCheck, History, ArrowLeft, ChevronRight, UserPlus, Layers, Armchair, Wallet } from "lucide-react";
import { orgApi } from "../api/org";
import { peopleApi, personnelActionsApi } from "../api/people";
import type { Employment } from "../api/people";
import { departmentMembers, employeeMatches, employeeName, moveTeamMembers } from "../lib/teamManagement";
import type { CompanyDetails, LegalEntity, Location, OrgUnit, Job, EmployeeIdScheme, ChangeLogEntry, Grade, CostCentre, Position, MasterStatus } from "../api/org";
import { dashboardApi } from "../api/dashboard";
import { usersApi } from "../api/users";
import type { Role, UserAccount } from "../api/users";
import { ResetPasswordSheet, SCOPE_LABEL, SignInChip } from "../components/users/AccessPanel";
import { UsageHelpButton } from "../components/ui/UsageHelpButton";
import { BrandingTab } from "../components/branding/BrandingTab";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { Sheet, ConfirmDialog } from "../components/ui/Overlay";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { format } from "date-fns";

import type { UsageHelpTopic } from "../lib/usageHelp";

type Tab = "overview" | "companies" | "branding" | "departments" | "locations" | "jobs" | "grades" | "positions" | "cost-centres" | "employee-ids" | "access";

const TAB_HELP_TOPICS: Record<Tab, UsageHelpTopic> = {
  overview: "org-overview",
  companies: "companies",
  branding: "branding",
  departments: "departments",
  locations: "locations",
  jobs: "jobs",
  grades: "grades",
  positions: "positions",
  "cost-centres": "cost-centres",
  "employee-ids": "employee-ids",
  access: "company-admins",
};

export function OrganizationPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const setTab = (t: Tab) => setParams({ tab: t }, { replace: true });

  const canCreateCompany = !!user?.isAllScope;
  const canManageAccess = !!user && (user.permissions.includes("iam.read") || user.permissions.includes("*"));
  const canWriteOrg = !!user && (user.permissions.includes("org.write") || user.permissions.includes("*"));

  return (
    <>
      <PageHeader
        title="Organization"
        description="Companies, departments, locations, job titles, grades, positions and cost centres across the group."
        actions={tab === "companies" && params.get("company") ? undefined : <UsageHelpButton key={tab} topic={TAB_HELP_TOPICS[tab] ?? "organization"} />}
      />
      <Tabs
        className="mb-6"
        value={tab}
        onChange={setTab}
        items={[
          { value: "overview", label: "Overview", help: <UsageHelpButton topic="org-overview" iconOnly /> },
          { value: "companies", label: "Companies", help: <UsageHelpButton topic="companies" iconOnly /> },
          { value: "branding", label: "Branding", help: <UsageHelpButton topic="branding" iconOnly /> },
          { value: "departments", label: "Departments", help: <UsageHelpButton topic="departments" iconOnly /> },
          { value: "locations", label: "Locations", help: <UsageHelpButton topic="locations" iconOnly /> },
          { value: "jobs", label: "Job titles", help: <UsageHelpButton topic="jobs" iconOnly /> },
          { value: "grades", label: "Grades", help: <UsageHelpButton topic="grades" iconOnly /> },
          { value: "positions", label: "Positions", help: <UsageHelpButton topic="positions" iconOnly /> },
          { value: "cost-centres", label: "Cost centres", help: <UsageHelpButton topic="cost-centres" iconOnly /> },
          { value: "employee-ids", label: "Employee IDs", help: <UsageHelpButton topic="employee-ids" iconOnly /> },
          ...(canManageAccess ? [{ value: "access" as const, label: "Company admins", help: <UsageHelpButton topic="company-admins" iconOnly /> }] : []),
        ]}
      />
      {tab === "overview" && <OrganizationOverviewTab onNavigateTab={setTab} />}
      {tab === "companies" && <CompaniesTab canCreate={canCreateCompany} />}
      {tab === "branding" && <BrandingTab canEditGroup={canCreateCompany && canWriteOrg} canEdit={canWriteOrg} />}
      {tab === "departments" && <DepartmentsTab />}
      {tab === "locations" && <LocationsTab />}
      {tab === "jobs" && <JobsTab />}
      {tab === "grades" && <GradesTab />}
      {tab === "positions" && <PositionsTab />}
      {tab === "cost-centres" && <CostCentresTab />}
      {tab === "employee-ids" && <EmployeeIdSchemesTab canCreateGlobal={canCreateCompany} />}
      {tab === "access" && canManageAccess && <AccessTab />}
    </>
  );
}

/* ─────────────────────────── Summary of Organization (Overview) ─────────────────────────── */

function OrganizationOverviewTab({ onNavigateTab }: { onNavigateTab: (tab: Tab) => void }) {
  const [distView, setDistView] = useState<"company" | "dept">("company");
  const { data: hrData, isPending: hrPending } = useQuery({
    queryKey: ["dash-hr", "org-overview"],
    queryFn: () => dashboardApi.hr("headcount,org_summary,entity_distribution,department_distribution"),
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
    select: (rows) => rows.filter((u) => u.type !== "DEPARTMENT_TEMPLATE"),
  });

  const isLoading = hrPending || entitiesPending;
  const orgSummary = (hrData?.org_summary as Record<string, unknown>) ?? null;
  const entityDist = (hrData?.entity_distribution as { company: string; short_name?: string; count: number }[]) ?? [];
  const deptDist = (hrData?.department_distribution as { department: string; count: number }[]) ?? [];
  const hc = (hrData?.headcount as Record<string, unknown>) ?? {};
  const total = typeof hc.total === "number" ? hc.total : 0;

  const companyItems = entityDist.length > 0
    ? entityDist
    : entities.map((e) => ({ company: e.name, short_name: e.short_name, count: 0 }));

  const deptItems = deptDist.length > 0
    ? deptDist
    : orgUnits.map((u) => ({ department: u.name, count: 0 }));

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
        <div className="card p-5 space-y-4">
          <div className="flex justify-between items-center">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-8 w-36 rounded-lg" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
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
            {/* Left Column: Seniority & Retention */}
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

            {/* Right Column: Operating Hubs & Locations */}
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <p className="eyebrow">Operating locations & hubs ({locations.length})</p>
                <button
                  onClick={() => onNavigateTab("locations")}
                  className="link text-xs"
                >
                  Manage locations
                </button>
              </div>
              <div className="divide-y divide-line rounded-lg border border-line">
                {locations.length > 0 ? (
                  locations.slice(0, 5).map((l) => (
                    <div
                      key={l.id}
                      className="flex items-center justify-between px-3.5 py-2.5 text-[13px]"
                    >
                      <div className="min-w-0 pr-2">
                        <span className="font-medium text-fg block truncate">{l.name}</span>
                        {(l.city || l.country_code) && (
                          <span className="text-xs text-fg-subtle">
                            {[l.city, l.country_code].filter(Boolean).join(", ")}
                          </span>
                        )}
                      </div>
                      <span className="badge badge-neutral text-xs">{l.country_code || "HUB"}</span>
                    </div>
                  ))
                ) : (
                  <div className="p-4 text-center text-xs text-fg-subtle">
                    No operating locations configured yet.
                  </div>
                )}
                {locations.length > 5 && (
                  <div className="p-2 text-center text-xs text-fg-subtle">
                    +{locations.length - 5} more locations
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─── Workforce Allocation Card ─────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600 dark:text-brand-400">
              <Building2 size={16} />
            </div>
            <div>
              <h3 className="card-title">Workforce Allocation</h3>
              <p className="card-desc">Active employees distributed across group entities & departments</p>
            </div>
          </div>
          {/* Segmented Switcher */}
          <div className="seg">
            <button
              onClick={() => setDistView("company")}
              data-active={distView === "company"}
              className="seg-item"
            >
              By Company ({companyItems.length})
            </button>
            <button
              onClick={() => setDistView("dept")}
              data-active={distView === "dept"}
              className="seg-item"
            >
              By Department ({deptItems.length})
            </button>
          </div>
        </div>

        <div className="p-5">
          {distView === "company" ? (
            companyItems.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {companyItems.map((e) => {
                  const pct = total > 0 ? Math.round((e.count / total) * 100) : 0;
                  return (
                    <Link
                      key={e.company}
                      to={`/employees?company=${encodeURIComponent(e.company)}`}
                      className="group rounded-xl border border-line bg-surface-raised p-3.5 hover:border-brand-500/40 hover:bg-muted/40 transition-all"
                    >
                      <div className="flex items-center justify-between text-[13px] mb-2">
                        <span className="font-semibold text-fg truncate group-hover:text-brand-600 dark:group-hover:text-brand-400">
                          {e.company}
                        </span>
                        <span className="tabular-nums font-bold text-fg ml-2">{e.count}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-brand-500 transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="flex items-center justify-between text-[11px] text-fg-subtle mt-1.5">
                        <span>{pct}% of workforce</span>
                        <span className="opacity-0 group-hover:opacity-100 text-brand-600 dark:text-brand-400 font-medium">Filter →</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-fg-subtle">
                No company distribution data available.
              </div>
            )
          ) : (
            deptItems.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {deptItems.map((d) => {
                  const pct = total > 0 ? Math.round((d.count / total) * 100) : 0;
                  return (
                    <div key={d.department} className="rounded-xl border border-line bg-surface-raised p-3.5">
                      <div className="flex items-center justify-between text-[13px] mb-2">
                        <span className="font-semibold text-fg truncate">{d.department}</span>
                        <span className="tabular-nums font-bold text-fg ml-2">{d.count}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                      <p className="text-[11px] text-fg-subtle mt-1.5">{pct}% of active workforce</p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-fg-subtle">
                No department distribution data available.
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Companies ─────────────────────────── */

function CompaniesTab({ canCreate }: { canCreate: boolean }) {
  const [params, setParams] = useSearchParams();
  const selectedCompany = params.get("company");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<LegalEntity | null>(null);
  const [viewingHistory, setViewingHistory] = useState<LegalEntity | null>(null);
  const { data, isPending, isError, refetch } = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });

  if (selectedCompany) return <CompanyDepartmentsTab key={selectedCompany} companyId={selectedCompany} onBack={() => { const next = new URLSearchParams(params); next.delete("company"); setParams(next); }} />;

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
                <div className="flex gap-1">
                  <button className="btn-icon" onClick={() => setViewingHistory(e)} aria-label={`History for ${e.name}`}><History size={14} /></button>
                  <button className="btn-icon" onClick={() => setEditing(e)} aria-label={`Edit ${e.name}`} disabled={!canCreate} title={canCreate ? undefined : "Only a group-level administrator can edit a company"}><Pencil size={14} /></button>
                </div>
              </div>
              <p className="mt-3 text-[15px] font-semibold text-fg">{e.name}</p>
              <p className="text-xs text-fg-subtle">{e.short_name ?? "—"} · {e.country_code}</p>
              <div className="mt-3"><StatusChip status={e.status} /></div>
              <button className="btn-secondary w-full mt-4" onClick={() => { const next = new URLSearchParams(params); next.set("company", e.id); setParams(next); }}>Departments & teams <ChevronRight size={15} /></button>
            </div>
          ))}
        </div>
      )}
      <CompanySheet open={adding} onClose={() => setAdding(false)} />
      <CompanySheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.name}` : "History"}
        fetcher={viewingHistory ? () => orgApi.legalEntityHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function CompanySheet({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: LegalEntity }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = { establishmentDate: initial?.establishment_date ?? "", name: initial?.name ?? "", shortName: initial?.short_name ?? "", country: initial?.country_code ?? "IN", fyStart: initial?.financial_year_start_month ?? 0 };
  const [form, setForm] = useState(empty);
  const emptyDetails = Object.fromEntries(COMPANY_DETAIL_FIELDS.map((f) => [f.key, initial?.[f.key] ?? ""])) as Record<keyof CompanyDetails, string>;
  const [details, setDetails] = useState(emptyDetails);

  const save = useMutation({
    mutationFn: () => {
      const companyDetails = Object.fromEntries(COMPANY_DETAIL_FIELDS.map((f) => [f.key, details[f.key].trim() || null])) as Partial<CompanyDetails>;
      const body = { establishment_date: form.establishmentDate || null, name: form.name.trim(), short_name: form.shortName.trim() || undefined, country_code: form.country, financial_year_start_month: form.fyStart || undefined, ...companyDetails };
      return isEdit ? orgApi.updateLegalEntity(initial!.id, { ...body, version: initial!.version }) : orgApi.createLegalEntity(body);
    },
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["legal-entities"] });
      qc.invalidateQueries({ queryKey: ["dash-hr"] });
      toast.success(isEdit ? "Company updated" : "Company added", e.name);
      setForm(empty);
      setDetails(emptyDetails);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update company" : "Couldn’t add company", errorMessage(e)),
  });

  const valid = form.name.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit company" : "Add company"}
      description={isEdit ? "Renaming here updates it everywhere it's referenced — see History for the record of every change." : "A new legal entity people can be hired into — a sister company."}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="company-form" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add company"}
          </button>
        </>
      }
    >
      <form id="company-form" onSubmit={submit} className="space-y-4">
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
        <div>
          <label className="label" htmlFor="co-established">Company establishment date</label>
          <input id="co-established" type="date" className="input" value={form.establishmentDate}
            onChange={(e) => setForm((f) => ({ ...f, establishmentDate: e.target.value }))} />
          <p className="mt-1 text-xs text-fg-subtle">Celebrate this date each year in today’s dashboard highlights.</p>
        </div>
        <div>
          <label className="label" htmlFor="co-fy">Financial year starts <span className="font-normal text-fg-subtle">(optional — inherits the tenant default)</span></label>
          <select id="co-fy" className="input" value={form.fyStart} onChange={(e) => setForm((f) => ({ ...f, fyStart: Number(e.target.value) }))}>
            <option value={0}>Tenant default</option>
            {MONTH_NAMES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
        </div>
        <div className="border-t border-line pt-4">
          <p className="text-sm font-semibold text-fg">Details for payslips</p>
          <p className="mb-3 text-xs text-fg-subtle">The registered name and address print in every payslip’s header, with the registration numbers you fill in.</p>
          <div className="grid grid-cols-2 gap-3">
            {COMPANY_DETAIL_FIELDS.map((f) => (
              <div key={f.key} className={f.wide ? "col-span-2" : undefined}>
                <label className="label" htmlFor={`co-${f.key}`}>{f.label}</label>
                <input id={`co-${f.key}`} className={`input ${f.code ? "font-mono uppercase" : ""}`} maxLength={f.max} placeholder={f.placeholder}
                  value={details[f.key]} onChange={(e) => setDetails((d) => ({ ...d, [f.key]: e.target.value }))} />
              </div>
            ))}
          </div>
        </div>
      </form>
    </Sheet>
  );
}

/** What payslips print about the employer; the API checks each number's format. */
const COMPANY_DETAIL_FIELDS: { key: keyof CompanyDetails; label: string; placeholder?: string; max: number; wide?: boolean; code?: boolean }[] = [
  { key: "registered_name", label: "Registered name", placeholder: "e.g. Novusha Industries Private Limited", max: 255, wide: true },
  { key: "address_line1", label: "Address line 1", placeholder: "Plot 12, MIDC", max: 255, wide: true },
  { key: "address_line2", label: "Address line 2", placeholder: "Andheri East", max: 255, wide: true },
  { key: "city", label: "City", placeholder: "Mumbai", max: 100 },
  { key: "state_code", label: "State", placeholder: "MH", max: 10, code: true },
  { key: "pincode", label: "PIN code", placeholder: "400093", max: 10 },
  { key: "cin", label: "CIN", placeholder: "U63090MH2015PTC123456", max: 30, code: true },
  { key: "pan", label: "PAN", placeholder: "AAACA1234A", max: 20, code: true },
  { key: "tan", label: "TAN", placeholder: "MUMA12345B", max: 20, code: true },
  { key: "gstin", label: "GSTIN", placeholder: "27AAACA1234A1Z5", max: 30, code: true },
  { key: "pf_establishment_code", label: "PF establishment code", placeholder: "MHBAN0012345000", max: 30, code: true },
  { key: "esic_employer_code", label: "ESIC employer code", placeholder: "17 digits", max: 30, code: true },
];

/** Shared read-only view of an entity's change history — old value, new value, who, when. */
function HistoryModal({ open, onClose, title, fetcher }: {
  open: boolean; onClose: () => void; title: string; fetcher?: () => Promise<ChangeLogEntry[]>;
}) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["entity-history", title],
    queryFn: () => fetcher!(),
    enabled: open && !!fetcher,
  });

  return (
    <Sheet open={open} onClose={onClose} title={title} description="Every change to this record — oldest at the bottom.">
      {isError ? (
        <p className="text-[13px] text-danger">Couldn’t load history.</p>
      ) : isPending ? (
        <div className="space-y-2">{[0, 1].map((i) => <Skeleton key={i} className="h-16 rounded-lg" />)}</div>
      ) : !data?.length ? (
        <p className="text-[13px] text-fg-subtle">No changes recorded yet.</p>
      ) : (
        <ul className="space-y-3">
          {data.map((h) => (
            <li key={h.id} className="rounded-lg border border-border-subtle p-3">
              <div className="flex items-center justify-between text-xs text-fg-subtle">
                <span className="badge badge-neutral">{h.action}</span>
                <span>{format(new Date(h.changed_at), "d MMM yyyy, h:mm a")} · {h.changed_by_name ?? "Unknown"}</span>
              </div>
              <ul className="mt-2 space-y-1 text-[13px]">
                {Object.entries(h.changes).map(([field, { old, new: next }]) => (
                  <li key={field}>
                    <span className="font-medium text-fg">{field.replace(/_/g, " ")}: </span>
                    <span className="text-fg-subtle line-through">{old === null || old === undefined ? "—" : String(old)}</span>
                    {" → "}
                    <span className="text-fg">{next === null || next === undefined ? "—" : String(next)}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}

/* ─────────────────────────── Departments ─────────────────────────── */

export function DepartmentsTab() {
  const { user } = useAuth();
  const canManage = !!user?.isAllScope;
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<OrgUnit | null>(null);
  const [assigning, setAssigning] = useState<string[] | null>(null);
  const [search, setSearch] = useState("");
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const catalog = (units.data ?? []).filter((u) => u.type === "DEPARTMENT_TEMPLATE");
  const visible = catalog.filter((d) => `${d.name} ${d.code ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  const openCompany = (id: string) => { const next = new URLSearchParams(params); next.set("tab", "companies"); next.set("company", id); setParams(next); };
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-3"><input className="input flex-1 min-w-48" aria-label="Search shared departments" placeholder="Search department name or code…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <button className="btn-secondary" disabled={!catalog.length || !entities.data?.length} onClick={() => setAssigning([])}><Building2 size={15} /> Assign to company</button>
      {canManage && <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Create department</button>}</div>
    {units.isPending ? <Skeleton className="h-48" /> : units.isError ? <div className="card p-5"><p>Couldn’t load departments.</p><button className="link" onClick={() => units.refetch()}>Try again</button></div>
      : !visible.length ? <div className="card"><EmptyState icon={Landmark} title={search ? "No matching departments" : "Create your shared department list"}
        description={canManage ? "Add Sales, HR, Finance or other departments. Company assignment comes next." : "A group administrator can create shared departments for your companies."} /></div>
      : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{visible.map((d) => {
        const assigned = (units.data ?? []).filter((u) => u.department_template_id === d.id && u.legal_entity_id);
        return <div className="card p-5 space-y-4" key={d.id}>
          <div className="flex items-start justify-between gap-2"><div><h3 className="text-base font-semibold">{d.name}</h3><p className="text-xs text-fg-subtle">{d.code || "Shared department"}</p></div>
            {canManage && <button className="btn-icon" aria-label={`Edit ${d.name}`} onClick={() => setEditing(d)}><Pencil size={14} /></button>}</div>
          <div className="flex flex-wrap gap-2">{assigned.length ? assigned.map((u) => <button key={u.id} className="badge badge-brand" onClick={() => openCompany(u.legal_entity_id!)}>{entities.data?.find((e) => e.id === u.legal_entity_id)?.name ?? "Company"} <ChevronRight size={12} /></button>) : <p className="text-xs text-fg-subtle">Not assigned to a company yet</p>}</div>
          <button className="btn-secondary btn-sm w-full" disabled={!entities.data?.length} onClick={() => setAssigning([d.id])}><Building2 size={14} /> Assign to company</button>
        </div>;
      })}</div>}
    {adding && <SharedDepartmentSheet onClose={() => setAdding(false)} />}
    {editing && <SharedDepartmentSheet key={editing.id} initial={editing} onClose={() => setEditing(null)} />}
    {assigning && <AssignDepartmentsSheet initialIds={assigning} departments={catalog} units={units.data ?? []} entities={entities.data ?? []} onClose={() => setAssigning(null)} />}
  </div>;
}

function SharedDepartmentSheet({ initial, onClose }: { initial?: OrgUnit; onClose: () => void }) {
  const qc = useQueryClient(); const toast = useToast();
  const [name, setName] = useState(initial?.name ?? ""); const [code, setCode] = useState(initial?.code ?? "");
  const save = useMutation({
    mutationFn: () => initial ? orgApi.updateOrgUnit(initial.id, { name: name.trim(), code: code.trim() || null, version: initial.version })
      : orgApi.createOrgUnit({ name: name.trim(), code: code.trim() || undefined, type: "DEPARTMENT_TEMPLATE", effective_from: format(new Date(), "yyyy-MM-dd") }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["org-units"] }); void qc.invalidateQueries({ queryKey: ["employees"] }); void qc.invalidateQueries({ queryKey: ["dash-hr"] }); toast.success(initial ? "Shared department updated" : "Department created"); onClose(); },
    onError: (e) => toast.error("Couldn’t save department", errorMessage(e)),
  });
  return <Sheet open onClose={onClose} title={initial ? "Edit shared department" : "Create department"}
    description={initial ? "Name and code changes update this department in every assigned company." : "Define the department first. Assign it to one or more companies afterward."}
    footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" type="submit" form="shared-department-form" disabled={!name.trim() || save.isPending}>{save.isPending ? "Saving…" : initial ? "Save changes" : "Create department"}</button></>}>
    <form id="shared-department-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }}>
      <div><label className="label" htmlFor="shared-department-name">Department name</label><input className="input" id="shared-department-name" required maxLength={255} placeholder="e.g. Sales" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div><label className="label" htmlFor="shared-department-code">Code (optional)</label><input className="input" id="shared-department-code" maxLength={50} placeholder="e.g. SALES" value={code} onChange={(e) => setCode(e.target.value)} /></div>
    </form>
  </Sheet>;
}

function AssignDepartmentsSheet({ initialIds = [], companyId, departments, units, entities, onClose }: {
  initialIds?: string[]; companyId?: string; departments: OrgUnit[]; units: OrgUnit[]; entities: LegalEntity[]; onClose: () => void;
}) {
  const qc = useQueryClient(); const toast = useToast();
  const [entityId, setEntityId] = useState(companyId ?? entities[0]?.id ?? "");
  const [selected, setSelected] = useState(new Set(initialIds)); const [search, setSearch] = useState("");
  const already = new Set(units.filter((u) => u.legal_entity_id === entityId).map((u) => u.department_template_id));
  const chosen = departments.filter((d) => selected.has(d.id) && !already.has(d.id));
  const visible = departments.filter((d) => `${d.name} ${d.code ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  const save = useMutation({ mutationFn: () => orgApi.assignDepartments(entityId, chosen.map((d) => d.id)),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["org-units"] }); toast.success("Departments assigned", entities.find((e) => e.id === entityId)?.name); onClose(); },
    onError: (e) => toast.error("Couldn’t assign departments", errorMessage(e)),
  });
  return <Sheet open onClose={onClose} title="Assign departments to company" description="Choose departments from the shared list. This company will manage its own teams and employees."
    footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!entityId || !chosen.length || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Assigning…" : `Assign ${chosen.length || ""} ${chosen.length === 1 ? "department" : "departments"}`}</button></>}>
    <div className="space-y-4"><div><label className="label" htmlFor="assign-department-company">Company / entity</label><select className="input" id="assign-department-company" value={entityId} disabled={!!companyId || save.isPending} onChange={(e) => setEntityId(e.target.value)}>
      {entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></div>
      <input className="input" aria-label="Search departments to assign" placeholder="Search departments…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <p className="text-xs text-fg-subtle">{chosen.length} selected · Existing assignments are marked below.</p>
      <div className="divide-y divide-line rounded-xl border border-line">{visible.map((d) => <label key={d.id} className="flex items-center gap-3 p-3">
        <input type="checkbox" className="checkbox" checked={already.has(d.id) || selected.has(d.id)} disabled={already.has(d.id) || save.isPending} aria-label={`Assign ${d.name}`}
          onChange={() => setSelected((old) => { const next = new Set(old); if (next.has(d.id)) next.delete(d.id); else next.add(d.id); return next; })} />
        <div className="flex-1"><p className="font-medium text-sm">{d.name}</p><p className="text-xs text-fg-subtle">{d.code}</p></div>{already.has(d.id) && <span className="badge badge-neutral">Assigned</span>}
      </label>)}{!visible.length && <p className="p-4 text-sm text-fg-subtle">{departments.length ? "No matching departments." : "Create departments in the shared department list first."}</p>}</div>
    </div>
  </Sheet>;
}

function CompanyDepartmentsTab({ companyId, onBack }: { companyId: string; onBack: () => void }) {
  const [adding, setAdding] = useState(false);
  const [departmentId, setDepartmentId] = useState<string | null>(null);
  const [addingTeam, setAddingTeam] = useState(false);
  const [editing, setEditing] = useState<OrgUnit | null>(null);
  const [viewingHistory, setViewingHistory] = useState<OrgUnit | null>(null);

  const [search, setSearch] = useState("");
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });
  const employees = useQuery({ queryKey: ["employees", "team-members"], queryFn: () => peopleApi.listAllEmployees() });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));
  const department = units.data?.find((u) => u.id === departmentId && u.legal_entity_id === companyId);
  const departments = (units.data ?? []).filter((u) => u.type !== "COMPANY" && u.type !== "TEAM"
    && u.type !== "DEPARTMENT_TEMPLATE" && u.legal_entity_id === companyId
    && `${u.name} ${u.code ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  const teamsFor = (id: string) => (units.data ?? []).filter((u) => u.type === "TEAM" && u.parent_id === id);
  const membersFor = (d: OrgUnit) => departmentMembers(d, teamsFor(d.id), employees.data ?? []);
  if (entities.isPending) return <Skeleton className="h-48" />;
  if (entities.isError) return <div className="card p-5"><p>Couldn’t load this company.</p><button className="link" onClick={() => entities.refetch()}>Try again</button></div>;
  if (!entities.data?.some((e) => e.id === companyId)) return <div className="card p-5"><p>This company is not available to your account.</p><button className="btn-secondary mt-3" onClick={onBack}>All companies</button></div>;

  return <div className="space-y-5">
    {!department && <><button className="btn-secondary btn-sm" onClick={onBack}><ArrowLeft size={14} /> All companies</button>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">{entityName.get(companyId)} — Departments</h2><p className="text-sm text-fg-subtle mt-1">Manage this company’s teams and employees within each assigned department.</p></div><UsageHelpButton topic="company-departments" /></div></>}
    {department ? <>
      <button className="btn-secondary btn-sm" onClick={() => { setDepartmentId(null); setAddingTeam(false); }}><ArrowLeft size={14} /> All departments</button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs text-fg-subtle mb-1">{entityName.get(department.legal_entity_id ?? "")}</p>
          <h2 className="text-xl font-semibold">{department.name}</h2><p className="text-sm text-fg-subtle mt-1">Organize your department’s employees into teams.</p></div>
        <div className="flex gap-2"><UsageHelpButton topic="teams" /><button className="btn-secondary btn-sm" onClick={() => setEditing(department)}><Pencil size={14} /> Department settings</button>
          <button className="btn-primary btn-sm" onClick={() => setAddingTeam(true)}><Plus size={14} /> Create team</button></div>
      </div>
      <TeamWorkspace key={department.id} department={department} teams={teamsFor(department.id)} employees={employees.data ?? []}
        loading={employees.isPending} failed={employees.isError} retry={() => employees.refetch()}
        onCreate={() => setAddingTeam(true)} onEdit={setEditing} onHistory={setViewingHistory} />
    </> : <>
      <div className="flex flex-wrap items-center gap-3">
        <input className="input flex-1 min-w-48" aria-label="Search departments" placeholder="Search departments…" value={search} onChange={(e) => setSearch(e.target.value)} />

        <button className="btn-primary" onClick={() => setAdding(true)} disabled={!entities.data?.length}><Plus size={15} /> Assign departments</button>
      </div>
      {units.isError ? <div className="card p-5"><p>Couldn’t load departments.</p><button className="link" onClick={() => units.refetch()}>Try again</button></div>
        : units.isPending ? <Skeleton className="h-64 rounded-xl" />
        : !departments.length ? <div className="card"><EmptyState icon={Landmark} title={search ? "No matching departments" : "Assign departments to this company"}
            description="Choose departments from the shared department list. Then create teams for this company." /></div>
        : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{departments.map((d) => <div className="card p-5 flex flex-col gap-4" key={d.id}>
          <div className="flex items-start justify-between gap-2"><div><h3 className="text-base font-semibold">{d.name}</h3><p className="text-xs text-fg-subtle mt-1">{entityName.get(d.legal_entity_id ?? "") ?? "Shared department"}</p></div>
            <div className="flex">{!d.department_template_id && <button className="btn-icon" onClick={() => setEditing(d)} aria-label={`Edit ${d.name}`}><Pencil size={14} /></button>}<button className="btn-icon" onClick={() => setViewingHistory(d)} aria-label={`History for ${d.name}`}><History size={14} /></button></div></div>
          <div className="flex gap-4 text-sm text-fg-muted"><span>{teamsFor(d.id).length} teams</span><span>{employees.isPending ? "…" : employees.isError ? "—" : membersFor(d).length} employees</span></div>
          <button className="btn-secondary w-full" onClick={() => setDepartmentId(d.id)}>Manage teams & employees <ChevronRight size={15} /></button>
        </div>)}</div>}
    </>}
    {department && <DepartmentSheet key={`team-${department.id}-${addingTeam}`} open={addingTeam} onClose={() => setAddingTeam(false)} entities={entities.data ?? []} departments={units.data ?? []} teamParent={department} />}
    {adding && <AssignDepartmentsSheet companyId={companyId} departments={(units.data ?? []).filter((u) => u.type === "DEPARTMENT_TEMPLATE")} units={units.data ?? []} entities={entities.data ?? []} onClose={() => setAdding(false)} />}
    <DepartmentSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} entities={entities.data ?? []} departments={units.data ?? []} initial={editing ?? undefined} />
    <HistoryModal open={viewingHistory !== null} onClose={() => setViewingHistory(null)} title={viewingHistory ? `History — ${viewingHistory.name}` : "History"}
      fetcher={viewingHistory ? () => orgApi.orgUnitHistory(viewingHistory.id) : undefined} />
  </div>;
}

function TeamWorkspace({ department, teams, employees, loading, failed, retry, onCreate, onEdit, onHistory }: {
  department: OrgUnit; teams: OrgUnit[]; employees: Employment[]; loading: boolean; failed: boolean; retry: () => void;
  onCreate: () => void; onEdit: (team: OrgUnit) => void; onHistory: (team: OrgUnit) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [picker, setPicker] = useState<{ target: string; ids: string[] } | null>(null);
  const members = departmentMembers(department, teams, employees);
  const activeTeam = teams.find((t) => t.id === filter);
  const effectiveFilter = filter === "all" || filter === department.id || activeTeam ? filter : "all";
  const label = activeTeam?.name ?? (effectiveFilter === department.id ? "Employees without a team" : "All employees");
  const visible = members.filter((e) => (effectiveFilter === "all" || e.org_unit_id === effectiveFilter) && employeeMatches(e, search));
  const groups = [{ id: "all", name: "All employees", count: members.length }, { id: department.id, name: "Without a team", count: members.filter((e) => e.org_unit_id === department.id).length },
    ...teams.map((t) => ({ id: t.id, name: t.name, count: members.filter((e) => e.org_unit_id === t.id).length }))];
  return <>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{groups.map((g) => <button key={g.id} type="button" aria-pressed={effectiveFilter === g.id}
      className={`card p-4 text-left transition-colors ${effectiveFilter === g.id ? "ring-2 ring-brand-500 bg-brand-500/5" : "hover:bg-surface-raised"}`}
      onClick={() => { setFilter(g.id); setSearch(""); }}><div className="flex items-center gap-2 text-sm font-medium"><Users size={16} /><span className="truncate">{g.name}</span></div>
      <p className="mt-3 text-2xl font-semibold">{loading ? "…" : failed ? "—" : g.count}</p><p className="text-xs text-fg-subtle">{g.count === 1 ? "employee" : "employees"}</p></button>)}</div>
    {!teams.length && <div className="card p-5 flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">Start by creating a team</h3><p className="text-sm text-fg-subtle">For example, split Sales into Inside Sales and Field Sales.</p></div><button className="btn-primary btn-sm" onClick={onCreate}><Plus size={14} /> Create team</button></div>}
    <section className="card overflow-hidden">
      <div className="p-5 border-b border-line flex flex-wrap items-center justify-between gap-3"><div><h3 className="card-title">{label}</h3><p className="card-desc">{activeTeam ? "View members or add employees from this department." : "Choose a team above, or assign employees to a team."}</p></div>
        <div className="flex flex-wrap gap-2">{activeTeam && <><button className="btn-secondary btn-sm" onClick={() => onEdit(activeTeam)}><Pencil size={14} /> Edit team</button><button className="btn-icon" aria-label={`History for ${activeTeam.name}`} onClick={() => onHistory(activeTeam)}><History size={14} /></button></>}
          <button className="btn-primary btn-sm" disabled={loading || failed || !teams.length || !members.length}
            onClick={() => setPicker({ target: activeTeam?.id ?? teams[0]?.id ?? department.id, ids: [] })}><UserPlus size={14} /> {activeTeam ? "Add employees" : "Assign employees"}</button></div>
      </div>
      {loading ? <div className="p-5"><Skeleton className="h-32" /></div> : failed ? <div className="p-5"><p>Couldn’t load employees.</p><button className="link" onClick={retry}>Try again</button></div> : <>
        <div className="px-5 pt-4"><input className="input" aria-label="Search team members" placeholder="Search employee name or number…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        {!visible.length ? <EmptyState icon={Users} title={search ? "No matching employees" : activeTeam ? "This team is ready for employees" : "No employees here yet"}
          description={search ? "Try a different name or employee number." : members.length ? "Use Add employees to choose people from your department." : "Place employees in this department from the Employees page, then assign them to teams here."} />
          : <ul className="divide-y divide-line p-5">{visible.map((e) => <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3 min-w-0"><div className="h-10 w-10 rounded-full bg-brand-500/10 text-accent flex items-center justify-center shrink-0"><Users size={17} /></div>
              <div className="min-w-0"><p className="font-medium truncate">{employeeName(e)}</p><p className="text-xs text-fg-subtle">{e.employee_number}{e.designation ? ` · ${e.designation}` : ""}</p></div></div>
            <div className="flex items-center gap-3"><span className={`badge ${e.org_unit_id === department.id ? "badge-neutral" : "badge-brand"}`}>{teams.find((t) => t.id === e.org_unit_id)?.name ?? "No team"}</span>
              <button className="btn-secondary btn-sm" disabled={!teams.length && e.org_unit_id === department.id} onClick={() => setPicker({ target: e.org_unit_id === department.id ? teams[0]?.id ?? department.id : department.id, ids: [e.id] })}>{e.org_unit_id === department.id ? "Assign team" : "Move"}</button></div>
          </li>)}</ul>}
      </>}
    </section>
    {picker && <TeamMemberPicker department={department} teams={teams} members={members} initial={picker} onClose={() => setPicker(null)} />}
  </>;
}

function TeamMemberPicker({ department, teams, members, initial, onClose }: {
  department: OrgUnit; teams: OrgUnit[]; members: Employment[]; initial: { target: string; ids: string[] }; onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [target, setTarget] = useState(initial.target);
  const [selected, setSelected] = useState(new Set(initial.ids));
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState(false);
  const [failures, setFailures] = useState<{ id: string; message: string }[]>([]);
  const [progress, setProgress] = useState(0);
  const eligible = members.filter((e) => e.org_unit_id !== target);
  const visible = eligible.filter((e) => employeeMatches(e, search));
  const chosen = eligible.filter((e) => selected.has(e.id));
  const destination = teams.find((t) => t.id === target)?.name ?? "No team";
  const toggle = (id: string) => setSelected((old) => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const save = async () => {
    setPending(true); setFailures([]); setProgress(0);
    const result = await moveTeamMembers(chosen, target, (employee, unit) => personnelActionsApi.create({
      employment_id: employee.id, type: "TRANSFER", effective_date: format(new Date(), "yyyy-MM-dd"),
      reason_code: "TEAM_ASSIGNMENT", changes: { org_unit_id: unit },
    }), errorMessage, setProgress);
    await qc.invalidateQueries({ queryKey: ["employees"] });
    void qc.invalidateQueries({ queryKey: ["employees-picker"] });
    void qc.invalidateQueries({ queryKey: ["dash-hr"] });
    setPending(false);
    if (result.succeeded.length) toast.success(`${result.succeeded.length} ${result.succeeded.length === 1 ? "employee" : "employees"} updated`, `Assigned to ${destination}.`);
    if (result.failed.length) { setSelected(new Set(result.failed.map((f) => f.id))); setFailures(result.failed); }
    else onClose();
  };
  return <Sheet open onClose={() => { if (!pending) onClose(); }} title="Assign employees" description={`Choose employees from ${department.name}.`} className="max-w-lg"
    footer={<><button className="btn-secondary" disabled={pending} onClick={onClose}>Cancel</button><button className="btn-primary" disabled={pending || !chosen.length} onClick={() => void save()}>
      {pending ? `Updating ${progress} of ${chosen.length}…` : `Assign ${chosen.length || ""} ${chosen.length === 1 ? "employee" : "employees"}`}</button></>}>
    <div className="space-y-4">
      <div><label className="label" htmlFor="team-destination">Assign to</label><select className="input" id="team-destination" value={target} disabled={pending}
        onChange={(e) => { setTarget(e.target.value); setSelected(new Set()); setFailures([]); }}><option value={department.id}>No team — stay in {department.name}</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
      <p className="text-xs text-fg-subtle">Employees already in {destination} are hidden. Changes take effect today.</p>
      {failures.length > 0 && <div role="alert" className="rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm"><p className="font-medium">Some employees couldn’t be updated. Successful changes are saved.</p>{failures.map((f) => <p className="mt-1" key={f.id}>{members.find((e) => e.id === f.id) ? employeeName(members.find((e) => e.id === f.id)!) : f.id}: {f.message}</p>)}<p className="mt-2">Retry the selected employees or cancel.</p></div>}
      <input className="input" aria-label="Search employees to assign" placeholder="Search name or employee number…" disabled={pending} value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="flex justify-between items-center text-xs text-fg-subtle"><span>{chosen.length} selected</span><button type="button" className="link" disabled={pending || !visible.length}
        onClick={() => setSelected((old) => { const next = new Set(old); const all = visible.every((e) => next.has(e.id)); for (const e of visible) { if (all) next.delete(e.id); else next.add(e.id); } return next; })}>{visible.length && visible.every((e) => selected.has(e.id)) ? "Deselect shown" : "Select all shown"}</button></div>
      <div className="divide-y divide-line rounded-xl border border-line">{visible.map((e) => <label key={e.id} className={`flex items-center gap-3 p-3 cursor-pointer ${selected.has(e.id) ? "bg-brand-500/5" : "hover:bg-surface-raised"}`}>
        <input type="checkbox" className="checkbox" disabled={pending} checked={selected.has(e.id)} onChange={() => toggle(e.id)} aria-label={`Select ${employeeName(e)}`} />
        <div><p className="font-medium text-sm">{employeeName(e)}</p><p className="text-xs text-fg-subtle">{e.employee_number} · {teams.find((t) => t.id === e.org_unit_id)?.name ?? "No team"}</p></div></label>)}
        {!visible.length && <p className="p-4 text-sm text-fg-subtle">{search ? "No matching employees." : "All department employees are already assigned here."}</p>}</div>
    </div>
  </Sheet>;
}

function DepartmentSheet({ open, onClose, entities, departments, initial, teamParent }: {
  open: boolean; onClose: () => void; entities: LegalEntity[]; departments: OrgUnit[]; initial?: OrgUnit; teamParent?: OrgUnit;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = { name: initial?.name ?? "", code: initial?.code ?? "", entity: initial?.legal_entity_id ?? teamParent?.legal_entity_id ?? entities[0]?.id ?? "", parent: initial?.parent_id ?? teamParent?.id ?? "", type: initial?.type ?? (teamParent ? "TEAM" : "DEPARTMENT") };
  const [form, setForm] = useState(empty);
  const [head, setHead] = useState(initial?.head_employment_id ?? "");
  const [lead, setLead] = useState(initial?.lead_employment_id ?? "");
  const [pm, setPm] = useState(initial?.pm_employment_id ?? "");
  const employees = useQuery({ queryKey: ["employees"], queryFn: peopleApi.listAllEmployees, enabled: ["TEAM", "DEPARTMENT"].includes(form.type) });
  const unitLabel = form.type === "TEAM" ? "team" : "department";
  const entityId = form.entity || entities[0]?.id || "";
  const parentOptions = departments.filter((d) => d.legal_entity_id === entityId && d.id !== initial?.id && (form.type !== "TEAM" || d.type === "DEPARTMENT"));

  const save = useMutation({
    mutationFn: () =>
      isEdit
        ? orgApi.updateOrgUnit(initial!.id, { version: initial!.version, ...(initial!.department_template_id ? {} : { name: form.name.trim(), code: form.code.trim() || null }), ...(form.type === "DEPARTMENT" ? { head_employment_id: head || null } : {}), ...(form.type === "TEAM" ? { lead_employment_id: lead || null, pm_employment_id: pm || null } : {}) })
        : orgApi.createOrgUnit({
            name: form.name.trim(), type: form.type, code: form.code.trim() || undefined,
            legal_entity_id: entityId, parent_id: form.parent || undefined,
            effective_from: format(new Date(), "yyyy-MM-dd"),
            ...(form.type === "DEPARTMENT" ? { head_employment_id: head || null } : {}),
            ...(form.type === "TEAM" ? { lead_employment_id: lead || null, pm_employment_id: pm || null } : {}),
          }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["org-units"] });
      toast.success(`${form.type === "TEAM" ? "Team" : "Department"} ${isEdit ? "updated" : "added"}`, d.name);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(`Couldn’t ${isEdit ? "update" : "add"} ${unitLabel}`, errorMessage(e)),
  });

  const valid = form.name.trim().length > 0 && !!entityId && (form.type !== "TEAM" || !!form.parent || isEdit);
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={`${isEdit ? "Edit" : "Add"} ${unitLabel}`}
      description={teamParent ? `Create a team within ${teamParent.name}.` : isEdit ? "Update the name and code for this unit." : undefined}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="dept-form" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : isEdit ? "Save changes" : `Add ${unitLabel}`}
          </button>
        </>
      }
    >
      <form id="dept-form" onSubmit={submit} className="space-y-4">
        {form.type === "TEAM" ? <div className="rounded-xl bg-surface-raised p-3 text-sm">
          <p className="font-medium">{teamParent?.name ?? departments.find((d) => d.id === form.parent)?.name ?? "Department"}</p>
          <p className="text-xs text-fg-subtle">{entities.find((e) => e.id === entityId)?.name}</p>
        </div> : <div>
          <label className="label" htmlFor="dp-company">Company</label>
          <select id="dp-company" className="input" value={entityId} disabled={isEdit}
            onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value, parent: "" }))}>
            {entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>}
        <div>
          <label className="label" htmlFor="dp-name">{form.type === "TEAM" ? "Team name" : "Department name"}</label>
          <input id="dp-name" className="input" disabled={!!initial?.department_template_id} required placeholder={form.type === "TEAM" ? "e.g. Inside Sales" : "e.g. Sales"}
            value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="dp-code">Code <span className="font-normal text-fg-subtle">(optional)</span></label>
          <input id="dp-code" className="input font-mono" disabled={!!initial?.department_template_id} placeholder={form.type === "TEAM" ? "e.g. SALES-IN" : "e.g. SALES"}
            value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
        </div>
        {["TEAM", "DEPARTMENT"].includes(form.type) && <div className="space-y-3">
          <p className="text-xs text-fg-subtle">Choose the people who manage this department or team. Approval workflows select their approvers separately.</p>
          {employees.isError && <p className="text-sm text-danger">Couldn’t load employees. <button type="button" className="link" onClick={() => employees.refetch()}>Retry</button></p>}
          {(form.type === "DEPARTMENT" ? [{ title: "Head of Department", value: head, change: setHead }] : [{ title: "Team lead", value: lead, change: setLead }, { title: "Project Manager", value: pm, change: setPm }]).map((role) => <label key={role.title} className="label block">{role.title}<select className="input mt-1" value={role.value} disabled={employees.isPending || employees.isError} onChange={(e) => role.change(e.target.value)}>
            <option value="">Unassigned</option>{employees.data?.filter((e) => e.legal_entity_id === entityId && e.employment_state !== "SEPARATED").map((e) => <option key={e.id} value={e.id}>{employeeName(e)} · {e.employee_number}</option>)}
          </select></label>)}
        </div>}
        {form.type !== "TEAM" && !isEdit && parentOptions.length > 0 && <div>
          <label className="label" htmlFor="dp-parent">Parent department (optional)</label>
          <select id="dp-parent" className="input" value={form.parent} onChange={(e) => setForm((f) => ({ ...f, parent: e.target.value }))}>
            <option value="">None — top level</option>{parentOptions.filter((d) => d.type !== "TEAM").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Locations ─────────────────────────── */

function LocationsTab() {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Location | null>(null);
  const [viewingHistory, setViewingHistory] = useState<Location | null>(null);
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
              <div className="flex items-start justify-between gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/10 text-accent"><MapPin size={18} /></span>
                <div className="flex gap-1">
                  <button className="btn-icon" onClick={() => setViewingHistory(l)} aria-label={`History for ${l.name}`}><History size={14} /></button>
                  <button className="btn-icon" onClick={() => setEditing(l)} aria-label={`Edit ${l.name}`}><Pencil size={14} /></button>
                </div>
              </div>
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
      <LocationSheet open={adding} onClose={() => setAdding(false)} entities={entities.data ?? []} />
      <LocationSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} entities={entities.data ?? []} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.name}` : "History"}
        fetcher={viewingHistory ? () => orgApi.locationHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

function LocationSheet({ open, onClose, entities, initial }: {
  open: boolean; onClose: () => void; entities: LegalEntity[]; initial?: Location;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = { name: initial?.name ?? "", type: initial?.type ?? "OFFICE", entity: initial?.legal_entity_id ?? "", city: initial?.city ?? "" };
  const [form, setForm] = useState(empty);

  const save = useMutation({
    mutationFn: () =>
      isEdit
        ? orgApi.updateLocation(initial!.id, { name: form.name.trim(), type: form.type, city: form.city.trim() || undefined, version: initial!.version })
        : orgApi.createLocation({ name: form.name.trim(), type: form.type, city: form.city.trim() || undefined, legal_entity_id: form.entity || undefined }),
    onSuccess: (l) => {
      qc.invalidateQueries({ queryKey: ["locations"] });
      toast.success(isEdit ? "Location updated" : "Location added", l.name);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update location" : "Couldn’t add location", errorMessage(e)),
  });

  const valid = form.name.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title={isEdit ? "Edit location" : "Add location"}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="loc-form" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add location"}
        </button>
      </>}
    >
      <form id="loc-form" onSubmit={submit} className="space-y-4">
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
        {!isEdit && (
          <div>
            <label className="label" htmlFor="lo-entity">Company <span className="font-normal text-fg-subtle">(optional — leave blank to share across all)</span></label>
            <select id="lo-entity" className="input" value={form.entity} onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value }))}>
              <option value="">All companies</option>
              {entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </div>
        )}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Job titles ─────────────────────────── */

function JobsTab() {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Job | null>(null);
  const [viewingHistory, setViewingHistory] = useState<Job | null>(null);
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
            <thead><tr><th>Title</th><th className="hidden sm:table-cell">Function</th><th>Code</th><th className="w-20" /></tr></thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.id}>
                  <td className="font-medium text-fg">{j.title}</td>
                  <td className="hidden sm:table-cell">{j.function ?? "—"}</td>
                  <td className="font-mono text-xs">{j.code ?? "—"}</td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <button className="btn-icon" onClick={() => setViewingHistory(j)} aria-label={`History for ${j.title}`}><History size={14} /></button>
                      <button className="btn-icon" onClick={() => setEditing(j)} aria-label={`Edit ${j.title}`}><Pencil size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <JobSheet open={adding} onClose={() => setAdding(false)} />
      <JobSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.title}` : "History"}
        fetcher={viewingHistory ? () => orgApi.jobHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

function JobSheet({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: Job }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = { title: initial?.title ?? "", code: initial?.code ?? "", function: initial?.function ?? "" };
  const [form, setForm] = useState(empty);

  const save = useMutation({
    mutationFn: () => {
      const body = { title: form.title.trim(), code: form.code.trim() || undefined, function: form.function.trim() || undefined };
      return isEdit ? orgApi.updateJob(initial!.id, { ...body, version: initial!.version }) : orgApi.createJob(body);
    },
    onSuccess: (j) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      toast.success(isEdit ? "Job title updated" : "Job title added", j.title);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update job title" : "Couldn’t add job title", errorMessage(e)),
  });

  const valid = form.title.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title={isEdit ? "Edit job title" : "Add job title"}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="job-form" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add job title"}
        </button>
      </>}
    >
      <form id="job-form" onSubmit={submit} className="space-y-4">
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

/* ─────────────────────────── Grades ─────────────────────────── */

function StatusSelect({ id, value, onChange }: { id: string; value: MasterStatus; onChange: (v: MasterStatus) => void }) {
  return (
    <div>
      <label className="label" htmlFor={id}>Status</label>
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value as MasterStatus)}>
        <option value="ACTIVE">Active — can be chosen for new records</option>
        <option value="INACTIVE">Inactive — kept on old records only</option>
      </select>
    </div>
  );
}

function GradesTab() {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Grade | null>(null);
  const [viewingHistory, setViewingHistory] = useState<Grade | null>(null);
  const grades = useQuery({ queryKey: ["grades"], queryFn: () => orgApi.listGrades() });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">Levels or bands shared across every company, from junior to senior.</p>
        <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add grade</button>
      </div>
      {grades.isError ? (
        <div className="card"><EmptyState icon={Layers} title="Couldn’t load grades" description="The organization API isn’t responding." /></div>
      ) : grades.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : !grades.data?.length ? (
        <div className="card">
          <EmptyState icon={Layers} title="No grades yet" description="Add the levels your companies use, for example W1–W4 for workers and M1–M3 for managers."
            action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add grade</button>} />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th className="w-16">Order</th><th>Code</th><th>Name</th><th>Status</th><th className="w-20" /></tr></thead>
            <tbody>
              {grades.data.map((g) => (
                <tr key={g.id}>
                  <td className="tabular-nums text-fg-subtle">{g.sequence}</td>
                  <td className="font-mono text-xs font-medium text-fg">{g.code}</td>
                  <td>{g.name}</td>
                  <td><StatusChip status={g.status} /></td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <button className="btn-icon" onClick={() => setViewingHistory(g)} aria-label={`History for ${g.code}`}><History size={14} /></button>
                      <button className="btn-icon" onClick={() => setEditing(g)} aria-label={`Edit ${g.code}`}><Pencil size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <GradeSheet open={adding} onClose={() => setAdding(false)} />
      <GradeSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.code}` : "History"}
        fetcher={viewingHistory ? () => orgApi.gradeHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

function GradeSheet({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: Grade }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = {
    code: initial?.code ?? "", name: initial?.name ?? "", sequence: String(initial?.sequence ?? 0),
    status: (initial?.status ?? "ACTIVE") as MasterStatus,
  };
  const [form, setForm] = useState(empty);

  const save = useMutation({
    mutationFn: () => {
      const body = { code: form.code.trim(), name: form.name.trim(), sequence: Number(form.sequence) || 0 };
      return isEdit ? orgApi.updateGrade(initial!.id, { ...body, status: form.status, version: initial!.version }) : orgApi.createGrade(body);
    },
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["grades"] });
      toast.success(isEdit ? "Grade updated" : "Grade added", `${g.code} · ${g.name}`);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update grade" : "Couldn’t add grade", errorMessage(e)),
  });

  const valid = form.code.trim().length > 0 && form.name.trim().length > 0 && Number(form.sequence) >= 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title={isEdit ? "Edit grade" : "Add grade"}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="grade-form" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add grade"}
        </button>
      </>}
    >
      <form id="grade-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="gr-code">Code</label>
            <input id="gr-code" className="input font-mono" placeholder="e.g. M2" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
          </div>
          <div className="col-span-2">
            <label className="label" htmlFor="gr-name">Name</label>
            <input id="gr-name" className="input" placeholder="e.g. Manager" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="gr-seq">Order</label>
          <input id="gr-seq" type="number" min={0} className="input" value={form.sequence} onChange={(e) => setForm((f) => ({ ...f, sequence: e.target.value }))} />
          <p className="mt-1 text-xs text-fg-subtle">Lower numbers are more junior. Lists and reports sort by this.</p>
        </div>
        {isEdit && <StatusSelect id="gr-status" value={form.status} onChange={(status) => setForm((f) => ({ ...f, status }))} />}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Cost centres ─────────────────────────── */

function CostCentresTab() {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<CostCentre | null>(null);
  const [viewingHistory, setViewingHistory] = useState<CostCentre | null>(null);
  const centres = useQuery({ queryKey: ["cost-centres"], queryFn: () => orgApi.listCostCentres() });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">Where employee costs are booked. Payroll and reports group cost by these.</p>
        <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add cost centre</button>
      </div>
      {centres.isError ? (
        <div className="card"><EmptyState icon={Wallet} title="Couldn’t load cost centres" description="The organization API isn’t responding." /></div>
      ) : centres.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : !centres.data?.length ? (
        <div className="card">
          <EmptyState icon={Wallet} title="No cost centres yet" description="Add the cost centres your accounts team uses."
            action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add cost centre</button>} />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Code</th><th>Name</th><th>Status</th><th className="w-20" /></tr></thead>
            <tbody>
              {centres.data.map((c) => (
                <tr key={c.id}>
                  <td className="font-mono text-xs font-medium text-fg">{c.code}</td>
                  <td>{c.name}</td>
                  <td><StatusChip status={c.status} /></td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <button className="btn-icon" onClick={() => setViewingHistory(c)} aria-label={`History for ${c.code}`}><History size={14} /></button>
                      <button className="btn-icon" onClick={() => setEditing(c)} aria-label={`Edit ${c.code}`}><Pencil size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CostCentreSheet open={adding} onClose={() => setAdding(false)} />
      <CostCentreSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.code}` : "History"}
        fetcher={viewingHistory ? () => orgApi.costCentreHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

function CostCentreSheet({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: CostCentre }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const empty = { code: initial?.code ?? "", name: initial?.name ?? "", status: (initial?.status ?? "ACTIVE") as MasterStatus };
  const [form, setForm] = useState(empty);

  const save = useMutation({
    mutationFn: () => {
      const body = { code: form.code.trim(), name: form.name.trim() };
      return isEdit ? orgApi.updateCostCentre(initial!.id, { ...body, status: form.status, version: initial!.version }) : orgApi.createCostCentre(body);
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["cost-centres"] });
      toast.success(isEdit ? "Cost centre updated" : "Cost centre added", `${c.code} · ${c.name}`);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update cost centre" : "Couldn’t add cost centre", errorMessage(e)),
  });

  const valid = form.code.trim().length > 0 && form.name.trim().length > 0;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open} onClose={onClose} title={isEdit ? "Edit cost centre" : "Add cost centre"}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="cc-form" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add cost centre"}
        </button>
      </>}
    >
      <form id="cc-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="cc-code">Code</label>
            <input id="cc-code" className="input font-mono" placeholder="e.g. CC-OPS" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
          </div>
          <div className="col-span-2">
            <label className="label" htmlFor="cc-name">Name</label>
            <input id="cc-name" className="input" placeholder="e.g. Operations" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
        </div>
        {isEdit && <StatusSelect id="cc-status" value={form.status} onChange={(status) => setForm((f) => ({ ...f, status }))} />}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Positions ─────────────────────────── */

function PositionsTab() {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Position | null>(null);
  const [viewingHistory, setViewingHistory] = useState<Position | null>(null);
  const [entityFilter, setEntityFilter] = useState("");
  const positions = useQuery({ queryKey: ["positions"], queryFn: () => orgApi.listPositions() });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));
  const rows = (positions.data ?? []).filter((p) => !entityFilter || p.legal_entity_id === entityFilter);
  const totals = rows.reduce(
    (t, p) => (p.status === "ACTIVE" && p.max_headcount != null
      ? { seats: t.seats + p.max_headcount, filled: t.filled + Math.min(p.filled, p.max_headcount) }
      : t),
    { seats: 0, filled: 0 },
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {(entities.data?.length ?? 0) > 1 && (
            <select className="input w-auto" aria-label="Company" value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)}>
              <option value="">All companies</option>
              {entities.data!.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          )}
          {rows.length > 0 && (
            <p className="text-sm text-fg-muted">
              <span className="font-semibold text-fg tabular-nums">{totals.seats - totals.filled}</span> open of{" "}
              <span className="tabular-nums">{totals.seats}</span> approved seats
            </p>
          )}
        </div>
        <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add position</button>
      </div>
      {positions.isError ? (
        <div className="card"><EmptyState icon={Armchair} title="Couldn’t load positions" description="The organization API isn’t responding." /></div>
      ) : positions.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !rows.length ? (
        <div className="card">
          <EmptyState icon={Armchair} title="No positions yet" description="A position is an approved seat in a department, for example “Shift Supervisor × 3”. Positions with a headcount feed the vacancies figure."
            action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add position</button>} />
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Position</th><th>Department</th><th className="hidden md:table-cell">Job · Grade</th>
                <th className="text-right">Filled</th><th className="text-right">Open</th><th>Status</th><th className="w-20" />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>
                    <p className="font-medium text-fg">{p.title}</p>
                    {p.code && <p className="font-mono text-[11px] text-fg-subtle">{p.code}</p>}
                  </td>
                  <td>
                    <p>{p.org_unit_name ?? "—"}</p>
                    {(entities.data?.length ?? 0) > 1 && p.legal_entity_id && <p className="text-xs text-fg-subtle">{entityName.get(p.legal_entity_id)}</p>}
                  </td>
                  <td className="hidden md:table-cell">{[p.job_title, p.grade_name].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="text-right tabular-nums">{p.filled}{p.max_headcount != null && <span className="text-fg-subtle"> / {p.max_headcount}</span>}</td>
                  <td className="text-right tabular-nums">
                    {p.vacancies == null ? <span className="text-fg-subtle">—</span> : p.vacancies > 0 ? <span className="font-semibold text-warning">{p.vacancies}</span> : 0}
                  </td>
                  <td><StatusChip status={p.status} /></td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <button className="btn-icon" onClick={() => setViewingHistory(p)} aria-label={`History for ${p.title}`}><History size={14} /></button>
                      <button className="btn-icon" onClick={() => setEditing(p)} aria-label={`Edit ${p.title}`}><Pencil size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <PositionSheet open={adding} onClose={() => setAdding(false)} />
      <PositionSheet key={editing?.id} open={editing !== null} onClose={() => setEditing(null)} initial={editing ?? undefined} />
      <HistoryModal
        open={viewingHistory !== null}
        onClose={() => setViewingHistory(null)}
        title={viewingHistory ? `History — ${viewingHistory.title}` : "History"}
        fetcher={viewingHistory ? () => orgApi.positionHistory(viewingHistory.id) : undefined}
      />
    </div>
  );
}

function PositionSheet({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: Position }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isEdit = !!initial;
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits(), enabled: open });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities(), enabled: open });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs(), enabled: open });
  const grades = useQuery({ queryKey: ["grades"], queryFn: () => orgApi.listGrades(), enabled: open });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));
  // Positions live in a company's own department or team, never in the shared department list.
  const placeable = (units.data ?? [])
    .filter((u) => u.type !== "DEPARTMENT_TEMPLATE" && u.status === "ACTIVE")
    .sort((a, b) => (entityName.get(a.legal_entity_id ?? "") ?? "").localeCompare(entityName.get(b.legal_entity_id ?? "") ?? "") || a.name.localeCompare(b.name));
  const empty = {
    title: initial?.title ?? "", code: initial?.code ?? "", unit: initial?.org_unit_id ?? "",
    job: initial?.job_id ?? "", grade: initial?.grade_id ?? "",
    headcount: initial?.max_headcount != null ? String(initial.max_headcount) : "",
    from: initial?.effective_from ?? format(new Date(), "yyyy-MM-dd"),
    to: initial?.effective_to ?? "",
    status: (initial?.status ?? "ACTIVE") as MasterStatus,
  };
  const [form, setForm] = useState(empty);
  const set = (patch: Partial<typeof empty>) => setForm((f) => ({ ...f, ...patch }));

  const save = useMutation({
    mutationFn: () => {
      const headcount = form.headcount.trim() ? Number(form.headcount) : null;
      if (isEdit) {
        return orgApi.updatePosition(initial!.id, {
          version: initial!.version,
          title: form.title.trim(), code: form.code.trim() || null, job_id: form.job || null, grade_id: form.grade || null,
          max_headcount: headcount, status: form.status, effective_to: form.to || null,
        });
      }
      return orgApi.createPosition({
        title: form.title.trim(), org_unit_id: form.unit, code: form.code.trim() || undefined,
        job_id: form.job || undefined, grade_id: form.grade || undefined,
        max_headcount: headcount ?? undefined, effective_from: form.from,
      });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(isEdit ? "Position updated" : "Position added", p.title);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error(isEdit ? "Couldn’t update position" : "Couldn’t add position", errorMessage(e)),
  });

  const headcountOk = !form.headcount.trim() || (Number.isInteger(Number(form.headcount)) && Number(form.headcount) >= 1);
  const valid = form.title.trim().length > 0 && (isEdit || form.unit !== "") && headcountOk;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };
  const activeOr = <T extends { id: string; status: string }>(list: T[] | undefined, current: string) =>
    (list ?? []).filter((x) => x.status === "ACTIVE" || x.id === current);

  return (
    <Sheet
      open={open} onClose={onClose} title={isEdit ? "Edit position" : "Add position"}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="pos-form" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : isEdit ? "Save changes" : "Add position"}
        </button>
      </>}
    >
      <form id="pos-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label className="label" htmlFor="po-title">Title</label>
            <input id="po-title" className="input" placeholder="e.g. Shift Supervisor" value={form.title} onChange={(e) => set({ title: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="po-code">Code <span className="font-normal text-fg-subtle">(optional)</span></label>
            <input id="po-code" className="input font-mono" value={form.code} onChange={(e) => set({ code: e.target.value })} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="po-unit">Department or team</label>
          {isEdit ? (
            <p className="input flex items-center bg-muted text-fg-muted">{initial!.org_unit_name ?? "—"}</p>
          ) : (
            <select id="po-unit" className="input" value={form.unit} onChange={(e) => set({ unit: e.target.value })}>
              <option value="">Choose…</option>
              {placeable.map((u) => (
                <option key={u.id} value={u.id}>
                  {(entities.data?.length ?? 0) > 1 && u.legal_entity_id ? `${entityName.get(u.legal_entity_id)} · ` : ""}{u.name}{u.type === "TEAM" ? " (team)" : ""}
                </option>
              ))}
            </select>
          )}
          {isEdit && <p className="mt-1 text-xs text-fg-subtle">To move a seat to another department, retire this one and add a new position there.</p>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="po-job">Job title <span className="font-normal text-fg-subtle">(optional)</span></label>
            <select id="po-job" className="input" value={form.job} onChange={(e) => set({ job: e.target.value })}>
              <option value="">—</option>
              {activeOr(jobs.data, form.job).sort((a, b) => a.title.localeCompare(b.title)).map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="po-grade">Grade <span className="font-normal text-fg-subtle">(optional)</span></label>
            <select id="po-grade" className="input" value={form.grade} onChange={(e) => set({ grade: e.target.value })}>
              <option value="">—</option>
              {activeOr(grades.data, form.grade).map((g) => <option key={g.id} value={g.id}>{g.code} · {g.name}</option>)}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="po-hc">Approved headcount</label>
            <input id="po-hc" type="number" min={1} className="input" placeholder="No limit" value={form.headcount} onChange={(e) => set({ headcount: e.target.value })} />
            {!headcountOk && <p className="mt-1 text-xs text-danger">Use a whole number of 1 or more, or leave it empty.</p>}
          </div>
          {isEdit ? (
            <div>
              <label className="label" htmlFor="po-to">End date <span className="font-normal text-fg-subtle">(optional)</span></label>
              <input id="po-to" type="date" className="input" min={initial!.effective_from} value={form.to} onChange={(e) => set({ to: e.target.value })} />
            </div>
          ) : (
            <div>
              <label className="label" htmlFor="po-from">Approved from</label>
              <input id="po-from" type="date" className="input" value={form.from} onChange={(e) => set({ from: e.target.value })} />
            </div>
          )}
        </div>
        <p className="text-xs text-fg-subtle">With a headcount, this position counts towards the vacancies on the HR dashboard. Leave it empty for a seat with no limit.</p>
        {isEdit && <StatusSelect id="po-status" value={form.status} onChange={(status) => set({ status })} />}
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
        ? orgApi.updateEmployeeIdScheme(initial!.id, { prefix, separator, number_digits: numberDigits, next_number: nextNumber, version: initial!.version })
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

/**
 * Company-wide admin logins only — HR managers, accountants, a second Super Admin —
 * accounts that aren't any one employee's own login. An ordinary employee's login is
 * now managed from their own profile (Employee → Access), not listed here; that's
 * where the "linked employee" column used to point, and it's redundant once you're
 * already looking at that employee.
 */
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
  const admins = (users.data ?? []).filter((u) => !u.employment_id);
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
      <div className="flex items-start justify-between gap-3">
        <p className="max-w-lg text-[13px] text-fg-subtle">
          Company-wide admin logins — HR, accounts, another Super Admin. An employee's own
          login is managed from their profile now (Employees → open them → Access).
        </p>
        <button className="btn-primary shrink-0" onClick={() => setAdding(true)} disabled={!canCreate} title={canCreate ? undefined : "You don't have permission to grant access"}>
          <Plus size={15} /> Add admin
        </button>
      </div>
      {users.isError ? (
        <div className="card"><EmptyState icon={Users} title="Couldn't load users" description="The users API isn't responding." /></div>
      ) : users.isPending ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !admins.length ? (
        <div className="card">
          <EmptyState
            icon={Users}
            title="No company-wide admins yet"
            description={canCreate ? "Grant someone access that isn't tied to one employee — HR, accounts, another administrator." : "No admin accounts are visible to you yet."}
            action={canCreate ? <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={15} /> Add admin</button> : undefined}
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Email</th><th>Role</th><th>Access</th><th>Sign-in</th>{canCreate && <th className="w-px"><span className="sr-only">Actions</span></th>}</tr></thead>
            <tbody>
              {admins.map((u) => (
                <tr key={u.id + u.role}>
                  <td className="font-medium text-fg">{u.email ?? "—"}</td>
                  <td>{u.role}</td>
                  <td>
                    {u.scope_type === "LEGAL_ENTITY" && u.legal_entity_ids.length
                      ? u.legal_entity_ids.map((id) => entityName.get(id) ?? id).join(", ")
                      : SCOPE_LABEL[u.scope_type]}
                  </td>
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
      title="Add admin"
      description="Grant someone a company-wide login and full access to the companies you choose — not tied to their own employee record."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="add-user" disabled={!valid || create.isPending}>
            {create.isPending ? "Creating…" : "Add admin"}
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
