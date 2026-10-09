import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ClipboardCheck, Pencil, Plus, Star, Trash2, X } from "lucide-react";
import { onboardingApi } from "../../api/onboarding";
import type { OnboardingAssignee, OnboardingItemType, OnboardingTemplate, OnboardingTemplateItem } from "../../api/onboarding";
import { ConfirmDialog, Sheet } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const TYPE_LABEL: Record<OnboardingItemType, string> = {
  TASK: "Task", DOCUMENT: "Document", FORM: "Form", POLICY_ACK: "Policy acknowledgement",
  IT_SETUP: "IT setup", TRAINING: "Training",
};
const OWNER_LABEL: Record<OnboardingAssignee, string> = { HR: "HR", EMPLOYEE: "New hire", MANAGER: "Manager", IT: "IT" };

function dueLabel(days: number) {
  if (days === 0) return "On joining day";
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} before joining`;
  return `Day ${days}`;
}

/** HR's onboarding checklists: start from the standard one, edit, set the default, retire. */
export function ChecklistTemplates() {
  const qc = useQueryClient();
  const toast = useToast();
  const templates = useQuery({ queryKey: ["onboarding-templates"], queryFn: () => onboardingApi.listTemplates() });
  const [editing, setEditing] = useState<OnboardingTemplate | "new" | null>(null);
  const [retiring, setRetiring] = useState<OnboardingTemplate | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["onboarding-templates"] });

  const standard = useMutation({
    mutationFn: () => onboardingApi.createStandardTemplate(),
    onSuccess: (t) => { refresh(); toast.success("Standard checklist added", t.name); },
    onError: (e) => toast.error("Couldn’t add the standard checklist", errorMessage(e)),
  });
  const makeDefault = useMutation({
    mutationFn: (t: OnboardingTemplate) => onboardingApi.replaceTemplate(t.id, { name: t.name, description: t.description, is_default: true, items: t.items.map(stripId) }),
    onSuccess: (t) => { refresh(); toast.success("Default checklist changed", t.name); },
    onError: (e) => toast.error("Couldn’t change the default", errorMessage(e)),
  });
  const retire = useMutation({
    mutationFn: (t: OnboardingTemplate) => onboardingApi.deactivateTemplate(t.id),
    onSuccess: (t) => { refresh(); toast.success("Checklist retired", t.name); setRetiring(null); },
    onError: (e) => toast.error("Couldn’t retire the checklist", errorMessage(e)),
  });

  if (templates.isError) {
    return <Notice title="Couldn’t load checklists">The onboarding API isn’t responding.</Notice>;
  }
  if (templates.isPending) return <Skeleton className="h-48 rounded-xl" />;
  const list = [...templates.data].sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">Checklists new hires get. Editing one doesn’t change onboarding that has already started.</p>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => standard.mutate()} disabled={standard.isPending}>Add standard checklist</button>
          <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} /> New checklist</button>
        </div>
      </div>

      {!list.length ? (
        <div className="card">
          <EmptyState icon={ClipboardCheck} title="No checklists yet"
            description="Start from the standard checklist (documents, bank details, policies, IT setup, induction) and adjust it, or build your own."
            action={<button className="btn-primary" onClick={() => standard.mutate()} disabled={standard.isPending}>Use the standard checklist</button>} />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {list.map((t) => (
            <div key={t.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-semibold text-fg">{t.name}</p>
                  {t.description && <p className="mt-0.5 text-xs text-fg-muted">{t.description}</p>}
                </div>
                {t.is_default && <span className="badge badge-success shrink-0">Default</span>}
              </div>
              <ol className="mt-3 space-y-1 text-[13px]">
                {t.items.slice(0, 5).map((i) => (
                  <li key={i.id ?? i.title} className="flex items-baseline gap-2">
                    <span className="w-28 shrink-0 text-xs text-fg-subtle">{dueLabel(i.due_days_from_hire)}</span>
                    <span className="truncate text-fg">{i.title}</span>
                    {!i.required && <span className="text-xs text-fg-subtle">(optional)</span>}
                  </li>
                ))}
                {t.items.length > 5 && <li className="text-xs text-fg-subtle">and {t.items.length - 5} more</li>}
              </ol>
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                <button className="btn-secondary btn-sm" onClick={() => setEditing(t)}><Pencil size={13} /> Edit</button>
                {!t.is_default && (
                  <>
                    <button className="btn-ghost btn-sm" onClick={() => makeDefault.mutate(t)} disabled={makeDefault.isPending}><Star size={13} /> Make default</button>
                    <button className="btn-ghost btn-sm hover:text-danger" onClick={() => setRetiring(t)}><Trash2 size={13} /> Retire</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <ChecklistEditor key={editing === "new" ? "new" : editing?.id ?? "none"} template={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={retiring !== null}
        onClose={() => setRetiring(null)}
        onConfirm={() => retiring && retire.mutate(retiring)}
        loading={retire.isPending}
        title={retiring ? `Retire “${retiring.name}”?` : "Retire checklist?"}
        description="It can no longer be chosen for new hires. Onboarding already started with it is not affected."
        confirmLabel="Retire"
      />
    </div>
  );
}

function stripId(i: OnboardingTemplateItem): Omit<OnboardingTemplateItem, "id"> {
  return {
    title: i.title, description: i.description, item_type: i.item_type, assignee_type: i.assignee_type,
    due_days_from_hire: i.due_days_from_hire, required: i.required, sequence: i.sequence,
  };
}

type Draft = Omit<OnboardingTemplateItem, "id" | "sequence"> & { key: number; due: string };

let nextKey = 1;
const blankItem = (): Draft => ({
  key: nextKey++, title: "", description: null, item_type: "TASK", assignee_type: "HR",
  due_days_from_hire: 0, due: "0", required: true,
});

function ChecklistEditor({ template, onClose }: { template: OnboardingTemplate | "new" | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const existing = template && template !== "new" ? template : null;
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [isDefault, setIsDefault] = useState(existing?.is_default ?? false);
  const [items, setItems] = useState<Draft[]>(() =>
    existing?.items.length
      ? [...existing.items].sort((a, b) => a.sequence - b.sequence).map((i) => ({ ...stripId(i), key: nextKey++, due: String(i.due_days_from_hire) }))
      : [blankItem()],
  );
  const [tried, setTried] = useState(false);

  const update = (key: number, patch: Partial<Draft>) => setItems((list) => list.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  const move = (index: number, by: -1 | 1) => setItems((list) => {
    const next = [...list];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row);
    return next;
  });

  const problems: string[] = [];
  if (!name.trim()) problems.push("Give the checklist a name.");
  if (!items.length) problems.push("Add at least one item.");
  if (items.some((i) => !i.title.trim())) problems.push("Every item needs a title.");
  if (items.some((i) => !/^-?\d+$/.test(i.due.trim()) || Number(i.due) < -90 || Number(i.due) > 365)) problems.push("Due days must be whole numbers between -90 and 365.");

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(), description: description.trim() || null, is_default: isDefault,
        items: items.map((i, index) => ({
          title: i.title.trim(), description: i.description, item_type: i.item_type, assignee_type: i.assignee_type,
          due_days_from_hire: Number(i.due), required: i.required, sequence: index,
        })),
      };
      return existing ? onboardingApi.replaceTemplate(existing.id, body) : onboardingApi.createTemplate(body);
    },
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["onboarding-templates"] });
      toast.success(existing ? "Checklist saved" : "Checklist created", t.name);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t save the checklist", errorMessage(e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };

  return (
    <Sheet
      open={template !== null}
      onClose={onClose}
      title={existing ? `Edit “${existing.name}”` : "New onboarding checklist"}
      description={existing ? "Saving creates a new version. Onboarding already started keeps the checklist it was given." : "The tasks a new hire, HR, IT and the manager complete around the joining date."}
      className="max-w-3xl"
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="checklist-form" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save checklist"}</button>
      </>}
    >
      <form id="checklist-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="cl-name">Name</label>
            <input id="cl-name" className="input" placeholder="e.g. Plant worker onboarding" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="cl-desc">Description <span className="font-normal text-fg-subtle">(optional)</span></label>
            <input id="cl-desc" className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-fg">
          <input type="checkbox" className="checkbox" checked={isDefault} disabled={existing?.is_default} onChange={(e) => setIsDefault(e.target.checked)} />
          Default checklist for new hires {existing?.is_default && <span className="text-xs text-fg-subtle">(make another one the default to change this)</span>}
        </label>

        <div>
          <p className="eyebrow mb-2">Items</p>
          <ol className="space-y-2">
            {items.map((i, index) => (
              <li key={i.key} className="rounded-xl border border-line p-3">
                <div className="flex items-start gap-2">
                  <span className="mt-2 w-5 shrink-0 text-right text-xs tabular-nums text-fg-subtle">{index + 1}</span>
                  <div className="min-w-0 flex-1 space-y-2">
                    <input aria-label={`Item ${index + 1} title`} className="input" placeholder="e.g. Submit identity documents" value={i.title} onChange={(e) => update(i.key, { title: e.target.value })} />
                    <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
                      <label className="block">
                        <span className="mb-1 block text-[11px] text-fg-subtle">Type</span>
                        <select className="input w-48" value={i.item_type} onChange={(e) => update(i.key, { item_type: e.target.value as OnboardingItemType })}>
                          {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-[11px] text-fg-subtle">Done by</span>
                        <select className="input w-32" value={i.assignee_type} onChange={(e) => update(i.key, { assignee_type: e.target.value as OnboardingAssignee })}>
                          {Object.entries(OWNER_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-[11px] text-fg-subtle">Due (day)</span>
                        <input className="input w-20" inputMode="numeric" value={i.due} onChange={(e) => update(i.key, { due: e.target.value })} />
                      </label>
                      <span className="pb-2.5 text-xs text-fg-subtle">{/^-?\d+$/.test(i.due.trim()) ? dueLabel(Number(i.due)) : ""}</span>
                      <label className="flex items-center gap-2 pb-2.5 text-xs text-fg-muted">
                        <input type="checkbox" className="checkbox" checked={i.required} onChange={(e) => update(i.key, { required: e.target.checked })} />
                        Required
                      </label>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col gap-1">
                    <button type="button" className="btn-icon" aria-label={`Move item ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={13} /></button>
                    <button type="button" className="btn-icon" aria-label={`Move item ${index + 1} down`} disabled={index === items.length - 1} onClick={() => move(index, 1)}><ArrowDown size={13} /></button>
                    <button type="button" className="btn-icon hover:text-danger" aria-label={`Remove item ${index + 1}`} disabled={items.length === 1} onClick={() => setItems((list) => list.filter((x) => x.key !== i.key))}><X size={13} /></button>
                  </div>
                </div>
              </li>
            ))}
          </ol>
          <button type="button" className="btn-ghost btn-sm mt-2" onClick={() => setItems((list) => [...list, blankItem()])}><Plus size={13} /> Add item</button>
          <p className="mt-1 text-xs text-fg-subtle">Due day counts from the joining date: 0 is the joining day, 7 is a week later, -3 is three days before joining.</p>
        </div>

        {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      </form>
    </Sheet>
  );
}
