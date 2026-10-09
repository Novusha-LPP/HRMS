import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Pencil, Plus } from "lucide-react";
import { payrollApi } from "../../api/payroll";
import type { ComponentKind, PayComponent } from "../../api/payroll";
import { Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const KIND_LABEL: Record<ComponentKind, string> = {
  EARNING: "Earning",
  DEDUCTION: "Deduction",
  EMPLOYER_CONTRIBUTION: "Employer contribution",
  REIMBURSEMENT: "Reimbursement",
  INFO: "Information only",
};

const KIND_TONE: Record<ComponentKind, string> = {
  EARNING: "badge-success",
  DEDUCTION: "badge-danger",
  EMPLOYER_CONTRIBUTION: "badge-info",
  REIMBURSEMENT: "badge-plum",
  INFO: "badge-neutral",
};

function Flag({ on, label }: { on: boolean; label: string }) {
  return on ? <span className="badge badge-neutral">{label}</span> : null;
}

/** Everything that can appear on a payslip, and how each behaves. */
export function ComponentsTab({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const components = useQuery({ queryKey: ["payroll", "components"], queryFn: () => payrollApi.components() });
  const [editing, setEditing] = useState<PayComponent | "new" | null>(null);

  const standard = useMutation({
    mutationFn: () => payrollApi.createStandardComponents(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["payroll"] }); toast.success("Standard components added"); },
    onError: (e) => toast.error("Couldn’t add the standard components", errorMessage(e)),
  });

  if (components.isError) return <Notice title="Couldn’t load pay components">The payroll API isn’t responding.</Notice>;
  if (components.isPending) return <Skeleton className="h-64 rounded-xl" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-fg-muted">
          The lines a payslip can show. PF and ESIC are calculated by law from the components marked as part of PF or ESIC wages.
        </p>
        {canWrite && (
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={() => standard.mutate()} disabled={standard.isPending}>Add standard components</button>
            <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} /> New component</button>
          </div>
        )}
      </div>

      {!components.data.length ? (
        <div className="card">
          <EmptyState icon={Layers} title="No pay components yet"
            description="Start with the standard set (Basic, HRA, Special allowance, PF and ESIC) and add your own allowances and deductions."
            action={canWrite ? <button className="btn-primary" onClick={() => standard.mutate()} disabled={standard.isPending}>Add standard components</button> : undefined} />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Component</th><th>Kind</th><th className="hidden md:table-cell">Counts towards</th><th className="hidden sm:table-cell">Status</th><th className="w-px" /></tr>
              </thead>
              <tbody>
                {components.data.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <p className="font-medium text-fg">{c.name}</p>
                      <p className="font-mono text-[11px] text-fg-subtle">{c.code}{c.statutory_code ? ` · by law (${c.statutory_code.replace("_", " ").toLowerCase()})` : ""}</p>
                    </td>
                    <td><span className={`badge ${KIND_TONE[c.kind]}`}>{KIND_LABEL[c.kind]}</span></td>
                    <td className="hidden md:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {c.kind === "EARNING" ? (
                          <>
                            <Flag on={c.in_pf_wages} label="PF wages" />
                            <Flag on={c.in_esic_wages} label="ESIC wages" />
                            <Flag on={c.taxable} label="Taxable" />
                            <Flag on={c.prorate} label="Prorated" />
                          </>
                        ) : <span className="text-fg-subtle">—</span>}
                      </div>
                    </td>
                    <td className="hidden sm:table-cell">{c.status === "ACTIVE" ? <span className="badge badge-success">Active</span> : <span className="badge badge-neutral">Inactive</span>}</td>
                    <td className="text-right">
                      {canWrite && <button className="btn-ghost btn-sm" onClick={() => setEditing(c)}><Pencil size={13} /> Edit</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ComponentEditor key={editing === "new" ? "new" : editing?.id ?? "none"} component={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function ComponentEditor({ component, onClose }: { component: PayComponent | "new" | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const existing = component && component !== "new" ? component : null;
  const [code, setCode] = useState(existing?.code ?? "");
  const [name, setName] = useState(existing?.name ?? "");
  const [kind, setKind] = useState<ComponentKind>(existing?.kind ?? "EARNING");
  const [taxable, setTaxable] = useState(existing?.taxable ?? true);
  const [inPf, setInPf] = useState(existing?.in_pf_wages ?? false);
  const [inEsic, setInEsic] = useState(existing?.in_esic_wages ?? true);
  const [prorate, setProrate] = useState(existing?.prorate ?? true);
  const [order, setOrder] = useState(String(existing?.payslip_order ?? 50));
  const [active, setActive] = useState(existing ? existing.status === "ACTIVE" : true);
  const [tried, setTried] = useState(false);
  const statutory = !!existing?.statutory_code;

  const problems: string[] = [];
  if (!existing && !/^[A-Za-z0-9_-]{1,30}$/.test(code.trim())) problems.push("The code is letters, digits, - and _ only (up to 30).");
  if (!name.trim()) problems.push("Give the component a name.");
  if (!/^\d{1,5}$/.test(order.trim())) problems.push("Payslip order is a whole number.");

  const save = useMutation({
    mutationFn: () => {
      const flags = { taxable, in_pf_wages: inPf, in_esic_wages: inEsic, prorate, payslip_order: Number(order) };
      return existing
        ? payrollApi.updateComponent(existing.id, { name: name.trim(), ...flags, status: active ? "ACTIVE" : "INACTIVE" })
        : payrollApi.createComponent({ code: code.trim(), name: name.trim(), kind, statutory_code: null, ...flags });
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["payroll"] });
      toast.success(existing ? "Component saved" : "Component created", c.name);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t save the component", errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };
  const earning = kind === "EARNING";

  return (
    <Sheet open={component !== null} onClose={onClose} title={existing ? `Edit ${existing.name}` : "New pay component"}
      description={existing ? "Changes apply to breakups worked out from now on. The code and kind can't change." : "An allowance, deduction, reimbursement or employer cost that can appear on a payslip."}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="component-form" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save component"}</button>
      </>}>
      <form id="component-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
          <div>
            <label className="label" htmlFor="pc-code">Code</label>
            <input id="pc-code" className="input font-mono uppercase" value={code} disabled={!!existing} placeholder="CONV" onChange={(e) => setCode(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="pc-name">Name</label>
            <input id="pc-name" className="input" value={name} placeholder="e.g. Conveyance allowance" onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="pc-kind">Kind</label>
            <select id="pc-kind" className="input" value={kind} disabled={!!existing} onChange={(e) => setKind(e.target.value as ComponentKind)}>
              {Object.entries(KIND_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="pc-order">Payslip order</label>
            <input id="pc-order" className="input" inputMode="numeric" value={order} onChange={(e) => setOrder(e.target.value)} />
          </div>
        </div>
        {statutory && <Notice tone="info" title="Calculated by law">PF and ESIC amounts come from the statutory values, not from the structure.</Notice>}
        {earning && !statutory && (
          <fieldset className="space-y-2">
            <legend className="label">This earning…</legend>
            {([
              { on: inPf, set: setInPf, label: "counts towards PF wages", hint: "Usually only Basic (and DA)." },
              { on: inEsic, set: setInEsic, label: "counts towards ESIC wages", hint: "Most earnings do; reimbursements and annual bonus don't." },
              { on: taxable, set: setTaxable, label: "is taxable" },
              { on: prorate, set: setProrate, label: "is reduced for unpaid days", hint: "Turn off for fixed monthly amounts." },
            ] as { on: boolean; set: (v: boolean) => void; label: string; hint?: string }[]).map((f) => (
              <label key={f.label} className="flex items-start gap-2 text-sm text-fg">
                <input type="checkbox" className="checkbox mt-0.5" checked={f.on} onChange={(e) => f.set(e.target.checked)} />
                <span>{f.label}{f.hint && <span className="block text-xs text-fg-subtle">{f.hint}</span>}</span>
              </label>
            ))}
          </fieldset>
        )}
        {existing && (
          <label className="flex items-center gap-2 text-sm text-fg">
            <input type="checkbox" className="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active <span className="text-xs text-fg-subtle">(inactive components can't be added to structures)</span>
          </label>
        )}
        {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      </form>
    </Sheet>
  );
}
