import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, FileText, ListChecks, FileSignature, Laptop, ClipboardList, GraduationCap, CalendarClock, ClipboardCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { format, isAfter } from "date-fns";
import { onboardingApi } from "../../api/onboarding";
import type { OnboardingCase, OnboardingItem } from "../../api/onboarding";
import { StatusBadge, humanize } from "../ui/StatusBadge";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const TYPE_ICON: Record<string, LucideIcon> = {
  DOCUMENT: FileText,
  TASK: ListChecks,
  POLICY_ACK: FileSignature,
  IT_SETUP: Laptop,
  FORM: ClipboardList,
  TRAINING: GraduationCap,
};

function ItemRow({ item, caseId }: { item: OnboardingItem; caseId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const [notes, setNotes] = useState(item.notes ?? "");

  const mutation = useMutation({
    mutationFn: (status: string) => onboardingApi.updateItem(item.id, status, notes || undefined),
    onSuccess: (_, status) => {
      qc.invalidateQueries({ queryKey: ["onboarding-case", caseId] });
      qc.invalidateQueries({ queryKey: ["onboarding-cases"] });
      qc.invalidateQueries({ queryKey: ["onboarding-cases-all"] });
      toast.success(status === "COMPLETED" ? "Task completed" : "Task skipped", item.title);
      setExpanded(false);
    },
    onError: (e) => toast.error("Couldn’t update task", errorMessage(e)),
  });

  const done = item.status === "COMPLETED" || item.status === "SKIPPED";
  const overdue = !done && !!item.due_date && isAfter(new Date(), new Date(item.due_date));
  const Icon = TYPE_ICON[item.item_type] ?? ListChecks;

  return (
    <li className={`rounded-xl border transition-colors ${overdue ? "border-danger/30 bg-danger/[0.03]" : "border-line bg-surface"}`}>
      <div className="flex items-center gap-3 px-3.5 py-3">
        <button
          onClick={() => !done && mutation.mutate("COMPLETED")}
          disabled={done || mutation.isPending}
          aria-label={done ? "Completed" : `Mark “${item.title}” complete`}
          className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border transition-colors ${
            item.status === "COMPLETED"
              ? "border-success bg-success text-white dark:text-zinc-950"
              : done
                ? "border-line-strong bg-muted text-fg-subtle"
                : "border-line-strong hover:border-brand-500 hover:bg-brand-500/10"
          }`}
        >
          {done && <Check size={12} strokeWidth={3} />}
        </button>
        <button onClick={() => !done && setExpanded((x) => !x)} className="flex min-w-0 flex-1 items-center gap-3 text-left" disabled={done}>
          <Icon size={15} className="shrink-0 text-fg-subtle" />
          <span className="min-w-0 flex-1">
            <span className={`block truncate text-[13px] font-medium ${done ? "text-fg-subtle line-through decoration-line-strong" : "text-fg"}`}>
              {item.title}
              {!item.required && <span className="ml-1.5 font-normal text-fg-subtle no-underline">· optional</span>}
            </span>
            {item.due_date && !done && (
              <span className={`flex items-center gap-1 text-xs ${overdue ? "font-medium text-danger" : "text-fg-subtle"}`}>
                <CalendarClock size={11} /> {overdue ? "Overdue · was due" : "Due"} {format(new Date(item.due_date), "d MMM")}
              </span>
            )}
          </span>
          {item.status === "SKIPPED" && <StatusBadge status="SKIPPED" dot={false} />}
          {!done && <ChevronDown size={15} className={`shrink-0 text-fg-subtle transition-transform ${expanded ? "rotate-180" : ""}`} />}
        </button>
      </div>

      {expanded && !done && (
        <div className="space-y-3 border-t border-line px-3.5 py-3 pl-[46px] animate-fade-in">
          {item.description && <p className="text-[13px] text-fg-muted">{item.description}</p>}
          <textarea className="input" rows={2} placeholder="Add a note (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex gap-2">
            <button onClick={() => mutation.mutate("COMPLETED")} disabled={mutation.isPending} className="btn-primary btn-sm">
              <Check size={13} /> Mark complete
            </button>
            {!item.required && (
              <button onClick={() => mutation.mutate("SKIPPED")} disabled={mutation.isPending} className="btn-ghost btn-sm">Skip</button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export function OnboardingChecklist({ employmentId, bare, hideWhenEmpty }: {
  employmentId: string;
  bare?: boolean;
  hideWhenEmpty?: boolean;
}) {
  const { data: cases, isPending: isLoading, isError } = useQuery<OnboardingCase[]>({
    queryKey: ["onboarding-cases", employmentId],
    queryFn: () => onboardingApi.getCases(employmentId),
  });

  const activeCase = cases?.find((c) => c.status === "IN_PROGRESS") ?? cases?.[0];

  const { data: detail } = useQuery<OnboardingCase>({
    queryKey: ["onboarding-case", activeCase?.id],
    queryFn: () => onboardingApi.getCase(activeCase!.id),
    enabled: !!activeCase?.id,
  });

  const wrap = bare ? "" : "card p-5";

  if (isLoading) return <div className={wrap}><Skeleton className="mb-4 h-5 w-40" /><Skeleton className="h-24" /></div>;
  if (!activeCase) {
    if (hideWhenEmpty) return null;
    return (
      <div className={bare ? "" : "card"}>
        <EmptyState
          icon={ClipboardCheck}
          title={isError ? "Couldn’t load onboarding" : "No onboarding in progress"}
          description={isError ? "The onboarding API isn’t responding." : "When an onboarding plan is assigned, your tasks will appear here."}
        />
      </div>
    );
  }

  const c = detail ?? activeCase;
  const pct = c.total_items > 0 ? Math.round((c.completed_items / c.total_items) * 100) : 0;
  const grouped: Record<string, OnboardingItem[]> = {};
  for (const item of [...c.items].sort((a, b) => a.sequence - b.sequence)) {
    (grouped[item.assignee_type] ??= []).push(item);
  }

  return (
    <div className={wrap}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="card-title">Onboarding checklist</h3>
          <p className="card-desc">Started {format(new Date(c.started_at ?? c.hire_date), "d MMM yyyy")}</p>
        </div>
        <StatusBadge status={c.status} />
      </div>

      <div className="mt-4 flex items-center gap-4">
        <p className="text-2xl font-semibold tabular-nums text-fg">{pct}%</p>
        <div className="flex-1">
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-brand-500 transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1.5 text-xs text-fg-subtle">
            {c.completed_items} of {c.total_items} tasks done
            {c.overdue_items > 0 && <span className="font-medium text-danger"> · {c.overdue_items} overdue</span>}
          </p>
        </div>
      </div>

      <div className="mt-6 space-y-5">
        {Object.entries(grouped).map(([group, items]) => (
          <section key={group}>
            <p className="eyebrow mb-2">{humanize(group)}</p>
            <ul className="space-y-2">
              {items.map((item) => <ItemRow key={item.id} item={item} caseId={c.id} />)}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
