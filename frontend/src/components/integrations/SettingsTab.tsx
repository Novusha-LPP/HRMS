import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Eye, Pencil, Send, Trash2, TriangleAlert } from "lucide-react";
import { integrationsApi } from "../../api/integrations";
import type { Catalog, ConnectedApp, IntegrationSettings, Owner, Preview, Profile } from "../../api/integrations";
import { orgApi } from "../../api/org";
import { Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { humanizeEvent, when } from "./shared";

type Json = Record<string, unknown>;

const OWNER_LABEL: Record<Owner, string> = { APP: "App", HRMS: "HRMS", SHARED: "Shared", NOT_SYNCED: "Not synced" };

function isObject(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Lay a partial override over a full document (lists replace, objects merge), as the server does. */
function merge(base: Json, over: Json): Json {
  const out: Json = structuredClone(base);
  for (const [k, v] of Object.entries(over)) {
    out[k] = isObject(v) && isObject(out[k]) ? merge(out[k] as Json, v) : structuredClone(v);
  }
  return out;
}

/** What `next` changes relative to `base`: the partial document a company override stores. */
function diff(next: Json, base: Json): Json {
  const out: Json = {};
  for (const [k, v] of Object.entries(next)) {
    if (isObject(v) && isObject(base[k])) {
      const inner = diff(v, base[k] as Json);
      if (Object.keys(inner).length) out[k] = inner;
    } else if (JSON.stringify(v) !== JSON.stringify(base[k])) {
      out[k] = v;
    }
  }
  return out;
}

function paths(doc: Json, prefix = ""): string[] {
  return Object.entries(doc).flatMap(([k, v]) =>
    isObject(v) ? paths(v, `${prefix}${k}.`) : [`${prefix}${k}`]);
}

/** Per-company, versioned settings for one app: draft, preview, publish from a date. */
export function SettingsTab({ app }: { app: ConnectedApp }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [company, setCompany] = useState("");
  const catalog = useQuery({ queryKey: ["integrations", "catalog"], queryFn: () => integrationsApi.catalog() });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const locations = useQuery({ queryKey: ["locations"], queryFn: () => orgApi.listLocations() });
  const scopeKey = ["integrations", app.id, "settings", company || "default"];
  const effective = useQuery({ queryKey: scopeKey, queryFn: () => integrationsApi.settings(app.id, company || null) });
  const groupDefault = useQuery({
    queryKey: ["integrations", app.id, "settings", "default"],
    queryFn: () => integrationsApi.settings(app.id, null),
    enabled: !!company,
  });
  const versions = useQuery({
    queryKey: ["integrations", app.id, "profiles", company || "default"],
    queryFn: () => integrationsApi.profiles(app.id, company || null),
  });
  const draft = versions.data?.find((p) => p.status === "DRAFT") ?? null;
  const base = (company ? groupDefault.data?.settings : null) as Json | null | undefined;

  const [form, setForm] = useState<Json | null>(null);
  const [formFor, setFormFor] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [publishOn, setPublishOn] = useState(format(new Date(), "yyyy-MM-dd"));

  // The document being edited: the draft (over the group default, for a company), else what is in force.
  const loaded: Json | null = useMemo(() => {
    if (!effective.data) return null;
    if (!draft) return effective.data.settings as unknown as Json;
    if (company) return base ? merge(base, draft.settings as Json) : null;
    return merge(effective.data.settings as unknown as Json, draft.settings as Json);
  }, [effective.data, draft, company, base]);
  const formKey = `${company}|${draft?.id ?? "live"}|${draft?.version ?? ""}`;
  if (loaded && formFor !== formKey) {
    setForm(structuredClone(loaded));
    setFormFor(formKey);
    setPreview(null);
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ["integrations", app.id] });
  const documentToSave = (): Json => (company && base ? diff(form!, base) : form!);

  const start = useMutation({
    mutationFn: (preset?: string) => integrationsApi.createProfile(app.id, { legal_entity_id: company || null, preset }),
    onSuccess: () => invalidate(),
    onError: (e) => toast.error("Couldn’t start a draft", errorMessage(e)),
  });
  const save = useMutation({
    mutationFn: () => integrationsApi.updateProfile(draft!.id, documentToSave() as Partial<IntegrationSettings>),
    onSuccess: () => { invalidate(); toast.success("Draft saved"); },
    onError: (e) => toast.error("Couldn’t save the draft", errorMessage(e)),
  });
  const runPreview = useMutation({
    mutationFn: async () => {
      await integrationsApi.updateProfile(draft!.id, documentToSave() as Partial<IntegrationSettings>);
      return integrationsApi.previewProfile(draft!.id);
    },
    onSuccess: (p) => { setPreview(p); invalidate(); },
    onError: (e) => toast.error("Couldn’t preview", errorMessage(e)),
  });
  const publish = useMutation({
    mutationFn: async () => {
      await integrationsApi.updateProfile(draft!.id, documentToSave() as Partial<IntegrationSettings>);
      return integrationsApi.publishProfile(draft!.id, publishOn);
    },
    onSuccess: (p) => {
      invalidate();
      toast.success(`Version ${p.version} published`, `In force from ${p.effective_from}`);
    },
    onError: (e) => toast.error("Couldn’t publish", errorMessage(e)),
  });
  const discard = useMutation({
    mutationFn: () => integrationsApi.discardProfile(draft!.id),
    onSuccess: () => { invalidate(); toast.success("Draft discarded"); },
    onError: (e) => toast.error("Couldn’t discard", errorMessage(e)),
  });

  if (effective.isError) return <Notice title="Couldn’t load the settings">{errorMessage(effective.error)}</Notice>;
  const cat = catalog.data;
  if (!effective.data || !cat || !form) return <Skeleton className="h-96 rounded-xl" />;

  const editing = !!draft;
  const changed = company && base ? new Set(paths(diff(form, base))) : new Set<string>();
  const set = (path: string, value: unknown) => {
    const next = structuredClone(form);
    const keys = path.split(".");
    let node = next as Json;
    for (const k of keys.slice(0, -1)) node = node[k] as Json;
    node[keys[keys.length - 1]] = value;
    setForm(next);
    setPreview(null);
  };
  const s = form as unknown as IntegrationSettings;
  const two = app.kind === "TWO_WAY";
  const mark = (path: string) => (company && changed.has(path) ? <span className="badge badge-info ml-2">This company</span> : null);
  const warnings = preview?.warnings ?? effective.data.warnings;

  return (
    <div className="space-y-5">
      <div className="card flex flex-wrap items-end justify-between gap-4 p-4">
        <div className="min-w-[16rem]">
          <label className="label" htmlFor="settings-scope">Settings for</label>
          <select id="settings-scope" className="input" value={company} onChange={(e) => { setCompany(e.target.value); setFormFor(null); }}>
            <option value="">All companies (group default)</option>
            {entities.data?.map((le) => <option key={le.id} value={le.id}>{le.name} (override)</option>)}
          </select>
        </div>
        {editing ? (
          <div className="flex flex-wrap items-end gap-2">
            <span className="badge badge-warning">Draft v{draft!.version}</span>
            <button className="btn-secondary" onClick={() => save.mutate()} disabled={save.isPending}>Save draft</button>
            <button className="btn-secondary" onClick={() => runPreview.mutate()} disabled={runPreview.isPending}><Eye size={14} /> Preview</button>
            <div>
              <label className="label" htmlFor="publish-on">From</label>
              <input id="publish-on" type="date" className="input" value={publishOn} min={format(new Date(), "yyyy-MM-dd")} onChange={(e) => setPublishOn(e.target.value)} />
            </div>
            <button className="btn-primary" onClick={() => publish.mutate()} disabled={publish.isPending}><Send size={14} /> Publish</button>
            <button className="btn-ghost text-danger" onClick={() => discard.mutate()} disabled={discard.isPending}><Trash2 size={14} /> Discard</button>
          </div>
        ) : (
          <button className="btn-primary" onClick={() => start.mutate(undefined)} disabled={start.isPending}><Pencil size={14} /> Change settings</button>
        )}
      </div>

      {company && !editing && (
        <p className="text-sm text-fg-muted">
          This company follows the group default except where marked. {effective.data.overridden.length ? `${effective.data.overridden.length} setting(s) overridden.` : "Nothing is overridden yet."}
        </p>
      )}
      {warnings.length > 0 && (
        <Notice title="These settings contradict each other">
          <ul className="list-disc pl-5">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Notice>
      )}
      {preview && <PreviewPanel preview={preview} labels={fieldLabels(cat)} />}

      <fieldset disabled={!editing} className="space-y-5">
        {two && (
          <Section title="Who owns each field" hint="An app-owned field is locked in HRMS (HR may override it if allowed below). A shared field takes the most recent change from either side.">
            <div className="mb-3 flex flex-wrap gap-2">
              {cat.presets.map((p) => (
                <button key={p.id} type="button" className="btn-secondary btn-sm" title={p.description}
                  onClick={() => set("field_ownership", { ...p.field_ownership })}>{p.label}</button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Field</th><th>Owner</th></tr></thead>
                <tbody>
                  {cat.fields.filter((f) => f.ownable).map((f) => (
                    <tr key={f.field}>
                      <td className="text-fg">{f.label}{mark(`field_ownership.${f.field}`)}</td>
                      <td>
                        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={f.label}>
                          {(Object.keys(OWNER_LABEL) as Owner[]).map((o) => {
                            const current = (s.field_ownership[f.field] ?? "HRMS") === o;
                            return (
                              <button key={o} type="button" role="radio" aria-checked={current}
                                className={`btn-sm rounded-md border px-2 py-1 text-xs ${current ? "border-brand-500 bg-brand-500/10 text-fg" : "border-line text-fg-muted"}`}
                                onClick={() => set(`field_ownership.${f.field}`, o)}>{OWNER_LABEL[o]}</button>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Row>
              <Choice label="When HR edits an app-owned field" path="hr_override" value={s.hr_override} set={set} mark={mark}
                options={{ WITH_REASON: "Allowed with a reason (recorded)", WITH_APPROVAL: "Allowed with a reason, after approval", NOT_ALLOWED: "Not allowed" }} />
              <Choice label="When the app sends a field it doesn't own" path="inbound_unowned" value={s.inbound_unowned} set={set} mark={mark}
                options={{ IGNORE: "Ignore it, with a warning", REJECT: "Refuse the call" }} />
            </Row>
          </Section>
        )}

        {two && (
          <Section title="Where people are hired, moved and exited" hint="Both = either system. App only = HRMS screens are switched off for it.">
            <Row>
              {(["hire", "job_change", "exit", "rehire"] as const).map((op) => (
                <Choice key={op} label={{ hire: "Hiring", job_change: "Job changes", exit: "Exits", rehire: "Rehires" }[op]}
                  path={`lifecycle.${op}`} value={s.lifecycle[op]} set={set} mark={mark}
                  options={{ BOTH: "Both", APP: `${app.code} only`, HRMS: "HRMS only" }} />
              ))}
            </Row>
          </Section>
        )}

        {two && (
          <Section title="Matching and values" hint="How records from the app are matched to HRMS employees and HRMS departments, locations and designations.">
            <Row>
              <Choice label="Link an existing HRMS employee automatically when" path="matching" value={s.matching} set={set} mark={mark}
                options={{ CODE_NAME_DOB: "Code, name and date of birth (or email) match", CODE_EMAIL: "Code and email match", NEVER: "Never: always ask HR" }} />
              <Choice label="A value HRMS doesn't know" path="unknown_values" value={s.unknown_values} set={set} mark={mark}
                options={{ REJECT: "Refuse it and list it for mapping", CREATE: "Create it in HRMS" }} />
              <div>
                <label className="label">Default location{mark("default_location_id")}</label>
                <select className="input" value={s.default_location_id ?? ""} onChange={(e) => set("default_location_id", e.target.value || null)}>
                  <option value="">None (the app must send one)</option>
                  {locations.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </div>
            </Row>
          </Section>
        )}

        {two && (
          <Section title="Logins for employees the app creates">
            <Row>
              <Choice label="Password" path="logins.password_source" value={s.logins.password_source} set={set} mark={mark}
                options={{ APP_THEN_DEFAULT: "The app's password if sent, else the default", DEFAULT: "Always the default pattern", NONE: "No HRMS password (through the app only)" }} />
              <div>
                <label className="label">Default password pattern{mark("logins.default_pattern")}</label>
                <input className="input font-mono" value={s.logins.default_pattern} onChange={(e) => set("logins.default_pattern", e.target.value)} />
                <p className="mt-1 text-xs text-fg-subtle">Use {"{FirstName}"}, {"{LastName}"} or {"{EmployeeCode}"}.</p>
              </div>
              <Toggle label="Must change it at the first direct sign-in" checked={s.logins.force_change} onChange={(v) => set("logins.force_change", v)} marker={mark("logins.force_change")} />
            </Row>
          </Section>
        )}

        {two && (
          <Section title="Self-service through the app" hint="What employees can do from inside the app's screens. HR and admin work always needs HRMS.">
            <div className="grid gap-2 sm:grid-cols-3">
              {(["punch", "attendance", "corrections", "leave", "profile_edit", "approvals"] as const).map((k) => (
                <Toggle key={k} label={{ punch: "Punch in and out", attendance: "See attendance", corrections: "Request corrections", leave: "Leave", profile_edit: "Edit own profile", approvals: "Managers approve" }[k]}
                  checked={s.self_service[k]} onChange={(v) => set(`self_service.${k}`, v)} marker={mark(`self_service.${k}`)} />
              ))}
            </div>
            <Row>
              <NumberField label="Session length (minutes)" value={s.self_service.session_minutes} min={5} max={480}
                onChange={(v) => set("self_service.session_minutes", v)} marker={mark("self_service.session_minutes")} />
            </Row>
          </Section>
        )}

        {two && (
          <Section title="Exit safety valve" hint="Exits beyond the limit in 24 hours wait for HR, so a faulty job or a stolen key can't lock everyone out.">
            <Row>
              <NumberField label="Most exits per day" value={s.safety.max_exits_per_day} min={1} max={100000}
                onChange={(v) => set("safety.max_exits_per_day", v)} marker={mark("safety.max_exits_per_day")} />
              <NumberField label="Or % of headcount" value={s.safety.max_exit_percent} min={0.1} max={100} step={0.1}
                onChange={(v) => set("safety.max_exit_percent", v)} marker={mark("safety.max_exit_percent")} />
              <Choice label="Over the limit" path="safety.over_limit" value={s.safety.over_limit} set={set} mark={mark}
                options={{ HOLD: "Hold for HR", REJECT: "Refuse" }} />
            </Row>
          </Section>
        )}

        <Section title="What the app receives" hint="Events and fields it gets from the events feed and read endpoints. KYC, bank details and salary are never sent.">
          <p className="label">Events</p>
          <div className="mb-3 grid gap-2 sm:grid-cols-3">
            {cat.events.map((ev) => (
              <Toggle key={ev} label={humanizeEvent(ev)} checked={s.outbound.events.includes(ev)} marker={null}
                onChange={(v) => set("outbound.events", v ? [...s.outbound.events, ev] : s.outbound.events.filter((x) => x !== ev))} />
            ))}
          </div>
          <p className="label">Data{mark("outbound.data_classes")}</p>
          <div className="mb-3 grid gap-2 sm:grid-cols-4">
            {cat.data_classes.map((dc) => (
              <Toggle key={dc} label={{ BASIC: "Basic (name, job)", CONTACT: "Contact", PERSONAL: "Personal (birth date, gender)", ATTENDANCE_LEAVE: "Attendance and leave" }[dc]}
                checked={s.outbound.data_classes.includes(dc)} marker={null}
                onChange={(v) => set("outbound.data_classes", v ? [...s.outbound.data_classes, dc] : s.outbound.data_classes.filter((x) => x !== dc))} />
            ))}
          </div>
          <Row>
            <Choice label="A new joiner reaches the app" path="outbound.timing.mode" value={s.outbound.timing.mode} set={set} mark={mark}
              options={{ ON_SAVE: "When the hire is saved", DAYS_BEFORE_JOIN: "Some days before joining", ON_JOIN: "On the joining date" }} />
            {s.outbound.timing.mode === "DAYS_BEFORE_JOIN" && (
              <NumberField label="Days before joining" value={s.outbound.timing.days} min={0} max={90}
                onChange={(v) => set("outbound.timing.days", v)} marker={mark("outbound.timing.days")} />
            )}
            <NumberField label="Keep the sync log (days)" value={s.retention_days} min={90} max={1095}
              onChange={(v) => set("retention_days", v)} marker={mark("retention_days")} />
          </Row>
        </Section>
      </fieldset>

      <Versions versions={versions.data ?? []} />
    </div>
  );
}

function fieldLabels(catalog: Catalog) {
  return Object.fromEntries(catalog.fields.map((f) => [f.field, f.label]));
}

function PreviewPanel({ preview, labels }: { preview: Preview; labels: Record<string, string> }) {
  const name = (f: string) => labels[f] ?? f;
  return (
    <div className="card space-y-2 border-info/40 p-4 text-sm">
      <h3 className="font-semibold text-fg">If you publish this</h3>
      <ul className="list-disc space-y-1 pl-5 text-fg-muted">
        <li>{preview.linked_employees_affected} linked employee(s) are covered by these settings.</li>
        {preview.fields_becoming_locked.length > 0 && <li>Becomes locked in HRMS: {preview.fields_becoming_locked.map(name).join(", ")}.</li>}
        {preview.fields_becoming_unlocked.length > 0 && <li>Becomes editable in HRMS: {preview.fields_becoming_unlocked.map(name).join(", ")}.</li>}
        {preview.employees_with_recent_hr_edits_to_newly_locked_fields > 0 && (
          <li className="text-warning"><TriangleAlert size={13} className="mr-1 inline" />
            {preview.employees_with_recent_hr_edits_to_newly_locked_fields} employee(s) had these fields changed in HRMS in the last 30 days; the app's next update will replace those changes.</li>
        )}
        {preview.events_switched_on.length > 0 && <li>Events switched on: {preview.events_switched_on.map(humanizeEvent).join(", ")}.</li>}
        {preview.events_switched_off.length > 0 && <li>Events switched off: {preview.events_switched_off.map(humanizeEvent).join(", ")}.</li>}
        {Object.entries(preview.lifecycle).map(([op, c]) => <li key={op}>{op.replace("_", " ")}: {c.from} → {c.to}</li>)}
        {!preview.fields_becoming_locked.length && !preview.fields_becoming_unlocked.length && !preview.events_switched_on.length
          && !preview.events_switched_off.length && !Object.keys(preview.lifecycle).length && <li>No change to ownership, events or where people are hired.</li>}
      </ul>
    </div>
  );
}

function Versions({ versions }: { versions: Profile[] }) {
  if (!versions.length) return <p className="text-xs text-fg-subtle">No versions yet: the built-in defaults apply.</p>;
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line px-5 py-3 text-sm font-semibold text-fg">Versions</div>
      <table className="tbl">
        <thead><tr><th>Version</th><th>Status</th><th>In force from</th><th>Published</th></tr></thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td className="text-fg">v{v.version}{v.note && <span className="block text-xs text-fg-subtle">{v.note}</span>}</td>
              <td><span className={`badge ${v.status === "PUBLISHED" ? "badge-success" : v.status === "DRAFT" ? "badge-warning" : "badge-neutral"}`}>{v.status.toLowerCase()}</span></td>
              <td>{v.effective_from ?? "—"}</td>
              <td>{when(v.published_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="card space-y-3 p-5">
      <div>
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {hint && <p className="text-xs text-fg-subtle">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{children}</div>;
}

function Choice({ label, path, value, options, set, mark }: {
  label: string; path: string; value: string; options: Record<string, string>;
  set: (path: string, value: unknown) => void; mark: (path: string) => ReactNode;
}) {
  return (
    <div>
      <label className="label">{label}{mark(path)}</label>
      <select className="input" value={value} onChange={(e) => set(path, e.target.value)}>
        {Object.entries(options).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

function Toggle({ label, checked, onChange, marker }: { label: string; checked: boolean; onChange: (v: boolean) => void; marker: ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-sm text-fg">
      <input type="checkbox" className="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}{marker}
    </label>
  );
}

function NumberField({ label, value, min, max, step = 1, onChange, marker }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; marker: ReactNode;
}) {
  return (
    <div>
      <label className="label">{label}{marker}</label>
      <input type="number" className="input" value={value} min={min} max={max} step={step}
        onChange={(e) => onChange(e.target.value === "" ? min : Number(e.target.value))} />
    </div>
  );
}
