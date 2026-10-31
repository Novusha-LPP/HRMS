import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { BellRing, Cake, LogOut, PartyPopper, Pencil, Plus, UserPlus } from "lucide-react";
import { remindersApi, type ReminderRule, type ReminderRuleInput } from "../api/reminders";
import { orgApi } from "../api/org";
import { TRIGGERS, describeRule } from "../lib/reminders";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Tabs";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useToast, errorMessage } from "../components/ui/Toast";
import { RuleForm } from "../components/reminders/RuleForm";

const ICON = { BIRTHDAY: Cake, WORK_ANNIVERSARY: PartyPopper, NEW_JOINER: UserPlus, EXIT: LogOut } as const;

/** Ready-made starting points for the empty page: each opens the form already filled in. */
const QUICK_STARTS: { title: string; help: string; preset: Partial<ReminderRuleInput> }[] = [
  { title: "Birthday wishes", help: "A personal message to each employee on their birthday.", preset: { trigger: "BIRTHDAY", frequency: "SAME_DAY", notify_employee: true } },
  { title: "Birthday heads-up", help: "Tell managers a few days before, and again on the day.", preset: { trigger: "BIRTHDAY", frequency: "CUSTOM", custom_offsets: [3, 0], notify_manager: true } },
  { title: "Announce new joiners", help: "Tell everyone on the joining day.", preset: { trigger: "NEW_JOINER", frequency: "SAME_DAY", notify_everyone: true } },
  { title: "Exit checklist", help: "Remind managers as a last working day approaches.", preset: { trigger: "EXIT", frequency: "ALTERNATE_DAYS", days_before: 5, notify_manager: true } },
];

