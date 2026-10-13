import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { ChevronRight, IndianRupee, Search } from "lucide-react";
import { payrollApi } from "../../api/payroll";
import type { SalaryRow } from "../../api/payroll";
import { useAuth } from "../../context/AuthContext";
import { inr } from "../../lib/money";
import { Avatar } from "../ui/Avatar";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { Segmented } from "../ui/Tabs";
import { EmployeeSalarySheet } from "./EmployeeSalarySection";

const day = (d: string) => format(new Date(`${d}T00:00:00`), "d MMM yyyy");

type Show = "ALL" | "MISSING";

/** Every current employee in scope with their CTC; opens one person's salary, breakup and history. */
export function SalariesTab({ canWrite }: { canWrite: boolean }) {
  const { user } = useAuth();
  const [company, setCompany] = useState("");
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<Show>("ALL");
  const [open, setOpen] = useState<SalaryRow | null>(null);
  const salaries = useQuery({ queryKey: ["payroll", "salaries", company], queryFn: () => payrollApi.salaries(company || undefined), placeholderData: keepPreviousData });

  const all = useMemo(() => salaries.data ?? [], [salaries.data]);
  const today = format(new Date(), "yyyy-MM-dd");
  const missing = all.filter((r) => !r.annual_ctc).length;
  const needle = query.trim().toLowerCase();
  const rows = all.filter((r) =>
    (show === "ALL" || !r.annual_ctc)
    && (!needle || r.name.toLowerCase().includes(needle) || r.employee_number.toLowerCase().includes(needle) || (r.department ?? "").toLowerCase().includes(needle)));

  if (salaries.isError) return <Notice title="Couldn’t load salaries">The payroll API isn’t responding.</Notice>;

  return (
    <div className="space-y-4">
      {!salaries.isPending && missing > 0 && (
        <Notice tone="info" title={`${missing} ${missing === 1 ? "person has" : "people have"} no salary yet`}>
          They can't be paid until a salary is assigned. Use “Without a salary” to list them.
        </Notice>
      )}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[14rem] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input className="input pl-8" placeholder="Search name, employee number or department" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search salaries" />
          </div>
          {(user?.legalEntities.length ?? 0) > 1 && (
            <select className="input w-56" value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company">
              <option value="">All companies</option>
              {user?.legalEntities.map((le) => <option key={le.id} value={le.id}>{le.name}</option>)}
            </select>
          )}
          <Segmented<Show> value={show} onChange={setShow} items={[{ value: "ALL", label: `All${salaries.isPending ? "" : ` (${all.length})`}` }, { value: "MISSING", label: `Without a salary${salaries.isPending ? "" : ` (${missing})`}` }]} />
        </div>
        {salaries.isPending ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={IndianRupee} title={all.length ? "Nobody matches" : "No employees"} description={all.length ? "Try another search or filter." : "Employees you can see appear here once they're added."} />
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Employee</th><th className="hidden md:table-cell">Department</th><th className="text-right">Annual CTC</th><th className="hidden sm:table-cell">Structure</th><th className="hidden lg:table-cell">From</th><th className="w-8" /></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.employment_id} className="group cursor-pointer" onClick={() => setOpen(r)}>
                    <td>
                      <div className="flex items-center gap-3">
                        <Avatar name={r.name} size="sm" />
                        <div className="min-w-0 leading-tight">
                          <p className="truncate font-medium text-fg">{r.name}</p>
                          <p className="truncate text-[11px] text-fg-subtle">{r.employee_number}{r.designation ? ` · ${r.designation}` : ""}</p>
                        </div>
                      </div>
                    </td>
                    <td className="hidden md:table-cell">{r.department ?? "—"}</td>
                    <td className="whitespace-nowrap text-right tabular-nums">
                      {r.annual_ctc ? <span className="text-fg">{inr(r.annual_ctc)}</span> : <span className="badge badge-warning">Not set</span>}
                    </td>
                    <td className="hidden sm:table-cell">{r.structure_name ?? "—"}</td>
                    <td className="hidden whitespace-nowrap lg:table-cell">
                      {!r.effective_from ? "—" : r.effective_from > today ? <span className="badge badge-info">Starts {day(r.effective_from)}</span> : day(r.effective_from)}
                    </td>
                    <td><ChevronRight size={15} className="text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <EmployeeSalarySheet key={open?.employment_id ?? "none"} row={open} canWrite={canWrite && open?.employment_id !== user?.employmentId} onClose={() => setOpen(null)} />
    </div>
  );
}
