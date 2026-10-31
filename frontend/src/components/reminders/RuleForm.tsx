import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Cake, Eye, LogOut, PartyPopper, RotateCcw, Send, Trash2, UserPlus, X } from "lucide-react";
import {
  remindersApi,
  type Audience, type ReminderFrequency, type ReminderRule, type ReminderRuleInput, type ReminderTrigger,
} from "../../api/reminders";
import { orgApi } from "../../api/org";
import { FREQUENCIES, TRIGGERS, describeAudience, describeOffsets, describeRule, offsetsFor } from "../../lib/reminders";
import { ConfirmDialog, Sheet } from "../ui/Overlay";
import { Notice, Skeleton } from "../ui/Feedback";
import { Segmented } from "../ui/Tabs";
import { useToast, errorMessage } from "../ui/Toast";
import { WordingEditor } from "./WordingEditor";

const EVENT_ICON = { BIRTHDAY: Cake, WORK_ANNIVERSARY: PartyPopper, NEW_JOINER: UserPlus, EXIT: LogOut } as const;
const DAY_CHOICES = [0, 1, 2, 3, 5, 7, 14, 30];
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const hhmm = (time: string) => time.slice(0, 5);

const BLANK: ReminderRuleInput = {
  name: "", trigger: "BIRTHDAY", legal_entity_id: null, org_unit_id: null, frequency: "SAME_DAY", days_before: 3,
  custom_offsets: [], send_time: "09:00", notify_employee: false, notify_manager: false, notify_everyone: false,
  extra_emails: [], digest: true, subject: "", body_html: "", employee_subject: "", employee_body_html: "", is_active: true,
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

function Step({ n, title, hint, children }: { n: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/15 text-xs font-semibold text-accent" aria-hidden>{n}</span>
        <div>
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
          {hint && <p className="text-xs text-fg-subtle">{hint}</p>}
        </div>
      </div>
      <div className="space-y-3 sm:pl-9">{children}</div>
    </section>
  );
}

function Choice({ checked, onChange, title, help, type = "checkbox", disabled }: {
  checked: boolean; onChange: (v: boolean) => void; title: string; help: string; type?: "checkbox" | "radio"; disabled?: boolean;
}) {
  return (
    <label className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors ${checked ? "border-brand-500 bg-brand-500/5" : "border-line hover:bg-muted"} ${disabled ? "cursor-not-allowed opacity-60" : ""}`}>
      <input type={type} className="mt-0.5" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="block text-[13px] font-medium text-fg">{title}</span>
        <span className="block text-xs text-fg-subtle">{help}</span>
      </span>
    </label>
  );
}

/** Create or change a reminder: four short steps, a one-sentence summary, and a live preview. */
export function RuleForm({ rule, preset, onClose }: { rule?: ReminderRule; preset?: Partial<ReminderRuleInput>; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const initial = useMemo<ReminderRuleInput>(
    () => (rule ? { ...rule, send_time: hhmm(rule.send_time) } : { ...BLANK, ...preset }),
    [rule, preset],
  );
  const [state, setD] = useState<ReminderRuleInput>(initial);
  const [wordingEdited, setWordingEdited] = useState(!!rule);
  const [emailText, setEmailText] = useState("");
  const [mail, setMail] = useState<Audience>("TEAM");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showUpcoming, setShowUpcoming] = useState(false);

  const companies = useQuery({ queryKey: ["legal-entities"], queryFn: orgApi.listLegalEntities });
  const units = useQuery({ queryKey: ["org-units"], queryFn: orgApi.listOrgUnits });
  const variables = useQuery({ queryKey: ["reminder-variables", state.trigger], queryFn: () => remindersApi.variables(state.trigger) });
  const starter = useQuery({ queryKey: ["reminder-defaults", state.trigger], queryFn: () => remindersApi.defaults(state.trigger) });

  // A new rule shows ready-made wording for its event until the wording is edited.
  const starterWording = !wordingEdited ? starter.data : undefined;
  const d: ReminderRuleInput = starterWording ? { ...state, ...starterWording } : state;
  const set = <K extends keyof ReminderRuleInput>(k: K, v: ReminderRuleInput[K]) => {
    const wording = k === "subject" || k === "body_html" || k === "employee_subject" || k === "employee_body_html";
    if (wording) setWordingEdited(true);
    setD((p) => ({ ...(wording && starterWording ? { ...p, ...starterWording } : p), [k]: v }));
  };
  const resetWording = () => {
    if (!starter.data) return;
    setD((p) => ({ ...p, ...starter.data }));
    setWordingEdited(true);
  };

  const hasHeadsUp = d.notify_manager || d.notify_everyone || d.extra_emails.length > 0;
  // Show only the messages that will actually be sent.
  const kinds: { value: Audience; label: string }[] = [
    ...(hasHeadsUp ? [{ value: "TEAM" as Audience, label: "Heads-up message" }] : []),
    ...(d.notify_employee ? [{ value: "EMPLOYEE" as Audience, label: "Message to the person" }] : []),
  ];
  const shown: Audience = kinds.some((k) => k.value === mail) ? mail : (kinds[0]?.value ?? "TEAM");
  const own = shown === "EMPLOYEE";

  const offsets = offsetsFor(d.frequency, d.days_before, d.custom_offsets);
  const needsDays = d.frequency === "CONTINUOUS" || d.frequency === "ALTERNATE_DAYS";
  const oneOff = TRIGGERS[d.trigger].oneOff;

  const draft = useDebounced({ subject: own ? d.employee_subject : d.subject, body: own ? d.employee_body_html : d.body_html }, 600);
  const preview = useQuery({
    queryKey: ["reminder-preview", d.trigger, shown, d.digest, d.legal_entity_id, draft],
    queryFn: () => remindersApi.preview({ trigger: d.trigger, audience: shown, subject: draft.subject, body_html: draft.body, digest: d.digest, legal_entity_id: d.legal_entity_id }),
    enabled: draft.subject.length > 0 && draft.body.length > 0,
    placeholderData: (prev) => prev,
  });

  const companyUnits = (units.data ?? []).filter((u) => u.status === "ACTIVE" && (!d.legal_entity_id || !u.legal_entity_id || u.legal_entity_id === d.legal_entity_id));
  const defaultName = `${TRIGGERS[d.trigger].label} reminder`;

  // Problems that block saving, in plain words; shown beside the Save button.
  const problems: string[] = [];
  if (!d.notify_employee && !hasHeadsUp) problems.push("choose who should get it");
  if (needsDays && !(d.days_before >= 1)) problems.push("say how many days ahead it starts");
  if (d.frequency === "CUSTOM" && d.custom_offsets.length === 0) problems.push("pick at least one day");
  if (!d.subject || !d.body_html || !d.employee_subject || !d.employee_body_html) problems.push("fill in the message");
  if (preview.data && preview.data.problems.length > 0) problems.push("fix the message");

  // Only the user's own edits count: the ready-made wording a new rule shows is not stored in `state`.
  const dirty = JSON.stringify(state) !== JSON.stringify(initial);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const close = () => (dirty ? setConfirmDiscard(true) : onClose());

  const payload: ReminderRuleInput = { ...d, name: d.name.trim() || defaultName };
  const save = useMutation({
    mutationFn: () => rule ? remindersApi.update(rule.id, { ...payload, version: rule.version }) : remindersApi.create(payload),
    onSuccess: (saved) => {
      toast.success(rule ? "Reminder saved" : "Reminder created", saved.name);
      qc.invalidateQueries({ queryKey: ["reminder-rules"] });
      onClose();
    },
    onError: (e) => toast.error("Couldn’t save the reminder", errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => remindersApi.remove(rule!.id),
    onSuccess: () => { toast.success("Reminder removed", rule!.name); qc.invalidateQueries({ queryKey: ["reminder-rules"] }); onClose(); },
    onError: (e) => toast.error("Couldn’t remove the reminder", errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: () => remindersApi.testSend(rule!.id, shown),
    onSuccess: (r) => toast.success("Test mail sent", r.sent_to),
    onError: (e) => toast.error("Couldn’t send the test", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (problems.length === 0) save.mutate(); };

  const dirtyWording = rule && (d.subject !== rule.subject || d.body_html !== rule.body_html || d.employee_subject !== rule.employee_subject || d.employee_body_html !== rule.employee_body_html);
  const toggleDay = (n: number) => set("custom_offsets", d.custom_offsets.includes(n) ? d.custom_offsets.filter((x) => x !== n) : [...d.custom_offsets, n].sort((a, b) => b - a));

  const addEmails = () => {
    const parts = emailText.split(/[\s,;]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);
    if (parts.length === 0) return;
    const good = parts.filter((p) => EMAIL.test(p));
    if (good.length < parts.length) toast.error("Some addresses weren’t valid", parts.filter((p) => !EMAIL.test(p)).join(", "));
    set("extra_emails", [...new Set([...d.extra_emails, ...good])]);
    setEmailText("");
  };
  const emailKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addEmails(); }
    if (e.key === "Backspace" && !emailText && d.extra_emails.length) set("extra_emails", d.extra_emails.slice(0, -1));
  };

  return (
    <>
      <Sheet open onClose={close} className="max-w-3xl" title={rule ? `Edit “${rule.name}”` : "New reminder"}
        description="Four short steps. The sentence below always shows what this reminder will do."
        footer={<>
          {rule && <button type="button" className="btn-ghost text-danger" onClick={() => setConfirmDelete(true)}><Trash2 size={15} /> Remove</button>}
          <p className="mr-auto min-w-0 flex-1 truncate text-xs text-fg-subtle" role="status">
            {problems.length > 0 ? `To save: ${problems.join(", ")}.` : dirty ? "You have unsaved changes." : ""}
          </p>
          <button type="button" className="btn-secondary" onClick={close}>Cancel</button>
          <button className="btn-primary" type="submit" form="reminder-form" disabled={problems.length > 0 || save.isPending}>{save.isPending ? "Saving…" : rule ? "Save changes" : "Create reminder"}</button>
        </>}>
        <form id="reminder-form" onSubmit={submit} className="space-y-7">
          <div className="rounded-xl border border-brand-500/30 bg-brand-500/5 px-4 py-3 text-[13px] text-fg" aria-live="polite">
            <span className="font-medium">In short: </span>{describeRule({ ...d, send_time: d.send_time })}
          </div>

          <Step n={1} title="Which event is this about?" hint="Pick the date the reminder counts from.">
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Event">
              {(Object.keys(TRIGGERS) as ReminderTrigger[]).map((t) => {
                const Icon = EVENT_ICON[t];
                const on = d.trigger === t;
                return (
                  <button key={t} type="button" role="radio" aria-checked={on} disabled={!!rule && !on}
                    onClick={() => { set("trigger", t); if (!rule) setWordingEdited(false); }}
                    className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${on ? "border-brand-500 bg-brand-500/5" : "border-line hover:bg-muted"}`}>
                    <Icon size={18} className={on ? "text-accent" : "text-fg-subtle"} />
                    <span><span className="block text-[13px] font-medium text-fg">{TRIGGERS[t].label}</span><span className="block text-xs text-fg-subtle">{TRIGGERS[t].help}</span></span>
                  </button>
                );
              })}
            </div>
            {rule && <p className="hint">The event can’t be changed after the reminder is created. Create a new reminder for a different event.</p>}
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="rm-company">Whose {TRIGGERS[d.trigger].label.toLowerCase()}?</label>
                <select id="rm-company" className="input" value={d.legal_entity_id ?? ""} onChange={(e) => { set("legal_entity_id", e.target.value || null); set("org_unit_id", null); }}>
                  <option value="">Everyone in the group</option>
                  {(companies.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="rm-dept">Department (optional)</label>
                <select id="rm-dept" className="input" value={d.org_unit_id ?? ""} onChange={(e) => set("org_unit_id", e.target.value || null)} disabled={companyUnits.length === 0}>
                  <option value="">All departments</option>
                  {companyUnits.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="label" htmlFor="rm-name">Name (optional)</label>
              <input id="rm-name" className="input" maxLength={120} value={d.name} onChange={(e) => set("name", e.target.value)} placeholder={defaultName} />
            </div>
          </Step>

          <Step n={2} title="When should the mail go out?" hint={oneOff ? "This date happens once, so the mail goes out before it and on it." : "The mail goes out ahead of the date and on it."}>
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="How often">
              {(Object.keys(FREQUENCIES) as ReminderFrequency[]).map((f) => (
                <button key={f} type="button" role="radio" aria-checked={d.frequency === f} onClick={() => set("frequency", f)}
                  className={`rounded-lg border px-3 py-2 text-left transition-colors ${d.frequency === f ? "border-brand-500 bg-brand-500/5" : "border-line hover:bg-muted"}`}>
                  <span className="block text-[13px] font-medium text-fg">{FREQUENCIES[f].label}</span>
                  <span className="block text-xs text-fg-subtle">{FREQUENCIES[f].help}</span>
                </button>
              ))}
            </div>
            {needsDays && (
              <div className="max-w-[16rem]">
                <label className="label" htmlFor="rm-days">Start how many days ahead?</label>
                <input id="rm-days" type="number" min={1} max={60} className="input" value={d.days_before} onChange={(e) => set("days_before", Math.min(60, Number(e.target.value)))} />
              </div>
            )}
            {d.frequency === "CUSTOM" && (
              <div>
                <p className="label">Tick the days (before the date)</p>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Days before">
                  {DAY_CHOICES.map((n) => (
                    <button key={n} type="button" aria-pressed={d.custom_offsets.includes(n)} onClick={() => toggleDay(n)}
                      className={`rounded-full border px-3 py-1 text-xs transition-colors ${d.custom_offsets.includes(n) ? "border-brand-500 bg-brand-500/10 text-accent" : "border-line text-fg-muted hover:bg-muted"}`}>
                      {n === 0 ? "On the day" : n === 1 ? "1 day before" : `${n} days before`}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="max-w-[16rem]">
              <label className="label" htmlFor="rm-time">At what time?</label>
              <input id="rm-time" type="time" className="input" value={d.send_time} onChange={(e) => set("send_time", e.target.value)} />
              <p className="hint">Company time. Mail goes out within about 15 minutes of this. A reminder saved after this time today starts tomorrow.</p>
            </div>
            <p className="text-xs text-fg-muted">Mail goes out {describeOffsets(offsets, TRIGGERS[d.trigger].short)}.</p>
          </Step>

          <Step n={3} title="Who should get it?" hint="Tick everyone who should be told. You can choose more than one.">
            <Choice checked={d.notify_employee} onChange={(v) => set("notify_employee", v)} title="The person themselves" help="A personal message (like “Happy birthday”), sent on the day only." />
            <Choice checked={d.notify_manager} onChange={(v) => set("notify_manager", v)} title="Their line manager" help="A heads-up about the people in their team." />
            <Choice checked={d.notify_everyone} onChange={(v) => set("notify_everyone", v)} title="Everyone in the company"
              help={`A heads-up to every employee with an email address (${d.org_unit_id ? "in that department" : d.legal_entity_id ? "in that company" : "in the whole group"}), never about themselves.`} />
            <div>
              <label className="label" htmlFor="rm-emails">Other email addresses</label>
              <div className="input flex h-auto min-h-9 flex-wrap items-center gap-1.5 py-1.5">
                {d.extra_emails.map((a) => (
                  <span key={a} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-fg">
                    {a}
                    <button type="button" aria-label={`Remove ${a}`} onClick={() => set("extra_emails", d.extra_emails.filter((x) => x !== a))}><X size={12} /></button>
                  </span>
                ))}
                <input id="rm-emails" className="min-w-[10rem] flex-1 bg-transparent text-[13px] outline-none" value={emailText} placeholder={d.extra_emails.length ? "Add another…" : "hr@company.com"}
                  onChange={(e) => setEmailText(e.target.value)} onKeyDown={emailKey} onBlur={addEmails} />
              </div>
              <p className="hint">Type an address and press Enter. These get the heads-up for everyone this reminder covers.</p>
            </div>
            {hasHeadsUp && (
              <fieldset className="space-y-2">
                <legend className="label">How should the heads-up be sent?</legend>
                <Choice type="radio" checked={d.digest} onChange={() => set("digest", true)} title="One mail listing everyone due" help="Best when several people share a day." />
                <Choice type="radio" checked={!d.digest} onChange={() => set("digest", false)} title="A separate mail for each person" help="Each mail is about one person." />
              </fieldset>
            )}
            <p className="text-xs text-fg-muted">This will email {describeAudience(d)}.</p>
          </Step>

          <Step n={4} title="What should it say?" hint="We’ve written a message to start from. Change anything you like.">
            {kinds.length > 1 && <Segmented value={shown} onChange={setMail} items={kinds} />}
            {kinds.length === 0 && <Notice tone="info" title="Choose who gets it first">Pick at least one person in step 3 to write their message.</Notice>}
            {kinds.length > 0 && <>
              <div>
                <label className="label" htmlFor="rm-subject">Subject</label>
                <input id="rm-subject" className="input" maxLength={300} value={own ? d.employee_subject : d.subject} onChange={(e) => set(own ? "employee_subject" : "subject", e.target.value)} />
              </div>
              <WordingEditor key={`${d.trigger}-${shown}`} label={own ? "Message to the person" : "Heads-up message"}
                value={own ? d.employee_body_html : d.body_html} onChange={(html) => set(own ? "employee_body_html" : "body_html", html)}
                variables={variables.data?.variables ?? {}} allowRepeat={!own} />
              <p className="hint">Use “Insert field” to add things like the person’s name or date; they’re filled in for each mail.{!own && " “Repeat for each person” lists everyone when one mail covers several people."}</p>
              <button type="button" className="btn-ghost btn-sm" onClick={resetWording}><RotateCcw size={14} /> Start over with the ready-made message</button>
              {preview.data && preview.data.problems.length > 0 && <Notice title="This message needs a fix">{preview.data.problems.join(" ")}</Notice>}
              <div>
                <p className="label">How it will look (with sample people)</p>
                {preview.data ? (
                  <div className="overflow-hidden rounded-lg border border-line">
                    <p className="border-b border-line bg-panel px-3 py-2 text-xs text-fg-muted">Subject: <span className="text-fg">{preview.data.subject}</span></p>
                    <iframe title="Mail preview" sandbox="" srcDoc={preview.data.html} className="h-72 w-full bg-white" />
                  </div>
                ) : <Skeleton className="h-40 rounded-lg" />}
              </div>
              {rule && (
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn-secondary btn-sm" disabled={test.isPending || !!dirtyWording} onClick={() => test.mutate()}
                    title={dirtyWording ? "Save your changes first; the test uses the saved message" : undefined}>
                    <Send size={14} /> Send this message to me
                  </button>
                  <button type="button" className="btn-secondary btn-sm" onClick={() => setShowUpcoming((s) => !s)}><Eye size={14} /> Who will get mail soon?</button>
                </div>
              )}
            </>}
          </Step>
          {rule && showUpcoming && <Upcoming ruleId={rule.id} />}
        </form>
      </Sheet>
      <ConfirmDialog open={confirmDiscard} onClose={() => setConfirmDiscard(false)} onConfirm={onClose}
        title="Discard your changes?" description="What you changed in this reminder hasn’t been saved."
        confirmLabel="Discard changes" cancelLabel="Keep editing" />
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} onConfirm={() => remove.mutate()}
        title="Remove this reminder?" description="It stops sending. Its history and the mail already sent are kept." confirmLabel="Remove" loading={remove.isPending} />
    </>
  );
}

function Upcoming({ ruleId }: { ruleId: string }) {
  const q = useQuery({ queryKey: ["reminder-upcoming", ruleId], queryFn: () => remindersApi.upcoming(ruleId, 30) });
  if (q.isPending) return <Skeleton className="h-24 rounded-lg" />;
  if (q.isError) return <Notice title="Couldn’t load who is coming up">{errorMessage(q.error)}</Notice>;
  if (q.data.length === 0) return <p className="text-[13px] text-fg-muted">Nobody in the next 30 days, using the saved schedule.</p>;
  return (
    <div className="rounded-lg border border-line">
      <p className="border-b border-line bg-panel px-3 py-2 text-xs text-fg-muted">Next 30 days, from the saved schedule</p>
      <ul className="divide-y divide-line">
        {q.data.map((p) => (
          <li key={`${p.full_name}-${p.event_date}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
            <span>{p.full_name}{p.department && <span className="text-fg-subtle"> · {p.department}</span>}</span>
            <span className="text-xs text-fg-muted">{format(parseISO(p.event_date), "d MMM")} · mail on {p.sends_on.map((s) => format(parseISO(s), "d MMM")).join(", ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
