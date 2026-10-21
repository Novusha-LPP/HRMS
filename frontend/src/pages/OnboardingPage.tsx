import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { ChevronRight, ClipboardCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { onboardingApi } from "../api/onboarding";
import type { OnboardingCase } from "../api/onboarding";
import { OnboardingChecklist } from "../components/onboarding/OnboardingChecklist";
import { ChecklistTemplates } from "../components/onboarding/ChecklistTemplates";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Avatar } from "../components/ui/Avatar";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Notice, NoEmployeeRecord, Skeleton } from "../components/ui/Feedback";
import { usePeopleDirectory } from "../lib/usePeopleDirectory";

type Filter = "IN_PROGRESS" | "COMPLETED" | "ALL";

function HROnboardingView() {
  const { data, isPending: isLoading, isError, refetch } = useQuery<OnboardingCase[]>({
    queryKey: ["onboarding-cases-all"],
    queryFn: () => onboardingApi.getCases(),
  });
  const people = usePeopleDirectory(true);
  const [filter, setFilter] = useState<Filter>("IN_PROGRESS");
  const [openEmp, setOpenEmp] = useState<string | null>(null);

  const cases = data ?? [];
  const list = filter === "ALL" ? cases : cases.filter((c) => c.status === filter);

  if (isError) {
    return (
      <Notice title="Couldn’t load onboarding cases" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
        The onboarding API isn’t responding.
      </Notice>
    );
  }

  return (
    <>
      <div className="card overflow-hidden">
        <div className="px-5 pt-1">
          <Tabs
            value={filter}
            onChange={setFilter}
            items={[
              { value: "IN_PROGRESS", label: "In progress", count: isLoading ? undefined : cases.filter((c) => c.status === "IN_PROGRESS").length },
              { value: "COMPLETED", label: "Completed", count: isLoading ? undefined : cases.filter((c) => c.status === "COMPLETED").length },
              { value: "ALL", label: "All", count: isLoading ? undefined : cases.length },
            ]}
          />
        </div>
        {isLoading ? (
          <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : list.length === 0 ? (
          <EmptyState icon={ClipboardCheck} title="No onboarding cases" description="Cases are created when a new hire is assigned an onboarding plan." />
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>New hire</th><th>Joining date</th><th>Progress</th><th className="hidden sm:table-cell">Overdue</th><th>Status</th><th className="w-8" /></tr>
              </thead>
              <tbody>
                {list.map((c) => {
                  const name = people.get(c.employment_id);
                  const total = c.items?.length || c.total_items;
                  const done = c.items?.length ? c.items.filter((i) => ["COMPLETED", "SKIPPED"].includes(i.status)).length : c.completed_items;
                  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
                  return (
                    <tr key={c.id} onClick={() => setOpenEmp(c.employment_id)} className="group cursor-pointer">
                      <td>
                        <div className="flex items-center gap-3">
                          <Avatar name={name ?? c.employment_id} size="sm" employmentId={c.employment_id} />
                          <div className="min-w-0 leading-tight">
                            <p className="truncate font-medium text-fg">{name ?? "Unknown employee"}</p>
                            <p className="truncate font-mono text-[11px] text-fg-subtle">{c.employment_id}</p>
                          </div>
                        </div>
                      </td>
                      <td className="whitespace-nowrap tabular-nums">{c.hire_date ? format(new Date(c.hire_date), "d MMM yyyy") : "—"}</td>
                      <td>
                        <div className="flex items-center gap-2.5">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-xs tabular-nums text-fg-subtle">{done}/{total}</span>
                        </div>
                      </td>
                      <td className="hidden sm:table-cell">
                        {c.overdue_items > 0 ? <span className="badge badge-danger">{c.overdue_items}</span> : <span className="text-fg-subtle">—</span>}
                      </td>
                      <td><StatusBadge status={c.status} /></td>
                      <td><ChevronRight size={15} className="text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Sheet open={!!openEmp} onClose={() => setOpenEmp(null)} title={openEmp ? people.get(openEmp) ?? "Onboarding" : ""} description="Onboarding plan and task progress">
        {openEmp && <OnboardingChecklist employmentId={openEmp} bare />}
      </Sheet>
    </>
  );
}

type PageTab = "hires" | "checklists";

export function OnboardingPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  if (!user) return null;
  const isHR = user.role === "HR" || user.role === "SUPER_ADMIN";
  const canEditChecklists = user.permissions.includes("*") || user.permissions.includes("onboarding.write");
  const tab: PageTab = canEditChecklists && params.get("tab") === "checklists" ? "checklists" : "hires";

  return (
    <>
      <PageHeader
        title="Onboarding"
        description={isHR ? "Track new-hire onboarding plans and overdue tasks, and maintain the checklists they follow." : "Your onboarding tasks for getting started."}
      />
      {isHR && canEditChecklists && (
        <Tabs<PageTab>
          className="mb-6"
          value={tab}
          onChange={(t) => setParams(t === "hires" ? {} : { tab: t }, { replace: true })}
          items={[{ value: "hires", label: "New hires" }, { value: "checklists", label: "Checklists" }]}
        />
      )}
      {isHR
        ? tab === "checklists" ? <ChecklistTemplates /> : <HROnboardingView />
        : user.employmentId ? <OnboardingChecklist employmentId={user.employmentId} /> : <NoEmployeeRecord feature="onboarding checklist" />}
    </>
  );
}
