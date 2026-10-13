import { useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cable, Lock, Pause, Play, Plus, Unplug } from "lucide-react";
import { integrationsApi } from "../api/integrations";
import type { AppKind, ConnectedApp } from "../api/integrations";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { ConfirmDialog, Sheet } from "../components/ui/Overlay";
import { useToast, errorMessage } from "../components/ui/Toast";
import { AppStatusBadge } from "../components/integrations/badges";
import { KIND_HINT, KIND_LABEL, ago } from "../components/integrations/shared";
import { OverviewTab } from "../components/integrations/OverviewTab";
import { KeysTab } from "../components/integrations/KeysTab";
import { SettingsTab } from "../components/integrations/SettingsTab";
import { MappingsTab } from "../components/integrations/MappingsTab";
import { SyncLogTab } from "../components/integrations/SyncLogTab";
import { ReviewTab } from "../components/integrations/ReviewTab";

type AppTab = "overview" | "keys" | "settings" | "mappings" | "log" | "review";
const TABS: AppTab[] = ["overview", "keys", "settings", "mappings", "log", "review"];

/**
 * Settings → Integrations: the ERP, CRM and other systems connected to HRMS, their keys, the
 * rules each follows (per company, with versions), and what needs HR's attention.
 */
export function IntegrationsPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const has = (p: string) => !!user && (user.permissions.includes("*") || user.permissions.includes(p));
  const canManage = has("integrations.manage");
  const apps = useQuery({ queryKey: ["integrations", "apps"], queryFn: () => integrationsApi.apps(), enabled: canManage });
  const [connecting, setConnecting] = useState(false);

  if (!user) return null;
  if (!canManage) {
    return (
      <>
        <PageHeader title="Integrations" />
        <div className="card">
          <EmptyState icon={Lock} title="Integrations are for the administrator"
            description="Connecting other systems gives them access to employee data, so only the company's administrator can manage it." />
        </div>
      </>
    );
  }

  const list = apps.data ?? [];
  const selected = list.find((a) => a.id === params.get("app"))
    ?? list.find((a) => a.kind === "TWO_WAY" && a.status !== "DISCONNECTED")
    ?? list.find((a) => a.status !== "DISCONNECTED")
    ?? list[0];
  const requested = params.get("tab") as AppTab | null;
  const tab: AppTab = requested && TABS.includes(requested) ? requested : "overview";
  const go = (app: ConnectedApp, next: AppTab = "overview") => setParams({ app: app.id, ...(next !== "overview" ? { tab: next } : {}) }, { replace: true });

  return (
    <>
      <PageHeader
        title="Integrations"
        description="Your ERP, CRM and other systems connected to HRMS: their keys, what each may do and see, and the log of everything they send."
        actions={<button className="btn-primary" onClick={() => setConnecting(true)}><Plus size={15} /> Connect an app</button>}
      />
      {apps.isError && <Notice title="Couldn’t load the connected apps">{errorMessage(apps.error)}</Notice>}
      {apps.isPending ? <Skeleton className="h-40 rounded-xl" /> : !list.length ? (
        <div className="card">
          <EmptyState icon={Cable} title="No apps connected yet"
            description="Connect your ERP or CRM so new joiners, changes and exits flow between it and HRMS, and employees can punch and see their own data from inside it."
            action={<button className="btn-primary" onClick={() => setConnecting(true)}><Plus size={15} /> Connect an app</button>} />
        </div>
      ) : (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {list.map((app) => (
              <button key={app.id} type="button" onClick={() => go(app)}
                className={`card p-4 text-left transition hover:border-brand-400 ${selected?.id === app.id ? "ring-2 ring-brand-500" : ""}`}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-fg">{app.name}</p>
                    <p className="font-mono text-xs text-fg-subtle">{app.code} · {KIND_LABEL[app.kind]}</p>
                  </div>
                  <AppStatusBadge status={app.status} />
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div><dt className="text-fg-subtle">Linked</dt><dd className="font-medium text-fg">{app.linked_employees}</dd></div>
                  <div><dt className="text-fg-subtle">Keys</dt><dd className="font-medium text-fg">{app.active_keys}</dd></div>
                  <div><dt className="text-fg-subtle">Last call</dt><dd className="font-medium text-fg">{ago(app.last_request_at)}</dd></div>
                </dl>
              </button>
            ))}
          </div>
          {selected && (
            <AppDetail key={selected.id} app={selected} tab={tab} onTab={(t) => go(selected, t)} />
          )}
        </>
      )}
      <ConnectAppSheet open={connecting} onClose={() => setConnecting(false)} onCreated={(app) => go(app, "keys")} />
    </>
  );
}

