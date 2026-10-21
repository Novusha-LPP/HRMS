import { useState } from "react";
import { Download } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { format, subDays } from "date-fns";
import { lifecycleReportsApi } from "../../api/people";
import type { LifecycleReportKind } from "../../api/people";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const KINDS: { value: LifecycleReportKind; label: string }[] = [
  { value: "rejoins", label: "People who rejoined" },
  { value: "separation-settlements", label: "Leave settled for leavers" },
  { value: "company-transfers", label: "Moves between companies" },
];

/** What happened when people left, came back or moved, for any period, as a table or a file. */
export function LifecycleReports() {
  const toast = useToast();
  const [kind, setKind] = useState<LifecycleReportKind>("rejoins");
  const [from, setFrom] = useState(format(subDays(new Date(), 90), "yyyy-MM-dd"));
  const [to, setTo] = useState(format(new Date(), "yyyy-MM-dd"));
  const [downloading, setDownloading] = useState(false);
  const report = useQuery({
    queryKey: ["lifecycle-report", kind, from, to],
    queryFn: () => lifecycleReportsApi.table(kind, from, to),
    enabled: !!from && !!to && from <= to,
    retry: false,
  });
  const download = async () => {
    setDownloading(true);
    try { await lifecycleReportsApi.downloadCsv(kind, from, to); }
    catch (e) { toast.error("Couldn’t download the report", errorMessage(e)); }
    finally { setDownloading(false); }
  };

  return (
    <section className="card p-5" aria-labelledby="lifecycle-reports">
      <h3 id="lifecycle-reports" className="text-base font-semibold text-fg">Reports</h3>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="label" htmlFor="lr-kind">Report</label>
          <select id="lr-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as LifecycleReportKind)}>
            {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </div>
        <div><label className="label" htmlFor="lr-from">From</label><input id="lr-from" type="date" className="input" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></div>
        <div><label className="label" htmlFor="lr-to">To</label><input id="lr-to" type="date" className="input" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></div>
        <button type="button" className="btn-secondary btn-sm" onClick={download} disabled={downloading || !report.data?.rows.length}>
          <Download size={14} /> {downloading ? "Preparing…" : "Download CSV"}
        </button>
      </div>
      <div className="mt-4 overflow-x-auto" data-testid="lifecycle-report">
        {report.isPending ? <Skeleton className="h-24 rounded-xl" /> : report.isError ? (
          <p className="text-[13px] text-danger">{errorMessage(report.error)}</p>
        ) : report.data.rows.length === 0 ? (
          <p className="text-[13px] text-fg-subtle">Nothing in this period.</p>
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-xs text-fg-subtle">{report.data.columns.map((c) => <th key={c} className="whitespace-nowrap px-2 py-1 font-medium">{c}</th>)}</tr></thead>
            <tbody>
              {report.data.rows.slice(0, 100).map((r, i) => (
                <tr key={i} className="border-t border-line">
                  {r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1.5">{v === null || v === "" ? "—" : String(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {report.data && (report.data.rows.length > 100 || report.data.truncated) && (
          <p className="mt-2 text-xs text-fg-subtle">Showing the first 100 rows. Download the file for the full list.</p>
        )}
      </div>
    </section>
  );
}
