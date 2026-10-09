import { useState } from "react";
import type { FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Pencil, Plus, Table2, Trash2, X } from "lucide-react";
import { payrollApi } from "../../api/payroll";
import type { CalcType, PayComponent, SalaryStructure, StructureLine, StructureLineInput } from "../../api/payroll";
import { useAuth } from "../../context/AuthContext";
import { parseAmount, inr, useDebounced } from "../../lib/money";
import { ConfirmDialog, Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { BreakupTable } from "./BreakupTable";

const CALC_LABEL: Record<CalcType, string> = {
  FIXED: "Fixed amount",
  PERCENT: "Percentage",
  BALANCE: "Balance of CTC",
  STATUTORY: "By law",
};

function describeLine(l: StructureLine, all: StructureLine[]) {
  switch (l.calc_type) {
    case "FIXED": return `${inr(l.amount)} a month`;
    case "PERCENT": {
      const base = l.base === "CTC" ? "CTC" : all.find((x) => x.component_id === l.base_component_id)?.component_name ?? "a component";
      return `${+Number(l.percent)}% of ${base}`;
    }
    case "BALANCE": return "whatever is left of the CTC";
    default: return "calculated by law";
  }
}

/** How a CTC is split into components. Editing saves a new version; assigned salaries keep theirs. */
export function StructuresTab({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const structures = useQuery({ queryKey: ["payroll", "structures"], queryFn: () => payrollApi.structures() });
  const [editing, setEditing] = useState<SalaryStructure | "new" | null>(null);
  const [retiring, setRetiring] = useState<SalaryStructure | null>(null);
  const companyName = (id: string | null) => (id ? user?.legalEntities.find((le) => le.id === id)?.name ?? "One company" : "All companies");

  const standard = useMutation({
    mutationFn: () => payrollApi.createStandardStructure(),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["payroll"] }); toast.success("Standard structure added", s.name); },
    onError: (e) => toast.error("Couldn’t add the standard structure", errorMessage(e)),
  });
  const retire = useMutation({
    mutationFn: (s: SalaryStructure) => payrollApi.deactivateStructure(s.id),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["payroll"] }); toast.success("Structure retired", s.name); setRetiring(null); },
    onError: (e) => toast.error("Couldn’t retire the structure", errorMessage(e)),
  });

  if (structures.isError) return <Notice title="Couldn’t load salary structures">The payroll API isn’t responding.</Notice>;
  if (structures.isPending) return <Skeleton className="h-64 rounded-xl" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-fg-muted">
          How a CTC is split into components. Editing a structure saves a new version; salaries already given keep their version until they are revised.
        </p>
        {canWrite && (
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={() => standard.mutate()} disabled={standard.isPending}>Add standard structure</button>
            <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} /> New structure</button>
          </div>
        )}
      </div>

      {!structures.data.length ? (
        <div className="card">
          <EmptyState icon={Table2} title="No salary structures yet"
            description="Start with the standard structure (Basic 50% of CTC, HRA 40% of Basic, Special allowance as the balance, PF and ESIC) and adjust it."
            action={canWrite ? <button className="btn-primary" onClick={() => standard.mutate()} disabled={standard.isPending}>Use the standard structure</button> : undefined} />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {structures.data.map((s) => (
            <div key={s.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-semibold text-fg">{s.name}</p>
                  <p className="mt-0.5 text-xs text-fg-subtle">{companyName(s.legal_entity_id)} · {s.employees} on this version</p>
                </div>
              </div>
              {s.description && <p className="mt-2 text-xs text-fg-muted">{s.description}</p>}
              <ol className="mt-3 space-y-1 text-[13px]">
                {s.lines.map((l) => (
                  <li key={l.id} className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-fg">{l.component_name}</span>
                    <span className="shrink-0 text-xs text-fg-subtle">{describeLine(l, s.lines)}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                <button className="btn-secondary btn-sm" onClick={() => setEditing(s)}>
                  {canWrite ? <><Pencil size={13} /> Edit</> : <><Table2 size={13} /> Try a CTC</>}
                </button>
                {canWrite && <button className="btn-ghost btn-sm hover:text-danger" onClick={() => setRetiring(s)}><Trash2 size={13} /> Retire</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      <StructureEditor key={editing === "new" ? "new" : editing?.id ?? "none"} structure={editing} readOnly={!canWrite} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={retiring !== null}
        onClose={() => setRetiring(null)}
        onConfirm={() => retiring && retire.mutate(retiring)}
        loading={retire.isPending}
        title={retiring ? `Retire “${retiring.name}”?` : "Retire structure?"}
        description={retiring?.employees
          ? `It can't be chosen for new salaries. The ${retiring.employees} people on it keep it until their salary is revised.`
          : "It can't be chosen for new salaries."}
        confirmLabel="Retire"
      />
    </div>
  );
}

type Draft = {
  key: number;
  component_id: string;
  calc_type: CalcType;
  amount: string;
  percent: string;
  base: "CTC" | "COMPONENT";
  base_component_id: string;
};

let nextKey = 1;

function toDraft(l: StructureLine): Draft {
  return {
    key: nextKey++, component_id: l.component_id, calc_type: l.calc_type,
    amount: l.amount ? String(+Number(l.amount)) : "", percent: l.percent ? String(+Number(l.percent)) : "",
    base: l.base === "COMPONENT" ? "COMPONENT" : "CTC", base_component_id: l.base_component_id ?? "",
  };
}

function toInput(d: Draft): StructureLineInput {
  return {
    component_id: d.component_id,
    calc_type: d.calc_type,
    amount: d.calc_type === "FIXED" ? parseAmount(d.amount) : null,
    percent: d.calc_type === "PERCENT" && /^\d+(\.\d{1,4})?$/.test(d.percent.trim()) ? d.percent.trim() : null,
    base: d.calc_type === "PERCENT" ? d.base : null,
    base_component_id: d.calc_type === "PERCENT" && d.base === "COMPONENT" ? d.base_component_id || null : null,
  };
}

function StructureEditor({ structure, readOnly, onClose }: { structure: SalaryStructure | "new" | null; readOnly: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const existing = structure && structure !== "new" ? structure : null;
  const components = useQuery({ queryKey: ["payroll", "components"], queryFn: () => payrollApi.components(), enabled: structure !== null });
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [company, setCompany] = useState(existing?.legal_entity_id ?? "");
  const [lines, setLines] = useState<Draft[]>(() => existing?.lines.map(toDraft) ?? []);
  const [ctc, setCtc] = useState("600000");
  const [tried, setTried] = useState(false);

  const byId = new Map<string, PayComponent>((components.data ?? []).map((c) => [c.id, c]));
  const unused = (components.data ?? []).filter((c) => c.status === "ACTIVE" && !lines.some((l) => l.component_id === c.id));
  const update = (key: number, patch: Partial<Draft>) => setLines((list) => list.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const move = (index: number, by: -1 | 1) => setLines((list) => {
    const next = [...list];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row);
    return next;
  });
  const add = (id: string) => {
    const c = byId.get(id);
    if (!c) return;
    const calc: CalcType = c.statutory_code ? "STATUTORY" : "FIXED";
    setLines((list) => [...list, { key: nextKey++, component_id: id, calc_type: calc, amount: "", percent: "", base: "CTC", base_component_id: "" }]);
  };

  const problems: string[] = [];
  if (!name.trim()) problems.push("Give the structure a name.");
  if (!lines.length) problems.push("Add the components.");
  if (lines.filter((l) => l.calc_type === "BALANCE").length !== 1) problems.push("Exactly one earning must take the balance of the CTC (usually Special allowance).");
  lines.forEach((l, i) => {
    const c = byId.get(l.component_id);
    const label = c?.name ?? `Line ${i + 1}`;
    if (l.calc_type === "FIXED" && !parseAmount(l.amount)) problems.push(`${label}: enter the monthly amount.`);
    if (l.calc_type === "PERCENT") {
      if (!/^\d+(\.\d{1,4})?$/.test(l.percent.trim()) || Number(l.percent) > 100) problems.push(`${label}: enter a percentage up to 100.`);
      if (l.base === "COMPONENT" && !lines.slice(0, i).some((x) => x.component_id === l.base_component_id && ["FIXED", "PERCENT"].includes(x.calc_type)))
        problems.push(`${label}: a percentage can only be of a fixed or percentage component listed above it.`);
    }
    if (l.calc_type === "BALANCE" && c && c.kind !== "EARNING") problems.push(`${label}: only an earning can take the balance.`);
  });

  const inputs = lines.map(toInput);
  const ctcValue = parseAmount(ctc);
  const previewable = !!ctcValue && lines.length > 0 && problems.every((p) => p.startsWith("Give the structure"));
  const previewKey = useDebounced(JSON.stringify([ctcValue, inputs]), 300);
  const preview = useQuery({
    queryKey: ["payroll", "preview", previewKey],
    queryFn: () => {
      const [annual, body] = JSON.parse(previewKey) as [string, StructureLineInput[]];
      return payrollApi.preview({ annual_ctc: annual, lines: body });
    },
    enabled: structure !== null && previewable && previewKey === JSON.stringify([ctcValue, inputs]),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), description: description.trim() || null, legal_entity_id: company || null, lines: inputs };
      return existing ? payrollApi.replaceStructure(existing.id, body) : payrollApi.createStructure(body);
    },
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["payroll"] });
      toast.success(existing ? "New version saved" : "Structure created", s.name);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t save the structure", errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };

  const earlier = (index: number) => lines.slice(0, index).filter((x) => ["FIXED", "PERCENT"].includes(x.calc_type));

  return (
    <Sheet
      open={structure !== null}
      onClose={onClose}
      title={readOnly ? existing?.name ?? "" : existing ? `Edit “${existing.name}”` : "New salary structure"}
      description={readOnly ? "Try any CTC to see how this structure splits it." : existing ? "Saving creates a new version. People already on this structure keep their breakup until their salary is revised." : "Add components in the order they're worked out. A percentage can be of the CTC or of a component above it."}
      className="max-w-5xl"
      footer={readOnly ? <button className="btn-secondary" onClick={onClose}>Close</button> : <>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="structure-form" disabled={save.isPending}>{save.isPending ? "Saving…" : existing ? "Save new version" : "Create structure"}</button>
      </>}
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
        <form id="structure-form" onSubmit={submit} className="min-w-0 space-y-4">
          <fieldset disabled={readOnly} className="min-w-0 space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="ss-name">Name</label>
                <input id="ss-name" className="input" placeholder="e.g. Staff, Workers" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="ss-company">Company</label>
                <select id="ss-company" className="input" value={company} onChange={(e) => setCompany(e.target.value)}>
                  <option value="">All companies</option>
                  {user?.legalEntities.map((le) => <option key={le.id} value={le.id}>{le.name}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="label" htmlFor="ss-desc">Description <span className="font-normal text-fg-subtle">(optional)</span></label>
              <input id="ss-desc" className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>

            <div>
              <p className="eyebrow mb-2">Components</p>
              {components.isPending ? <Skeleton className="h-32 rounded-xl" /> : (
                <ol className="space-y-2">
                  {lines.map((l, index) => {
                    const c = byId.get(l.component_id);
                    const statutory = !!c?.statutory_code;
                    return (
                      <li key={l.key} className="rounded-xl border border-line p-3">
                        <div className="flex items-start gap-2">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-fg">{c?.name ?? "Unknown component"} <span className="font-mono text-[11px] font-normal text-fg-subtle">{c?.code}</span></p>
                            {statutory ? (
                              <p className="mt-1 text-xs text-fg-subtle">Calculated by law from PF / ESIC wages and the statutory values.</p>
                            ) : (
                              <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-2">
                                <label className="block">
                                  <span className="mb-1 block text-[11px] text-fg-subtle">How</span>
                                  <select className="input w-40" value={l.calc_type} onChange={(e) => update(l.key, { calc_type: e.target.value as CalcType })}>
                                    {(["FIXED", "PERCENT", ...(c?.kind === "EARNING" ? ["BALANCE"] : [])] as CalcType[]).map((v) => <option key={v} value={v}>{CALC_LABEL[v]}</option>)}
                                  </select>
                                </label>
                                {l.calc_type === "FIXED" && (
                                  <label className="block">
                                    <span className="mb-1 block text-[11px] text-fg-subtle">₹ a month</span>
                                    <input className="input w-32" inputMode="decimal" value={l.amount} onChange={(e) => update(l.key, { amount: e.target.value })} />
                                  </label>
                                )}
                                {l.calc_type === "PERCENT" && (
                                  <>
                                    <label className="block">
                                      <span className="mb-1 block text-[11px] text-fg-subtle">%</span>
                                      <input className="input w-20" inputMode="decimal" value={l.percent} onChange={(e) => update(l.key, { percent: e.target.value })} />
                                    </label>
                                    <label className="block">
                                      <span className="mb-1 block text-[11px] text-fg-subtle">of</span>
                                      <select className="input w-44"
                                        value={l.base === "CTC" ? "CTC" : l.base_component_id}
                                        onChange={(e) => update(l.key, e.target.value === "CTC" ? { base: "CTC", base_component_id: "" } : { base: "COMPONENT", base_component_id: e.target.value })}>
                                        <option value="CTC">CTC</option>
                                        {earlier(index).map((x) => <option key={x.key} value={x.component_id}>{byId.get(x.component_id)?.name}</option>)}
                                        {l.base === "COMPONENT" && !earlier(index).some((x) => x.component_id === l.base_component_id) && <option value={l.base_component_id}>(choose)</option>}
                                      </select>
                                    </label>
                                  </>
                                )}
                                {l.calc_type === "BALANCE" && <p className="pb-2.5 text-xs text-fg-subtle">Takes whatever is left so the total equals the CTC.</p>}
                              </div>
                            )}
                          </div>
                          {!readOnly && (
                            <div className="flex shrink-0 gap-1">
                              <button type="button" className="btn-icon" aria-label={`Move ${c?.name} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={13} /></button>
                              <button type="button" className="btn-icon" aria-label={`Move ${c?.name} down`} disabled={index === lines.length - 1} onClick={() => move(index, 1)}><ArrowDown size={13} /></button>
                              <button type="button" className="btn-icon hover:text-danger" aria-label={`Remove ${c?.name}`} onClick={() => setLines((list) => list.filter((x) => x.key !== l.key))}><X size={13} /></button>
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
              {!readOnly && unused.length > 0 && (
                <select className="input mt-2 w-64" value="" aria-label="Add a component" onChange={(e) => add(e.target.value)}>
                  <option value="">+ Add a component…</option>
                  {unused.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
                </select>
              )}
            </div>
          </fieldset>
          {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        </form>

        <aside className="min-w-0 space-y-3 lg:sticky lg:top-0 lg:self-start">
          <div>
            <label className="label" htmlFor="ss-ctc">Try an annual CTC</label>
            <input id="ss-ctc" className="input" inputMode="decimal" value={ctc} onChange={(e) => setCtc(e.target.value)} />
            {ctcValue && <p className="mt-1 text-xs text-fg-subtle">{inr(ctcValue)} a year · {inr(Number(ctcValue) / 12, true)} a month</p>}
          </div>
          {!previewable ? (
            <p className="rounded-xl border border-dashed border-line p-4 text-xs text-fg-subtle">
              {ctcValue ? "The breakup appears once every component is filled in and one takes the balance." : "Enter a CTC to see the breakup."}
            </p>
          ) : preview.isError ? (
            <Notice title="This CTC doesn't work with the structure">{errorMessage(preview.error)}</Notice>
          ) : preview.data ? (
            <div className={preview.isFetching ? "opacity-60 transition-opacity" : "transition-opacity"}><BreakupTable breakup={preview.data} compact /></div>
          ) : <Skeleton className="h-64 rounded-xl" />}
        </aside>
      </div>
    </Sheet>
  );
}

