import { useState } from "react";
import type { FormEvent } from "react";
import { format } from "date-fns";
import { Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { leaveApi } from "../../api/leave";
import { rejoinApi, separationApi } from "../../api/people";
import type { RejoinMode, SeparationAction } from "../../api/people";
import { orgApi } from "../../api/org";
import { formatDateOnly } from "../../lib/dates";
import { ACTION_LABEL, MODE_LABEL } from "../../lib/rejoin";
import { Skeleton, Notice } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { UsageHelpButton } from "../ui/UsageHelpButton";
import { LifecycleReports } from "./LifecycleReports";

const today = () => format(new Date(), "yyyy-MM-dd");

/** What happens to unused leave when someone leaves, and how a company treats people who rejoin. */
export function LeaversSettings() {
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-fg-muted">
          Two company rules for people who leave. With no rule set, unused leave is left as it is when someone leaves,
          and a rejoin continues their earlier service.
        </p>
        <UsageHelpButton topic="leavers" label="How this works" />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <SeparationRules />
        <RejoinPolicies />
      </div>
      <LifecycleReports />
    </div>
  );
}

function useScopeNames() {
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const types = useQuery({ queryKey: ["leave-types"], queryFn: () => leaveApi.listTypes() });
  return {
    entities: entities.data ?? [],
    types: types.data ?? [],
    company: (id: string | null) => (id ? entities.data?.find((e) => e.id === id)?.name ?? "A company" : "Every company"),
    leaveType: (id: string | null) => (id ? types.data?.find((t) => t.id === id)?.name ?? "A leave type" : "Every leave type"),
  };
}