function AppDetail({ app, tab, onTab }: { app: ConnectedApp; tab: AppTab; onTab: (t: AppTab) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [disconnecting, setDisconnecting] = useState(false);
  const review = useQuery({
    queryKey: ["integrations", app.id, "review-counts"],
    queryFn: async () => {
      const [d, h, n] = await Promise.all([
        integrationsApi.duplicates(app.id), integrationsApi.heldExits(app.id), integrationsApi.notLinked(app.id),
      ]);
      return d.length + h.length + n.length;
    },
  });
  const setStatus = useMutation({
    mutationFn: (status: "ACTIVE" | "PAUSED" | "DISCONNECTED") => integrationsApi.updateApp(app.id, { status }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success(a.status === "PAUSED" ? "App paused" : a.status === "ACTIVE" ? "App resumed" : "App disconnected", a.name);
      setDisconnecting(false);
    },
    onError: (e) => toast.error("Couldn’t change the app", errorMessage(e)),
  });
  const two = app.kind === "TWO_WAY";
  const disconnected = app.status === "DISCONNECTED";

  return (
    <section aria-label={app.name}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-fg">{app.name}</h2>
          <p className="text-sm text-fg-muted">{KIND_HINT[app.kind]}</p>
        </div>
        {!disconnected && (
          <div className="flex gap-2">
            {app.status === "ACTIVE" ? (
              <button className="btn-secondary" onClick={() => setStatus.mutate("PAUSED")} disabled={setStatus.isPending}><Pause size={14} /> Pause</button>
            ) : (
              <button className="btn-secondary" onClick={() => setStatus.mutate("ACTIVE")} disabled={setStatus.isPending}><Play size={14} /> Resume</button>
            )}
            <button className="btn-ghost text-danger" onClick={() => setDisconnecting(true)}><Unplug size={14} /> Disconnect</button>
          </div>
        )}
      </div>
      {app.status === "PAUSED" && (
        <div className="mb-4"><Notice title="This app is paused">Its calls are refused. Events keep queuing and are there when you resume it.</Notice></div>
      )}
      <Tabs<AppTab>
        className="mb-6"
        value={tab}
        onChange={onTab}
        items={[
          { value: "overview", label: "Overview" },
          { value: "keys", label: "Keys" },
          { value: "settings", label: "Settings" },
          ...(two ? [{ value: "mappings" as AppTab, label: "Mappings" }] : []),
          { value: "log", label: "Sync log" },
          ...(two ? [{ value: "review" as AppTab, label: "Needs review", count: review.data || undefined }] : []),
        ]}
      />
      {tab === "overview" && <OverviewTab app={app} />}
      {tab === "keys" && <KeysTab app={app} />}
      {tab === "settings" && <SettingsTab app={app} />}
      {tab === "mappings" && two && <MappingsTab app={app} />}
      {tab === "log" && <SyncLogTab app={app} />}
      {tab === "review" && two && <ReviewTab app={app} />}
      <ConfirmDialog
        open={disconnecting}
        onClose={() => setDisconnecting(false)}
        onConfirm={() => setStatus.mutate("DISCONNECTED")}
        loading={setStatus.isPending}
        title={`Disconnect ${app.name}?`}
        description="Every key stops working at once and can't be restored. The sync log and links stay as history. To stop it temporarily, pause it instead."
        confirmLabel="Disconnect"
      />
    </section>
  );
}

function ConnectAppSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (app: ConnectedApp) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AppKind>("TWO_WAY");
  const valid = /^[A-Za-z][A-Za-z0-9_]{1,39}$/.test(code.trim()) && name.trim().length > 0;
  const create = useMutation({
    mutationFn: () => integrationsApi.createApp({ code: code.trim().toUpperCase(), name: name.trim(), kind }),
    onSuccess: (app) => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("App connected", "Now create a key for it.");
      setCode(""); setName(""); setKind("TWO_WAY");
      onClose();
      onCreated(app);
    },
    onError: (e) => toast.error("Couldn’t connect the app", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid && !create.isPending) create.mutate(); };
  return (
    <Sheet open={open} onClose={onClose} title="Connect an app"
      description="An app is one outside system. It gets its own keys, settings and log."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="connect-app" disabled={!valid || create.isPending}>{create.isPending ? "Connecting…" : "Connect"}</button>
      </>}>
      <form id="connect-app" onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
          <div>
            <label className="label" htmlFor="app-code">Code</label>
            <input id="app-code" className="input font-mono uppercase" value={code} placeholder="ERP" onChange={(e) => setCode(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="app-name">Name</label>
            <input id="app-name" className="input" value={name} placeholder="e.g. EXIM ERP" onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        <p className="text-xs text-fg-subtle">The code appears in logs, on punches made through the app, and on employees it manages.</p>
        <fieldset className="space-y-2">
          <legend className="label">What does it do?</legend>
          {(Object.keys(KIND_LABEL) as AppKind[]).map((k) => (
            <label key={k} className="flex items-start gap-2 text-sm text-fg">
              <input type="radio" name="app-kind" className="mt-0.5" checked={kind === k} onChange={() => setKind(k)} />
              <span><span className="font-medium">{KIND_LABEL[k]}</span><span className="block text-xs text-fg-subtle">{KIND_HINT[k]}</span></span>
            </label>
          ))}
        </fieldset>
      </form>
    </Sheet>
  );
}
