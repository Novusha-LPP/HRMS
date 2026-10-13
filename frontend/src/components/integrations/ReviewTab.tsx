import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { ConnectedApp, Duplicate } from "../../api/integrations";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { ago, when } from "./shared";

/** What needs HR: possible duplicates, exits held by the safety valve, hires the app hasn't linked. */
export function ReviewTab({ app }: { app: ConnectedApp }) {
  const qc = useQueryClient();
  const toast = useToast();
  const duplicates = useQuery({ queryKey: ["integrations", app.id, "duplicates"], queryFn: () => integrationsApi.duplicates(app.id) });
  const held = useQuery({ queryKey: ["integrations", app.id, "held"], queryFn: () => integrationsApi.heldExits(app.id) });
  const notLinked = useQuery({ queryKey: ["integrations", app.id, "not-linked"], queryFn: () => integrationsApi.notLinked(app.id) });
  const done = () => qc.invalidateQueries({ queryKey: ["integrations", app.id] });

  const resolve = useMutation({
    mutationFn: (v: { id: string; decision: "SAME_PERSON" | "DIFFERENT_PERSON" }) => integrationsApi.resolveDuplicate(v.id, v.decision),
    onSuccess: (_, v) => { done(); toast.success(v.decision === "SAME_PERSON" ? "Linked" : "Marked as a different person", "The app's next retry goes through."); },
    onError: (e) => toast.error("Couldn’t resolve it", errorMessage(e)),
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; decision: "RELEASE" | "REJECT" }) => integrationsApi.decideHeldExit(v.id, v.decision),
    onSuccess: (r) => { done(); toast.success(r.decision === "RELEASE" ? `Exit ${r.outcome.toLowerCase()}` : "Exit rejected"); },
    onError: (e) => toast.error("Couldn’t decide the exit", errorMessage(e)),
  });

  if (duplicates.isPending || held.isPending || notLinked.isPending) return <Skeleton className="h-64 rounded-xl" />;
  const nothing = !duplicates.data?.length && !held.data?.length && !notLinked.data?.length;
  if (nothing) return <div className="card"><EmptyState icon={CheckCircle2} title="Nothing needs review" description="Possible duplicates, held exits and unlinked hires appear here." /></div>;

  return (
    <div className="space-y-5">
      {!!duplicates.data?.length && (
        <Panel title="Possible duplicates" hint="The app sent someone who looks like an unlinked HRMS employee. Nothing was created; confirm or reject the match.">
          {duplicates.data.map((d) => (
            <div key={d.id} className="grid gap-3 border-b border-line p-4 last:border-b-0 md:grid-cols-[1fr_1fr_auto]">
              <Side title={`${app.code} · ${d.external_id}`} record={appSide(d)} />
              <Side title={`HRMS · ${d.hrms_employee.employee_code}`} record={{
                Name: `${d.hrms_employee.first_name} ${d.hrms_employee.last_name}`,
                "Date of birth": d.hrms_employee.date_of_birth ?? "—",
                Email: d.hrms_employee.email ?? "—",
              }} />
              <div className="flex flex-col gap-2">
                <p className="text-xs text-fg-subtle">{d.match_reason} · {ago(d.created_at)}</p>
                <button className="btn-primary btn-sm" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: d.id, decision: "SAME_PERSON" })}>Same person: link</button>
                <button className="btn-secondary btn-sm" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: d.id, decision: "DIFFERENT_PERSON" })}>Different person</button>
              </div>
            </div>
          ))}
        </Panel>
      )}
      {!!held.data?.length && (
        <Panel title="Exits held by the safety valve" hint="The app sent more exits in 24 hours than this company allows. Check each with HR before releasing it.">
          <table className="tbl">
            <thead><tr><th>Employee</th><th>Last working day</th><th>Requested</th><th className="w-px" /></tr></thead>
            <tbody>
              {held.data.map((h) => (
                <tr key={h.id}>
                  <td><p className="text-fg">{h.employee_name}</p><p className="font-mono text-[11px] text-fg-subtle">{h.employee_code} · {h.external_id}</p></td>
                  <td>{h.last_working_day ?? "—"}</td>
                  <td className="text-xs">{when(h.requested_at)}</td>
                  <td className="whitespace-nowrap text-right">
                    <button className="btn-primary btn-sm mr-2" disabled={decide.isPending} onClick={() => decide.mutate({ id: h.id, decision: "RELEASE" })}>Release</button>
                    <button className="btn-ghost btn-sm text-danger" disabled={decide.isPending} onClick={() => decide.mutate({ id: h.id, decision: "REJECT" })}>Reject</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {!!notLinked.data?.length && (
        <Panel title="Hired in HRMS, not linked by the app" hint="Announced to the app over 24 hours ago with no link yet. Usually the app's poller or its import of new joiners has stopped.">
          <table className="tbl">
            <thead><tr><th>Employee</th><th>Hire date</th><th>Announced</th></tr></thead>
            <tbody>
              {notLinked.data.map((n) => (
                <tr key={n.employment_id}>
                  <td><p className="text-fg">{n.employee_name}</p><p className="font-mono text-[11px] text-fg-subtle">{n.employee_code}</p></td>
                  <td>{n.hire_date}</td>
                  <td className="text-xs">{ago(n.announced_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}

function appSide(d: Duplicate): Record<string, string> {
  const r = (d.app_record ?? {}) as Record<string, unknown>;
  const name = [r.first_name, r.last_name].filter(Boolean).join(" ");
  return {
    Name: name || "—",
    "Date of birth": (r.date_of_birth as string) ?? "—",
    Email: (r.email as string) ?? "—",
    Code: (r.employee_code as string) ?? "—",
  };
}

function Side({ title, record }: { title: string; record: Record<string, string> }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="mb-2 font-mono text-[11px] text-fg-subtle">{title}</p>
      <dl className="space-y-1 text-sm">
        {Object.entries(record).map(([k, v]) => (
          <div key={k} className="flex gap-2"><dt className="w-28 shrink-0 text-fg-subtle">{k}</dt><dd className="text-fg">{v}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function Panel({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line px-5 py-3">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        <p className="text-xs text-fg-subtle">{hint}</p>
      </div>
      {children}
    </div>
  );
}
