import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, format, startOfMonth } from "date-fns";
import { ChevronRight, IndianRupee, Search } from "lucide-react";
import { lineInput, payrollApi } from "../../api/payroll";
import type { SalaryRow } from "../../api/payroll";
import { useAuth } from "../../context/AuthContext";
import { inr, lakhs, parseAmount, useDebounced } from "../../lib/money";
import { Avatar } from "../ui/Avatar";
import { Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { Segmented } from "../ui/Tabs";
import { useToast, errorMessage } from "../ui/Toast";
import { BreakupTable } from "./BreakupTable";

const day = (d: string) => format(new Date(`${d}T00:00:00`), "d MMM yyyy");
const REASONS = ["Joining", "Annual revision", "Promotion", "Confirmation", "Market correction", "Correction of an error", "Other"];

type Show = "ALL" | "MISSING";

/** Every current employee in scope with their CTC; opens one person's salary, breakup and history. */
export function SalariesTab({ canWrite }: { canWrite: boolean }) {
  const { user } = useAuth();
  const [company, setCompany] = useState("");
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<Show>("ALL");
  const [open, setOpen] = useState<SalaryRow | null>(null);
  const salaries = useQuery({ queryKey: ["payroll", "salaries", company], queryFn: () => payrollApi.salaries(company || undefined), placeholderData: keepPreviousData });

  const all = useMemo(() => salaries.data ?? [], [salaries.data]);
  const today = format(new Date(), "yyyy-MM-dd");
  const missing = all.filter((r) => !r.annual_ctc).length;
  const needle = query.trim().toLowerCase();
  const rows = all.filter((r) =>
    (show === "ALL" || !r.annual_ctc)
    && (!needle || r.name.toLowerCase().includes(needle) || r.employee_number.toLowerCase().includes(needle) || (r.department ?? "").toLowerCase().includes(needle)));

  if (salaries.isError) return <Notice title="Couldn’t load salaries">The payroll API isn’t responding.</Notice>;

  return (
    <div className="space-y-4">
      {!salaries.isPending && missing > 0 && (
        <Notice tone="info" title={`${missing} ${missing === 1 ? "person has" : "people have"} no salary yet`}>
          They can't be paid until a salary is assigned. Use “Without a salary” to list them.
        </Notice>
      )}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[14rem] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input className="input pl-8" placeholder="Search name, employee number or department" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search salaries" />
          </div>
          {(user?.legalEntities.length ?? 0) > 1 && (
            <select className="input w-56" value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company">
              <option value="">All companies</option>
              {user?.legalEntities.map((le) => <option key={le.id} value={le.id}>{le.name}</option>)}
            </select>
          )}
          <Segmented<Show> value={show} onChange={setShow} items={[{ value: "ALL", label: `All${salaries.isPending ? "" : ` (${all.length})`}` }, { value: "MISSING", label: `Without a salary${salaries.isPending ? "" : ` (${missing})`}` }]} />
        </div>
        {salaries.isPending ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={IndianRupee} title={all.length ? "Nobody matches" : "No employees"} description={all.length ? "Try another search or filter." : "Employees you can see appear here once they're added."} />
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Employee</th><th className="hidden md:table-cell">Department</th><th className="text-right">Annual CTC</th><th className="hidden sm:table-cell">Structure</th><th className="hidden lg:table-cell">From</th><th className="w-8" /></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.employment_id} className="group cursor-pointer" onClick={() => setOpen(r)}>
                    <td>
                      <div className="flex items-center gap-3">
                        <Avatar name={r.name} size="sm" />
                        <div className="min-w-0 leading-tight">
                          <p className="truncate font-medium text-fg">{r.name}</p>
                          <p className="truncate text-[11px] text-fg-subtle">{r.employee_number}{r.designation ? ` · ${r.designation}` : ""}</p>
                        </div>
                      </div>
                    </td>
                    <td className="hidden md:table-cell">{r.department ?? "—"}</td>
                    <td className="whitespace-nowrap text-right tabular-nums">
                      {r.annual_ctc ? <span className="text-fg">{inr(r.annual_ctc)}</span> : <span className="badge badge-warning">Not set</span>}
                    </td>
                    <td className="hidden sm:table-cell">{r.structure_name ?? "—"}</td>
                    <td className="hidden whitespace-nowrap lg:table-cell">
                      {!r.effective_from ? "—" : r.effective_from > today ? <span className="badge badge-info">Starts {day(r.effective_from)}</span> : day(r.effective_from)}
                    </td>
                    <td><ChevronRight size={15} className="text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <EmployeeSalarySheet key={open?.employment_id ?? "none"} row={open} canWrite={canWrite && open?.employment_id !== user?.employmentId} onClose={() => setOpen(null)} />
    </div>
  );
}

function EmployeeSalarySheet({ row, canWrite, onClose }: { row: SalaryRow | null; canWrite: boolean; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["payroll", "compensation", row?.employment_id],
    queryFn: () => payrollApi.compensation(row!.employment_id),
    enabled: !!row,
  });
  const [revising, setRevising] = useState(false);
  const current = detail.data?.current ?? null;

  return (
    <Sheet open={!!row} onClose={onClose} className="max-w-2xl"
      title={row ? row.name : ""}
      description={row ? [row.employee_number, row.designation, row.department, row.company].filter(Boolean).join(" · ") : undefined}>
      {detail.isPending ? <Skeleton className="h-64 rounded-xl" /> : detail.isError ? (
        <Notice title="Couldn’t load this salary">{errorMessage(detail.error)}</Notice>
      ) : revising && row ? (
        <SalaryForm row={row} currentFrom={current?.effective_from ?? null} currentStructure={current?.structure_id ?? null} onDone={() => setRevising(false)} />
      ) : (
        <div className="space-y-6">
          <section className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow">Annual CTC</p>
              {current ? (
                <>
                  <p className="mt-1 text-2xl font-semibold tabular-nums text-fg">{inr(current.annual_ctc)}</p>
                  <p className="text-xs text-fg-subtle">
                    {current.structure_name} · {current.effective_from > format(new Date(), "yyyy-MM-dd") ? "starts" : "from"} {day(current.effective_from)}
                  </p>
                </>
              ) : <p className="mt-1 text-sm text-fg-muted">No salary assigned yet.</p>}
            </div>
            {canWrite && <button className="btn-primary" onClick={() => setRevising(true)}>{current ? "Revise salary" : "Assign salary"}</button>}
          </section>

          {detail.data.breakup_error && <Notice title="The breakup can't be worked out">{detail.data.breakup_error}</Notice>}
          {detail.data.breakup && <BreakupTable breakup={detail.data.breakup} />}

          {detail.data.history.length > 0 && (
            <section>
              <p className="eyebrow mb-2">History</p>
              <ol className="space-y-2">
                {detail.data.history.map((h, i) => {
                  const previous = detail.data.history[i + 1];
                  const change = previous ? (Number(h.annual_ctc) - Number(previous.annual_ctc)) / Number(previous.annual_ctc) : null;
                  return (
                    <li key={h.id} className="flex items-start justify-between gap-3 rounded-xl border border-line px-4 py-3 text-[13px]">
                      <div className="min-w-0">
                        <p className="font-medium text-fg">
                          {inr(h.annual_ctc)}
                          {change !== null && Number.isFinite(change) && (
                            <span className={`ml-2 text-xs font-normal ${change >= 0 ? "text-success" : "text-danger"}`}>{change >= 0 ? "+" : ""}{(change * 100).toFixed(1)}%</span>
                          )}
                        </p>
                        <p className="text-xs text-fg-subtle">{h.structure_name}{h.reason ? ` · ${h.reason}` : ""}{h.note ? ` · ${h.note}` : ""}</p>
                      </div>
                      <div className="shrink-0 text-right text-xs text-fg-subtle">
                        <p>{day(h.effective_from)}{h.effective_to ? ` – ${day(h.effective_to)}` : " onwards"}</p>
                        {h.recorded_by_name && <p>by {h.recorded_by_name}</p>}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>
          )}
        </div>
      )}
    </Sheet>
  );
}

function SalaryForm({ row, currentFrom, currentStructure, onDone }: { row: SalaryRow; currentFrom: string | null; currentStructure: string | null; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const structures = useQuery({ queryKey: ["payroll", "structures"], queryFn: () => payrollApi.structures() });
  const usable = (structures.data ?? []).filter((s) => !s.legal_entity_id || s.legal_entity_id === row.legal_entity_id);
  const [structureId, setStructureId] = useState(currentStructure ?? "");
  const chosen = usable.find((s) => s.id === structureId) ?? (usable.length === 1 ? usable[0] : undefined);
  const [ctc, setCtc] = useState("");
  const [from, setFrom] = useState(format(startOfMonth(addMonths(new Date(), 1)), "yyyy-MM-dd"));
  const [reason, setReason] = useState(currentFrom ? "Annual revision" : "Joining");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const ctcValue = parseAmount(ctc);

  const problems: string[] = [];
  if (!chosen) problems.push("Choose a salary structure.");
  if (!ctcValue) problems.push("Enter the annual CTC.");
  if (!from) problems.push("Choose the date it applies from.");
  else if (currentFrom && from <= currentFrom) problems.push(`A revision must start after ${day(currentFrom)}, when the current salary started.`);

  const previewKey = useDebounced(JSON.stringify([ctcValue, chosen?.id, from]), 300);
  const preview = useQuery({
    queryKey: ["payroll", "preview-salary", previewKey],
    queryFn: () => payrollApi.preview({ annual_ctc: ctcValue!, lines: chosen!.lines.map(lineInput), on: from || undefined }),
    enabled: !!ctcValue && !!chosen && previewKey === JSON.stringify([ctcValue, chosen?.id, from]),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => payrollApi.setCompensation(row.employment_id, { structure_id: chosen!.id, annual_ctc: ctcValue!, effective_from: from, reason, note: note.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payroll"] });
      toast.success(currentFrom ? "Salary revised" : "Salary assigned", `${row.name}: ${inr(ctcValue)} from ${day(from)}`);
      onDone();
    },
    onError: (e) => toast.error("Couldn’t save the salary", errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };

  if (structures.isPending) return <Skeleton className="h-64 rounded-xl" />;
  if (!usable.length) {
    return <Notice title="No salary structure for this company" action={<button className="btn-secondary btn-sm" onClick={onDone}>Back</button>}>Create one in the Structures tab first.</Notice>;
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-fg-muted">{currentFrom ? "The current salary ends the day before the new one starts. Its history is kept." : "The first salary for this employee."}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="sal-ctc">Annual CTC (₹)</label>
          <input id="sal-ctc" className="input" inputMode="decimal" placeholder="600000" value={ctc} onChange={(e) => setCtc(e.target.value)} autoFocus />
          {ctcValue && <p className="mt-1 text-xs text-fg-subtle">{lakhs(ctcValue)} · {inr(Number(ctcValue) / 12, true)} a month</p>}
        </div>
        <div>
          <label className="label" htmlFor="sal-from">Applies from</label>
          <input id="sal-from" type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="sal-structure">Structure</label>
          <select id="sal-structure" className="input" value={chosen?.id ?? ""} onChange={(e) => setStructureId(e.target.value)}>
            {!chosen && <option value="">Choose…</option>}
            {usable.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sal-reason">Reason</label>
          <select id="sal-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => <option key={r}>{r}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="sal-note">Note <span className="font-normal text-fg-subtle">(optional)</span></label>
        <input id="sal-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>

      {ctcValue && chosen && (preview.isError
        ? <Notice title="This CTC doesn't work with the structure">{errorMessage(preview.error)}</Notice>
        : preview.data ? <div className={preview.isFetching ? "opacity-60" : undefined}><BreakupTable breakup={preview.data} /></div>
          : <Skeleton className="h-48 rounded-xl" />)}

      {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <button type="button" className="btn-secondary" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>{save.isPending ? "Saving…" : currentFrom ? "Save revision" : "Assign salary"}</button>
      </div>
    </form>
  );
}
