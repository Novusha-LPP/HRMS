import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, LayoutTemplate, Plus, RotateCcw, X } from "lucide-react";
import { payslipTemplatesApi } from "../../api/payroll";
import type { PayslipLayout, PayslipTemplate, PayslipTemplateInput, PayslipTemplateOverview } from "../../api/payroll";
import { brandingApi } from "../../api/branding";
import { Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const LAYOUTS: { value: PayslipLayout; title: string; text: string }[] = [
  { value: "MODERN", title: "Modern", text: "Brand colour header, earnings and deductions side by side, net pay highlighted." },
  { value: "CLASSIC", title: "Classic", text: "Bordered tables in black and grey: what accounts teams, auditors and banks expect." },
  { value: "COMPACT", title: "Compact", text: "Half an A4 page with the essentials, for printing two to a sheet." },
];

const BLOCKS: { key: keyof Pick<PayslipTemplateInput, "show_attendance" | "show_leave_balances" | "show_employer_contributions" | "show_ytd" | "hide_zero_lines">; label: string; hint: string }[] = [
  { key: "show_attendance", label: "Attendance summary", hint: "Days in month, weekly offs, holidays, leave, loss of pay, overtime." },
  { key: "show_leave_balances", label: "Leave balances", hint: "Opening, availed and closing for each leave type." },
  { key: "show_employer_contributions", label: "Employer contributions", hint: "PF employer share and gratuity, marked as not part of net pay." },
  { key: "show_ytd", label: "Year-to-date column", hint: "Totals since the start of the financial year." },
  { key: "hide_zero_lines", label: "Hide lines that are zero", hint: "For example ESIC for someone above the wage ceiling." },
];

/** The month the sample payslip is for (last month), as the preview prints it. */
const LAST_MONTH = (() => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return d.toLocaleString("en-GB", { month: "long", year: "numeric" });
})();

