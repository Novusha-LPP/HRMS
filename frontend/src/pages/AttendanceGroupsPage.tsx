import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { format, parseISO } from "date-fns";
import { ClipboardCheck, Eye, KeyRound, Pencil, Plus, Search, Trash2, UserMinus, Users } from "lucide-react";
import { groupsApi, type AttendanceGroup, type GroupAccessLevel } from "../api/marking";
import { timeApi } from "../api/time";
import { usersApi } from "../api/users";
import { PageHeader } from "../components/ui/PageHeader";
import { Avatar } from "../components/ui/Avatar";
import { Segmented } from "../components/ui/Tabs";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";

const LEVEL_LABEL: Record<GroupAccessLevel, string> = { VIEW: "View", MARK: "Mark" };

/**
 * HR's set-up for marked attendance: groups such as Guards, Drivers and Cleaners, who is in each
 * one and from when, and who may view or mark each group's daily sheet.
 * URL: ?group=<group id>&tab=members|access
 */
export function AttendanceGroupsPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("group");
  const tab = (params.get("tab") as "members" | "access") ?? "members";
  const [creating, setCreating] = useState(false);
  const groups = useQuery({ queryKey: ["attendance-groups"], queryFn: groupsApi.list });
  const current = groups.data?.find((g) => g.id === selected) ?? groups.data?.[0] ?? null;
  const choose = (id: string, nextTab = tab) => setParams((p) => {
    const n = new URLSearchParams(p);
    n.set("group", id);
    n.set("tab", nextTab);
    return n;
  });

  return (
    <>
      <PageHeader
        title="Attendance groups"
        description="Groups of people whose attendance is marked instead of punched — guards, drivers, cleaners. Add people to a group, then decide who may view or mark its daily sheet."
        actions={<>
          <Link to="/attendance/marking" className="btn-secondary"><ClipboardCheck size={15} /> Mark attendance</Link>
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> New group</button>
        </>}
      />
      {groups.isError && <div className="mb-4"><Notice title="Couldn’t load groups" action={<button className="btn-secondary btn-sm" onClick={() => groups.refetch()}>Retry</button>}>
        {errorMessage(groups.error)}
      </Notice></div>}
      {groups.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]"><Skeleton className="h-64 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div>
      ) : (groups.data ?? []).length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Users}
            title="No attendance groups yet"
            description="Create a group such as Guards, Drivers or Cleaners. Everyone you add to it has their attendance marked instead of punched."
            action={<button type="button" className="btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> New group</button>}
          />
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <ul className="card divide-y divide-line overflow-hidden" aria-label="Groups">
            {(groups.data ?? []).map((g) => {
              const active = g.id === current?.id;
              return (
                <li key={g.id}>
                  <button type="button" onClick={() => choose(g.id)} aria-current={active}
                    className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors ${active ? "bg-brand-500/10" : "hover:bg-muted"}`}>
                    <span className="min-w-0">
                      <span className={`block truncate text-[13px] font-medium ${active ? "text-accent" : "text-fg"}`}>{g.name}</span>
                      <span className="block truncate text-xs text-fg-subtle">{g.company ?? "Any company"}</span>
                    </span>
                    <span className="shrink-0 text-xs text-fg-muted">{g.member_count} {g.member_count === 1 ? "person" : "people"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {current && <GroupDetail key={current.id} group={current} tab={tab} onTab={(t) => choose(current.id, t)} />}
        </div>
      )}
      <GroupForm open={creating} onClose={() => setCreating(false)} onSaved={(g) => { setCreating(false); choose(g.id, "members"); }} />
    </>
  );
}

function GroupDetail({ group, tab, onTab }: { group: AttendanceGroup; tab: "members" | "access"; onTab: (t: "members" | "access") => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const retire = useMutation({
    mutationFn: () => groupsApi.archive(group.id),
    onSuccess: () => { toast.success("Group retired", group.name); qc.invalidateQueries({ queryKey: ["attendance-groups"] }); },
    onError: (e) => toast.error("Couldn’t retire the group", errorMessage(e)),
  });
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-fg">{group.name}</h2>
          <p className="text-xs text-fg-subtle">{group.description || "No description"} · {group.company ?? "Any company"}</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(true)}><Pencil size={14} /> Edit</button>
          <button type="button" className="btn-ghost btn-sm" disabled={retire.isPending}
            onClick={() => window.confirm(`Retire ${group.name}? Its history stays; nobody can be added any more.`) && retire.mutate()}>
            <Trash2 size={14} /> Retire
          </button>
        </div>
      </div>
      <div className="border-b border-line px-5 py-3">
        <Segmented value={tab} onChange={onTab} items={[{ value: "members", label: "Members", icon: Users }, { value: "access", label: "Who can view or mark", icon: KeyRound }]} />
      </div>
      {tab === "members" ? <Members group={group} /> : <Access group={group} />}
      <GroupForm open={editing} group={group} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />
    </div>
  );
}

function Members({ group }: { group: AttendanceGroup }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const members = useQuery({ queryKey: ["group-members", group.id], queryFn: () => groupsApi.members(group.id) });
  const remove = useMutation({
    mutationFn: ({ id, lastDay }: { id: string; lastDay: string }) => groupsApi.removeMember(group.id, id, lastDay),
    onSuccess: () => {
      toast.success("Taken out of the group");
      qc.invalidateQueries({ queryKey: ["group-members", group.id] });
      qc.invalidateQueries({ queryKey: ["attendance-groups"] });
    },
    onError: (e) => toast.error("Couldn’t take them out", errorMessage(e)),
  });
  const takeOut = (id: string, name: string) => {
    const lastDay = window.prompt(`Last day in ${group.name} for ${name} (YYYY-MM-DD). From the next day they punch again.`, format(new Date(), "yyyy-MM-dd"));
    if (lastDay && /^\d{4}-\d{2}-\d{2}$/.test(lastDay)) remove.mutate({ id, lastDay });
  };
  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <p className="text-xs text-fg-subtle">People in this group today. Their days are marked on Mark attendance; their policy still sets their shift, holidays and weekly offs.</p>
        <button type="button" className="btn-secondary btn-sm shrink-0" onClick={() => setAdding(true)}><Plus size={14} /> Add people</button>
      </div>
      {members.isPending ? <div className="p-5"><Skeleton className="h-24 rounded-lg" /></div>
        : (members.data ?? []).length === 0 ? (
          <EmptyState icon={Users} title="Nobody in this group" description="Add the people whose attendance should be marked." />
        ) : (
          <ul className="divide-y divide-line border-t border-line">
            {(members.data ?? []).map((m) => (
              <li key={m.employment_id} className="flex items-center gap-3 px-5 py-2.5">
                <Avatar name={m.name} size="sm" employmentId={m.employment_id} />
                <div className="min-w-0 flex-1 leading-tight">
                  <p className="truncate text-[13px] font-medium text-fg">{m.name}</p>
                  <p className="truncate text-xs text-fg-subtle">{m.employee_number}{m.department ? ` · ${m.department}` : ""} · since {format(parseISO(m.effective_from), "d MMM yyyy")}</p>
                </div>
                <button type="button" className="btn-ghost btn-sm" onClick={() => takeOut(m.employment_id, m.name)} aria-label={`Take ${m.name} out`}><UserMinus size={14} /> Take out</button>
              </li>
            ))}
          </ul>
        )}
      <AddMembersSheet group={group} open={adding} onClose={() => setAdding(false)} existing={new Set((members.data ?? []).map((m) => m.employment_id))} />
    </div>
  );
}

function AddMembersSheet({ group, open, onClose, existing }: { group: AttendanceGroup; open: boolean; onClose: () => void; existing: Set<string> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [from, setFrom] = useState(format(new Date(), "yyyy-MM-dd"));
  const people = useQuery({
    queryKey: ["group-candidates", search, group.legal_entity_id],
    queryFn: () => timeApi.findEmployees(search.trim(), group.legal_entity_id ?? undefined),
    enabled: open,
  });
  const add = useMutation({
    mutationFn: () => groupsApi.addMembers(group.id, [...chosen], from),
    onSuccess: () => {
      toast.success(`${chosen.size} added to ${group.name}`);
      setChosen(new Set());
      qc.invalidateQueries({ queryKey: ["group-members", group.id] });
      qc.invalidateQueries({ queryKey: ["attendance-groups"] });
      onClose();
    },
    onError: (e) => toast.error("Nobody was added", errorMessage(e)),
  });
  const toggle = (id: string) => setChosen((c) => { const n = new Set(c); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const submit = (e: FormEvent) => { e.preventDefault(); if (chosen.size) add.mutate(); };
  return (
    <Sheet open={open} onClose={onClose} title={`Add people to ${group.name}`}
      description="From the date you pick, their attendance is marked instead of punched. Someone in another group must be taken out of it first."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="add-members" disabled={!chosen.size || add.isPending}>{add.isPending ? "Adding…" : `Add ${chosen.size || ""}`}</button>
      </>}>
      <form id="add-members" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="am-from">In the group from</label>
          <input id="am-from" type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input className="input pl-9" placeholder="Search name or ID" aria-label="Search people" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {people.isPending ? <li className="p-3"><Skeleton className="h-8" /></li>
            : (people.data ?? []).filter((p) => !existing.has(p.employment_id)).map((p) => (
              <li key={p.employment_id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted">
                  <input type="checkbox" checked={chosen.has(p.employment_id)} onChange={() => toggle(p.employment_id)} />
                  <span className="min-w-0 leading-tight">
                    <span className="block truncate text-[13px] text-fg">{p.name}</span>
                    <span className="block truncate text-xs text-fg-subtle">{p.employee_number}{p.department ? ` · ${p.department}` : ""} · {p.company}</span>
                  </span>
                </label>
              </li>
            ))}
        </ul>
      </form>
    </Sheet>
  );
}

function Access({ group }: { group: AttendanceGroup }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [granting, setGranting] = useState(false);
  const access = useQuery({ queryKey: ["group-access", group.id], queryFn: () => groupsApi.access(group.id) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["group-access", group.id] });
  const change = useMutation({
    mutationFn: ({ user, level }: { user: string; level: GroupAccessLevel }) => groupsApi.grant(group.id, user, level),
    onSuccess: () => { toast.success("Access changed"); refresh(); },
    onError: (e) => toast.error("Couldn’t change access", errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (user: string) => groupsApi.revoke(group.id, user),
    onSuccess: () => { toast.success("Access removed"); refresh(); },
    onError: (e) => toast.error("Couldn’t remove access", errorMessage(e)),
  });
  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <p className="text-xs text-fg-subtle">
          <Eye size={12} className="mr-1 inline" /><b>View</b>: see the daily sheet. <ClipboardCheck size={12} className="mx-1 inline" /><b>Mark</b>: also mark days and record leave.
          A supervisor needs no HR role for this. HR managers can always view and mark.
        </p>
        <button type="button" className="btn-secondary btn-sm shrink-0" onClick={() => setGranting(true)}><Plus size={14} /> Give access</button>
      </div>
      {access.isPending ? <div className="p-5"><Skeleton className="h-24 rounded-lg" /></div>
        : (access.data ?? []).length === 0 ? (
          <EmptyState icon={KeyRound} title="Only HR can see this group" description="Give a supervisor Mark to keep the daily sheet, or View to see it." />
        ) : (
          <ul className="divide-y divide-line border-t border-line">
            {(access.data ?? []).map((a) => (
              <li key={a.user_account_id} className="flex items-center gap-3 px-5 py-2.5">
                <Avatar name={a.name} size="sm" />
                <div className="min-w-0 flex-1 leading-tight">
                  <p className="truncate text-[13px] font-medium text-fg">{a.name}</p>
                  {a.email && <p className="truncate text-xs text-fg-subtle">{a.email}</p>}
                </div>
                <select className="input w-28" aria-label={`${a.name}'s access`} value={a.access_level} disabled={change.isPending}
                  onChange={(e) => change.mutate({ user: a.user_account_id, level: e.target.value as GroupAccessLevel })}>
                  <option value="VIEW">View</option>
                  <option value="MARK">Mark</option>
                </select>
                <button type="button" className="btn-ghost btn-sm" aria-label={`Remove ${a.name}'s access`} disabled={revoke.isPending}
                  onClick={() => window.confirm(`Remove ${a.name}'s access to ${group.name}?`) && revoke.mutate(a.user_account_id)}><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
      <GrantSheet group={group} open={granting} onClose={() => setGranting(false)} taken={new Set((access.data ?? []).map((a) => a.user_account_id))} />
    </div>
  );
}

function GrantSheet({ group, open, onClose, taken }: { group: AttendanceGroup; open: boolean; onClose: () => void; taken: Set<string> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [user, setUser] = useState("");
  const [level, setLevel] = useState<GroupAccessLevel>("MARK");
  const users = useQuery({ queryKey: ["users"], queryFn: usersApi.listUsers, enabled: open });
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (users.data ?? [])
      .filter((u) => u.status === "ACTIVE" && u.can_sign_in && !taken.has(u.id))
      .filter((u) => !q || `${u.employee_name ?? ""} ${u.email ?? ""}`.toLowerCase().includes(q))
      .slice(0, 50);
  }, [users.data, search, taken]);
  const grant = useMutation({
    mutationFn: () => groupsApi.grant(group.id, user, level),
    onSuccess: () => {
      toast.success(`${LEVEL_LABEL[level]} access given`, group.name);
      setUser("");
      qc.invalidateQueries({ queryKey: ["group-access", group.id] });
      onClose();
    },
    onError: (e) => toast.error("Couldn’t give access", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (user) grant.mutate(); };
  return (
    <Sheet open={open} onClose={onClose} title={`Who can view or mark ${group.name}`}
      description="Pick a login. Mark lets them keep the daily sheet and record leave for this group only."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="grant-access" disabled={!user || grant.isPending}>{grant.isPending ? "Saving…" : "Give access"}</button>
      </>}>
      <form id="grant-access" onSubmit={submit} className="space-y-4">
        <div>
          <span className="label">Access</span>
          <Segmented value={level} onChange={setLevel} items={[{ value: "MARK", label: "Mark", icon: ClipboardCheck }, { value: "VIEW", label: "View", icon: Eye }]} />
        </div>
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input className="input pl-9" placeholder="Search name or email" aria-label="Search logins" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line" role="listbox" aria-label="Logins">
          {users.isPending ? <li className="p-3"><Skeleton className="h-8" /></li>
            : matches.map((u) => (
              <li key={u.id}>
                <button type="button" role="option" aria-selected={user === u.id} onClick={() => setUser(u.id)}
                  className={`flex w-full flex-col px-3 py-2 text-left ${user === u.id ? "bg-brand-500/10" : "hover:bg-muted"}`}>
                  <span className="truncate text-[13px] text-fg">{u.employee_name ?? u.email ?? u.id}</span>
                  <span className="truncate text-xs text-fg-subtle">{u.email ?? ""} · {u.role}</span>
                </button>
              </li>
            ))}
        </ul>
      </form>
    </Sheet>
  );
}

function GroupForm({ open, group, onClose, onSaved }: { open: boolean; group?: AttendanceGroup; onClose: () => void; onSaved: (g: AttendanceGroup) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(group?.name ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [company, setCompany] = useState(group?.legal_entity_id ?? "");
  const filters = useQuery({ queryKey: ["register-filters"], queryFn: timeApi.registerFilters, enabled: open });
  const save = useMutation({
    mutationFn: () => group
      ? groupsApi.update(group.id, { name: name.trim(), description: description.trim() || null, legal_entity_id: company || null })
      : groupsApi.create({ name: name.trim(), description: description.trim() || undefined, legal_entity_id: company || undefined }),
    onSuccess: (g) => {
      toast.success(group ? "Group saved" : "Group created", g.name);
      qc.invalidateQueries({ queryKey: ["attendance-groups"] });
      if (!group) { setName(""); setDescription(""); setCompany(""); }
      onSaved(g);
    },
    onError: (e) => toast.error("Couldn’t save the group", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) save.mutate(); };
  return (
    <Sheet open={open} onClose={onClose} title={group ? `Edit ${group.name}` : "New attendance group"}
      description="For example Guards, Drivers or Cleaners."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="group-form" disabled={!name.trim() || save.isPending}>{save.isPending ? "Saving…" : group ? "Save" : "Create group"}</button>
      </>}>
      <form id="group-form" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="gf-name">Name</label>
          <input id="gf-name" className="input" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="Guards" />
        </div>
        <div>
          <label className="label" htmlFor="gf-desc">Description (optional)</label>
          <input id="gf-desc" className="input" maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Gate and site security" />
        </div>
        <div>
          <label className="label" htmlFor="gf-company">Company</label>
          <select id="gf-company" className="input" value={company} onChange={(e) => setCompany(e.target.value)}>
            <option value="">Any company</option>
            {(filters.data?.companies ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <p className="hint">Pick one to allow only that company’s people in the group.</p>
        </div>
      </form>
    </Sheet>
  );
}
