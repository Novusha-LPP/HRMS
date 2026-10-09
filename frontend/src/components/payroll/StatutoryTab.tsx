import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { BadgeCheck, Landmark, Plus } from "lucide-react";
import { payrollApi } from "../../api/payroll";
import type { StatutoryRule } from "../../api/payroll";
import { useAuth } from "../../context/AuthContext";
import { inr } from "../../lib/money";
import { Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const day = (d: string) => format(new Date(`${d}T00:00:00`), "d MMM yyyy");

function ruleValue(r: Pick<StatutoryRule, "unit" | "value">) {
  const n = Number(r.value);
  if (r.unit === "PERCENT") return `${+n.toFixed(4)}%`;
  if (r.unit === "FLAG") return n >= 1 ? "Yes" : "No";
  return inr(n);
}

/** PF and ESIC values as data: dated, sourced, and verified by someone other than who entered them. */
export function StatutoryTab({ canWrite, canReview }: { canWrite: boolean; canReview: boolean }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const rules = useQuery({ queryKey: ["payroll", "statutory-rules"], queryFn: () => payrollApi.statutoryRules() });
  const [adding, setAdding] = useState<StatutoryRule | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["payroll"] });

  const load = useMutation({
    mutationFn: () => payrollApi.loadIndiaDefaults(),
    onSuccess: () => { refresh(); toast.success("India defaults loaded", "Ask the payroll reviewer to verify each value."); },
    onError: (e) => toast.error("Couldn’t load the defaults", errorMessage(e)),
  });
  const verify = useMutation({
    mutationFn: (r: StatutoryRule) => payrollApi.verifyStatutoryRule(r.id),
    onSuccess: (r) => { refresh(); toast.success("Verified", r.label); },
    onError: (e) => toast.error("Couldn’t verify", errorMessage(e)),
  });

  if (rules.isError) return <Notice title="Couldn’t load statutory values">The payroll API isn’t responding.</Notice>;
  if (rules.isPending) return <Skeleton className="h-64 rounded-xl" />;

  const today = format(new Date(), "yyyy-MM-dd");
  const current = rules.data.filter((r) => r.effective_from <= today && (!r.effective_to || r.effective_to > today));
  const upcoming = rules.data.filter((r) => r.effective_from > today);
  const past = rules.data.filter((r) => r.effective_to && r.effective_to <= today);
  const unverified = rules.data.filter((r) => !r.verified && (!r.effective_to || r.effective_to > today)).length;

  if (!rules.data.length) {
    return (
      <div className="card">
        <EmptyState icon={Landmark} title="No statutory values yet"
          description="Payroll needs the PF and ESIC rates and wage ceilings. Load the India defaults, then have the payroll reviewer check each one against the current EPFO and ESIC notifications."
          action={canWrite ? <button className="btn-primary" onClick={() => load.mutate()} disabled={load.isPending}>Load India defaults</button> : undefined} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-fg-muted">
          Rates and ceilings payroll calculates with. A change takes effect from its date; past payroll keeps the value it used.
          Someone other than the person who entered a value must verify it.
        </p>
        {canWrite && <button className="btn-secondary" onClick={() => load.mutate()} disabled={load.isPending}>Load missing India defaults</button>}
      </div>
      {unverified > 0 && (
        <Notice title={`${unverified} value${unverified === 1 ? "" : "s"} not verified`}>
          Salary breakups are marked provisional until the payroll reviewer verifies them against the official notifications.
        </Notice>
      )}

      <RuleTable title="In force today" rules={current} me={user?.id} canWrite={canWrite} canReview={canReview}
        onVerify={(r) => verify.mutate(r)} verifying={verify.isPending} onNewValue={setAdding} />
      {upcoming.length > 0 && <RuleTable title="Coming up" rules={upcoming} me={user?.id} canReview={canReview} onVerify={(r) => verify.mutate(r)} verifying={verify.isPending} />}
      {past.length > 0 && <RuleTable title="Earlier values" rules={past} muted />}

      <NewValueSheet key={adding?.id ?? "none"} rule={adding} onClose={() => setAdding(null)} />
    </div>
  );
}

