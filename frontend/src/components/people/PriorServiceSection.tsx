import { useState } from "react";
import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { priorServiceApi } from "../../api/people";
import { formatDateOnly } from "../../lib/dates";
import { describeService } from "../../lib/rejoin";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { UsageHelpButton } from "../ui/UsageHelpButton";

/** Work for earlier employers that the company recognises for leave eligibility and gratuity. */
export function PriorServiceSection({ personId }: { personId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["prior-service", personId];
  const list = useQuery({ queryKey: key, queryFn: () => priorServiceApi.list(personId), retry: false });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ employer: "", from: "", to: "", leave: false, gratuity: false, note: "" });

  const add = useMutation({
    mutationFn: () => priorServiceApi.add(personId, {
      employer_name: form.employer.trim(), from_date: form.from, to_date: form.to,
      recognised_for_leave: form.leave, recognised_for_gratuity: form.gratuity,
      note: form.note.trim() || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      toast.success("Earlier service recorded");
      setForm({ employer: "", from: "", to: "", leave: false, gratuity: false, note: "" });
      setAdding(false);
    },
    onError: (e) => toast.error("Couldn’t record the earlier service", errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => priorServiceApi.remove(personId, id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: key }); toast.success("Removed"); },
    onError: (e) => toast.error("Couldn’t remove it", errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form.employer.trim() && form.from && form.to && !add.isPending) add.mutate();
  };

  if (list.isPending) return <Skeleton className="h-16 rounded-xl" />;
  if (list.isError) return null;
  const items = list.data.items;

  return (
    <div data-testid="prior-service">
      <div className="mb-2 flex items-center justify-between">
        <p className="eyebrow">Earlier service <UsageHelpButton topic="prior-service" iconOnly /></p>
        {!adding && <button type="button" className="btn-ghost btn-sm" onClick={() => setAdding(true)}><Plus size={14} /> Add</button>}
      </div>
      {items.length === 0 && !adding && <p className="text-[13px] text-fg-subtle">No work for earlier employers is recorded.</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {items.map((p) => (
            <li key={p.id} className="flex items-start gap-3 px-4 py-2.5 text-[13px]">
              <div className="min-w-0 flex-1">
                <p className="font-medium text-fg">{p.employer_name}</p>
                <p className="text-xs text-fg-subtle">
                  {formatDateOnly(p.from_date)} – {formatDateOnly(p.to_date)} · {describeService(p.months)}
                  {p.recognised_for_leave && " · counts for leave"}{p.recognised_for_gratuity && " · counts for gratuity"}
                </p>
                {p.note && <p className="text-xs text-fg-subtle">{p.note}</p>}
              </div>
              <button type="button" className="btn-ghost btn-sm" aria-label={`Remove ${p.employer_name}`} onClick={() => remove.mutate(p.id)}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      {items.length > 0 && (
        <p className="mt-2 text-xs text-fg-subtle">
          Recognised for leave: {describeService(list.data.recognised_leave_months)} · for gratuity: {list.data.recognised_gratuity_days} days
        </p>
      )}
      {adding && (
        <form onSubmit={submit} className="mt-3 space-y-3 rounded-xl border border-line p-4" aria-label="Record earlier service">
          <div>
            <label className="label" htmlFor="ps-employer">Employer</label>
            <input id="ps-employer" className="input" maxLength={200} value={form.employer} onChange={(e) => setForm({ ...form, employer: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label" htmlFor="ps-from">From</label><input id="ps-from" type="date" className="input" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} /></div>
            <div><label className="label" htmlFor="ps-to">To</label><input id="ps-to" type="date" className="input" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} /></div>
          </div>
          <label className="flex items-start gap-2 text-[13px]"><input type="checkbox" checked={form.leave} onChange={(e) => setForm({ ...form, leave: e.target.checked })} /><span>Count towards the service a leave rule asks for</span></label>
          <label className="flex items-start gap-2 text-[13px]"><input type="checkbox" checked={form.gratuity} onChange={(e) => setForm({ ...form, gratuity: e.target.checked })} /><span>Count towards service for gratuity</span></label>
          <div><label className="label" htmlFor="ps-note">Note <span className="font-normal text-fg-subtle">(optional)</span></label><input id="ps-note" className="input" maxLength={500} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></div>
          <div className="flex gap-2">
            <button className="btn-primary btn-sm" type="submit" disabled={add.isPending}>Save</button>
            <button className="btn-secondary btn-sm" type="button" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
