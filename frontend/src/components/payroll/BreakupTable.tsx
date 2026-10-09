import type { Breakup, BreakupLine, ComponentKind } from "../../api/payroll";
import { inr } from "../../lib/money";
import { Notice } from "../ui/Feedback";

const SECTIONS: { kind: ComponentKind; title: string }[] = [
  { kind: "EARNING", title: "Earnings" },
  { kind: "REIMBURSEMENT", title: "Reimbursements" },
  { kind: "EMPLOYER_CONTRIBUTION", title: "Employer contributions (part of CTC, not paid out)" },
  { kind: "DEDUCTION", title: "Deductions" },
];

/** The monthly and annual breakup of a CTC, the way the reviewer checks it. */
export function BreakupTable({ breakup, compact = false }: { breakup: Breakup; compact?: boolean }) {
  const byKind = (kind: ComponentKind) => breakup.lines.filter((l) => l.kind === kind);
  const notes = breakup.warnings.filter((w) => !w.startsWith("Provisional"));

  return (
    <div className="space-y-3">
      {breakup.provisional && (
        <Notice title="Provisional">
          Some PF / ESIC values haven’t been verified by the payroll reviewer yet. Check them in Statutory values.
        </Notice>
      )}
      <div className="overflow-hidden rounded-xl border border-line">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="bg-muted/60 text-left text-[11px] font-medium uppercase tracking-wide text-fg-subtle">
              <th className="px-4 py-2">Component</th>
              <th className="px-4 py-2 text-right">Monthly</th>
              {!compact && <th className="px-4 py-2 text-right">Annual</th>}
            </tr>
          </thead>
          <tbody>
            {SECTIONS.map(({ kind, title }) => {
              const rows = byKind(kind);
              if (!rows.length) return null;
              return (
                <Section key={kind} title={title} rows={rows} compact={compact}
                  total={kind === "EARNING" ? { label: "Gross pay", value: breakup.gross } : kind === "DEDUCTION" ? { label: "Total deductions", value: breakup.deductions } : undefined} />
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-line bg-muted/40 font-semibold text-fg">
              <td className="px-4 py-2.5">Net pay <span className="font-normal text-fg-subtle">(before PT and TDS)</span></td>
              <td className="px-4 py-2.5 text-right tabular-nums">{inr(breakup.net_before_tax, true)}</td>
              {!compact && <td className="px-4 py-2.5 text-right tabular-nums">{inr(Number(breakup.net_before_tax) * 12, true)}</td>}
            </tr>
            <tr className="text-fg-muted">
              <td className="px-4 py-2">Cost to company</td>
              <td className="px-4 py-2 text-right tabular-nums">{inr(breakup.monthly_ctc, true)}</td>
              {!compact && <td className="px-4 py-2 text-right tabular-nums">{inr(breakup.annual_ctc, true)}</td>}
            </tr>
          </tfoot>
        </table>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-fg-muted sm:grid-cols-3">
        <div><dt className="inline">PF wages: </dt><dd className="inline tabular-nums text-fg">{inr(breakup.pf_wages, true)}</dd></div>
        <div><dt className="inline">ESIC wages: </dt><dd className="inline tabular-nums text-fg">{inr(breakup.esic_wages, true)}</dd></div>
        <div><dt className="inline">ESIC: </dt><dd className="inline text-fg">{breakup.esic_applies ? "applies" : "doesn’t apply"}</dd></div>
      </dl>
      {notes.length > 0 && <ul className="space-y-0.5 text-xs text-fg-subtle">{notes.map((w) => <li key={w}>{w}</li>)}</ul>}
    </div>
  );
}

function Section({ title, rows, total, compact }: {
  title: string; rows: BreakupLine[]; total?: { label: string; value: string }; compact: boolean;
}) {
  return (
    <>
      <tr><td colSpan={compact ? 2 : 3} className="px-4 pb-1 pt-3 text-[11px] font-medium text-fg-subtle">{title}</td></tr>
      {rows.map((l) => (
        <tr key={l.code} className="text-fg-muted">
          <td className="px-4 py-1.5"><span className="text-fg">{l.name}</span> <span className="font-mono text-[11px] text-fg-subtle">{l.code}</span></td>
          <td className="px-4 py-1.5 text-right tabular-nums">{inr(l.monthly, true)}</td>
          {!compact && <td className="px-4 py-1.5 text-right tabular-nums">{inr(l.annual, true)}</td>}
        </tr>
      ))}
      {total && (
        <tr className="font-medium text-fg">
          <td className="px-4 py-1.5">{total.label}</td>
          <td className="px-4 py-1.5 text-right tabular-nums">{inr(total.value, true)}</td>
          {!compact && <td className="px-4 py-1.5 text-right tabular-nums">{inr(Number(total.value) * 12, true)}</td>}
        </tr>
      )}
    </>
  );
}
