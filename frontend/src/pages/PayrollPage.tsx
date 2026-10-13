import { useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { EmptyState } from "../components/ui/Feedback";
import { UsageHelpButton } from "../components/ui/UsageHelpButton";
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
        actions={<UsageHelpButton topic="payroll" />}
      />
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
