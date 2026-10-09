import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Lock } from "lucide-react";
import { payrollApi } from "../api/payroll";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { EmptyState } from "../components/ui/Feedback";
import { SalariesTab } from "../components/payroll/SalariesTab";
import { StructuresTab } from "../components/payroll/StructuresTab";
import { ComponentsTab } from "../components/payroll/ComponentsTab";
import { StatutoryTab } from "../components/payroll/StatutoryTab";

type PageTab = "salaries" | "structures" | "components" | "statutory";
const TABS: PageTab[] = ["salaries", "structures", "components", "statutory"];

/**
 * Payroll set-up: statutory values, pay components, salary structures and each employee's salary.
 * Visible to the payroll roles the Admin grants (payroll.read); HR managers don't see salaries.
 */
export function PayrollPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const has = (p: string) => !!user && (user.permissions.includes("*") || user.permissions.includes(p));
  const canRead = has("payroll.read");
  const canWrite = has("payroll.write");
  const canReview = has("payroll.review");
  const requested = params.get("tab") as PageTab | null;
  const tab: PageTab = requested && TABS.includes(requested) ? requested : "salaries";

  if (!user) return null;
  if (!canRead) {
    return (
      <>
        <PageHeader title="Payroll" />
        <div className="card">
          <EmptyState icon={Lock} title="Payroll is restricted" description="Only the payroll administrator, approver and reviewer can see salaries. Ask your Admin if you need access." />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Payroll"
        description="Salary structures, each employee's salary, and the PF and ESIC values payroll calculates with."
      />
      <SetupSteps canWrite={canWrite} go={(t) => setParams({ tab: t }, { replace: true })} />
      <Tabs<PageTab>
        className="mb-6"
        value={tab}
        onChange={(t) => setParams(t === "salaries" ? {} : { tab: t }, { replace: true })}
        items={[
          { value: "salaries", label: "Salaries" },
          { value: "structures", label: "Structures" },
          { value: "components", label: "Components" },
          { value: "statutory", label: "Statutory values" },
        ]}
      />
      {tab === "salaries" && <SalariesTab canWrite={canWrite} />}
      {tab === "structures" && <StructuresTab canWrite={canWrite} />}
      {tab === "components" && <ComponentsTab canWrite={canWrite} />}
      {tab === "statutory" && <StatutoryTab canWrite={canWrite} canReview={canReview} />}
    </>
  );
}

/** First-run guide: shown until statutory values are verified and a structure exists. */
function SetupSteps({ canWrite, go }: { canWrite: boolean; go: (tab: PageTab) => void }) {
  const rules = useQuery({ queryKey: ["payroll", "statutory-rules"], queryFn: () => payrollApi.statutoryRules() });
  const structures = useQuery({ queryKey: ["payroll", "structures"], queryFn: () => payrollApi.structures() });
  if (!rules.data || !structures.data) return null;

  const loaded = rules.data.length > 0;
  const verified = loaded && rules.data.every((r) => r.verified || (r.effective_to !== null && r.effective_to <= new Date().toISOString().slice(0, 10)));
  const hasStructure = structures.data.length > 0;
  if (loaded && verified && hasStructure) return null;

  const steps: { done: boolean; title: string; detail: string; tab: PageTab }[] = [
    { done: loaded, title: "Load the PF and ESIC values", detail: "Start from the India defaults.", tab: "statutory" },
    { done: verified, title: "Have them verified", detail: "The payroll reviewer checks each against the official notification.", tab: "statutory" },
    { done: hasStructure, title: "Set up a salary structure", detail: "Start from the standard one and adjust it.", tab: "structures" },
  ];

  return (
    <div className="card mb-6 p-5">
      <p className="text-sm font-semibold text-fg">Set up payroll</p>
      <p className="mt-0.5 text-xs text-fg-subtle">{canWrite ? "Three steps before salaries can be assigned with confidence." : "The payroll administrator is still setting payroll up."}</p>
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {steps.map((s, i) => (
          <li key={s.title}>
            <button type="button" onClick={() => go(s.tab)}
              className="flex h-full w-full items-start gap-3 rounded-xl border border-line p-3 text-left transition-colors hover:bg-muted/50">
              <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${s.done ? "bg-success/15 text-success" : "bg-muted text-fg-muted"}`}>
                {s.done ? <Check size={13} /> : i + 1}
              </span>
              <span className="min-w-0">
                <span className={`block text-[13px] font-medium ${s.done ? "text-fg-subtle line-through" : "text-fg"}`}>{s.title}</span>
                <span className="block text-xs text-fg-subtle">{s.detail}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
