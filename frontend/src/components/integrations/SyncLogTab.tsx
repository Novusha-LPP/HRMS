import { Fragment, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { ConnectedApp, SyncLogEntry } from "../../api/integrations";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { errorMessage } from "../ui/Toast";
import { OutcomeBadge } from "./badges";
import { when } from "./shared";

const OUTCOMES = ["CREATED", "LINKED", "UPDATED", "NO_CHANGE", "STALE_IGNORED", "APPLIED", "SCHEDULED", "HELD_FOR_REVIEW", "REJECTED", "FAILED", "DRY_RUN"];
const OPERATIONS = ["UPSERT", "BULK", "EXIT", "REHIRE", "LINK", "SESSION", "RECONCILE", "EXIT_RELEASED", "EXIT_REJECTED", "NEW_IP"];
const PAGE = 100;

/** Every call the app made, newest first. Contact details are masked; passwords never appear. */
export function SyncLogTab({ app }: { app: ConnectedApp }) {
  const [outcome, setOutcome] = useState("");
  const [operation, setOperation] = useState("");
  const [externalId, setExternalId] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const log = useInfiniteQuery({
    queryKey: ["integrations", app.id, "log", outcome, operation, externalId],
    queryFn: ({ pageParam }) => integrationsApi.log(app.id, {
      outcome: outcome || undefined, operation: operation || undefined,
      external_id: externalId.trim() || undefined, before: pageParam || undefined,
    }),
    initialPageParam: "",
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].created_at : undefined),
  });
  const rows = log.data?.pages.flat() ?? [];

  return (
    <div className="space-y-4">
      <div className="card grid gap-3 p-4 sm:grid-cols-3">
        <div>
          <label className="label" htmlFor="log-outcome">Outcome</label>
          <select id="log-outcome" className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">All</option>
            {OUTCOMES.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ").toLowerCase()}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="log-op">Operation</label>
          <select id="log-op" className="input" value={operation} onChange={(e) => setOperation(e.target.value)}>
            <option value="">All</option>
            {OPERATIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ").toLowerCase()}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="log-ext">The app's employee ID</label>
          <input id="log-ext" className="input" value={externalId} placeholder="e.g. EMP-1042" onChange={(e) => setExternalId(e.target.value)} />
        </div>
      </div>
      {log.isError && <Notice title="Couldn’t load the log">{errorMessage(log.error)}</Notice>}
      {log.isPending ? <Skeleton className="h-64 rounded-xl" /> : !rows.length ? (
        <div className="card"><EmptyState icon={ScrollText} title="Nothing logged" description="Calls from the app appear here as they happen." /></div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th className="w-px" /><th>When</th><th>Operation</th><th>Employee</th><th>Outcome</th><th className="hidden md:table-cell">Detail</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="cursor-pointer" onClick={() => setOpen(open === r.id ? null : r.id)}>
                      <td>{open === r.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                      <td className="whitespace-nowrap text-xs">{when(r.created_at)}</td>
                      <td className="text-xs">{r.operation.toLowerCase()}</td>
                      <td>
                        <p className="text-fg">{r.employee_name ?? "—"}</p>
                        {r.external_id && <p className="font-mono text-[11px] text-fg-subtle">{r.external_id}</p>}
                      </td>
                      <td><OutcomeBadge outcome={r.outcome} /></td>
                      <td className="hidden max-w-sm truncate text-xs md:table-cell">{r.error_code ?? summary(r)}</td>
                    </tr>
                    {open === r.id && (
                      <tr><td colSpan={6} className="bg-muted/30"><Detail row={r} /></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {log.hasNextPage && (
            <div className="border-t border-line p-3 text-center">
              <button className="btn-secondary btn-sm" onClick={() => log.fetchNextPage()} disabled={log.isFetchingNextPage}>Load older</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function summary(r: SyncLogEntry) {
  if (r.changes) return `Changed: ${Object.keys(r.changes).map((k) => k.replace(/_/g, " ")).join(", ")}`;
  return r.warnings?.[0] ?? "";
}

function Detail({ row }: { row: SyncLogEntry }) {
  const message = row.error_detail?.message as string | undefined;
  return (
    <div className="space-y-2 py-2 text-xs">
      {message && <p className="text-danger">{message}</p>}
      {row.changes && (
        <table className="w-auto">
          <tbody>
            {Object.entries(row.changes).map(([k, v]) => (
              <tr key={k}>
                <td className="pr-4 text-fg-subtle">{k.replace(/_/g, " ")}</td>
                <td className="pr-2 text-fg-muted line-through">{String(v.old ?? "—")}</td>
                <td className="text-fg">{String(v.new ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {row.warnings?.map((w) => <p key={w} className="text-warning">{w}</p>)}
      <p className="text-fg-subtle">
        {row.http_status && `HTTP ${row.http_status} · `}{row.duration_ms != null && `${row.duration_ms} ms · `}
        {row.key_prefix && `key …${row.key_prefix} · `}{row.request_id && <>reference <code>{row.request_id}</code></>}
      </p>
    </div>
  );
}
