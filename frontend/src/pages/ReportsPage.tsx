import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Play, Trash2, FileBarChart, Plus, MoreHorizontal } from "lucide-react";
import { reportsApi } from "../api/reports";
import type { ReportDef, RunResult, FilterSpec } from "../api/reports";
import { ReportBuilder, MODULES, FilterRow } from "../components/reports/ReportBuilder";
import { ResultTable } from "../components/reports/ResultTable";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { ConfirmDialog } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { usePopover } from "../components/ui/Popover";
import { useToast, errorMessage } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";

function ReportCard({ report, running, onRun, onDelete }: {
  report: ReportDef;
  running: boolean;
  onRun: () => void;
  onDelete: () => void;
}) {
  const { open: menuOpen, setOpen: setMenuOpen, ref: menuRef } = usePopover();
  const mod = MODULES.find((m) => m.value === report.module);
  const Icon = mod?.icon ?? FileBarChart;
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-panel text-fg-subtle"><Icon size={16} /></span>
        {!report.is_system && (
          <div ref={menuRef} className="relative">
            <button className="btn-icon -mr-2 -mt-1" onClick={() => setMenuOpen((o) => !o)} aria-label={`Actions for ${report.name}`}>
              <MoreHorizontal size={16} />
            </button>
            {menuOpen && (
              <div className="popover absolute right-0 top-full mt-1 w-36">
                <button className="menu-item hover:text-danger" onClick={() => { setMenuOpen(false); onDelete(); }}><Trash2 size={14} /> Delete</button>
              </div>
            )}
          </div>
        )}
      </div>
      <p className="mt-3 text-[13px] font-semibold text-fg">{report.name}</p>
      <p className="mt-0.5 line-clamp-2 min-h-[2.5em] text-xs text-fg-subtle">{report.description || `${mod?.label ?? report.module} report · ${report.columns.length} columns`}</p>
      <div className="mt-4 flex items-center justify-between gap-2">
        <div className="flex gap-1.5">
          <span className="badge badge-neutral">{mod?.label ?? report.module}</span>
          {report.is_system && <span className="badge badge-brand">Built-in</span>}
        </div>
        <button onClick={onRun} disabled={running} className="btn-secondary btn-sm">
          <Play size={12} /> {running ? "Running…" : "Run"}
        </button>
      </div>
    </div>
  );
}

export function ReportsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"saved" | "builder">("saved");
  const [result, setResult] = useState<RunResult | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ReportDef | null>(null);
  const [configuring, setConfiguring] = useState<ReportDef | null>(null);
  const [runFilters, setRunFilters] = useState<FilterSpec[]>([]);
  const { data: runMeta, isPending: isRunMetaPending } = useQuery({
    queryKey: ["report-meta", configuring?.module],
    queryFn: () => reportsApi.meta(configuring!.module),
    enabled: !!configuring,
  });
  const resultRef = useRef<HTMLDivElement>(null);

  const ownerType = user?.role === "EMPLOYEE" ? "EMPLOYEE" : "HR";
  const canBuild = user?.role !== "EMPLOYEE";

  const { data: reports, isPending: isLoading, isError, refetch } = useQuery<ReportDef[]>({
    queryKey: ["reports", ownerType],
    queryFn: () => reportsApi.list(ownerType),
  });

  const run = async (r: ReportDef, filters: FilterSpec[]) => {
    setRunningId(r.id);
    try {
      setResult(await reportsApi.run(r.id, filters.filter((f) => f.field)));
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (e) {
      toast.error("Couldn’t run report", errorMessage(e));
    } finally {
      setRunningId(null);
    }
  };

  const deleteMut = useMutation({
    mutationFn: (id: string) => reportsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      toast.success("Report deleted", deleting?.name);
      setDeleting(null);
    },
    onError: (e) => toast.error("Couldn’t delete report", errorMessage(e)),
  });

  const exportMut = useMutation({
    mutationFn: ({ id, filters }: { id: string; filters: FilterSpec[] }) => reportsApi.exportAttendance(id, filters),
    onError: (e) => toast.error("Couldn’t export Excel", errorMessage(e)),
  });

  return (
    <>
      <PageHeader
        title="Reports"
        description="Run built-in reports or build your own from attendance, people and onboarding data."
        actions={canBuild && tab === "saved" ? <button className="btn-primary" onClick={() => setTab("builder")}><Plus size={15} /> New report</button> : undefined}
      />

      {canBuild && (
        <Tabs
          className="mb-6"
          value={tab}
          onChange={setTab}
          items={[
            { value: "saved", label: "Saved reports", count: reports?.length },
            { value: "builder", label: "Report builder" },
          ]}
        />
      )}

      {tab === "saved" ? (
        <div className="space-y-6">
          {isError ? (
            <Notice title="Couldn’t load reports" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
              The reports API isn’t responding.
            </Notice>
          ) : isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
          ) : !reports?.length ? (
            <div className="card">
              <EmptyState
                icon={FileBarChart}
                title="No saved reports"
                description="Build a report once and run it any time from here."
                action={canBuild ? <button className="btn-primary" onClick={() => setTab("builder")}><Plus size={15} /> New report</button> : undefined}
              />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {reports.map((r) => (
                <ReportCard key={r.id} report={r} running={runningId !== null} onRun={() => { setConfiguring(r); setRunFilters(r.filters); setResult(null); }} onDelete={() => setDeleting(r)} />
              ))}
            </div>
          )}
          {configuring && (
            <div className="card space-y-3 p-5">
              <h3 className="card-title">Run {configuring.name}</h3>
              <p className="card-desc">Choose filters for this run. Empty values leave the report unrestricted.</p>
              {runFilters.map((filter, index) => <FilterRow key={index} filter={filter} meta={runMeta?.filters ?? []}
                onChange={(updated) => setRunFilters((fs) => fs.map((f, i) => i === index ? updated : f))}
                onRemove={() => setRunFilters((fs) => fs.filter((_, i) => i !== index))} />)}
              <div className="flex flex-wrap gap-2">
                <button className="btn-secondary btn-sm" disabled={!runMeta?.filters.length || runningId !== null}
                  onClick={() => setRunFilters((fs) => [...fs, { field: "", op: "eq", value: "" }])}><Plus size={13} /> Add filter</button>
                <button className="btn-primary btn-sm" disabled={!runMeta || runningId !== null}
                  onClick={() => run(configuring, runFilters)}><Play size={13} /> {runningId ? "Running…" : "Run report"}</button>
                {configuring.module === "ATTENDANCE" && <button className="btn-secondary btn-sm"
                  disabled={!runMeta || isRunMetaPending || exportMut.isPending || runningId !== null}
                  onClick={() => exportMut.mutate({ id: configuring.id, filters: runFilters.filter((filter) => filter.field) })}>
                  <Download size={13} /> {exportMut.isPending && exportMut.variables.id === configuring.id ? "Exporting…" : "Export Excel"}
                </button>}
              </div>
              {configuring.module === "ATTENDANCE" && <p className="text-xs text-fg-subtle">Set both dates to export company summaries, leave balances and daily logs to Excel.</p>}
            </div>
          )}
          <div ref={resultRef} className="scroll-mt-6">{result && <ResultTable result={result} />}</div>
        </div>
      ) : (
        <ReportBuilder onSave={() => qc.invalidateQueries({ queryKey: ["reports"] })} />
      )}

      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && deleteMut.mutate(deleting.id)}
        loading={deleteMut.isPending}
        title={`Delete “${deleting?.name}”?`}
        description="The saved report definition will be removed. This can’t be undone."
        confirmLabel="Delete report"
      />
    </>
  );
}
