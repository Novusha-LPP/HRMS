import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { BriefcaseBusiness, ChevronLeft, ChevronRight, Clock, Plus, Search, UserCheck, Users } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { Tabs } from "../components/ui/Tabs";
import { StatusBadge } from "../components/ui/StatusBadge";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { errorMessage } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { recruitmentApi } from "../api/recruitment";
import type { OpeningStatus, OpeningSummary, Stage } from "../api/recruitment";
import { OPENING_STATUS, PRIORITY, STAGE_DOT, years } from "../components/recruitment/meta";
import { OpeningFormSheet } from "../components/recruitment/OpeningFormSheet";
import { StagesSettings } from "../components/recruitment/StagesSettings";
import { LinkIcon } from "../components/recruitment/LinkIcon";

type PageTab = "openings" | "candidates" | "pipeline";
type Filter = "active" | "approval" | "drafts" | "done" | "all";

const FILTERS: Record<Filter, { label: string; statuses: OpeningStatus[] | null }> = {
  active: { label: "Active", statuses: ["OPEN", "ON_HOLD"] },
  approval: { label: "Awaiting approval", statuses: ["PENDING_APPROVAL"] },
  drafts: { label: "Drafts", statuses: ["DRAFT", "REJECTED"] },
  done: { label: "Filled & closed", statuses: ["FILLED", "CLOSED"] },
  all: { label: "All", statuses: null },
};

function PipelineBar({ opening, stages }: { opening: OpeningSummary; stages: Stage[] }) {
  if (!opening.candidates) return <span className="text-xs text-fg-subtle">No candidates</span>;
  const byId = new Map(opening.stage_counts.map((c) => [c.stage_id, c.count]));
  return (
    <div className="w-36">
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted">
        {stages.filter((s) => byId.get(s.id)).map((s) => (
          <span key={s.id} className={STAGE_DOT[s.color]} style={{ width: `${(byId.get(s.id)! / opening.candidates) * 100}%` }} title={`${s.name}: ${byId.get(s.id)}`} />
        ))}
      </div>
      <p className="mt-1 text-[11px] text-fg-subtle">{opening.in_progress} in progress · {opening.candidates} total</p>
    </div>
  );
}

