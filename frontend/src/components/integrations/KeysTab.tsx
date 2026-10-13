import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { ApiKey, ApiKeyCreated, ConnectedApp } from "../../api/integrations";
import { orgApi } from "../../api/org";
import { Dialog, Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { ago, when } from "./shared";

const WRITE_SCOPES = ["employees.sync", "passwords.sync", "sessions.issue"];

/** The app's credentials. A key is shown once; two can be active, for switching without downtime. */
export function KeysTab({ app }: { app: ConnectedApp }) {
  const keys = useQuery({ queryKey: ["integrations", app.id, "keys"], queryFn: () => integrationsApi.keys(app.id) });
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const active = (keys.data ?? []).filter((k) => k.status === "ACTIVE");
  const disconnected = app.status === "DISCONNECTED";

  if (keys.isPending) return <Skeleton className="h-40 rounded-xl" />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-fg-muted">
          The app sends its key in the <code className="text-xs">X-API-Key</code> header (or as an OAuth client secret).
          A key only works on the integrations API, never on the rest of HRMS.
        </p>
        {!disconnected && (
          <button className="btn-primary" onClick={() => setCreating(true)} disabled={active.length >= 2}
            title={active.length >= 2 ? "Revoke a key first: an app can have two active keys" : undefined}>
            <Plus size={15} /> Create a key
          </button>
        )}
      </div>
      {!keys.data?.length ? (
        <div className="card"><EmptyState icon={KeyRound} title="No keys yet" description="Create a key and give it to the app's developers. It is shown only once." /></div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Key</th><th>Permissions</th><th className="hidden md:table-cell">Limits</th><th>Last used</th><th>Status</th><th className="w-px" /></tr></thead>
              <tbody>
                {keys.data.map((k) => (
                  <tr key={k.id}>
                    <td>
                      <p className="font-medium text-fg">{k.name}</p>
                      <p className="font-mono text-[11px] text-fg-subtle">{k.client_id}…</p>
                    </td>
                    <td><div className="flex max-w-xs flex-wrap gap-1">{k.scopes.map((s) => <span key={s} className="badge badge-neutral">{s}</span>)}</div></td>
                    <td className="hidden text-xs md:table-cell">
                      <p>{k.allowed_ips?.length ? k.allowed_ips.join(", ") : <span className="text-warning">Any address</span>}</p>
                      <p>{k.rate_limit_per_minute}/min · expires {k.expires_at ? when(k.expires_at) : "never"}</p>
                    </td>
                    <td className="text-xs">{ago(k.last_used_at)}{k.last_used_ip && <span className="block text-fg-subtle">{k.last_used_ip} · {k.calls_last_hour} calls in the last hour</span>}</td>
                    <td>
                      <span className={`badge ${k.status === "ACTIVE" ? "badge-success" : k.status === "EXPIRED" ? "badge-warning" : "badge-neutral"}`}>{k.status.toLowerCase()}</span>
                      {k.revoke_reason && <span className="block text-[11px] text-fg-subtle">{k.revoke_reason}</span>}
                    </td>
                    <td className="text-right">
                      {k.status === "ACTIVE" && <button className="btn-ghost btn-sm text-danger" onClick={() => setRevoking(k)}>Revoke</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <CreateKeySheet app={app} open={creating} onClose={() => setCreating(false)} onCreated={setCreated} />
      <ShowKeyOnce created={created} onClose={() => setCreated(null)} />
      <RevokeKeySheet app={app} apiKey={revoking} onClose={() => setRevoking(null)} />
    </div>
  );
}

function CreateKeySheet({ app, open, onClose, onCreated }: {
  app: ConnectedApp; open: boolean; onClose: () => void; onCreated: (k: ApiKeyCreated) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const catalog = useQuery({ queryKey: ["integrations", "catalog"], queryFn: () => integrationsApi.catalog(), enabled: open });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities(), enabled: open });
  const two = app.kind === "TWO_WAY";
  const defaults = two
    ? ["employees.sync", "employees.read", "sessions.issue", "org.read", "events.read"]
    : ["employees.read", "org.read", "events.read"];
  const [name, setName] = useState("App server");
  const [scopes, setScopes] = useState<string[]>(defaults);
  const [ips, setIps] = useState("");
  const [entityIds, setEntityIds] = useState<string[]>([]);
  const [days, setDays] = useState("365");
  const [rate, setRate] = useState("600");
  const create = useMutation({
    mutationFn: () => integrationsApi.createKey(app.id, {
      name: name.trim(),
      scopes,
      allowed_ips: ips.trim() ? ips.split(/[\s,]+/).filter(Boolean) : null,
      legal_entity_ids: entityIds.length ? entityIds : null,
      expires_in_days: days ? Number(days) : null,
      rate_limit_per_minute: Number(rate),
    }),
    onSuccess: (k) => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
      onCreated(k);
    },
    onError: (e) => toast.error("Couldn’t create the key", errorMessage(e)),
  });
  const valid = name.trim() && scopes.length && /^\d+$/.test(rate) && (!days || /^\d+$/.test(days));
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid && !create.isPending) create.mutate(); };
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <Sheet open={open} onClose={onClose} title={`New key for ${app.name}`} className="max-w-lg"
      description="The key is shown once, when you create it."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="create-key" disabled={!valid || create.isPending}>{create.isPending ? "Creating…" : "Create key"}</button>
      </>}>
      <form id="create-key" onSubmit={submit} className="space-y-5">
        <div>
          <label className="label" htmlFor="key-name">Name</label>
          <input id="key-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <fieldset className="space-y-2">
          <legend className="label">What the key may do</legend>
          {catalog.data?.scopes.filter((s) => two || !WRITE_SCOPES.includes(s.scope)).map((s) => (
            <label key={s.scope} className="flex items-start gap-2 text-sm text-fg">
              <input type="checkbox" className="checkbox mt-0.5" checked={scopes.includes(s.scope)} onChange={() => setScopes(toggle(scopes, s.scope))} />
              <span><span className="font-mono text-xs">{s.scope}</span><span className="block text-xs text-fg-subtle">{s.description}</span></span>
            </label>
          ))}
        </fieldset>
        <div>
          <label className="label" htmlFor="key-ips">Allowed addresses</label>
          <textarea id="key-ips" className="input min-h-[4rem] font-mono text-xs" value={ips} placeholder="203.0.113.10, 10.20.0.0/16"
            onChange={(e) => setIps(e.target.value)} />
          <p className="mt-1 text-xs text-fg-subtle">The app server's addresses or ranges. Strongly recommended: leave empty only while testing.</p>
        </div>
        <fieldset className="space-y-2">
          <legend className="label">Companies</legend>
          <p className="text-xs text-fg-subtle">Leave all unticked for every company.</p>
          {entities.data?.map((le) => (
            <label key={le.id} className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" className="checkbox" checked={entityIds.includes(le.id)} onChange={() => setEntityIds(toggle(entityIds, le.id))} />
              {le.name}
            </label>
          ))}
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="key-days">Expires after (days)</label>
            <input id="key-days" className="input" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="key-rate">Requests per minute</label>
            <input id="key-rate" className="input" inputMode="numeric" value={rate} onChange={(e) => setRate(e.target.value)} />
          </div>
        </div>
      </form>
    </Sheet>
  );
}

