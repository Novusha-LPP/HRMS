import { useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Building2, Landmark, MapPin, Briefcase, Users } from "lucide-react";
import { orgApi } from "../api/org";
import type { LegalEntity, OrgUnit } from "../api/org";
import { usersApi } from "../api/users";
import type { Role, ScopeType } from "../api/users";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { format } from "date-fns";

type Tab = "companies" | "departments" | "locations" | "jobs" | "access";

export function OrganizationPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "companies";
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
          { value: "companies", label: "Companies" },
          { value: "departments", label: "Departments" },
          { value: "locations", label: "Locations" },
          { value: "jobs", label: "Job titles" },
          ...(canManageAccess ? [{ value: "access" as const, label: "Users & access" }] : []),
        ]}
      />
      {tab === "companies" && <CompaniesTab canCreate={canCreateCompany} />}
      {tab === "departments" && <DepartmentsTab />}
      {tab === "locations" && <LocationsTab />}
      {tab === "jobs" && <JobsTab />}
      {tab === "access" && canManageAccess && <AccessTab />}
    </>
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
          <input id="dp-code" className="input font-mono" placeholder="e.g. SFPL-FIN" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
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
          <input id="lo-name" className="input" placeholder="e.g. SFPL Head Office" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
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
  const [adding, setAdding] = useState(false);
  const canCreate = !!user && (user.permissions.includes("iam.write") || user.permissions.includes("*"));
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => usersApi.listRoles() });
  const users = useQuery({ queryKey: ["users"], queryFn: () => usersApi.listUsers() });
  const entityName = new Map((entities.data ?? []).map((e) => [e.id, e.name]));

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
            <thead><tr><th>Email</th><th>Role</th><th>Access</th><th className="hidden sm:table-cell">Linked employee</th><th>Status</th></tr></thead>
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
                  <td><StatusChip status={u.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddUserSheet open={adding} onClose={() => setAdding(false)} entities={entities.data ?? []} roles={roles.data ?? []} />
    </div>
  );
}

function AddUserSheet({ open, onClose, entities, roles }: {
  open: boolean; onClose: () => void; entities: LegalEntity[]; roles: Role[];
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { email: "", password: "", role: "", legalEntityIds: [] as string[] };
  const [form, setForm] = useState(empty);

  // Only offer roles whose permissions are a subset of the caller's own —
  // the server enforces this too, but hiding the option is better than a 403.
  const grantableRoles = roles.filter(
    (r) => user?.permissions.includes("*") || r.permissions.every((p) => user?.permissions.includes(p))
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
          <p className="mt-1 text-xs text-fg-subtle">Share this with them directly — they can change it after signing in.</p>
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
