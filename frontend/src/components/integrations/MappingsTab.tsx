import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Shuffle, Trash2 } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { ConnectedApp, MappingKind } from "../../api/integrations";
import { orgApi } from "../../api/org";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { ago } from "./shared";

const KIND_LABEL: Record<MappingKind, string> = {
  LEGAL_ENTITY: "Company",
  DEPARTMENT: "Department",
  LOCATION: "Location",
  DESIGNATION: "Designation",
  ROLE: "Role",
};

interface Target { id: string; name: string }

function useTargets() {
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });
  const locations = useQuery({ queryKey: ["locations"], queryFn: () => orgApi.listLocations() });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs() });
  const entityName = (id: string | null) => entities.data?.find((e) => e.id === id)?.name;
  return (kind: MappingKind): Target[] => {
    switch (kind) {
      case "LEGAL_ENTITY": return (entities.data ?? []).map((e) => ({ id: e.id, name: e.name }));
      case "DEPARTMENT": return (units.data ?? []).filter((u) => u.type !== "DEPARTMENT_TEMPLATE")
        .map((u) => ({ id: u.id, name: `${u.name}${entityName(u.legal_entity_id) ? ` · ${entityName(u.legal_entity_id)}` : ""}` }));
      case "LOCATION": return (locations.data ?? []).map((l) => ({ id: l.id, name: l.name }));
      case "DESIGNATION": return (jobs.data ?? []).map((j) => ({ id: j.id, name: j.title }));
      case "ROLE": return [{ id: "EMPLOYEE", name: "Employee" }, { id: "MANAGER", name: "Manager" }];
    }
  };
}

/** The app's values mapped to HRMS records, and the values it sent that HRMS couldn't match. */
export function MappingsTab({ app }: { app: ConnectedApp }) {
  const mappings = useQuery({ queryKey: ["integrations", app.id, "mappings"], queryFn: () => integrationsApi.mappings(app.id) });
  const unmapped = useQuery({ queryKey: ["integrations", app.id, "unmapped"], queryFn: () => integrationsApi.unmapped(app.id) });
  const targets = useTargets();

  if (mappings.isPending || unmapped.isPending) return <Skeleton className="h-64 rounded-xl" />;
  return (
    <div className="space-y-5">
      <p className="max-w-3xl text-sm text-fg-muted">
        HRMS matches what the app sends by mapping first, then by exact code, then by exact name. Map anything spelt differently
        in the app (for example its <em>Ops</em> to HRMS's <em>Operations</em>). A role can map only to Employee or Manager.
      </p>
      {!!unmapped.data?.length && (
        <div className="card overflow-hidden">
          <div className="border-b border-line px-5 py-3">
            <h3 className="text-sm font-semibold text-fg">Unmapped values</h3>
            <p className="text-xs text-fg-subtle">The app sent these and HRMS refused them. Map each; the app's next retry then succeeds.</p>
          </div>
          <table className="tbl">
            <thead><tr><th>Kind</th><th>The app's value</th><th>Last seen</th><th>Map to</th></tr></thead>
            <tbody>
              {unmapped.data.map((u) => (
                <tr key={`${u.kind}:${u.value}`}>
                  <td>{KIND_LABEL[u.kind]}</td>
                  <td className="font-medium text-fg">{u.value} <span className="text-xs text-fg-subtle">({u.requests} calls)</span></td>
                  <td className="text-xs">{ago(u.last_seen)}</td>
                  <td><MapTo app={app} kind={u.kind} value={u.value} targets={targets(u.kind)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddMapping app={app} targets={targets} />
      {!mappings.data?.length ? (
        <div className="card"><EmptyState icon={Shuffle} title="No mappings" description="Values that match HRMS's codes or names exactly need none." /></div>
      ) : (
        <div className="card overflow-hidden">
          <table className="tbl">
            <thead><tr><th>Kind</th><th>The app's value</th><th /><th>HRMS</th><th className="w-px" /></tr></thead>
            <tbody>
              {mappings.data.map((m) => (
                <tr key={m.id}>
                  <td>{KIND_LABEL[m.kind]}</td>
                  <td className="font-medium text-fg">{m.external_value}</td>
                  <td><ArrowRight size={14} className="text-fg-subtle" /></td>
                  <td>{m.target_name ?? m.target_value}</td>
                  <td><DeleteMapping app={app} id={m.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function useCreateMapping(app: ConnectedApp, onDone?: () => void) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (v: { kind: MappingKind; value: string; target: string }) => integrationsApi.createMapping(app.id, {
      kind: v.kind,
      external_value: v.value,
      ...(v.kind === "ROLE" ? { target_value: v.target as "EMPLOYEE" | "MANAGER" } : { target_id: v.target }),
    }),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["integrations", app.id] });
      toast.success("Mapped", `${m.external_value} → ${m.target_name ?? m.target_value}`);
      onDone?.();
    },
    onError: (e) => toast.error("Couldn’t save the mapping", errorMessage(e)),
  });
}

function MapTo({ app, kind, value, targets }: { app: ConnectedApp; kind: MappingKind; value: string; targets: Target[] }) {
  const [target, setTarget] = useState("");
  const create = useCreateMapping(app);
  return (
    <div className="flex gap-2">
      <select className="input" value={target} onChange={(e) => setTarget(e.target.value)} aria-label={`Map ${value} to`}>
        <option value="">Choose…</option>
        {targets.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <button className="btn-primary btn-sm" disabled={!target || create.isPending} onClick={() => create.mutate({ kind, value, target })}>Map</button>
    </div>
  );
}

function AddMapping({ app, targets }: { app: ConnectedApp; targets: (k: MappingKind) => Target[] }) {
  const [kind, setKind] = useState<MappingKind>("DEPARTMENT");
  const [value, setValue] = useState("");
  const [target, setTarget] = useState("");
  const create = useCreateMapping(app, () => { setValue(""); setTarget(""); });
  return (
    <div className="card grid gap-3 p-4 sm:grid-cols-[10rem_1fr_1fr_auto] sm:items-end">
      <div>
        <label className="label" htmlFor="map-kind">Kind</label>
        <select id="map-kind" className="input" value={kind} onChange={(e) => { setKind(e.target.value as MappingKind); setTarget(""); }}>
          {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="map-value">The app's value</label>
        <input id="map-value" className="input" value={value} placeholder="e.g. Ops" onChange={(e) => setValue(e.target.value)} />
      </div>
      <div>
        <label className="label" htmlFor="map-target">HRMS</label>
        <select id="map-target" className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose…</option>
          {targets(kind).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      <button className="btn-primary" disabled={!value.trim() || !target || create.isPending}
        onClick={() => create.mutate({ kind, value: value.trim(), target })}>Add mapping</button>
    </div>
  );
}

function DeleteMapping({ app, id }: { app: ConnectedApp; id: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const remove = useMutation({
    mutationFn: () => integrationsApi.deleteMapping(app.id, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integrations", app.id] }),
    onError: (e) => toast.error("Couldn’t remove the mapping", errorMessage(e)),
  });
  return <button className="btn-ghost btn-sm" aria-label="Remove mapping" onClick={() => remove.mutate()} disabled={remove.isPending}><Trash2 size={13} /></button>;
}
