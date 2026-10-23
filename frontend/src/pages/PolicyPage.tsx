import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Pencil,
  Trash2,
  ShieldCheck,
  Clock,
  Coffee,
  Timer,
  Zap,
  FilePenLine,
  MoreHorizontal,
  Building2,
  Info,
  CalendarDays,
} from "lucide-react";
import type { PolicyTemplate, EmployeePolicyAssignment } from "../api/policy";
import { policyApi } from "../api/policy";
import { orgApi } from "../api/org";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { Sheet, ConfirmDialog } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { usePopover } from "../components/ui/Popover";
import { useToast, errorMessage } from "../components/ui/Toast";
import { LeavePoliciesView } from "./LeavePoliciesPage";
import { PolicyExplainerModal } from "../components/policy/PolicyExplainerModal";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SATURDAY_INDEX = 5;

// "HH:MM" or "HH:MM:SS" arithmetic for deriving end time from start + total
// working hours + break, so the policy form only needs a start time and a
// duration — never a separately-entered end time to keep in sync by hand.
function minutesBetween(start: string, end: string): number {
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const diff = (eh * 60 + em) - (sh * 60 + sm);
  return diff <= 0 ? diff + 24 * 60 : diff;
}
function addMinutes(time: string, minutes: number): string {
  const [h, m] = time.split(":").map(Number);
  const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}:00`;
}
// "No Saturdays" isn't listed here — that's what the Sat toggle above is
// for, so there's exactly one control for it instead of two that could
// disagree. A 5th Saturday, on months that have one, is never named as
// off by either alternating pattern below, so it's always a working day.
const SATURDAY_PATTERNS: { value: PolicyTemplate["saturday_pattern"]; label: string }[] = [
  { value: "ALL", label: "Every Saturday" },
  { value: "SECOND_OFF", label: "2nd Saturday off" },
  { value: "SECOND_FOURTH_OFF", label: "2nd & 4th Saturday off (alternate)" },
  { value: "FIRST_THIRD_OFF", label: "1st & 3rd Saturday off" },
];

const DEFAULTS: Partial<PolicyTemplate> = {
  name: "",
  description: "",
  timezone: "Asia/Kolkata",
  expected_start_time: "09:00:00",
  expected_end_time: "18:00:00",
  work_days: "1111100",
  saturday_pattern: "ALL",
  break_minutes: 60,
  break_auto_deduct: false,
  grace_late_minutes: 0,
  grace_early_departure_minutes: 0,
  half_day_threshold_pct: 50,
  ot_enabled: true,
  ot_qualifying_minutes: 30,
  ot_rate: 1.5,
  ot_daily_cap_minutes: null,
  off_day_work: "OVERTIME",
  punch_rounding_minutes: 0,
  punch_rounding_direction: "NONE",
  correction_requires_approval: true,
  correction_approval_levels: 1,
  is_default: false,
};

export function PolicyPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [explainerOpen, setExplainerOpen] = useState(false);

  const rawTab = params.get("tab");
  const isLeave =
    rawTab === "leave" ||
    ["policies", "policy-sets", "types", "holidays", "operations", "leavers"].includes(rawTab ?? "");
  const activeTab: "attendance" | "leave" = isLeave ? "leave" : "attendance";

  const setActiveTab = (tab: "attendance" | "leave") => {
    const next = new URLSearchParams(params);
    if (tab === "attendance") {
      next.delete("tab");
      next.delete("section");
    } else {
      next.set("tab", "leave");
    }
    setParams(next, { replace: true });
  };

  const [editing, setEditing] = useState<PolicyTemplate | "new" | null>(null);
  const [deleting, setDeleting] = useState<PolicyTemplate | null>(null);
  const [assigning, setAssigning] = useState<PolicyTemplate | null>(null);
  const [createSetOpen, setCreateSetOpen] = useState(false);
  // Bumped on every "New policy" click so the sheet's key changes and React
  // remounts it — otherwise every open reused the same "new" key, so toggle
  // state (auto-deduct, overtime, etc.) leaked from whatever the previous
  // new-policy draft was left at instead of resetting to DEFAULTS.
  const [newPolicyNonce, setNewPolicyNonce] = useState(0);
  const openNewPolicy = () => { setNewPolicyNonce((n) => n + 1); setEditing("new"); };

  const { data: templates, isPending: isLoading, isError, refetch } = useQuery<PolicyTemplate[]>({
    queryKey: ["policy-templates"],
    queryFn: () => policyApi.listTemplates(),
  });

  const saveMut = useMutation({
    mutationFn: (body: Partial<PolicyTemplate>) =>
      editing && editing !== "new"
        ? policyApi.updateTemplate(editing.id, { ...body, version: editing.version })
        : policyApi.createTemplate(body),
    onSuccess: (_, body) => {
      qc.invalidateQueries({ queryKey: ["policy-templates"] });
      toast.success(editing === "new" ? "Policy created" : "Policy updated", body.name);
      setEditing(null);
    },
    onError: (e) => toast.error("Couldn’t save policy", errorMessage(e)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => policyApi.deleteTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy-templates"] });
      toast.success("Policy deleted", deleting?.name);
      setDeleting(null);
    },
    onError: (e) => toast.error("Couldn’t delete policy", errorMessage(e)),
  });

  return (
    <>
      <PageHeader
        title="Policies"
        description="Configure attendance shifts, working hours, leave types, policy sets and holiday rules."
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary btn-sm flex items-center gap-1.5"
              onClick={() => setExplainerOpen(true)}
            >
              <Info size={14} className="text-accent" />
              <span>How policies work</span>
            </button>
            {activeTab === "attendance" ? (
              <button className="btn-primary btn-sm" onClick={openNewPolicy}>
                <Plus size={15} /> New policy
              </button>
            ) : (
              <button className="btn-primary btn-sm" onClick={() => setCreateSetOpen(true)}>
                <Plus size={15} /> New policy set
              </button>
            )}
          </div>
        }
      />

      <Tabs
        className="mb-6"
        value={activeTab}
        onChange={(t) => setActiveTab(t as "attendance" | "leave")}
        items={[
          { value: "attendance", label: "Attendance policies", count: templates?.length },
          { value: "leave", label: "Leave policies" },
        ]}
      />

      {activeTab === "attendance" && (
        <div className="space-y-6">
          {isError ? (
            <Notice title="Couldn’t load policies" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
              The policy API isn’t responding.
            </Notice>
          ) : isLoading ? (
            <div className="grid gap-4 lg:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-60 rounded-xl" />)}</div>
          ) : !templates?.length ? (
            <div className="card p-10">
              <EmptyState
                icon={ShieldCheck}
                title="No attendance policies yet"
                description="Create a policy to define working hours and attendance rules, then assign it to employees."
                action={<button className="btn-primary btn-sm" onClick={openNewPolicy}><Plus size={14} /> New policy</button>}
              />
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {templates.map((t) => (
                <PolicyCard key={t.id} tpl={t} onEdit={() => setEditing(t)} onDelete={() => setDeleting(t)} onAssign={() => setAssigning(t)} />
              ))}
            </div>
          )}

          <PolicyAssignSheet
            tpl={assigning}
            open={assigning !== null}
            onClose={() => setAssigning(null)}
          />

          <PolicySheet
            key={editing === "new" ? `new-${newPolicyNonce}` : editing?.id ?? "closed"}
            open={editing !== null}
            initial={editing && editing !== "new" ? editing : undefined}
            saving={saveMut.isPending}
            onSave={(v) => saveMut.mutate(v)}
            onClose={() => setEditing(null)}
          />
          <ConfirmDialog
            open={!!deleting}
            onClose={() => setDeleting(null)}
            onConfirm={() => deleting && deleteMut.mutate(deleting.id)}
            loading={deleteMut.isPending}
            title={`Delete “${deleting?.name}”?`}
            description="Employees assigned to this policy will need a new one. This can’t be undone."
            confirmLabel="Delete policy"
          />
        </div>
      )}

      {activeTab === "leave" && (
        <LeavePoliciesView
          standaloneHeader={false}
          createSetOpen={createSetOpen}
          onOpenCreateSet={() => setCreateSetOpen(true)}
          onCloseCreateSet={() => setCreateSetOpen(false)}
        />
      )}

      <PolicyExplainerModal
        open={explainerOpen}
        onClose={() => setExplainerOpen(false)}
        initialTab={activeTab === "attendance" ? "attendance" : "leave"}
      />
    </>
  );
}

function PolicyCard({ tpl, onEdit, onDelete, onAssign }: { tpl: PolicyTemplate; onEdit: () => void; onDelete: () => void; onAssign: () => void }) {
  const { open: menuOpen, setOpen: setMenuOpen, ref: menuRef } = usePopover();
  const hours = (tpl.standard_minutes / 60).toFixed(1).replace(/\.0$/, "");
  const satLabel = SATURDAY_PATTERNS.find((p) => p.value === tpl.saturday_pattern)?.label;
  const rows: [typeof Clock, string, string][] = [
    [Clock, "Hours", `${tpl.expected_start_time.slice(0, 5)} – ${tpl.expected_end_time.slice(0, 5)} · ${hours}h/day`],
    [Coffee, "Break", `${tpl.break_minutes} min · from actual check-outs`],
    [Timer, "Grace", `${tpl.grace_late_minutes} min late · ${tpl.grace_early_departure_minutes} min early`],
    [Zap, "Overtime", tpl.ot_enabled ? `After ${tpl.ot_qualifying_minutes} min at ${tpl.ot_rate}×` : "Disabled"],
    [CalendarDays, "Off-day work", tpl.off_day_work === "COMP_OFF" ? "Comp-off credited" : "Counted as overtime"],
    [FilePenLine, "Corrections", tpl.correction_requires_approval ? `${tpl.correction_approval_levels}-level approval` : "Auto-approved"],
  ];

  return (
    <div className="card flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-[15px] font-semibold tracking-tight text-fg">{tpl.name}</h3>
            {tpl.is_default && <span className="badge badge-brand">Default</span>}
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-subtle">{tpl.description || tpl.timezone}</p>
        </div>
        <div ref={menuRef} className="relative">
          <button className="btn-icon -mr-2 -mt-1" onClick={() => setMenuOpen((o) => !o)} aria-label={`Actions for ${tpl.name}`}>
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div className="popover absolute right-0 top-full mt-1 w-48">
              <button className="menu-item" onClick={() => { setMenuOpen(false); onEdit(); }}><Pencil size={14} /> Edit</button>
              <button className="menu-item" onClick={() => { setMenuOpen(false); onAssign(); }}><Building2 size={14} /> Assign</button>
              <button className="menu-item hover:text-danger" onClick={() => { setMenuOpen(false); onDelete(); }}><Trash2 size={14} /> Delete</button>
            </div>
          )}
        </div>
      </div>

      <dl className="mx-5 mt-4 divide-y divide-line rounded-xl border border-line">
        {rows.map(([Icon, k, v]) => (
          <div key={k} className="flex items-center gap-3 px-3.5 py-2.5 text-[13px]">
            <Icon size={14} className="shrink-0 text-fg-subtle" />
            <dt className="w-24 shrink-0 text-fg-subtle">{k}</dt>
            <dd className="min-w-0 truncate font-medium text-fg">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="flex items-center justify-between gap-3 px-5 py-4">
        <div className="flex gap-1">
          {DAYS.map((d, i) => (
            <span
              key={d}
              className={`grid h-7 w-8 place-items-center rounded-md text-[11px] font-medium ${
                tpl.work_days[i] === "1" ? "bg-brand-500/10 text-accent" : "bg-muted text-fg-subtle/70"
              }`}
            >
              {d.slice(0, 2)}
            </span>
          ))}
        </div>
        <button className="btn-ghost btn-sm" onClick={onEdit}><Pencil size={13} /> Edit</button>
      </div>
      {tpl.work_days[SATURDAY_INDEX] === "1" && tpl.saturday_pattern !== "ALL" && satLabel && (
        <p className="-mt-2 px-5 pb-4 text-xs text-fg-subtle">Saturday: {satLabel}</p>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="eyebrow mb-3">{title}</legend>
      {children}
    </fieldset>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border border-line px-3.5 py-3">
      <span>
        <span className="block text-[13px] font-medium text-fg">{label}</span>
        {hint && <span className="block text-xs text-fg-subtle">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? "bg-brand-600" : "bg-line-strong"}`}
      >
        <span className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`} />
      </button>
    </label>
  );
}

function PolicySheet({ open, initial, saving, onSave, onClose }: {
  open: boolean;
  initial?: PolicyTemplate;
  saving: boolean;
  onSave: (v: Partial<PolicyTemplate>) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Partial<PolicyTemplate>>({ ...DEFAULTS, ...initial });
  const set = <K extends keyof PolicyTemplate>(k: K, v: PolicyTemplate[K] | null) => setForm((f) => ({ ...f, [k]: v }));

  // The source of truth for the schedule is start time + this duration —
  // expected_end_time is derived and re-set on every change below, never
  // typed directly. Initialized by reversing an existing policy's
  // start/end/break back into a duration, so editing one doesn't ask HR to
  // re-derive hours from whatever end time happens to be stored.
  const [totalWorkingMinutes, setTotalWorkingMinutes] = useState(() => {
    const start = initial?.expected_start_time ?? DEFAULTS.expected_start_time!;
    const end = initial?.expected_end_time ?? DEFAULTS.expected_end_time!;
    const brk = initial?.break_minutes ?? DEFAULTS.break_minutes!;
    return Math.max(0, minutesBetween(start, end) - brk);
  });
  const recomputeEnd = (start: string, totalMin: number, breakMin: number) => set("expected_end_time", addMinutes(start, totalMin + breakMin));
  const onStartChange = (hhmm: string) => {
    const start = `${hhmm}:00`;
    set("expected_start_time", start);
    recomputeEnd(start, totalWorkingMinutes, form.break_minutes ?? 0);
  };
  const onTotalHoursChange = (hours: number) => {
    const mins = Math.max(0, Math.round(hours * 60));
    setTotalWorkingMinutes(mins);
    recomputeEnd(form.expected_start_time ?? DEFAULTS.expected_start_time!, mins, form.break_minutes ?? 0);
  };
  const onBreakChange = (mins: number) => {
    set("break_minutes", mins);
    recomputeEnd(form.expected_start_time ?? DEFAULTS.expected_start_time!, totalWorkingMinutes, mins);
  };

  const num = (label: string, k: keyof PolicyTemplate, suffix?: string, opts: { step?: string; nullable?: boolean } = {}) => (
    <div>
      <label className="label" htmlFor={`pol-${k}`}>{label}</label>
      <div className="relative">
        <input
          id={`pol-${k}`}
          type="number"
          step={opts.step}
          className={`input ${suffix ? "pr-12" : ""}`}
          value={form[k] == null ? "" : String(form[k])}
          placeholder={opts.nullable ? "No limit" : undefined}
          onChange={(e) => set(k, (e.target.value === "" && opts.nullable ? null : Number(e.target.value)) as never)}
        />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-fg-subtle">{suffix}</span>}
      </div>
    </div>
  );

  const toggleDay = (i: number) => {
    const bits = (form.work_days ?? "1111100").split("");
    bits[i] = bits[i] === "1" ? "0" : "1";
    set("work_days", bits.join(""));
  };

  const submit = (e: FormEvent) => { e.preventDefault(); if (form.name?.trim()) onSave(form); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={initial ? "Edit policy" : "New policy"}
      description={initial ? initial.name : "Define working hours and attendance rules."}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="policy-form" disabled={!form.name?.trim() || saving}>
            {saving ? "Saving…" : initial ? "Save changes" : "Create policy"}
          </button>
        </>
      }
    >
      <form id="policy-form" onSubmit={submit} className="space-y-7">
        <Section title="Basics">
          <div>
            <label className="label" htmlFor="pol-name">Policy name</label>
            <input id="pol-name" className="input" placeholder="e.g. Head office — general shift" value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="pol-desc">Description <span className="font-normal text-fg-subtle">(optional)</span></label>
            <textarea id="pol-desc" rows={2} className="input" value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="pol-tz">Timezone</label>
            <input id="pol-tz" className="input" value={form.timezone ?? ""} onChange={(e) => set("timezone", e.target.value)} />
          </div>
        </Section>

        <Section title="Schedule">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="pol-start">Start time</label>
              <input id="pol-start" type="time" className="input" value={form.expected_start_time?.slice(0, 5) ?? ""} onChange={(e) => onStartChange(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="pol-hours">Total working hours</label>
              <input
                id="pol-hours" type="number" step="0.25" min="0" className="input"
                value={totalWorkingMinutes / 60}
                onChange={(e) => onTotalHoursChange(Number(e.target.value))}
              />
            </div>
          </div>
          <p className="hint">
            Ends at <span className="font-medium text-fg">{form.expected_end_time?.slice(0, 5) ?? "—"}</span> — start time + total working hours + break, calculated automatically. Overtime is measured against these hours.
          </p>
          <div>
            <span className="label">Working days</span>
            <div className="flex gap-1.5">
              {DAYS.map((d, i) => {
                const on = (form.work_days ?? "1111100")[i] === "1";
                return (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleDay(i)}
                    className={`h-9 flex-1 rounded-lg border text-xs font-medium transition-colors ${
                      on ? "border-brand-500/40 bg-brand-500/10 text-accent" : "border-line text-fg-subtle hover:border-line-strong"
                    }`}
                  >
                    {d}
                  </button>
                );
              })}
            </div>
          </div>
          {(form.work_days ?? "1111100")[SATURDAY_INDEX] === "1" && (
            <div>
              <label className="label" htmlFor="pol-sat">Saturday pattern</label>
              <select
                id="pol-sat" className="input" value={form.saturday_pattern ?? "ALL"}
                onChange={(e) => set("saturday_pattern", e.target.value as PolicyTemplate["saturday_pattern"])}
              >
                {SATURDAY_PATTERNS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
              <p className="hint">
                Only applies to Saturday. A 5th Saturday, in months that have one, always works — it's never one of the named off days.
              </p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="pol-break_minutes">Break</label>
              <div className="relative">
                <input
                  id="pol-break_minutes" type="number" className="input pr-12"
                  value={form.break_minutes ?? 0}
                  onChange={(e) => onBreakChange(Number(e.target.value))}
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-fg-subtle">min</span>
              </div>
            </div>
            {num("Half-day threshold", "half_day_threshold_pct", "%")}
          </div>
          <p className="hint">
            The break sets the scheduled shift length. Worked time is measured from check-in to check-out,
            minus only the time actually spent checked out in between — nothing is deducted automatically.
          </p>
        </Section>

        <Section title="Grace & rounding">
          <div className="grid grid-cols-2 gap-3">
            {num("Late arrival grace", "grace_late_minutes", "min")}
            {num("Early departure grace", "grace_early_departure_minutes", "min")}
            {num("Punch rounding", "punch_rounding_minutes", "min")}
            <div>
              <label className="label" htmlFor="pol-round">Rounding direction</label>
              <select id="pol-round" className="input" value={form.punch_rounding_direction ?? "NONE"} onChange={(e) => set("punch_rounding_direction", e.target.value)}>
                {[["NONE", "None"], ["UP", "Round up"], ["DOWN", "Round down"], ["NEAREST", "Nearest"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>
        </Section>

        <Section title="Overtime">
          <Toggle label="Enable overtime" checked={!!form.ot_enabled} onChange={(v) => set("ot_enabled", v)} />
          {form.ot_enabled && (
            <div className="grid grid-cols-3 gap-3">
              {num("Qualifies after", "ot_qualifying_minutes", "min")}
              {num("Rate", "ot_rate", "×", { step: "0.25" })}
              {num("Daily cap", "ot_daily_cap_minutes", "min", { nullable: true })}
            </div>
          )}
          <p className="hint">
            {form.ot_enabled
              ? "Overtime counts after the full shift and goes for approval."
              : "With overtime off, extra time is still shown on the day — never approved or paid."}
          </p>
        </Section>

        <Section title="Work on weekly offs & holidays">
          <div>
            <label className="label" htmlFor="pol-offday">Time worked on an off day</label>
            <select
              id="pol-offday" className="input" value={form.off_day_work ?? "OVERTIME"}
              onChange={(e) => set("off_day_work", e.target.value as PolicyTemplate["off_day_work"])}
            >
              <option value="OVERTIME">Counts as overtime</option>
              <option value="COMP_OFF">Earns comp-off</option>
            </select>
            <p className="hint">
              {form.off_day_work === "COMP_OFF"
                ? "A full standard day credits 1 comp-off day, at least the half-day share credits ½ — added to the leave balance automatically."
                : "Every minute worked counts as overtime, under the overtime rules above. No late or early marks on an off day."}
            </p>
          </div>
        </Section>

        <Section title="Corrections">
          <Toggle label="Require approval" hint="Attendance corrections must be approved before they apply" checked={!!form.correction_requires_approval} onChange={(v) => set("correction_requires_approval", v)} />
          {form.correction_requires_approval && (
            <div>
              <label className="label" htmlFor="pol-levels">Approval levels</label>
              <select id="pol-levels" className="input" value={form.correction_approval_levels ?? 1} onChange={(e) => set("correction_approval_levels", Number(e.target.value))}>
                {[1, 2, 3].map((n) => <option key={n} value={n}>{n} level{n > 1 ? "s" : ""}</option>)}
              </select>
            </div>
          )}
        </Section>

        <Toggle label="Set as default policy" hint="Applied to employees without an explicit assignment" checked={!!form.is_default} onChange={(v) => set("is_default", v)} />
      </form>
    </Sheet>
  );
}

function PolicyAssignSheet({ tpl, open, onClose }: {
  tpl: PolicyTemplate | null;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  // Cascading, not independent: pick the company first, then — within that
  // company only — optionally narrow to one of its departments. Two
  // separate flat pickers meant "Finance" was ambiguous across every
  // company that has one; scoping the department list to the chosen
  // company removes that ambiguity entirely instead of trying to label
  // around it.
  const [legalEntityId, setLegalEntityId] = useState("");
  const [orgUnitId, setOrgUnitId] = useState(""); // "" = the whole company
  const [effectiveFrom, setEffectiveFrom] = useState(() => new Date().toISOString().slice(0, 10));

  const orgUnits = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits(), enabled: open });
  const legalEntities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities(), enabled: open });
  // Every assignment tenant-wide — filtered client-side to this policy's
  // company + department rows. Small dataset (one row per active
  // assignment), simpler than a dedicated "assignments for this template" endpoint.
  const assignments = useQuery<EmployeePolicyAssignment[]>({
    queryKey: ["policy-assignments"],
    queryFn: () => policyApi.listAssignments(),
    enabled: open,
  });

  const companyName = (id: string | null) => legalEntities.data?.find((e) => e.id === id)?.name ?? id ?? "";
  const orgUnitCompany = (ouId: string | null) => companyName(orgUnits.data?.find((o) => o.id === ouId)?.legal_entity_id ?? null);

  const companyAssignments = (assignments.data ?? []).filter((a) => a.legal_entity_id && a.policy_template_id === tpl?.id);
  const deptAssignments = (assignments.data ?? []).filter((a) => a.org_unit_id && a.policy_template_id === tpl?.id);
  const assignedOrgUnitIds = new Set((assignments.data ?? []).filter((a) => a.org_unit_id).map((a) => a.org_unit_id));
  // Departments that actually belong to the chosen company — never the
  // full tenant-wide list — and excludes its own root "company" org unit,
  // since picking that IS the whole-company option below.
  const departmentsInCompany = (orgUnits.data ?? []).filter(
    (o) => o.legal_entity_id === legalEntityId && o.type !== "COMPANY" && !assignedOrgUnitIds.has(o.id),
  );

  const assign = useMutation({
    mutationFn: () => policyApi.assignPolicy(
      orgUnitId
        ? { org_unit_id: orgUnitId, policy_template_id: tpl!.id, effective_from: effectiveFrom }
        : { legal_entity_id: legalEntityId, policy_template_id: tpl!.id, effective_from: effectiveFrom },
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy-assignments"] });
      toast.success(orgUnitId ? "Department assigned" : "Company assigned", tpl?.name);
      setLegalEntityId(""); setOrgUnitId("");
    },
    onError: (e) => toast.error("Couldn’t assign", errorMessage(e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => policyApi.removeAssignment(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy-assignments"] });
      toast.success("Assignment removed");
    },
    onError: (e) => toast.error("Couldn’t remove assignment", errorMessage(e)),
  });

  if (!tpl) return null;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Assign policy"
      description={`Everyone in scope follows "${tpl.name}" unless they have a more specific override.`}
    >
      <div className="space-y-5">
        <div>
          <p className="eyebrow mb-2">Currently assigned</p>
          {assignments.isPending ? (
            <Skeleton className="h-9" />
          ) : companyAssignments.length === 0 && deptAssignments.length === 0 ? (
            <p className="text-xs text-fg-subtle">No companies or departments are on this policy yet.</p>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {companyAssignments.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-[13px]">
                  <span className="flex min-w-0 items-center gap-2">
                    <Building2 size={13} className="shrink-0 text-fg-subtle" />
                    <span className="min-w-0 truncate font-medium text-fg">{a.legal_entity_name ?? a.legal_entity_id}</span>
                    <span className="shrink-0 text-xs text-fg-subtle">Whole company</span>
                  </span>
                  <button
                    className="shrink-0 text-fg-subtle transition-colors hover:text-danger"
                    onClick={() => remove.mutate(a.id)}
                    aria-label={`Remove ${a.legal_entity_name}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
              {deptAssignments.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-[13px]">
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-fg">{a.org_unit_name ?? a.org_unit_id}</span>
                    <span className="text-fg-subtle"> · {orgUnitCompany(a.org_unit_id)}</span>
                  </span>
                  <button
                    className="shrink-0 text-fg-subtle transition-colors hover:text-danger"
                    onClick={() => remove.mutate(a.id)}
                    aria-label={`Remove ${a.org_unit_name}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          <p className="eyebrow -mb-1">Assign to</p>
          {legalEntities.isError ? (
            <Notice title="Couldn’t load companies">The organization API isn’t responding.</Notice>
          ) : (
            <div>
              <label className="label" htmlFor="assign-entity">Company</label>
              <select
                id="assign-entity" className="input" value={legalEntityId}
                onChange={(e) => { setLegalEntityId(e.target.value); setOrgUnitId(""); }}
              >
                <option value="">Select company…</option>
                {(legalEntities.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </div>
          )}

          {legalEntityId && (
            orgUnits.isError ? (
              <Notice title="Couldn’t load departments">The organization API isn’t responding.</Notice>
            ) : (
              <div>
                <label className="label" htmlFor="assign-org-unit">
                  Department <span className="font-normal text-fg-subtle">(optional — leave blank for the whole company)</span>
                </label>
                <select id="assign-org-unit" className="input" value={orgUnitId} onChange={(e) => setOrgUnitId(e.target.value)}>
                  <option value="">— Whole company —</option>
                  {departmentsInCompany.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                {departmentsInCompany.length === 0 && (
                  <p className="hint">No departments in {companyName(legalEntityId)} without a policy already — create one on the Organization page, or assign the whole company above.</p>
                )}
              </div>
            )
          )}

          <div>
            <label className="label" htmlFor="assign-from">Effective from</label>
            <input id="assign-from" type="date" className="input" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          </div>
          <button
            className="btn-primary btn-sm"
            onClick={() => assign.mutate()}
            disabled={!legalEntityId || assign.isPending}
          >
            {assign.isPending ? "Assigning…" : orgUnitId ? "Assign to department" : "Assign to whole company"}
          </button>
        </div>

        <p className="hint">
          Priority when more than one applies: an employee's own individual assignment, then their department's
          (walking up to a parent department if it has none of its own), then their company's, then the tenant's default.
        </p>
      </div>
    </Sheet>
  );
}
