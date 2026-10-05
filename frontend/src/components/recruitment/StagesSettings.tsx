import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, RotateCcw, Trash2 } from "lucide-react";
import { Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { recruitmentApi } from "../../api/recruitment";
import type { Stage, StageCategory, StageColor } from "../../api/recruitment";
import { STAGE_CATEGORIES, STAGE_COLORS, STAGE_DOT } from "./meta";

type Row = { key: string; id?: string; name: string; category: StageCategory; color: StageColor; is_active: boolean };

const toRows = (stages: Stage[]): Row[] =>
  stages.filter((s) => s.is_active).map((s) => ({ key: s.id, id: s.id, name: s.name, category: s.category, color: s.color, is_active: true }));

/** The tenant's candidate pipeline: names, order, colour and what each stage means. */
export function StagesSettings({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const stages = useQuery({ queryKey: ["recruitment-stages"], queryFn: recruitmentApi.stages });
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadedVersion, setLoadedVersion] = useState<Stage[] | undefined>(undefined);
  if (stages.data && stages.data !== loadedVersion) {
    setLoadedVersion(stages.data);
    setRows(toRows(stages.data));
  }

  const save = useMutation({
    mutationFn: () => recruitmentApi.saveStages((rows ?? []).map(({ id, name, category, color, is_active }) => ({ id, name: name.trim(), category, color, is_active }))),
    onSuccess: (saved) => { qc.setQueryData(["recruitment-stages"], saved); qc.invalidateQueries({ queryKey: ["recruitment-applications"] }); toast.success("Pipeline saved"); },
    onError: (e) => toast.error("Couldn’t save the pipeline", errorMessage(e)),
  });

  if (stages.isPending || !rows) return <Skeleton className="h-80 rounded-xl" />;
  if (stages.isError) return <Notice title="Couldn’t load the pipeline">{errorMessage(stages.error)}</Notice>;

  const update = (i: number, patch: Partial<Row>) => setRows((r) => r!.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  const moveRow = (i: number, d: -1 | 1) => setRows((r) => {
    const next = [...r!];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    return next;
  });

  const names = rows.map((r) => r.name.trim().toLowerCase());
  const problems = [
    rows.some((r) => !r.name.trim()) && "Every stage needs a name.",
    new Set(names).size !== names.length && "Stage names must be unique.",
    !rows.some((r) => r.category === "ACTIVE") && "Keep at least one in-progress stage.",
    !rows.some((r) => r.category === "HIRED") && "Keep at least one hired stage (e.g. Onboarding).",
    !rows.some((r) => r.category === "REJECTED" || r.category === "WITHDRAWN") && "Keep a rejected or withdrawn stage.",
  ].filter(Boolean) as string[];
  const dirty = JSON.stringify(rows.map(({ key: _k, ...r }) => r)) !== JSON.stringify(toRows(stages.data ?? []).map(({ key: _k, ...r }) => r));

  return (
    <div className="card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h3 className="card-title">Candidate pipeline</h3>
          <p className="card-desc max-w-xl">
            The stages every opening uses, in order. The outcome decides what a stage means: candidates in a <span className="font-medium text-fg-muted">Hired</span> stage fill positions and can become employees; rejected and withdrawn stages ask for a reason.
          </p>
        </div>
        {canEdit && (
          <div className="flex items-center gap-2">
            {dirty && <button type="button" className="btn-ghost btn-sm" onClick={() => setRows(toRows(stages.data ?? []))}><RotateCcw size={13} /> Reset</button>}
            <button type="button" className="btn-primary btn-sm" disabled={!dirty || problems.length > 0 || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : "Save pipeline"}
            </button>
          </div>
        )}
      </div>
      <ol className="divide-y divide-line">
        {rows.map((row, i) => (
          <li key={row.key} className="flex flex-wrap items-center gap-3 px-5 py-3">
            <span className="w-5 text-right text-xs tabular-nums text-fg-subtle">{i + 1}</span>
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${STAGE_DOT[row.color]}`} />
            <input aria-label={`Stage ${i + 1} name`} className="input h-8 min-w-[10rem] flex-1 basis-40" maxLength={60}
              value={row.name} disabled={!canEdit} onChange={(e) => update(i, { name: e.target.value })} />
            <select aria-label="Outcome" className="input h-8 w-36" value={row.category} disabled={!canEdit} onChange={(e) => update(i, { category: e.target.value as StageCategory })}
              title={STAGE_CATEGORIES[row.category].hint}>
              {Object.entries(STAGE_CATEGORIES).map(([v, c]) => <option key={v} value={v}>{c.label}</option>)}
            </select>
            <div className="flex items-center gap-1" role="radiogroup" aria-label="Colour">
              {STAGE_COLORS.map((color) => (
                <button key={color} type="button" disabled={!canEdit} role="radio" aria-checked={row.color === color} aria-label={color}
                  onClick={() => update(i, { color })}
                  className={`grid h-6 w-6 place-items-center rounded-full ${row.color === color ? "ring-2 ring-brand-500 ring-offset-1 ring-offset-surface" : ""}`}>
                  <span className={`h-3.5 w-3.5 rounded-full ${STAGE_DOT[color]}`} />
                </button>
              ))}
            </div>
            {canEdit && (
              <div className="ml-auto flex items-center gap-0.5">
                <button type="button" className="btn-icon" aria-label="Move up" disabled={i === 0} onClick={() => moveRow(i, -1)}><ArrowUp size={14} /></button>
                <button type="button" className="btn-icon" aria-label="Move down" disabled={i === rows.length - 1} onClick={() => moveRow(i, 1)}><ArrowDown size={14} /></button>
                <button type="button" className="btn-icon hover:text-danger" aria-label="Remove stage" disabled={rows.length <= 3}
                  title="Removed stages are archived; candidates already in them stay put"
                  onClick={() => setRows((r) => r!.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
              </div>
            )}
          </li>
        ))}
      </ol>
      {canEdit && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
          <button type="button" className="btn-secondary btn-sm" disabled={rows.length >= 30}
            onClick={() => setRows((r) => {
              const next = [...r!];
              const at = Math.max(0, next.findIndex((x) => x.category !== "ACTIVE"));
              next.splice(at === -1 ? next.length : at, 0, { key: `new-${Date.now()}`, name: "", category: "ACTIVE", color: "info", is_active: true });
              return next;
            })}>
            <Plus size={13} /> Add stage
          </button>
          {problems.length > 0 && <p className="text-xs font-medium text-danger">{problems[0]}</p>}
        </div>
      )}
      {!canEdit && <p className="border-t border-line px-5 py-3 text-xs text-fg-subtle">Only recruiters with access to every company can change the pipeline.</p>}
    </div>
  );
}