function RuleTable({ title, rules, me, canWrite, canReview, onVerify, verifying, onNewValue, muted }: {
  title: string;
  rules: StatutoryRule[];
  me?: string;
  canWrite?: boolean;
  canReview?: boolean;
  onVerify?: (r: StatutoryRule) => void;
  verifying?: boolean;
  onNewValue?: (r: StatutoryRule) => void;
  muted?: boolean;
}) {
  return (
    <section className="card overflow-hidden">
      <p className="eyebrow px-5 pt-4">{title}</p>
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr><th>Rule</th><th className="text-right">Value</th><th>Applies</th><th className="hidden lg:table-cell">Source</th><th>Verified</th><th className="w-px" /></tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className={muted ? "opacity-70" : undefined}>
                <td>
                  <p className="font-medium text-fg">{r.label}</p>
                  <p className="font-mono text-[11px] text-fg-subtle">{r.rule_code}</p>
                </td>
                <td className="whitespace-nowrap text-right tabular-nums text-fg">{ruleValue(r)}</td>
                <td className="whitespace-nowrap text-xs">
                  {day(r.effective_from)}{r.effective_to ? ` – ${day(r.effective_to)}` : " onwards"}
                </td>
                <td className="hidden max-w-xs lg:table-cell"><p className="line-clamp-2 text-xs" title={r.source}>{r.source}</p></td>
                <td className="whitespace-nowrap">
                  {r.verified
                    ? <span className="badge badge-success" title={r.verified_at ? `on ${format(new Date(r.verified_at), "d MMM yyyy")}` : undefined}><BadgeCheck size={12} /> {r.verified_by_name ?? "Verified"}</span>
                    : <span className="badge badge-warning">Not verified</span>}
                </td>
                <td className="whitespace-nowrap text-right">
                  <div className="flex justify-end gap-1.5">
                    {canReview && !r.verified && onVerify && (r.recorded_by_id && r.recorded_by_id === me
                      ? <span className="self-center px-2 text-xs text-fg-subtle" title="Someone other than the person who entered a value must verify it.">You entered this</span>
                      : <button className="btn-secondary btn-sm" onClick={() => onVerify(r)} disabled={verifying}
                        title={r.recorded_by_name ? `Entered by ${r.recorded_by_name}` : undefined}>Verify</button>
                    )}
                    {canWrite && onNewValue && <button className="btn-ghost btn-sm" onClick={() => onNewValue(r)}><Plus size={13} /> New value</button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function NewValueSheet({ rule, onClose }: { rule: StatutoryRule | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState(rule ? String(+Number(rule.value)) : "");
  const [from, setFrom] = useState("");
  const [source, setSource] = useState("");
  const [tried, setTried] = useState(false);

  const problems: string[] = [];
  const numeric = value.trim().replace(/,/g, "");
  if (!/^\d+(\.\d{1,4})?$/.test(numeric)) problems.push("Enter the value as a number.");
  else if (rule?.unit === "PERCENT" && Number(numeric) > 100) problems.push("A percentage can't be more than 100.");
  else if (rule?.unit === "FLAG" && !["0", "1"].includes(numeric)) problems.push("Enter 1 for yes or 0 for no.");
  if (!from) problems.push("Choose the date it applies from.");
  else if (rule && from <= rule.effective_from) problems.push(`It must start after ${day(rule.effective_from)}, when the current value started.`);
  if (source.trim().length < 3) problems.push("Say where the value comes from (the notification or circular).");

  const save = useMutation({
    mutationFn: () => payrollApi.createStatutoryRule({ rule_code: rule!.rule_code, value: numeric, effective_from: from, source: source.trim() }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["payroll"] });
      toast.success("New value recorded", `${r.label}: ${ruleValue(r)} from ${day(r.effective_from)}`);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t record the value", errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };

  return (
    <Sheet open={rule !== null} onClose={onClose} title={rule ? `New value: ${rule.label}` : ""}
      description="The current value ends the day before the new one starts. The new value needs verifying by the payroll reviewer."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="rule-form" disabled={save.isPending}>{save.isPending ? "Saving…" : "Record value"}</button>
      </>}>
      {rule && (
        <form id="rule-form" onSubmit={submit} className="space-y-4">
          <p className="text-sm text-fg-muted">Current: <span className="font-medium text-fg">{ruleValue(rule)}</span> from {day(rule.effective_from)}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="rule-value">New value {rule.unit === "PERCENT" ? "(%)" : rule.unit === "AMOUNT" ? "(₹ a month)" : "(1 = yes, 0 = no)"}</label>
              <input id="rule-value" className="input" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="rule-from">Applies from</label>
              <input id="rule-from" type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="rule-source">Source</label>
            <textarea id="rule-source" className="input" rows={3} placeholder="e.g. ESIC notification no. … dated …" value={source} onChange={(e) => setSource(e.target.value)} />
          </div>
          {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        </form>
      )}
    </Sheet>
  );
}
