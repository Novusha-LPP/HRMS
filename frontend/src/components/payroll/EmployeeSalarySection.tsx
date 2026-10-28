import { useState } from "react";
import type { FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, format, startOfMonth } from "date-fns";
import { IndianRupee, Plus } from "lucide-react";
import { lineInput, payrollApi } from "../../api/payroll";
import type { SalaryRow } from "../../api/payroll";
import { inr, lakhs, parseAmount, useDebounced } from "../../lib/money";
import { Sheet } from "../ui/Overlay";
import { Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { BreakupTable } from "./BreakupTable";

const day = (d: string) => format(new Date(`${d}T00:00:00`), "d MMM yyyy");
const REASONS = [
  "Joining",
  "Annual revision",
  "Promotion",
  "Confirmation",
  "Market correction",
  "Correction of an error",
  "Other",
];

export interface SalaryTarget {
  employmentId: string;
  employeeName: string;
  employeeNumber?: string;
  designation?: string;
  department?: string;
  company?: string;
  legalEntityId?: string;
}

export interface EmployeeSalarySectionProps {
  target: SalaryTarget;
  canWrite: boolean;
  initialRevising?: boolean;
  onCloseForm?: () => void;
}

/**
 * Full compensation details, salary breakup, revision history, and salary assignment / revision form.
 * Used inside both the Payroll Salaries sheet and the Employee profile drawer.
 */
export function EmployeeSalarySection({
  target,
  canWrite,
  initialRevising = false,
  onCloseForm,
}: EmployeeSalarySectionProps) {
  const detail = useQuery({
    queryKey: ["payroll", "compensation", target.employmentId],
    queryFn: () => payrollApi.compensation(target.employmentId),
    enabled: !!target.employmentId,
  });

  const [revising, setRevising] = useState(initialRevising);
  const current = detail.data?.current ?? null;

  const handleDone = () => {
    setRevising(false);
    onCloseForm?.();
  };

  if (detail.isPending) {
    return <Skeleton className="h-64 rounded-xl" />;
  }

  if (detail.isError) {
    return <Notice title="Couldn’t load this salary">{errorMessage(detail.error)}</Notice>;
  }

  if (revising) {
    return (
      <SalaryForm
        target={target}
        currentFrom={current?.effective_from ?? null}
        currentStructure={current?.structure_id ?? null}
        onDone={handleDone}
      />
    );
  }

  return (
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
          ) : (
            <p className="mt-1 text-sm text-fg-muted">No salary assigned yet.</p>
          )}
        </div>
        {canWrite && (
          <button
            type="button"
            className="btn-primary"
            onClick={() => setRevising(true)}
          >
            {current ? "Revise salary" : "Assign salary"}
          </button>
        )}
      </section>

      {!current && (
        <div className="rounded-xl border border-dashed border-line p-8 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-brand-500/10 text-accent">
            <IndianRupee size={22} />
          </div>
          <h3 className="mt-3 text-sm font-semibold text-fg">No salary assigned</h3>
          <p className="mx-auto mt-1 max-w-sm text-xs text-fg-subtle">
            This employee does not have a salary structure or CTC assigned yet. Assigning a salary establishes their compensation breakup and payroll contributions.
          </p>
          {canWrite && (
            <button
              type="button"
              className="btn-primary mt-4 inline-flex items-center gap-1.5"
              onClick={() => setRevising(true)}
            >
              <Plus size={14} /> Assign salary
            </button>
          )}
        </div>
      )}

      {detail.data.breakup_error && (
        <Notice title="The breakup can't be worked out">{detail.data.breakup_error}</Notice>
      )}

      {detail.data.breakup && <BreakupTable breakup={detail.data.breakup} />}

      {detail.data.history.length > 0 && (
        <section>
          <p className="eyebrow mb-2">History</p>
          <ol className="space-y-2">
            {detail.data.history.map((h, i) => {
              const previous = detail.data.history[i + 1];
              const change = previous && h.annual_ctc !== null && previous.annual_ctc !== null
                ? (Number(h.annual_ctc) - Number(previous.annual_ctc)) / Number(previous.annual_ctc)
                : null;
              return (
                <li
                  key={h.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-line px-4 py-3 text-[13px]"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-fg">
                      {h.annual_ctc === null ? <span className="text-danger">Unreadable</span> : inr(h.annual_ctc)}
                      {change !== null && Number.isFinite(change) && (
                        <span
                          className={`ml-2 text-xs font-normal ${
                            change >= 0 ? "text-success" : "text-danger"
                          }`}
                        >
                          {change >= 0 ? "+" : ""}
                          {(change * 100).toFixed(1)}%
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-fg-subtle">
                      {h.error ?? h.structure_name}
                      {h.reason ? ` · ${h.reason}` : ""}
                      {h.note ? ` · ${h.note}` : ""}
                    </p>
                  </div>
                  <div className="shrink-0 text-right text-xs text-fg-subtle">
                    <p>
                      {day(h.effective_from)}
                      {h.effective_to ? ` – ${day(h.effective_to)}` : " onwards"}
                    </p>
                    {h.recorded_by_name && <p>by {h.recorded_by_name}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}

export function SalaryForm({
  target,
  currentFrom,
  currentStructure,
  onDone,
}: {
  target: SalaryTarget;
  currentFrom: string | null;
  currentStructure: string | null;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const structures = useQuery({
    queryKey: ["payroll", "structures"],
    queryFn: () => payrollApi.structures(),
  });
  const usable = (structures.data ?? []).filter(
    (s) => !s.legal_entity_id || !target.legalEntityId || s.legal_entity_id === target.legalEntityId,
  );
  const [structureId, setStructureId] = useState(currentStructure ?? "");
  const chosen = usable.find((s) => s.id === structureId) ?? (usable.length === 1 ? usable[0] : undefined);
  const [ctc, setCtc] = useState("");
  const [from, setFrom] = useState(
    format(startOfMonth(addMonths(new Date(), 1)), "yyyy-MM-dd"),
  );
  const [reason, setReason] = useState(currentFrom ? "Annual revision" : "Joining");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const ctcValue = parseAmount(ctc);

  const problems: string[] = [];
  if (!chosen) problems.push("Choose a salary structure.");
  if (!ctcValue) problems.push("Enter the annual CTC.");
  if (!from) problems.push("Choose the date it applies from.");
  else if (currentFrom && from <= currentFrom) {
    problems.push(`A revision must start after ${day(currentFrom)}, when the current salary started.`);
  }

  const previewKey = useDebounced(JSON.stringify([ctcValue, chosen?.id, from]), 300);
  const preview = useQuery({
    queryKey: ["payroll", "preview-salary", previewKey],
    queryFn: () =>
      payrollApi.preview({
        annual_ctc: ctcValue!,
        lines: chosen!.lines.map(lineInput),
        on: from || undefined,
      }),
    enabled: !!ctcValue && !!chosen && previewKey === JSON.stringify([ctcValue, chosen?.id, from]),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () =>
      payrollApi.setCompensation(target.employmentId, {
        structure_id: chosen!.id,
        annual_ctc: ctcValue!,
        effective_from: from,
        reason,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payroll"] });
      qc.invalidateQueries({ queryKey: ["payroll", "compensation", target.employmentId] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success(
        currentFrom ? "Salary revised" : "Salary assigned",
        `${target.employeeName}: ${inr(ctcValue)} from ${day(from)}`,
      );
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
    return (
      <Notice
        title="No salary structure available"
        action={
          <button type="button" className="btn-secondary btn-sm" onClick={onDone}>
            Back
          </button>
        }
      >
        Create a salary structure in Payroll → Structures first before assigning compensation.
      </Notice>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-fg-muted">
        {currentFrom
          ? "The current salary ends the day before the new one starts. Historical records are preserved."
          : `Assign the first salary for ${target.employeeName}.`}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="sal-ctc">
            Annual CTC (₹)
          </label>
          <input
            id="sal-ctc"
            className="input"
            inputMode="decimal"
            placeholder="600000"
            value={ctc}
            onChange={(e) => setCtc(e.target.value)}
            autoFocus
          />
          {ctcValue && (
            <p className="mt-1 text-xs text-fg-subtle">
              {lakhs(ctcValue)} · {inr(Number(ctcValue) / 12, true)} a month
            </p>
          )}
        </div>
        <div>
          <label className="label" htmlFor="sal-from">
            Applies from
          </label>
          <input
            id="sal-from"
            type="date"
            className="input"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="sal-structure">
            Structure
          </label>
          <select
            id="sal-structure"
            className="input"
            value={chosen?.id ?? ""}
            onChange={(e) => setStructureId(e.target.value)}
          >
            {!chosen && <option value="">Choose…</option>}
            {usable.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sal-reason">
            Reason
          </label>
          <select
            id="sal-reason"
            className="input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          >
            {REASONS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="sal-note">
          Note <span className="font-normal text-fg-subtle">(optional)</span>
        </label>
        <input
          id="sal-note"
          className="input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      {ctcValue && chosen && (preview.isError ? (
        <Notice title="This CTC doesn't work with the structure">{errorMessage(preview.error)}</Notice>
      ) : preview.data ? (
        <div className={preview.isFetching ? "opacity-60" : undefined}>
          <BreakupTable breakup={preview.data} />
        </div>
      ) : (
        <Skeleton className="h-48 rounded-xl" />
      ))}

      {tried && problems.length > 0 && (
        <ul className="space-y-1 text-xs text-danger">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : currentFrom ? "Save revision" : "Assign salary"}
        </button>
      </div>
    </form>
  );
}

/**
 * Slide-out sheet for the Payroll Salaries tab.
 */
export function EmployeeSalarySheet({
  row,
  canWrite,
  onClose,
}: {
  row: SalaryRow | null;
  canWrite: boolean;
  onClose: () => void;
}) {
  if (!row) return null;

  return (
    <Sheet
      open={!!row}
      onClose={onClose}
      className="max-w-2xl"
      title={row.name}
      description={[row.employee_number, row.designation, row.department, row.company]
        .filter(Boolean)
        .join(" · ")}
    >
      <EmployeeSalarySection
        target={{
          employmentId: row.employment_id,
          employeeName: row.name,
          employeeNumber: row.employee_number,
          designation: row.designation ?? undefined,
          department: row.department ?? undefined,
          company: row.company ?? undefined,
          legalEntityId: row.legal_entity_id,
        }}
        canWrite={canWrite}
      />
    </Sheet>
  );
}