function SeparationRules() {
  const qc = useQueryClient();
  const toast = useToast();
  const names = useScopeNames();
  const rules = useQuery({ queryKey: ["separation-rules"], queryFn: () => separationApi.listRules() });
  const [form, setForm] = useState({ entity: "", type: "", action: "LAPSE" as SeparationAction, holdDays: "", cap: "", from: today() });
  const create = useMutation({
    mutationFn: () => separationApi.createRule({
      legal_entity_id: form.entity || null,
      leave_type_id: form.type || null,
      on_separation: form.action,
      hold_days: form.action === "HOLD" && form.holdDays !== "" ? Number(form.holdDays) : null,
      max_encash_days: form.action === "ENCASH" && form.cap !== "" ? Number(form.cap) : null,
      effective_from: form.from,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["separation-rules"] });
      toast.success("Rule added");
      setForm((f) => ({ ...f, holdDays: "", cap: "" }));
    },
    onError: (e) => toast.error("Couldn’t add the rule", errorMessage(e)),
  });
  const archive = useMutation({
    mutationFn: (id: string) => separationApi.archiveRule(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["separation-rules"] }); toast.success("Rule removed"); },
    onError: (e) => toast.error("Couldn’t remove the rule", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (!create.isPending) create.mutate(); };
  const encashable = names.types.filter((t) => t.encashable);

  return (
    <section className="card p-5" aria-labelledby="sep-rules">
      <h3 id="sep-rules" className="text-base font-semibold text-fg">Unused leave when someone leaves</h3>
      <p className="mt-1 text-[13px] text-fg-muted">
        Applied when a separation is recorded. The most specific rule in force on the last day wins: a company and a leave type, then the company, then the leave type, then everyone.
      </p>
      {rules.isPending ? <Skeleton className="mt-4 h-20 rounded-xl" /> : (rules.data ?? []).length === 0 ? (
        <p className="mt-4 text-[13px] text-fg-subtle" data-testid="no-separation-rules">No rules yet, so unused leave is left untouched when someone leaves.</p>
      ) : (
        <ul className="mt-4 divide-y divide-line rounded-xl border border-line" data-testid="separation-rules">
          {rules.data!.map((r) => (
            <li key={r.id} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
              <div className="min-w-0 flex-1">
                <p className="font-medium text-fg">
                  {ACTION_LABEL[r.on_separation]}
                  {r.on_separation === "HOLD" && (r.hold_days !== null ? ` for ${r.hold_days} days, then lapse` : " until they rejoin or HR decides")}
                  {r.on_separation === "ENCASH" && (r.max_encash_days !== null ? ` up to ${r.max_encash_days} days, the rest lapses` : " all of it")}
                </p>
                <p className="truncate text-xs text-fg-subtle">{names.company(r.legal_entity_id)} · {names.leaveType(r.leave_type_id)} · from {formatDateOnly(r.effective_from)}</p>
              </div>
              <button type="button" className="btn-ghost btn-sm" aria-label="Remove rule" onClick={() => archive.mutate(r.id)}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-5 grid grid-cols-2 gap-3" aria-label="Add a rule for leavers">
        <div>
          <label className="label" htmlFor="sr-entity">Company</label>
          <select id="sr-entity" className="input" value={form.entity} onChange={(e) => setForm({ ...form, entity: e.target.value })}>
            <option value="">Every company</option>
            {names.entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sr-type">Leave type</label>
          <select id="sr-type" className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            <option value="">Every leave type</option>
            {names.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sr-action">What happens</label>
          <select id="sr-action" className="input" value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value as SeparationAction })}>
            <option value="LAPSE">Lapse the unused balance</option>
            <option value="ENCASH" disabled={encashable.length === 0}>Pay it out (encash)</option>
            <option value="HOLD">Hold it for a while</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sr-from">Starts on</label>
          <input id="sr-from" type="date" className="input" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
        </div>
        {form.action === "HOLD" && (
          <div className="col-span-2">
            <label className="label" htmlFor="sr-hold">Hold for (days) <span className="font-normal text-fg-subtle">(blank = until they rejoin or HR decides)</span></label>
            <input id="sr-hold" type="number" min={0} className="input" value={form.holdDays} onChange={(e) => setForm({ ...form, holdDays: e.target.value })} />
          </div>
        )}
        {form.action === "ENCASH" && (
          <div className="col-span-2">
            <label className="label" htmlFor="sr-cap">Pay out at most (days) <span className="font-normal text-fg-subtle">(blank = all; the rest lapses)</span></label>
            <input id="sr-cap" type="number" min={0} step={0.5} className="input" value={form.cap} onChange={(e) => setForm({ ...form, cap: e.target.value })} />
            <p className="hint">Only leave types marked encashable are paid out; others are held instead.</p>
          </div>
        )}
        <div className="col-span-2">
          <button className="btn-primary btn-sm" type="submit" disabled={create.isPending}><Plus size={14} /> Add rule</button>
        </div>
      </form>
    </section>
  );
}

function RejoinPolicies() {
  const qc = useQueryClient();
  const toast = useToast();
  const names = useScopeNames();
  const policies = useQuery({ queryKey: ["rejoin-policies"], queryFn: () => rejoinApi.listPolicies() });
  const [form, setForm] = useState({ entity: "", mode: "CONTINUE" as RejoinMode, limit: "", from: today() });
  const create = useMutation({
    mutationFn: () => rejoinApi.createPolicy({
      legal_entity_id: form.entity || null,
      default_mode: form.mode,
      force_fresh_after_days: form.limit !== "" ? Number(form.limit) : null,
      effective_from: form.from,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rejoin-policies"] }); toast.success("Policy added"); },
    onError: (e) => toast.error("Couldn’t add the policy", errorMessage(e)),
  });
  const archive = useMutation({
    mutationFn: (id: string) => rejoinApi.archivePolicy(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rejoin-policies"] }); toast.success("Policy removed"); },
    onError: (e) => toast.error("Couldn’t remove the policy", errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (!create.isPending) create.mutate(); };

  return (
    <section className="card p-5" aria-labelledby="rejoin-policies">
      <h3 id="rejoin-policies" className="text-base font-semibold text-fg">When someone rejoins</h3>
      <p className="mt-1 text-[13px] text-fg-muted">
        The default for a rejoin, and the longest break that may still continue earlier service. A company&apos;s own policy wins over the general one.
      </p>
      {policies.isPending ? <Skeleton className="mt-4 h-20 rounded-xl" /> : (policies.data ?? []).length === 0 ? (
        <p className="mt-4 text-[13px] text-fg-subtle" data-testid="no-rejoin-policies">No policy yet, so a rejoin continues earlier service whatever the length of the break.</p>
      ) : (
        <ul className="mt-4 divide-y divide-line rounded-xl border border-line" data-testid="rejoin-policies">
          {policies.data!.map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
              <div className="min-w-0 flex-1">
                <p className="font-medium text-fg">
                  {MODE_LABEL[p.default_mode]}
                  {p.force_fresh_after_days !== null && ` · a break over ${p.force_fresh_after_days} days must start fresh`}
                </p>
                <p className="truncate text-xs text-fg-subtle">{names.company(p.legal_entity_id)} · from {formatDateOnly(p.effective_from)}</p>
              </div>
              <button type="button" className="btn-ghost btn-sm" aria-label="Remove policy" onClick={() => archive.mutate(p.id)}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-5 grid grid-cols-2 gap-3" aria-label="Add a rejoin policy">
        <div>
          <label className="label" htmlFor="rp-entity">Company</label>
          <select id="rp-entity" className="input" value={form.entity} onChange={(e) => setForm({ ...form, entity: e.target.value })}>
            <option value="">Every company</option>
            {names.entities.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rp-mode">By default</label>
          <select id="rp-mode" className="input" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as RejoinMode })}>
            <option value="CONTINUE">{MODE_LABEL.CONTINUE}</option>
            <option value="FRESH">{MODE_LABEL.FRESH}</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rp-limit">Longest break to continue (days)</label>
          <input id="rp-limit" type="number" min={0} className="input" placeholder="No limit" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} />
        </div>
        <div>
          <label className="label" htmlFor="rp-from">Starts on</label>
          <input id="rp-from" type="date" className="input" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
        </div>
        <div className="col-span-2">
          <button className="btn-primary btn-sm" type="submit" disabled={create.isPending}><Plus size={14} /> Add policy</button>
        </div>
      </form>
      <Notice tone="info" title="Gratuity">
        If gratuity was paid when someone left, a rejoin always starts fresh, whatever this policy says.
      </Notice>
    </section>
  );
}
