import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, ClipboardList, LayoutGrid, LogOut, Plus, Search, ShieldAlert, ShieldCheck,
  ShieldOff, Users, ChevronRight, ChevronLeft, TriangleAlert, Archive, ArchiveRestore, Sun, Moon, Monitor,
} from "lucide-react";
import { format } from "date-fns";
import { usePlatformAuth } from "../context/PlatformAuthContext";
import { useTheme } from "../context/ThemeContext";
import { platformTenantsApi } from "../api/platform";
import type { AuditLogEntry, CompanyMode, PlatformAdminSummary, PlatformRole, TenantDetail, TenantSummary } from "../api/platform";
import { PlatformApiError } from "../api/platformClient";
import { useToast, errorMessage } from "../components/ui/Toast";
import { PageHeader } from "../components/ui/PageHeader";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Skeleton, Notice } from "../components/ui/Feedback";
import { Avatar } from "../components/ui/Avatar";
import { Segmented } from "../components/ui/Tabs";

type Section = "overview" | "tenants" | "admins" | "audit";

function PlanBadge({ plan }: { plan: string }) {
  const tone = plan === "ENTERPRISE" ? "badge-brand" : plan === "GROWTH" ? "badge-info" : "badge-neutral";
  return <span className={`badge ${tone}`}>{plan}</span>;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status === "ACTIVE" ? "badge-success" : "badge-danger"}`}>{status === "ACTIVE" ? "Active" : "Suspended"}</span>;
}

function RoleBadge({ role }: { role: PlatformRole }) {
  return <span className={`badge ${role === "ADMIN" ? "badge-brand" : "badge-neutral"}`}>{role}</span>;
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Segmented
      value={theme}
      onChange={setTheme}
      items={[
        { value: "light", label: "", icon: Sun },
        { value: "dark", label: "", icon: Moon },
        { value: "system", label: "", icon: Monitor },
      ]}
    />
  );
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

export function PlatformConsolePage() {
  const { admin, logout } = usePlatformAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [section, setSection] = useState<Section>("overview");
  const [addingCompany, setAddingCompany] = useState(false);
  const [openTenantId, setOpenTenantId] = useState<string | null>(null);
  const canWrite = admin?.role === "ADMIN";

  const overviewTenants = useQuery({
    queryKey: ["platform-tenants-overview"],
    queryFn: () => platformTenantsApi.listTenants({ limit: 1000, include_archived: true }),
  });

  const doLogout = () => {
    logout();
    navigate("/platform/login");
  };

  const NAV: { id: Section; label: string; icon: typeof LayoutGrid }[] = [
    { id: "overview", label: "Overview", icon: LayoutGrid },
    { id: "tenants", label: "Tenants", icon: Building2 },
    { id: "admins", label: "Platform admins", icon: Users },
    { id: "audit", label: "Audit log", icon: ClipboardList },
  ];

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <aside className="flex w-60 shrink-0 flex-col">
        <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-xs ring-1 ring-inset ring-white/15">
            <ShieldAlert size={16} />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-semibold text-fg">Platform Console</p>
            <p className="truncate text-[11px] text-fg-subtle">Cross-tenant admin</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2" aria-label="Platform">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => setSection(n.id)}
              className={`group flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] font-medium transition-colors ${
                section === n.id ? "bg-surface text-fg shadow-xs ring-1 ring-line" : "text-fg-muted hover:bg-fg/[0.045] hover:text-fg"
              }`}
            >
              <n.icon size={16} strokeWidth={section === n.id ? 2.2 : 1.9} className={section === n.id ? "text-accent" : "text-fg-subtle transition-colors group-hover:text-fg-muted"} />
              {n.label}
            </button>
          ))}
        </nav>

        <div className="shrink-0 border-t border-line p-3">
          <div className="flex items-center gap-2.5 px-1 py-1.5">
            <Avatar name={admin?.name ?? "?"} size="sm" />
            <div className="min-w-0 flex-1 leading-tight">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-[13px] font-medium text-fg">{admin?.name}</span>
                {admin && <RoleBadge role={admin.role} />}
              </span>
              <p className="truncate text-[11px] text-fg-subtle">{admin?.email}</p>
            </div>
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 px-2.5 py-1.5">
            <span className="text-[13px] text-fg-muted">Theme</span>
            <ThemeToggle />
          </div>
          <button onClick={doLogout} className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-fg-muted transition-colors hover:bg-fg/[0.045] hover:text-fg">
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col py-2 pr-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-panel shadow-xs">
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1100px] px-6 py-7 sm:px-8">
              {!canWrite && (
                <Notice tone="info" title="Read-only access" >
                  You can view everything here, but changes need an ADMIN-role platform admin.
                </Notice>
              )}
              <div className={!canWrite ? "mt-6" : ""}>
                {section === "overview" && (
                  <OverviewSection tenants={overviewTenants.data?.items ?? []} loading={overviewTenants.isPending} onGoToTenants={() => setSection("tenants")} />
                )}
                {section === "tenants" && (
                  <TenantsSection canWrite={canWrite} onAddCompany={() => setAddingCompany(true)} onOpenTenant={setOpenTenantId} />
                )}
                {section === "admins" && <AdminsSection canWrite={canWrite} />}
                {section === "audit" && <AuditSection />}
              </div>
            </div>
          </main>
        </div>
      </div>

      {addingCompany && (
        <AddCompanyDialog
          onClose={() => setAddingCompany(false)}
          onCreated={(msg) => toast.success("Company created", msg)}
        />
      )}
      <TenantDrawer tenantId={openTenantId} canWrite={canWrite} onClose={() => setOpenTenantId(null)} />
    </div>
  );
}

/* ─────────────────────────── Overview ─────────────────────────── */

function OverviewSection({ tenants, loading, onGoToTenants }: { tenants: TenantSummary[]; loading: boolean; onGoToTenants: () => void }) {
  const stats = useMemo(() => {
    const live = tenants.filter((t) => !t.archived_at);
    const totalCompanies = live.reduce((n, t) => n + t.legal_entity_count, 0);
    const active = live.filter((t) => t.status === "ACTIVE").length;
    const suspended = live.length - active;
    const archived = tenants.length - live.length;
    const byPlan = live.reduce<Record<string, number>>((acc, t) => ({ ...acc, [t.plan]: (acc[t.plan] ?? 0) + 1 }), {});
    return { totalTenants: live.length, totalCompanies, active, suspended, archived, byPlan };
  }, [tenants]);

  const cards = [
    { label: "Tenants", value: stats.totalTenants, icon: Building2, tone: "text-accent" },
    { label: "Companies across all tenants", value: stats.totalCompanies, icon: LayoutGrid, tone: "text-info" },
    { label: "Active", value: stats.active, icon: ShieldCheck, tone: "text-success" },
    { label: "Suspended", value: stats.suspended, icon: ShieldOff, tone: "text-danger" },
  ];

  return (
    <div>
      <PageHeader title="Overview" description="Everything registered on this platform, at a glance." />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {loading
          ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[104px] rounded-xl" />)
          : cards.map((c) => (
              <div key={c.label} className="card p-4">
                <span className={`grid h-9 w-9 place-items-center rounded-lg bg-muted ${c.tone}`}><c.icon size={16} /></span>
                <p className="mt-3 text-2xl font-semibold tabular-nums text-fg">{c.value}</p>
                <p className="mt-0.5 text-xs text-fg-subtle">{c.label}</p>
              </div>
            ))}
      </div>

      {!loading && !!tenants.length && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="card p-4">
            <p className="eyebrow">Plans</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(stats.byPlan).map(([plan, count]) => (
                <span key={plan} className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-fg-muted">
                  <PlanBadge plan={plan} /> × {count}
                </span>
              ))}
            </div>
          </div>
          <div className="card p-4">
            <p className="eyebrow">Archived (offboarded)</p>
            <p className="mt-3 text-2xl font-semibold tabular-nums text-fg-muted">{stats.archived}</p>
          </div>
        </div>
      )}

      <button onClick={onGoToTenants} className="mt-5 flex items-center gap-1 text-[13px] font-medium text-accent hover:underline">
        View all tenants <ChevronRight size={14} />
      </button>
    </div>
  );
}

/* ─────────────────────────── Tenants ─────────────────────────── */

const PAGE_SIZE = 10;

function TenantsSection({ canWrite, onAddCompany, onOpenTenant }: {
  canWrite: boolean; onAddCompany: () => void; onOpenTenant: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounced(query, 300);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState(0);

  useEffect(() => setPage(0), [debouncedQuery, includeArchived]);

  const { data, isPending, isError } = useQuery({
    queryKey: ["platform-tenants", debouncedQuery, includeArchived, page],
    queryFn: () => platformTenantsApi.listTenants({ q: debouncedQuery || undefined, include_archived: includeArchived, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const from = total ? page * PAGE_SIZE + 1 : 0;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <div>
      <PageHeader
        title="Tenants"
        description="Register a brand-new, isolated company, or link one as a subsidiary inside an existing group."
        actions={canWrite && <button onClick={onAddCompany} className="btn-primary"><Plus size={15} /> Add company</button>}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative max-w-xs flex-1">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search tenants…" className="input pl-8" />
        </div>
        <label className="flex items-center gap-2 text-[13px] text-fg-muted">
          <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} className="checkbox" />
          Show archived
        </label>
      </div>

      <div className="card overflow-hidden">
        {isPending ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : isError ? (
          <EmptyState icon={Building2} title="Couldn't load tenants" description="The platform API isn't responding." />
        ) : !items.length ? (
          <EmptyState icon={Building2} title={query ? "No matches" : "No tenants yet"} />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Company / group</th>
                <th>Plan</th>
                <th>Status</th>
                <th>Companies inside</th>
                <th>Created</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} onClick={() => onOpenTenant(t.id)} className={`cursor-pointer ${t.archived_at ? "opacity-50" : ""}`}>
                  <td className="font-medium text-fg">
                    <span className="flex items-center gap-2.5">
                      <Avatar name={t.display_name} size="xs" />
                      {t.display_name}
                      <span className="font-mono text-xs text-fg-subtle">{t.slug}</span>
                      {t.archived_at && <span className="badge badge-neutral">Archived</span>}
                    </span>
                  </td>
                  <td><PlanBadge plan={t.plan} /></td>
                  <td>{!t.archived_at && <StatusBadge status={t.status} />}</td>
                  <td>{t.legal_entity_count}</td>
                  <td>{format(new Date(t.created_at), "d MMM yyyy")}</td>
                  <td className="text-fg-subtle"><ChevronRight size={14} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-xs text-fg-subtle">
          <span>{from}–{to} of {total}</span>
          <div className="flex gap-1.5">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="btn-icon"><ChevronLeft size={14} /></button>
            <button onClick={() => setPage((p) => (to < total ? p + 1 : p))} disabled={to >= total} className="btn-icon"><ChevronRight size={14} /></button>
          </div>
        </div>
      )}
    </div>
  );
}

function TenantDrawer({ tenantId, canWrite, onClose }: { tenantId: string | null; canWrite: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirmAction, setConfirmAction] = useState<"suspend" | "archive" | null>(null);
  const detail = useQuery({
    queryKey: ["platform-tenant", tenantId],
    queryFn: () => platformTenantsApi.getTenant(tenantId as string),
    enabled: !!tenantId,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["platform-tenant", tenantId] });
    qc.invalidateQueries({ queryKey: ["platform-tenants"] });
    qc.invalidateQueries({ queryKey: ["platform-tenants-overview"] });
  };

  const update = useMutation({
    mutationFn: (body: { status?: string; plan?: string }) => platformTenantsApi.updateTenant(tenantId as string, body),
    onSuccess: (t) => { refresh(); toast.success(t.status === "SUSPENDED" ? "Tenant suspended" : "Tenant updated", t.display_name); setConfirmAction(null); },
    onError: (e) => toast.error("Couldn't update tenant", e instanceof PlatformApiError ? e.message : errorMessage(e)),
  });
  const archive = useMutation({
    mutationFn: () => platformTenantsApi.archiveTenant(tenantId as string),
    onSuccess: (t) => { refresh(); toast.success("Tenant archived", `${t.display_name} is offboarded and can no longer sign in.`); setConfirmAction(null); },
    onError: (e) => toast.error("Couldn't archive tenant", e instanceof PlatformApiError ? e.message : errorMessage(e)),
  });
  const restore = useMutation({
    mutationFn: () => platformTenantsApi.restoreTenant(tenantId as string),
    onSuccess: (t) => { refresh(); toast.success("Tenant restored", t.display_name); },
    onError: (e) => toast.error("Couldn't restore tenant", e instanceof PlatformApiError ? e.message : errorMessage(e)),
  });

  const t: TenantDetail | undefined = detail.data;
  const busy = update.isPending || archive.isPending || restore.isPending;

  return (
    <Sheet open={!!tenantId} onClose={onClose} title={t?.display_name ?? "…"} description={t ? t.slug : undefined}>
      {detail.isPending ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
      ) : !t ? (
        <p className="text-sm text-danger">Couldn't load this tenant.</p>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            {t.archived_at ? <span className="badge badge-neutral">Archived</span> : <StatusBadge status={t.status} />}
            <PlanBadge plan={t.plan} />
            <span className="text-xs text-fg-subtle">Since {format(new Date(t.created_at), "d MMM yyyy")}</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="card p-3">
              <p className="text-lg font-semibold tabular-nums text-fg">{t.legal_entity_count}</p>
              <p className="text-xs text-fg-subtle">Companies</p>
            </div>
            <div className="card p-3">
              <p className="text-lg font-semibold tabular-nums text-fg">{t.employee_count}</p>
              <p className="text-xs text-fg-subtle">Employees</p>
            </div>
          </div>

          {t.archived_at ? (
            canWrite && (
              <button onClick={() => restore.mutate()} disabled={busy} className="btn h-9 w-full bg-success text-white hover:bg-success/90">
                <ArchiveRestore size={14} /> Restore tenant
              </button>
            )
          ) : (
            <>
              <div>
                <p className="label mb-2">Plan</p>
                <div className="flex gap-2">
                  {(["STARTER", "GROWTH", "ENTERPRISE"] as const).map((p) => (
                    <button
                      key={p} onClick={() => update.mutate({ plan: p })} disabled={!canWrite || busy || t.plan === p}
                      className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                        t.plan === p ? "border-brand-500/50 bg-brand-500/10 text-accent" : "border-line text-fg-muted hover:border-line-strong hover:text-fg"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="label mb-2">Companies inside ({t.legal_entities.length})</p>
                <div className="space-y-1.5">
                  {t.legal_entities.map((e) => (
                    <div key={e.id} className="flex items-center justify-between rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg">
                      <span>{e.name}</span>
                      <span className="text-xs text-fg-subtle">{e.status}</span>
                    </div>
                  ))}
                </div>
              </div>

              {canWrite && (
                <div className="space-y-2 border-t border-line pt-5">
                  {confirmAction === "suspend" ? (
                    <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
                      <p className="flex items-center gap-1.5 text-[13px] font-medium text-danger"><TriangleAlert size={14} /> Suspend {t.display_name}?</p>
                      <p className="mt-1 text-xs text-fg-muted">Every user in this tenant is immediately blocked from signing in — including anyone already signed in right now.</p>
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => setConfirmAction(null)} className="btn-secondary btn-sm flex-1">Cancel</button>
                        <button onClick={() => update.mutate({ status: "SUSPENDED" })} disabled={busy} className="btn-danger btn-sm flex-1">
                          {update.isPending ? "Suspending…" : "Suspend"}
                        </button>
                      </div>
                    </div>
                  ) : confirmAction === "archive" ? (
                    <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
                      <p className="flex items-center gap-1.5 text-[13px] font-medium text-danger"><TriangleAlert size={14} /> Archive {t.display_name}?</p>
                      <p className="mt-1 text-xs text-fg-muted">Offboards this tenant — hidden from the default list and blocked from signing in. Its data is kept and this can be undone with Restore.</p>
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => setConfirmAction(null)} className="btn-secondary btn-sm flex-1">Cancel</button>
                        <button onClick={() => archive.mutate()} disabled={busy} className="btn-danger btn-sm flex-1">
                          {archive.isPending ? "Archiving…" : "Archive"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <button
                        onClick={() => (t.status === "ACTIVE" ? setConfirmAction("suspend") : update.mutate({ status: "ACTIVE" }))}
                        disabled={busy}
                        className={t.status === "ACTIVE" ? "btn-danger-soft h-9 w-full" : "btn h-9 w-full bg-success text-white hover:bg-success/90"}
                      >
                        {t.status === "ACTIVE" ? <><ShieldOff size={14} /> Suspend tenant</> : <><ShieldCheck size={14} /> Reactivate tenant</>}
                      </button>
                      <button onClick={() => setConfirmAction("archive")} disabled={busy} className="btn-secondary h-9 w-full">
                        <Archive size={14} /> Archive (offboard)
                      </button>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}

/* ─────────────────────────── Add company dialog ─────────────────────────── */

function AddCompanyDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (msg: string) => void }) {
  const qc = useQueryClient();
  const tenantsQuery = useQuery({ queryKey: ["platform-tenants-all-for-select"], queryFn: () => platformTenantsApi.listTenants({ limit: 500 }) });
  const tenants = tenantsQuery.data?.items ?? [];
  const empty = {
    companyName: "", country: "IN", mode: "NEW_TENANT" as CompanyMode,
    parentTenantId: "", adminEmail: "", adminPassword: "",
  };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!form.parentTenantId && tenants.length) setForm((f) => ({ ...f, parentTenantId: tenants[0].id }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenants.length]);

  const create = useMutation({
    mutationFn: () =>
      platformTenantsApi.createCompany({
        company_name: form.companyName.trim(),
        country_code: form.country,
        mode: form.mode,
        parent_tenant_id: form.mode === "SUBSIDIARY" ? form.parentTenantId : undefined,
        admin_email: form.mode === "NEW_TENANT" ? form.adminEmail.trim() : undefined,
        admin_password: form.mode === "NEW_TENANT" ? form.adminPassword : undefined,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["platform-tenants"] });
      qc.invalidateQueries({ queryKey: ["platform-tenants-overview"] });
      onCreated(
        r.mode === "NEW_TENANT"
          ? `${r.legal_entity_name} registered as its own tenant. Admin: ${r.admin_email}`
          : `${r.legal_entity_name} linked inside ${r.tenant_name}.`
      );
      onClose();
    },
    onError: (e) => setError(e instanceof PlatformApiError ? e.message : "Couldn't create company"),
  });

  const valid =
    form.companyName.trim().length >= 2 &&
    (form.mode === "SUBSIDIARY"
      ? !!form.parentTenantId
      : /\S+@\S+\.\S+/.test(form.adminEmail) && form.adminPassword.length >= 8);

  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open onClose={onClose} title="Add company"
      description="Choose whether this stands alone or joins an existing group."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="add-platform-company" disabled={!valid || create.isPending}>
          {create.isPending ? "Creating…" : "Create"}
        </button>
      </>}
    >
      <form id="add-platform-company" onSubmit={submit} className="space-y-4">
        {error && <p className="rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">{error}</p>}

        <div className="grid grid-cols-2 gap-2">
          <button
            type="button" onClick={() => setForm((f) => ({ ...f, mode: "NEW_TENANT" }))}
            className={`rounded-lg border px-3 py-2.5 text-left text-[13px] ${form.mode === "NEW_TENANT" ? "border-brand-500/50 bg-brand-500/10 text-fg" : "border-line text-fg-muted hover:border-line-strong"}`}
          >
            <span className="block font-medium">Independent</span>
            <span className="block text-xs text-fg-subtle">Its own new tenant</span>
          </button>
          <button
            type="button" onClick={() => setForm((f) => ({ ...f, mode: "SUBSIDIARY" }))}
            disabled={!tenants.length}
            className={`rounded-lg border px-3 py-2.5 text-left text-[13px] disabled:opacity-40 ${form.mode === "SUBSIDIARY" ? "border-brand-500/50 bg-brand-500/10 text-fg" : "border-line text-fg-muted hover:border-line-strong"}`}
          >
            <span className="block font-medium">Subsidiary</span>
            <span className="block text-xs text-fg-subtle">Inside an existing group</span>
          </button>
        </div>

        <div>
          <label className="label" htmlFor="ac-name">Company name</label>
          <input id="ac-name" className="input" placeholder="e.g. Zenith Robotics" value={form.companyName} onChange={(e) => setForm((f) => ({ ...f, companyName: e.target.value }))} />
        </div>

        {form.mode === "SUBSIDIARY" ? (
          <div>
            <label className="label" htmlFor="ac-parent">Parent group</label>
            <select id="ac-parent" className="input" value={form.parentTenantId} onChange={(e) => setForm((f) => ({ ...f, parentTenantId: e.target.value }))}>
              {tenants.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}
            </select>
          </div>
        ) : (
          <>
            <div>
              <label className="label" htmlFor="ac-country">Country</label>
              <input id="ac-country" maxLength={2} className="input" value={form.country} onChange={(e) => setForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))} />
            </div>
            <div className="border-t border-line pt-4">
              <label className="label" htmlFor="ac-email">First admin's email</label>
              <input id="ac-email" type="email" className="input" placeholder="admin@company.com" value={form.adminEmail} onChange={(e) => setForm((f) => ({ ...f, adminEmail: e.target.value }))} />
            </div>
            <div>
              <label className="label" htmlFor="ac-password">Temporary password</label>
              <input id="ac-password" type="password" className="input" placeholder="At least 8 characters" value={form.adminPassword} onChange={(e) => setForm((f) => ({ ...f, adminPassword: e.target.value }))} />
            </div>
          </>
        )}
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Admins ─────────────────────────── */

function AdminsSection({ canWrite }: { canWrite: boolean }) {
  const [adding, setAdding] = useState(false);
  const admins = useQuery({ queryKey: ["platform-admins"], queryFn: () => platformTenantsApi.listAdmins() });

  return (
    <div>
      <PageHeader
        title="Platform admins"
        description="Everyone who can sign in here — above every tenant, on the whole platform."
        actions={canWrite && <button onClick={() => setAdding(true)} className="btn-primary"><Plus size={15} /> Add admin</button>}
      />

      <div className="card overflow-hidden">
        {admins.isPending ? (
          <div className="space-y-2 p-4">{[0, 1].map((i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : admins.isError ? (
          <EmptyState icon={Users} title="Couldn't load admins" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last sign-in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {admins.data?.map((a) => <AdminRow key={a.id} admin={a} canWrite={canWrite} />)}
            </tbody>
          </table>
        )}
      </div>

      {adding && <AddAdminDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function AdminRow({ admin, canWrite }: { admin: PlatformAdminSummary; canWrite: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirmSuspend, setConfirmSuspend] = useState(false);

  const update = useMutation({
    mutationFn: (body: { status?: string; role?: PlatformRole }) => platformTenantsApi.updateAdmin(admin.id, body),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["platform-admins"] });
      toast.success(a.status === "SUSPENDED" ? "Admin suspended" : "Admin updated", a.name);
      setConfirmSuspend(false);
    },
    onError: (e) => toast.error("Couldn't update admin", e instanceof PlatformApiError ? e.message : errorMessage(e)),
  });

  const canEditThisRow = canWrite && !admin.is_you;

  return (
    <tr>
      <td className="font-medium text-fg">
        <span className="flex items-center gap-2.5">
          <Avatar name={admin.name} size="xs" />
          {admin.name}{admin.is_you && <span className="badge badge-neutral">You</span>}
        </span>
      </td>
      <td>{admin.email}</td>
      <td>
        {canEditThisRow ? (
          <select value={admin.role} onChange={(e) => update.mutate({ role: e.target.value as PlatformRole })} disabled={update.isPending} className="input h-8 w-28 py-0 text-xs">
            <option value="ADMIN">ADMIN</option>
            <option value="VIEWER">VIEWER</option>
          </select>
        ) : (
          <RoleBadge role={admin.role} />
        )}
      </td>
      <td><StatusBadge status={admin.status} /></td>
      <td>{admin.last_login_at ? format(new Date(admin.last_login_at), "d MMM yyyy, HH:mm") : "Never"}</td>
      <td className="text-right">
        {!canEditThisRow ? (
          <span className="text-xs text-fg-subtle">—</span>
        ) : confirmSuspend ? (
          <span className="flex items-center justify-end gap-1.5">
            <button onClick={() => setConfirmSuspend(false)} className="btn-secondary btn-sm">Cancel</button>
            <button onClick={() => update.mutate({ status: "SUSPENDED" })} disabled={update.isPending} className="btn-danger btn-sm">Confirm</button>
          </span>
        ) : admin.status === "ACTIVE" ? (
          <button onClick={() => setConfirmSuspend(true)} className="btn-danger-soft btn-sm">Suspend</button>
        ) : (
          <button onClick={() => update.mutate({ status: "ACTIVE" })} disabled={update.isPending} className="btn btn-sm bg-success text-white hover:bg-success/90">Reactivate</button>
        )}
      </td>
    </tr>
  );
}

function AddAdminDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "ADMIN" as PlatformRole });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => platformTenantsApi.createAdmin({ name: form.name.trim(), email: form.email.trim(), password: form.password, role: form.role }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["platform-admins"] });
      toast.success("Admin added", `${a.name} can now sign in to the Platform Console`);
      onClose();
    },
    onError: (e) => setError(e instanceof PlatformApiError ? e.message : "Couldn't add admin"),
  });

  const valid = form.name.trim().length >= 2 && /\S+@\S+\.\S+/.test(form.email) && form.password.length >= 8;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open onClose={onClose} title="Add platform admin"
      description="Choose ADMIN for full access, or VIEWER for read-only."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="add-platform-admin" disabled={!valid || create.isPending}>
          {create.isPending ? "Adding…" : "Add admin"}
        </button>
      </>}
    >
      <form id="add-platform-admin" onSubmit={submit} className="space-y-4">
        {error && <p className="rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">{error}</p>}
        <div>
          <label className="label" htmlFor="aa-name">Name</label>
          <input id="aa-name" className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="aa-email">Email</label>
          <input id="aa-email" type="email" className="input" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="aa-role">Role</label>
          <select id="aa-role" className="input" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as PlatformRole }))}>
            <option value="ADMIN">ADMIN — full access</option>
            <option value="VIEWER">VIEWER — read-only</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="aa-password">Temporary password</label>
          <input id="aa-password" type="password" className="input" placeholder="At least 8 characters" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
        </div>
      </form>
    </Sheet>
  );
}

/* ─────────────────────────── Audit log ─────────────────────────── */

const ACTION_LABEL: Record<string, string> = {
  TENANT_CREATED: "Company created",
  TENANT_SUSPENDED: "Tenant suspended",
  TENANT_REACTIVATED: "Tenant reactivated",
  TENANT_PLAN_CHANGED: "Plan changed",
  TENANT_ARCHIVED: "Tenant archived",
  TENANT_RESTORED: "Tenant restored",
  ADMIN_CREATED: "Admin added",
  ADMIN_SUSPENDED: "Admin suspended",
  ADMIN_REACTIVATED: "Admin reactivated",
  ADMIN_ROLE_CHANGED: "Admin role changed",
};

function metaSummary(entry: AuditLogEntry): string | null {
  if (!entry.metadata) return null;
  const m = entry.metadata;
  if ("from" in m && "to" in m) return `${String(m.from)} → ${String(m.to)}`;
  if ("mode" in m) return String(m.mode);
  if ("role" in m) return `role: ${String(m.role)}`;
  return null;
}

function AuditSection() {
  const [page, setPage] = useState(0);
  const limit = 25;
  const { data, isPending, isError } = useQuery({
    queryKey: ["platform-audit", page],
    queryFn: () => platformTenantsApi.getAuditLog({ limit, offset: page * limit }),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const from = total ? page * limit + 1 : 0;
  const to = Math.min(total, (page + 1) * limit);

  return (
    <div>
      <PageHeader title="Audit log" description="Every mutating action on the platform — who, what, and when. Nothing here is ever edited or removed." />

      <div className="card overflow-hidden">
        {isPending ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : isError ? (
          <EmptyState icon={ClipboardList} title="Couldn't load the audit log" />
        ) : !items.length ? (
          <EmptyState icon={ClipboardList} title="No activity yet" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.id}>
                  <td className="whitespace-nowrap text-fg-subtle">{format(new Date(entry.created_at), "d MMM yyyy, HH:mm")}</td>
                  <td className="font-medium text-fg">{entry.actor_name}</td>
                  <td>{ACTION_LABEL[entry.action] ?? entry.action}</td>
                  <td>{entry.target_label}</td>
                  <td className="text-xs text-fg-subtle">{metaSummary(entry) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > limit && (
        <div className="mt-3 flex items-center justify-between text-xs text-fg-subtle">
          <span>{from}–{to} of {total}</span>
          <div className="flex gap-1.5">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="btn-icon"><ChevronLeft size={14} /></button>
            <button onClick={() => setPage((p) => (to < total ? p + 1 : p))} disabled={to >= total} className="btn-icon"><ChevronRight size={14} /></button>
          </div>
        </div>
      )}
    </div>
  );
}