function ShowKeyOnce({ created, onClose }: { created: ApiKeyCreated | null; onClose: () => void }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const [stored, setStored] = useState(false);
  const close = () => { setCopied(false); setStored(false); onClose(); };
  const done = copied || stored;
  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      toast.success("Key copied");
    } catch {
      toast.error("Couldn’t copy", "Select the key and copy it yourself.");
    }
  };
  return (
    <Dialog open={!!created} onClose={() => { if (done) close(); }} className="max-w-lg">
      {created && (
        <div className="space-y-4 p-6">
          <h2 className="text-[15px] font-semibold text-fg">Copy the key now</h2>
          <p className="text-sm text-fg-muted">This is the only time it is shown. Store it in the app server's secret store; HRMS keeps only a fingerprint.</p>
          <div className="flex items-center gap-2 rounded-lg border border-line bg-muted/40 p-3">
            <code className="min-w-0 flex-1 select-all break-all text-xs text-fg">{created.key}</code>
            <button className="btn-secondary btn-sm" onClick={copy}><Copy size={13} /> Copy</button>
          </div>
          <p className="text-xs text-fg-subtle">OAuth client id: <code>{created.client_id}</code> (the client secret is the whole key).</p>
          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" className="checkbox" checked={stored} onChange={(e) => setStored(e.target.checked)} />
              I've stored the key somewhere safe
            </label>
            <button className="btn-primary" disabled={!done} onClick={close}>Done</button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function RevokeKeySheet({ app, apiKey, onClose }: { app: ConnectedApp; apiKey: ApiKey | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const revoke = useMutation({
    mutationFn: () => integrationsApi.revokeKey(app.id, apiKey!.id, reason.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Key revoked", "It stopped working at once, with its tokens and sessions.");
      setReason("");
      onClose();
    },
    onError: (e) => toast.error("Couldn’t revoke the key", errorMessage(e)),
  });
  return (
    <Sheet open={!!apiKey} onClose={onClose} title={`Revoke ${apiKey?.name ?? "key"}?`}
      description="The key, its OAuth tokens and the employee sessions it issued stop working at once."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-danger" disabled={reason.trim().length < 3 || revoke.isPending} onClick={() => revoke.mutate()}>{revoke.isPending ? "Revoking…" : "Revoke key"}</button>
      </>}>
      <Notice title="Switching keys?">Create the new key first and let the app switch to it, so nothing stops.</Notice>
      <label className="label mt-4" htmlFor="revoke-reason">Reason</label>
      <input id="revoke-reason" className="input" value={reason} placeholder="e.g. Rotated to a new key" onChange={(e) => setReason(e.target.value)} />
    </Sheet>
  );
}