/** HR's set-up for scheduled birthday, anniversary, joining and exit mail. */
export function RemindersPage() {
  const [view, setView] = useState<"rules" | "log">("rules");
  const [editing, setEditing] = useState<{ rule?: ReminderRule; preset?: Partial<ReminderRuleInput> } | null>(null);
  const rules = useQuery({ queryKey: ["reminder-rules"], queryFn: remindersApi.list });
  const companies = useQuery({ queryKey: ["legal-entities"], queryFn: orgApi.listLegalEntities });
  const names = useMemo(() => new Map((companies.data ?? []).map((c) => [c.id, c.name])), [companies.data]);
  const active = (rules.data ?? []).filter((r) => r.is_active).length;
  const open = (preset?: Partial<ReminderRuleInput>) => setEditing({ preset });

  return (
    <>
      <PageHeader
        title="Reminders"
        description="Send email automatically for birthdays, work anniversaries, new joiners and exits. You choose who gets it, when, and what it says."
        actions={<button type="button" className="btn-primary" onClick={() => open()}><Plus size={15} /> New reminder</button>}
      />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented value={view} onChange={setView} items={[{ value: "rules", label: "Reminders" }, { value: "log", label: "Mail sent" }]} />
        {view === "rules" && (rules.data ?? []).length > 0 && (
          <p className="text-xs text-fg-subtle">{active} on · {(rules.data ?? []).length - active} paused</p>
        )}
      </div>
      {view === "rules" ? (
        <>
          {rules.isError && <Notice title="Couldn’t load reminders" action={<button className="btn-secondary btn-sm" onClick={() => rules.refetch()}>Retry</button>}>{errorMessage(rules.error)}</Notice>}
          {rules.isPending ? <Skeleton className="h-40 rounded-xl" /> : (rules.data ?? []).length === 0 ? (
            <div className="space-y-4">
              <div className="card">
                <EmptyState icon={BellRing} title="No reminders yet"
                  description="Start from one of the ideas below, or create your own."
                  action={<button type="button" className="btn-primary" onClick={() => open()}><Plus size={15} /> Create your own</button>} />
              </div>
              <ul className="grid gap-3 sm:grid-cols-2" aria-label="Ideas to start from">
                {QUICK_STARTS.map((q) => {
                  const Icon = ICON[q.preset.trigger!];
                  return (
                    <li key={q.title}>
                      <button type="button" onClick={() => open(q.preset)} className="card flex h-full w-full items-start gap-3 p-4 text-left transition-colors hover:bg-muted">
                        <Icon size={18} className="mt-0.5 text-accent" />
                        <span><span className="block text-[13px] font-medium text-fg">{q.title}</span><span className="block text-xs text-fg-subtle">{q.help}</span></span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <ul className="card divide-y divide-line overflow-hidden" aria-label="Reminders">
              {(rules.data ?? []).map((r) => <RuleRow key={r.id} rule={r} company={r.legal_entity_id ? names.get(r.legal_entity_id) : undefined} onEdit={() => setEditing({ rule: r })} />)}
            </ul>
          )}
        </>
      ) : <DeliveryLog rules={rules.data ?? []} />}
      {editing && <RuleForm key={editing.rule?.id ?? "new"} rule={editing.rule} preset={editing.preset} onClose={() => setEditing(null)} />}
    </>
  );
}

function RuleRow({ rule, company, onEdit }: { rule: ReminderRule; company?: string; onEdit: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const toggle = useMutation({
    mutationFn: () => remindersApi.update(rule.id, { is_active: !rule.is_active, version: rule.version }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reminder-rules"] }),
    onError: (e) => toast.error("Couldn’t change the reminder", errorMessage(e)),
  });
  const Icon = ICON[rule.trigger];
  return (
    <li className={`flex flex-wrap items-center justify-between gap-3 px-5 py-4 ${rule.is_active ? "" : "opacity-70"}`}>
      <div className="flex min-w-0 items-start gap-3">
        <Icon size={18} className="mt-0.5 shrink-0 text-accent" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[13px] font-medium text-fg">{rule.name}</span>
            <StatusBadge status={rule.is_active ? "ACTIVE" : "INACTIVE"} label={rule.is_active ? "On" : "Paused"} />
          </div>
          <p className="mt-0.5 text-xs text-fg-muted">{describeRule(rule)}</p>
          <p className="mt-0.5 text-xs text-fg-subtle">{TRIGGERS[rule.trigger].label} · {company ?? "Whole group"}</p>
        </div>
      </div>
      <div className="flex gap-2">
        <button type="button" className="btn-ghost btn-sm" disabled={toggle.isPending} onClick={() => toggle.mutate()}>{rule.is_active ? "Pause" : "Resume"}</button>
        <button type="button" className="btn-secondary btn-sm" onClick={onEdit}><Pencil size={14} /> Edit</button>
      </div>
    </li>
  );
}

function DeliveryLog({ rules }: { rules: ReminderRule[] }) {
  const [ruleId, setRuleId] = useState("");
  const log = useQuery({ queryKey: ["reminder-deliveries", ruleId], queryFn: () => remindersApi.deliveries(ruleId || undefined) });
  const names = useMemo(() => new Map(rules.map((r) => [r.id, r.name])), [rules]);
  const rows = log.data ?? [];
  const failed = rows.filter((d) => d.status === "FAILED").length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select className="input w-auto" aria-label="Show mail for" value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
          <option value="">All reminders</option>
          {rules.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        {rows.length > 0 && <p className="text-xs text-fg-subtle">{rows.filter((d) => d.status === "SENT").length} sent · {rows.filter((d) => d.status === "PENDING").length} waiting · {failed} failed</p>}
      </div>
      {log.isPending ? <Skeleton className="h-40 rounded-xl" /> : log.isError ? <Notice title="Couldn’t load the log">{errorMessage(log.error)}</Notice>
        : rows.length === 0 ? <div className="card"><EmptyState icon={BellRing} title="Nothing sent yet" description="Mail appears here once a reminder has run." /></div>
        : (
          <div className="card overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-xs text-fg-muted"><tr><th className="px-4 py-2.5 font-medium">Date</th><th className="px-4 py-2.5 font-medium">Reminder</th><th className="px-4 py-2.5 font-medium">To</th><th className="px-4 py-2.5 font-medium">Status</th></tr></thead>
              <tbody className="divide-y divide-line">
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td className="whitespace-nowrap px-4 py-2.5">{format(parseISO(d.send_date), "d MMM yyyy")}</td>
                    <td className="px-4 py-2.5">{names.get(d.rule_id) ?? "Removed reminder"} <span className="text-xs text-fg-subtle">({d.audience === "EMPLOYEE" ? "the person" : "heads-up"})</span></td>
                    <td className="px-4 py-2.5">{d.recipient_email}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={d.status} label={d.status === "SENT" ? "Sent" : d.status === "FAILED" ? "Failed" : "Waiting"} tone={d.status === "SENT" ? "success" : d.status === "FAILED" ? "danger" : "warning"} />
                      {d.last_error && <span className="ml-2 text-xs text-fg-subtle">{d.last_error}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </div>
  );
}
