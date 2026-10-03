import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Trash2, Play, Clock, Users, ClipboardCheck, BarChart3, Umbrella } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { reportsApi } from "../../api/reports";
import type { ColumnMeta, FilterMeta, FilterSpec, RunResult } from "../../api/reports";
import { ResultTable } from "./ResultTable";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

export const MODULES: { value: string; label: string; icon: LucideIcon; desc: string }[] = [
  { value: "ATTENDANCE", label: "Attendance", icon: Clock, desc: "Daily records, punches, hours" },
  { value: "EMPLOYEE", label: "Employees", icon: Users, desc: "People and employment data" },
  { value: "LEAVE", label: "Leave", icon: Umbrella, desc: "Leave requests and their status" },
  { value: "ONBOARDING", label: "Onboarding", icon: ClipboardCheck, desc: "Cases and task progress" },
  { value: "HEADCOUNT", label: "Headcount", icon: BarChart3, desc: "Workforce size and movement" },
];

const OP_LABEL: Record<string, string> = {
  eq: "is", ne: "is not", gt: "after / above", gte: "on or after", lt: "before / below", lte: "on or before",
  in: "is any of", contains: "contains", between: "between",
};

export function FilterRow({ filter, meta, onChange, onRemove }: {
  filter: FilterSpec;
  meta: FilterMeta[];
  onChange: (f: FilterSpec) => void;
  onRemove: () => void;
}) {
  const fieldMeta = meta.find((m) => m.field === filter.field);
  return (
    <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
      <select className="input sm:w-44" value={filter.field} onChange={(e) => onChange({ field: e.target.value, op: meta.find((m) => m.field === e.target.value)?.ops[0] ?? "eq", value: "" })} aria-label="Field">
        <option value="">Choose field…</option>
        {meta.map((m) => <option key={m.field} value={m.field}>{m.label}</option>)}
      </select>
      <select className="input sm:w-36" value={filter.op} onChange={(e) => onChange({ ...filter, op: e.target.value, value: "" })} aria-label="Operator">
        {(fieldMeta?.ops ?? ["eq"]).map((op) => <option key={op} value={op}>{OP_LABEL[op] ?? op}</option>)}
      </select>
      {fieldMeta?.type === "date" && filter.op === "between" ? (
        <div className="flex flex-1 gap-2">
          {[0, 1].map((index) => <input key={index} className="input min-w-0" type="date"
            aria-label={index === 0 ? "Start date" : "End date"}
            value={Array.isArray(filter.value) ? String(filter.value[index] ?? "") : ""}
            onChange={(e) => {
              const values = Array.isArray(filter.value) ? [...filter.value] : ["", ""];
              values[index] = e.target.value;
              onChange({ ...filter, value: values });
            }} />)}
        </div>
      ) : fieldMeta?.type === "enum" && fieldMeta.options ? (
        <select className="input flex-1" value={String(filter.value ?? "")} onChange={(e) => onChange({ ...filter, value: e.target.value })} aria-label="Value">
          <option value="">Choose value…</option>
          {fieldMeta.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input
          className="input flex-1"
          type={fieldMeta?.type === "date" ? "date" : fieldMeta?.type === "number" ? "number" : "text"}
          placeholder="Value"
          value={String(filter.value ?? "")}
          onChange={(e) => onChange({ ...filter, value: e.target.value })}
          aria-label="Value"
        />
      )}
      <button onClick={onRemove} className="btn-icon shrink-0 hover:text-danger" aria-label="Remove filter"><Trash2 size={14} /></button>
    </div>
  );
}

function Step({ n, title, children, aside }: { n: number; title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-line px-5 py-5 last:border-0 md:grid-cols-[200px_1fr]">
      <div className="flex items-start gap-3">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-fg-muted">{n}</span>
        <div>
          <p className="text-[13px] font-semibold text-fg">{title}</p>
          {aside && <div className="mt-0.5 text-xs text-fg-subtle">{aside}</div>}
        </div>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export function ReportBuilder({ onSave }: { onSave?: () => void }) {
  const toast = useToast();
  const [module, setModule] = useState("ATTENDANCE");
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<{ module: string; cols: Set<string> } | null>(null);
  const [filters, setFilters] = useState<FilterSpec[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);

  const { data: meta, isPending: isLoading, isError } = useQuery({
    queryKey: ["report-meta", module],
    queryFn: () => reportsApi.meta(module),
  });

  const selectedCols = picked?.module === module
    ? picked.cols
    : new Set((meta?.columns ?? []).filter((c) => c.default).map((c) => c.field));
  const toggleCol = (field: string) => {
    const s = new Set(selectedCols);
    if (s.has(field)) s.delete(field); else s.add(field);
    setPicked({ module, cols: s });
  };

  const changeModule = (m: string) => {
    setModule(m);
    setResult(null);
    setFilters([]);
  };

  const runMutation = useMutation({
    mutationFn: async () => {
      const cols = (meta?.columns ?? [])
        .filter((c) => selectedCols.has(c.field))
        .map((c) => ({ field: c.field, label: c.label, visible: true }));
      const saved = await reportsApi.create({
        name: name.trim() || `Custom ${module.toLowerCase()} report`,
        description: "",
        module,
        columns: cols,
        filters: filters.filter((f) => f.field),
        owner_type: "HR",
      });
      return reportsApi.run(saved.id);
    },
    onSuccess: (data) => {
      setResult(data);
      toast.success("Report saved and run", `${data.total_rows} rows`);
      onSave?.();
    },
    onError: (e) => toast.error("Couldn’t run report", errorMessage(e)),
  });

  return (
    <div className="space-y-6">
      <div className="card">
        <Step n={1} title="Data source" aside="What are you reporting on?">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {MODULES.map((m) => {
              const active = module === m.value;
              return (
                <button
                  key={m.value}
                  disabled={runMutation.isPending}
                  onClick={() => changeModule(m.value)}
                  aria-pressed={active}
                  className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${
                    active ? "border-brand-500/50 bg-brand-500/[0.06] ring-1 ring-brand-500/30" : "border-line hover:border-line-strong hover:bg-muted/50"
                  }`}
                >
                  <m.icon size={16} className={`mt-0.5 shrink-0 ${active ? "text-accent" : "text-fg-subtle"}`} />
                  <span>
                    <span className="block text-[13px] font-medium text-fg">{m.label}</span>
                    <span className="block text-xs text-fg-subtle">{m.desc}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </Step>

        <Step n={2} title="Columns" aside={meta ? `${selectedCols.size} of ${meta.columns.length} selected` : undefined}>
          {isLoading ? (
            <div className="flex flex-wrap gap-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-8 w-24 rounded-full" />)}</div>
          ) : isError ? (
            <p className="text-[13px] text-danger">Couldn’t load columns — is the API running?</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {meta?.columns.map((col: ColumnMeta) => {
                const checked = selectedCols.has(col.field);
                return (
                  <label
                    key={col.field}
                    className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                      checked ? "border-brand-500/40 bg-brand-500/10 text-accent" : "border-line text-fg-muted hover:border-line-strong"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggleCol(col.field)}
                    />
                    {checked && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                    {col.label}
                  </label>
                );
              })}
            </div>
          )}
        </Step>

        <Step n={3} title="Filters" aside="Optional">
          <div className="space-y-2">
            {filters.map((f, i) => (
              <FilterRow
                key={i}
                filter={f}
                meta={meta?.filters ?? []}
                onChange={(updated) => setFilters((fs) => fs.map((x, j) => (j === i ? updated : x)))}
                onRemove={() => setFilters((fs) => fs.filter((_, j) => j !== i))}
              />
            ))}
            <button onClick={() => setFilters((fs) => [...fs, { field: "", op: "eq", value: "" }])} className="btn-ghost btn-sm -ml-2.5" disabled={!meta?.filters.length}>
              <Plus size={13} /> Add filter
            </button>
          </div>
        </Step>

        <Step n={4} title="Save & run">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              className="input sm:max-w-sm"
              placeholder={`Custom ${module.toLowerCase()} report`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-label="Report name"
            />
            <button onClick={() => runMutation.mutate()} disabled={runMutation.isPending || isLoading || isError || selectedCols.size === 0} className="btn-primary">
              <Play size={14} /> {runMutation.isPending ? "Running…" : "Save & run"}
            </button>
          </div>
        </Step>
      </div>

      {result && <ResultTable result={result} />}
    </div>
  );
}