function OpeningsTab({ stages, onRaise, canRequest }: { stages: Stage[]; onRaise: () => void; canRequest: boolean }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = (Object.keys(FILTERS).includes(params.get("filter") ?? "") ? params.get("filter") : "active") as Filter;
  const setFilter = (f: Filter) => { const next = new URLSearchParams(params); if (f === "active") next.delete("filter"); else next.set("filter", f); setParams(next, { replace: true }); };
  const [search, setSearch] = useState("");
  const [mine, setMine] = useState(false);
  const openings = useQuery({
    queryKey: ["recruitment-openings", mine ? "mine" : "all"],
    queryFn: () => recruitmentApi.openings({ mine }),
  });

  const all = openings.data ?? [];
  const q = search.trim().toLowerCase();
  const rows = all.filter((o) =>
    (!FILTERS[filter].statuses || FILTERS[filter].statuses!.includes(o.status))
    && (!q || `${o.code} ${o.title} ${o.org_unit_name ?? ""} ${o.hiring_manager_name ?? ""}`.toLowerCase().includes(q)),
  );
  const counts = (statuses: OpeningStatus[] | null) => all.filter((o) => !statuses || statuses.includes(o.status)).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1">
          {(Object.keys(FILTERS) as Filter[]).map((f) => (
            <button key={f} type="button" onClick={() => setFilter(f)}
              className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors ${filter === f ? "bg-fg text-surface" : "text-fg-muted hover:bg-muted hover:text-fg"}`}>
              {FILTERS[f].label}
              <span className={`rounded-full px-1.5 text-[10px] tabular-nums ${filter === f ? "bg-surface/20" : "bg-muted"}`}>{counts(FILTERS[f].statuses)}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex shrink-0 items-center gap-2 text-xs text-fg-muted">
            <input type="checkbox" className="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Raised by or for me
          </label>
          <div className="relative w-full lg:w-64">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input className="input pl-8" placeholder="Search openings" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
      </div>

      {openings.isPending ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : openings.isError ? (
        <Notice title="Couldn’t load openings">{errorMessage(openings.error)}</Notice>
      ) : rows.length === 0 ? (
        <div className="card">
          <EmptyState icon={BriefcaseBusiness}
            title={all.length ? "No openings match" : "No job openings yet"}
            description={all.length ? "Try another filter or search." : canRequest ? "Raise an opening for your team. It goes for approval, then HR starts sourcing candidates." : "Openings raised by department heads, team leads and PMs appear here once submitted."}
            action={!all.length && canRequest ? <button type="button" className="btn-primary btn-sm" onClick={onRaise}><Plus size={13} /> Raise opening</button> : undefined} />
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr><th>Opening</th><th>Status</th><th>Hiring manager</th><th>Pipeline</th><th className="text-right">Hired</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id} className="cursor-pointer" onClick={() => navigate(`/recruitment/openings/${o.id}`)}>
                  <td className="min-w-[16rem]">
                    <Link to={`/recruitment/openings/${o.id}`} className="font-medium text-fg hover:underline" onClick={(e) => e.stopPropagation()}>{o.title}</Link>
                    <p className="text-xs text-fg-subtle">
                      <span className="font-mono">{o.code}</span> · {o.org_unit_name}{o.legal_entity_name ? ` · ${o.legal_entity_name}` : ""}
                    </p>
                  </td>
                  <td>
                    <div className="flex flex-col items-start gap-1">
                      <StatusBadge tone={OPENING_STATUS[o.status].tone} label={OPENING_STATUS[o.status].label} />
                      {(o.priority === "HIGH" || o.priority === "CRITICAL") && <StatusBadge tone={PRIORITY[o.priority].tone} label={PRIORITY[o.priority].label} dot={false} />}
                    </div>
                  </td>
                  <td className="whitespace-nowrap">{o.hiring_manager_name ?? "—"}</td>
                  <td><PipelineBar opening={o} stages={stages} /></td>
                  <td className="text-right tabular-nums"><span className="font-medium text-fg">{o.hired}</span> / {o.positions}</td>
                  <td className="whitespace-nowrap text-xs">{formatDistanceToNow(new Date(o.updated_at), { addSuffix: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CandidatesTab() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const size = 25;
  const q = search.trim();
  const candidates = useQuery({
    queryKey: ["recruitment-candidates", q, page],
    queryFn: () => recruitmentApi.candidates({ q, limit: size, offset: page * size }),
    placeholderData: (prev) => prev,
  });
  const total = candidates.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-fg-muted">Everyone you’ve sourced, across openings. A candidate keeps one profile however many roles they’re considered for.</p>
        <div className="relative w-full sm:w-72">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input className="input pl-8" placeholder="Name, email, company or skill" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} />
        </div>
      </div>
      {candidates.isPending ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : candidates.isError ? (
        <Notice title="Couldn’t load the talent pool">{errorMessage(candidates.error)}</Notice>
      ) : !candidates.data?.items.length ? (
        <div className="card"><EmptyState icon={Users} title={q ? "No candidates match" : "No candidates yet"} description={q ? "Try a different search." : "Candidates you add to openings build up here."} /></div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Candidate</th><th>Experience</th><th>Skills</th><th>Profiles</th><th>Openings</th></tr></thead>
            <tbody>
              {candidates.data.items.map(({ candidate: c, applications }) => (
                <tr key={c.id}>
                  <td className="min-w-[14rem]">
                    <p className="font-medium text-fg">{c.full_name}</p>
                    <p className="text-xs text-fg-subtle">{[c.current_title, c.current_company].filter(Boolean).join(" · ") || c.email || "—"}</p>
                  </td>
                  <td className="whitespace-nowrap">{c.total_experience_years ? years(c.total_experience_years) : "—"}</td>
                  <td className="max-w-[14rem]">
                    <div className="flex flex-wrap gap-1">
                      {c.skills.slice(0, 3).map((s) => <span key={s} className="rounded bg-muted px-1.5 py-px text-[11px] text-fg">{s}</span>)}
                      {c.skills.length > 3 && <span className="text-[11px] text-fg-subtle">+{c.skills.length - 3}</span>}
                    </div>
                  </td>
                  <td>
                    <div className="flex items-center gap-1">
                      {c.links.slice(0, 4).map((l) => (
                        <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer nofollow" className="btn-icon h-7 w-7" title={l.url} aria-label={l.type}>
                          <LinkIcon type={l.type} size={13} />
                        </a>
                      ))}
                      {!c.links.length && <span className="text-xs text-fg-subtle">—</span>}
                    </div>
                  </td>
                  <td className="min-w-[14rem]">
                    <div className="flex flex-col gap-1">
                      {applications.map((a) => (
                        <Link key={a.id} to={`/recruitment/openings/${a.opening_id}?application=${a.id}`} className="inline-flex items-center gap-1.5 text-xs hover:underline">
                          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STAGE_DOT[a.stage_color ?? "neutral"]}`} />
                          <span className="font-mono text-fg-subtle">{a.opening_code}</span>
                          <span className="truncate text-fg">{a.stage_name}</span>
                        </Link>
                      ))}
                      {!applications.length && <span className="text-xs text-fg-subtle">—</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <div className="flex items-center justify-between border-t border-line px-5 py-3 text-xs text-fg-subtle">
              <span>{page * size + 1}–{Math.min(total, (page + 1) * size)} of {total}</span>
              <div className="flex items-center gap-1">
                <button type="button" className="btn-icon" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}><ChevronLeft size={14} /></button>
                <button type="button" className="btn-icon" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight size={14} /></button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function RecruitmentPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [raising, setRaising] = useState(params.get("new") === "1");
  const access = useQuery({ queryKey: ["recruitment-access"], queryFn: recruitmentApi.access });
  const stages = useQuery({ queryKey: ["recruitment-stages"], queryFn: recruitmentApi.stages });
  const openings = useQuery({ queryKey: ["recruitment-openings", "all"], queryFn: () => recruitmentApi.openings() });

  const perms = user?.permissions ?? [];
  const recruiter = perms.includes("*") || perms.includes("recruitment.read") || perms.includes("recruitment.manage");
  const canEditPipeline = !!access.data?.can_manage && (perms.includes("*") || !!user?.isAllScope);
  const tab = (["openings", "candidates", "pipeline"].includes(params.get("tab") ?? "") ? params.get("tab") : "openings") as PageTab;
  const setTab = (t: PageTab) => { const next = new URLSearchParams(); if (t !== "openings") next.set("tab", t); setParams(next, { replace: true }); };

  const stats = useMemo(() => {
    const all = openings.data ?? [];
    const live = all.filter((o) => o.status === "OPEN" || o.status === "ON_HOLD");
    return {
      open: all.filter((o) => o.status === "OPEN").length,
      pending: all.filter((o) => o.status === "PENDING_APPROVAL").length,
      pipeline: live.reduce((n, o) => n + o.in_progress, 0),
      hired: all.reduce((n, o) => n + o.hired, 0),
      positions: live.reduce((n, o) => n + Math.max(o.positions - o.hired, 0), 0),
    };
  }, [openings.data]);
  const canRequest = !!access.data?.can_request;

  return (
    <div>
      <PageHeader
        title="Recruitment"
        description={recruiter ? "Job openings from across the organisation, their approval and the candidate pipeline." : "Raise openings for your team and follow the candidates HR brings in."}
        actions={canRequest ? <button type="button" className="btn-primary" onClick={() => setRaising(true)}><Plus size={15} /> Raise opening</button> : undefined}
      />

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Open roles" value={stats.open} icon={BriefcaseBusiness} iconTone="teal" hint={`${stats.positions} position${stats.positions === 1 ? "" : "s"} to fill`} loading={openings.isPending} />
        <StatCard label="Awaiting approval" value={stats.pending} icon={Clock} iconTone="orange" hint="Openings pending sign-off" loading={openings.isPending} />
        <StatCard label="In pipeline" value={stats.pipeline} icon={Users} iconTone="blue" hint="Candidates in progress" loading={openings.isPending} />
        <StatCard label="Hired" value={stats.hired} icon={UserCheck} iconTone="green" hint="Across all openings" loading={openings.isPending} />
      </div>

      {access.isError && <div className="mb-4"><Notice title="Couldn’t load recruitment access">{errorMessage(access.error)}</Notice></div>}

      {recruiter && (
        <Tabs<PageTab>
          className="mb-5"
          value={tab}
          onChange={setTab}
          items={[
            { value: "openings", label: "Openings" },
            { value: "candidates", label: "Talent pool" },
            { value: "pipeline", label: "Pipeline stages" },
          ]}
        />
      )}

      {tab === "candidates" && recruiter ? (
        <CandidatesTab />
      ) : tab === "pipeline" && recruiter ? (
        <StagesSettings canEdit={canEditPipeline} />
      ) : (
        <OpeningsTab stages={stages.data ?? []} onRaise={() => setRaising(true)} canRequest={canRequest} />
      )}

      <OpeningFormSheet open={raising} onClose={() => {
        setRaising(false);
        if (params.get("new")) { const next = new URLSearchParams(params); next.delete("new"); setParams(next, { replace: true }); }
      }} />
    </div>
  );
}

