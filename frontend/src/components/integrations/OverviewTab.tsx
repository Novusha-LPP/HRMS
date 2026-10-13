import { useQuery } from "@tanstack/react-query";
import { BookOpen, ShieldCheck } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { ConnectedApp } from "../../api/integrations";
import { API_DOCS_URL } from "../../api/client";
import { Notice, Skeleton } from "../ui/Feedback";
import { ago, humanizeEvent } from "./shared";

/** How the app is doing, what it receives, and how its developers get started. */
export function OverviewTab({ app }: { app: ConnectedApp }) {
  const report = useQuery({ queryKey: ["integrations", app.id, "report"], queryFn: () => integrationsApi.report(app.id) });
  const two = app.kind === "TWO_WAY";

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <div className="card grid grid-cols-2 gap-4 p-5 xl:grid-cols-4">
          <Stat label="Linked employees" value={app.linked_employees} />
          <Stat label="Active keys" value={app.active_keys} />
          <Stat label="Last call" value={ago(app.last_request_at)} />
          <Stat label="Events not yet read" value={app.feed_lag} hint={app.feed_read_at ? `read ${ago(app.feed_read_at)}` : "feed never read"} />
        </div>
        {app.active_keys === 0 && app.status === "ACTIVE" && (
          <Notice tone="info" title="No active key">Create a key on the Keys tab and give it to the app's developers.</Notice>
        )}
        <div className="card p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-fg"><ShieldCheck size={16} /> What this app receives</h3>
          {report.isPending ? <Skeleton className="h-24" /> : report.data && (
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <Item label="Events">{report.data.events.map(humanizeEvent).join(", ") || "none"}</Item>
              <Item label="Data">{report.data.data_classes.map((c) => c.toLowerCase().replace("_", " and ")).join(", ")}</Item>
              <Item label="Fields">{report.data.fields.map((f) => f.replace(/_/g, " ")).join(", ")}</Item>
              <Item label="Key permissions">{report.data.scopes_granted.join(", ") || "none"}</Item>
              <Item label="Employees sent through the feed">{report.data.employees_delivered_through_feed}</Item>
              <Item label="Never sent">{report.data.never_sent}</Item>
            </dl>
          )}
        </div>
      </div>
      <aside className="card space-y-3 p-5 text-sm">
        <h3 className="flex items-center gap-2 font-semibold text-fg"><BookOpen size={16} /> For the app's developers</h3>
        <ol className="list-decimal space-y-2 pl-5 text-fg-muted">
          <li>Create a key (Keys tab) and store it on the app's server only.</li>
          {two && <li>Check the values HRMS accepts: <code className="text-xs">GET /v1/integrations/reference-data</code>.</li>}
          {two && <li>Link employees already in both systems with <code className="text-xs">POST /v1/integrations/employees/link</code> (dry run first).</li>}
          {two && <li>Send new joiners, changes and exits with <code className="text-xs">PUT /v1/integrations/employees/{"{id}"}</code>.</li>}
          <li>Poll <code className="text-xs">GET /v1/integrations/events</code> every 30–60 seconds for changes made in HRMS.</li>
          {two && <li>For punching and self-service inside the app: <code className="text-xs">POST /v1/integrations/sessions</code>.</li>}
        </ol>
        <a className="btn-secondary w-full justify-center" href={`${API_DOCS_URL}#/Integrations`} target="_blank" rel="noreferrer">Open the API reference</a>
      </aside>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div>
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className={`font-semibold text-fg ${typeof value === "number" ? "text-xl" : "text-sm leading-7"}`}>{value}</p>
      {hint && <p className="text-[11px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="text-fg">{children}</dd>
    </div>
  );
}
