import { format } from "date-fns";
import { Download, TableProperties } from "lucide-react";
import type { RunResult } from "../../api/reports";
import { StatusBadge } from "../ui/StatusBadge";
import { EmptyState } from "../ui/Feedback";

const STATUS_FIELDS = new Set(["status", "case_status", "employment_state"]);

function cell(field: string, value: unknown) {
  if (value == null || value === "") return <span className="text-fg-subtle">—</span>;
  const s = String(value);
  if (STATUS_FIELDS.has(field)) return <StatusBadge status={s} />;
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return format(new Date(s), "d MMM yyyy, hh:mm a");
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return format(new Date(s), "d MMM yyyy");
  return s;
}

function downloadCsv(result: RunResult) {
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    result.columns.map((c) => esc(c.label)).join(","),
    ...result.rows.map((row) => result.columns.map((c) => esc(row[c.field])).join(",")),
  ];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  a.download = `${result.name.replace(/\s+/g, "_")}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function ResultTable({ result }: { result: RunResult }) {
  const cols = result.columns.filter((c) => c.visible !== false);
  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="card-header border-b border-line pb-4">
        <div className="min-w-0">
          <h3 className="card-title truncate">{result.name}</h3>
          <p className="card-desc">
            {result.total_rows} {result.total_rows === 1 ? "row" : "rows"}
            {result.generated_at && ` · generated ${format(new Date(result.generated_at), "d MMM, hh:mm a")}`}
          </p>
        </div>
        <button onClick={() => downloadCsv(result)} className="btn-secondary btn-sm" disabled={!result.rows.length}>
          <Download size={13} /> Export CSV
        </button>
      </div>
      {result.truncated && <p className="px-5 py-3 text-sm text-warning">Showing the first {result.total_rows} rows. Narrow the date range or filters for a complete report and CSV.</p>}
      {result.rows.length === 0 ? (
        <EmptyState icon={TableProperties} title="No matching rows" description="Try removing a filter or choosing a different module." />
      ) : (
        <div className="max-h-[560px] overflow-auto">
          <table className="tbl">
            <thead className="sticky top-0 z-10 [&_th]:bg-muted">
              <tr>{cols.map((c) => <th key={c.field}>{c.label}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i}>
                  {cols.map((c) => <td key={c.field} className="whitespace-nowrap">{cell(c.field, row[c.field])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