function inputOf(t: PayslipTemplate): PayslipTemplateInput {
  const { layout, title, employee_fields, show_attendance, show_leave_balances, show_employer_contributions, show_ytd, hide_zero_lines, signature_mode, signatory_id, note_text } = t;
  return { layout, title, employee_fields, show_attendance, show_leave_balances, show_employer_contributions, show_ytd, hide_zero_lines, signature_mode, signatory_id, note_text };
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => { const t = setTimeout(() => setDebounced(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return debounced;
}

/**
 * The payslip layout for the group or one company, with a live SAMPLE preview. Used in
 * Organization → Branding (HR, Admin) and Payroll → Payslip (the payroll administrator).
 */
export function PayslipTemplateEditor({ canEditGroup, canEdit }: { canEditGroup: boolean; canEdit: boolean }) {
  const overview = useQuery({ queryKey: ["payslip-templates"], queryFn: () => payslipTemplatesApi.overview() });
  const [scope, setScope] = useState("");  // "" = group default, else a company id

  if (overview.isError) return <Notice title="Couldn’t load the payslip layout">{errorMessage(overview.error)}</Notice>;
  if (overview.isPending) return <Skeleton className="h-96 rounded-xl" />;

  const company = overview.data.companies.find((c) => c.legal_entity_id === scope);
  const saved = scope ? company?.template ?? null : overview.data.group;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-fg-muted" htmlFor="payslip-scope">Layout for</label>
        <select id="payslip-scope" className="input w-full sm:w-auto sm:min-w-[240px]" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">Group default (every company)</option>
          {overview.data.companies.map((c) => (
            <option key={c.legal_entity_id} value={c.legal_entity_id}>{c.name} · {c.template ? "own layout" : "uses group"}</option>
          ))}
        </select>
      </div>
      <TemplateForm
        key={`${scope}:${saved?.id ?? "none"}:${saved?.version ?? ""}`}
        overview={overview.data}
        companyId={scope || null}
        companyName={company?.name}
        saved={saved}
        canEdit={scope ? canEdit : canEditGroup}
      />
    </div>
  );
}

function TemplateForm({ overview, companyId, companyName, saved, canEdit }: {
  overview: PayslipTemplateOverview; companyId: string | null; companyName?: string; saved: PayslipTemplate | null; canEdit: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const inheriting = companyId !== null && saved === null;
  const start = inputOf(saved ?? overview.group);
  const [form, setForm] = useState<PayslipTemplateInput>(start);
  const [customizing, setCustomizing] = useState(false);
  const editable = canEdit && (!inheriting || customizing);
  const dirty = JSON.stringify(form) !== JSON.stringify(start) || (inheriting && customizing);
  const set = <K extends keyof PayslipTemplateInput>(key: K, value: PayslipTemplateInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  const signatories = useQuery({ queryKey: ["branding", "signatories"], queryFn: () => brandingApi.signatories(), enabled: canEdit });
  const eligible = (signatories.data ?? []).filter((s) => s.legal_entity_id === null || s.legal_entity_id === companyId);

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, version: saved?.version ?? undefined };
      return companyId ? payslipTemplatesApi.saveCompany(companyId, body) : payslipTemplatesApi.saveGroup(body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["payslip-templates"] }); toast.success("Payslip layout saved", companyName ?? "Group default"); },
    onError: (e) => toast.error("Couldn’t save the payslip layout", errorMessage(e)),
  });
  const reset = useMutation({
    mutationFn: () => payslipTemplatesApi.resetCompany(companyId!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["payslip-templates"] }); toast.success("Uses the group’s layout again", companyName); },
    onError: (e) => toast.error("Couldn’t reset the layout", errorMessage(e)),
  });

  const labels = new Map(overview.fields.map((f) => [f.key, f.label]));
  const unused = overview.fields.filter((f) => !form.employee_fields.includes(f.key));
  const move = (index: number, by: number) => setForm((f) => {
    const fields = [...f.employee_fields];
    const [item] = fields.splice(index, 1);
    fields.splice(index + by, 0, item);
    return { ...f, employee_fields: fields };
  });
  const signatoryMissing = form.signature_mode === "SIGNATORY" && !form.signatory_id;

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="min-w-0 space-y-5">
        {inheriting && (
          <Notice tone="info" title={`${companyName} uses the group’s layout`}
            action={canEdit && !customizing ? <button className="btn-secondary btn-sm" onClick={() => setCustomizing(true)}>Customize for this company</button> : undefined}>
            {customizing ? "Change what differs and save: from then on this company keeps its own layout." : "Changes to the group’s layout apply here too."}
          </Notice>
        )}
        {!canEdit && <p className="text-sm text-fg-muted">You can see this layout; only a group-level administrator can change it.</p>}

        <fieldset disabled={!editable} className="space-y-5 disabled:opacity-90">
          <div>
            <p className="label">Layout</p>
            <div className="grid gap-2 sm:grid-cols-3">
              {LAYOUTS.map((l) => (
                <button key={l.value} type="button" onClick={() => set("layout", l.value)} aria-pressed={form.layout === l.value}
                  className={`rounded-lg border p-3 text-left transition ${form.layout === l.value ? "border-accent bg-brand-500/5 ring-1 ring-accent" : "border-line hover:border-zinc-400"}`}>
                  <LayoutThumb layout={l.value} />
                  <p className="mt-2 text-sm font-semibold text-fg">{l.title}</p>
                  <p className="text-xs text-fg-subtle">{l.text}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="ps-title">Title</label>
              <input id="ps-title" className="input" maxLength={60} value={form.title} onChange={(e) => set("title", e.target.value)} />
              <p className="mt-1 text-xs text-fg-subtle">Printed as “{form.title || "Payslip"} for {LAST_MONTH}”.</p>
            </div>
          </div>

          <div>
            <p className="label">Employee details, in order</p>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {form.employee_fields.map((key, i) => (
                <li key={key} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                  <span className="flex-1 text-fg">{labels.get(key) ?? key}</span>
                  <button type="button" className="btn-icon" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${labels.get(key)} up`}><ArrowUp size={13} /></button>
                  <button type="button" className="btn-icon" onClick={() => move(i, 1)} disabled={i === form.employee_fields.length - 1} aria-label={`Move ${labels.get(key)} down`}><ArrowDown size={13} /></button>
                  <button type="button" className="btn-icon" onClick={() => set("employee_fields", form.employee_fields.filter((k) => k !== key))} aria-label={`Remove ${labels.get(key)}`}><X size={13} /></button>
                </li>
              ))}
              {!form.employee_fields.length && <li className="px-3 py-2 text-sm text-fg-subtle">Only the name prints.</li>}
            </ul>
            {unused.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {unused.map((f) => (
                  <button key={f.key} type="button" className="btn-secondary btn-sm" onClick={() => set("employee_fields", [...form.employee_fields, f.key])}><Plus size={12} /> {f.label}</button>
                ))}
              </div>
            )}
            <p className="mt-1 text-xs text-fg-subtle">PAN, UAN, PF, ESIC and bank account numbers always print masked, showing only the last four characters.</p>
          </div>

          <div>
            <p className="label">What else to show</p>
            <div className="space-y-2">
              {BLOCKS.map((b) => (
                <label key={b.key} className="flex items-start gap-2.5 text-sm">
                  <input type="checkbox" className="checkbox mt-0.5" aria-label={b.label} checked={form[b.key]} onChange={(e) => set(b.key, e.target.checked)} />
                  <span><span className="text-fg">{b.label}</span><span className="block text-xs text-fg-subtle">{b.hint}{form.layout === "COMPACT" && (b.key === "show_attendance" || b.key === "show_leave_balances") ? " Not shown on the Compact layout." : ""}</span></span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <p className="label">Signature</p>
            <div className="space-y-2 text-sm">
              <label className="flex items-center gap-2.5">
                <input type="radio" name="ps-signature" aria-label="Computer-generated, no signature" checked={form.signature_mode === "COMPUTER_GENERATED"} onChange={() => setForm((f) => ({ ...f, signature_mode: "COMPUTER_GENERATED", signatory_id: null }))} />
                <span className="text-fg">“This is a computer-generated payslip and needs no signature.”</span>
              </label>
              <label className="flex flex-wrap items-center gap-2.5">
                <input type="radio" name="ps-signature" aria-label="Signed by a signatory" checked={form.signature_mode === "SIGNATORY"} onChange={() => set("signature_mode", "SIGNATORY")} />
                <span className="text-fg">Signed by</span>
                <select className="input w-full sm:w-auto sm:min-w-[200px]" aria-label="Signatory" value={form.signatory_id ?? ""} disabled={form.signature_mode !== "SIGNATORY"}
                  onChange={(e) => set("signatory_id", e.target.value || null)}>
                  <option value="">Choose a signatory</option>
                  {eligible.map((s) => <option key={s.id} value={s.id}>{s.name}{s.designation ? `, ${s.designation}` : ""}</option>)}
                </select>
              </label>
              {form.signature_mode === "SIGNATORY" && !eligible.length && signatories.isSuccess && (
                <p className="text-xs text-fg-subtle">No signatory signs for {companyId ? "this company" : "every company"} yet. Add one under Organization → Branding → Signatories.</p>
              )}
            </div>
          </div>

          <div>
            <label className="label" htmlFor="ps-note">Note <span className="font-normal text-fg-subtle">(optional)</span></label>
            <textarea id="ps-note" className="input min-h-[60px]" maxLength={500} placeholder="e.g. For questions about your pay, write to payroll@company.com."
              value={form.note_text ?? ""} onChange={(e) => set("note_text", e.target.value || null)} />
          </div>
        </fieldset>

        {editable && (
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
            <button className="btn-primary" onClick={() => save.mutate()} disabled={!dirty || signatoryMissing || !form.title.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save layout"}
            </button>
            {dirty && <button className="btn-secondary" onClick={() => { setForm(start); setCustomizing(false); }}>Discard changes</button>}
            {companyId && saved && (
              <button className="btn-secondary ml-auto" onClick={() => reset.mutate()} disabled={reset.isPending}><RotateCcw size={14} /> Use the group’s layout</button>
            )}
            {signatoryMissing && <p className="w-full text-xs text-danger">Choose who signs, or use the computer-generated statement.</p>}
          </div>
        )}
      </div>

      <PreviewPanel companyId={companyId} template={form} />
    </div>
  );
}

function PreviewPanel({ companyId, template }: { companyId: string | null; template: PayslipTemplateInput }) {
  const toast = useToast();
  const ready = !(template.signature_mode === "SIGNATORY" && !template.signatory_id) && template.title.trim().length > 0;
  const request = useDebounced(useMemo(() => ({ companyId, template }), [companyId, template]), 450);
  const preview = useQuery({
    queryKey: ["payslip-preview", request.companyId, JSON.stringify(request.template)],
    queryFn: ({ signal }) => payslipTemplatesApi.preview(request.companyId, request.template, "png", signal),
    enabled: ready,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const url = useMemo(() => (preview.data ? URL.createObjectURL(preview.data) : null), [preview.data]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const download = useMutation({
    mutationFn: () => payslipTemplatesApi.preview(companyId, template, "pdf"),
    onSuccess: (pdf) => {
      const href = URL.createObjectURL(pdf);
      const link = Object.assign(document.createElement("a"), { href, download: "payslip-sample.pdf" });
      link.click();
      setTimeout(() => URL.revokeObjectURL(href), 10_000);
    },
    onError: (e) => toast.error("Couldn’t make the sample PDF", errorMessage(e)),
  });

  return (
    <div className="min-w-0 xl:sticky xl:top-4 xl:self-start">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <LayoutTemplate size={15} className="text-fg-subtle" />
        <p className="text-sm font-medium text-fg">Preview</p>
        <span className="badge badge-warning">Sample figures</span>
        {preview.isFetching && <span className="text-xs text-fg-subtle">Updating…</span>}
        <button type="button" className="btn-secondary btn-sm ml-auto" onClick={() => download.mutate()} disabled={!ready || download.isPending}>
          <Download size={13} /> {download.isPending ? "Preparing…" : "Download sample PDF"}
        </button>
      </div>
      {preview.isError ? (
        <Notice title="Couldn’t make the preview">{errorMessage(preview.error)}</Notice>
      ) : url ? (
        <div className="overflow-hidden rounded-lg border border-line bg-zinc-200 dark:bg-zinc-800">
          <img src={url} alt={`Sample payslip in the ${template.layout.toLowerCase()} layout`} className={`block w-full transition-opacity ${preview.isFetching ? "opacity-80" : ""}`} />
        </div>
      ) : (
        <Skeleton className={`${template.layout === "COMPACT" ? "h-[420px]" : "h-[820px]"} rounded-lg`} />
      )}
    </div>
  );
}

/** A small drawing of each layout, so the choice is visual. */
function LayoutThumb({ layout }: { layout: PayslipLayout }) {
  const bar = "rounded-sm bg-zinc-300 dark:bg-zinc-600";
  return (
    <div className={`overflow-hidden rounded-md border border-line bg-white p-1.5 dark:bg-zinc-900 ${layout === "COMPACT" ? "h-10" : "h-16"}`} aria-hidden="true">
      {layout === "MODERN" && <div className="h-3 rounded-sm bg-brand-500/80" />}
      {layout === "CLASSIC" && <><div className="mx-auto h-1.5 w-1/2 rounded-sm bg-zinc-500" /><div className="mt-1 h-1.5 border border-zinc-400" /></>}
      {layout === "COMPACT" && <div className="h-1.5 border-b-2 border-brand-500/80" />}
      <div className="mt-1 grid grid-cols-2 gap-1">
        <div className={`h-1 ${bar}`} /><div className={`h-1 ${bar}`} />
        {layout !== "COMPACT" && <><div className={`h-1 ${bar}`} /><div className={`h-1 ${bar}`} /></>}
      </div>
      <div className={`mt-1 h-2 rounded-sm ${layout === "CLASSIC" ? "border border-zinc-400" : "bg-brand-500/20"}`} />
    </div>
  );
}
