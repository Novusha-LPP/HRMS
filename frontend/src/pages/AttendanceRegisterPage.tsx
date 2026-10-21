import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Search, CalendarDays, Users } from "lucide-react";
import { timeApi, type RegisterEmployee } from "../api/time";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Avatar } from "../components/ui/Avatar";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { AttendanceRegister } from "../components/attendance/AttendanceRegister";

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

/**
 * HR's attendance register: the people on the left, the chosen person's month on the right.
 * URL: ?employee=<employment id>&month=YYYY-MM&edit=YYYY-MM-DD (opens that day in the editor).
 * Optional company=<legal entity id>&department=<department id> narrow the people picker.
 */
export function AttendanceRegisterPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const employmentId = params.get("employee");
  const month = params.get("month");
  const editDate = params.get("edit");
  const company = params.get("company") ?? "";
  const department = params.get("department") ?? "";
  const filters = useQuery({ queryKey: ["register-filters"], queryFn: timeApi.registerFilters });
  const companies = filters.data?.companies ?? [];
  const departments = (filters.data?.departments ?? [])
    .filter((d) => !company || d.legal_entity_id === company);
  const canEdit = !!user && (user.permissions.includes("*") || user.permissions.includes("corrections.write"));

  const clearEdit = () => setParams((p) => { const n = new URLSearchParams(p); n.delete("edit"); return n; }, { replace: true });
  const changeFilter = (key: "company" | "department", value: string) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (value) next.set(key, value); else next.delete(key);
    if (key === "company") next.delete("department");
    next.delete("employee");
    next.delete("edit");
    return next;
  });
  const clearFilters = () => setParams((p) => {
    const next = new URLSearchParams(p);
    next.delete("company");
    next.delete("department");
    next.delete("employee");
    next.delete("edit");
    return next;
  });

  return (
    <>
      <PageHeader
        title="Attendance register"
        description={canEdit
          ? "Filter by company and department, then pick a person to view or fix their attendance day by day."
          : "Filter by company and department, then pick a person to see their attendance day by day."}
      />
      <div className="card mb-4 flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1 sm:max-w-xs">
          <label className="label" htmlFor="register-company">Company</label>
          <select id="register-company" className="input mt-1" value={company} onChange={(e) => changeFilter("company", e.target.value)} disabled={filters.isPending || filters.isError}>
            <option value="">All companies</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="min-w-0 flex-1 sm:max-w-xs">
          <label className="label" htmlFor="register-department">Department</label>
          <select id="register-department" className="input mt-1" value={department} onChange={(e) => changeFilter("department", e.target.value)} disabled={filters.isPending || filters.isError}>
            <option value="">All departments</option>
            {departments.map((d) => <option key={`${d.legal_entity_id}:${d.id}`} value={d.id}>
              {d.name}{!company ? ` · ${companies.find((c) => c.id === d.legal_entity_id)?.name ?? ""}` : ""}
            </option>)}
          </select>
        </div>
        {(company || department) && <button type="button" className="btn-ghost" onClick={clearFilters}>Clear filters</button>}
      </div>
      {filters.isError && <div className="mb-4"><Notice title="Couldn’t load companies and departments" action={<button className="btn-secondary btn-sm" onClick={() => filters.refetch()}>Retry</button>}>
        Try loading the filters again, or search for a person below.
      </Notice></div>}
      <div className="grid items-start gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <PeopleList company={company} department={department} selectedId={employmentId} onChoose={(e) => setParams((p) => {
          const next = new URLSearchParams(p);
          next.set("employee", e.employment_id);
          next.delete("edit");
          return next;
        })} />
        {employmentId ? (
          <AttendanceRegister
            key={employmentId}
            employmentId={employmentId}
            // Your own attendance is corrected through a request, never directly.
            canEdit={canEdit && employmentId !== user?.employmentId}
            initialMonth={editDate ? new Date(`${editDate}T00:00:00`) : month ? new Date(`${month}-01T00:00:00`) : undefined}
            editDate={editDate}
            onEditDone={clearEdit}
          />
        ) : (
          <div className="card">
            <EmptyState
              icon={CalendarDays}
              title="Choose a person"
              description={company || department
                ? "Select someone from the filtered list to open their attendance for the month."
                : "Choose a company or department to narrow the list, then select a person to open their attendance."}
            />
          </div>
        )}
      </div>
    </>
  );
}

function PeopleList({ company, department, selectedId, onChoose }: {
  company: string; department: string; selectedId: string | null; onChoose: (e: RegisterEmployee) => void;
}) {
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 250);
  const { data: people = [], isPending, isError, refetch } = useQuery({
    queryKey: ["register-employees", search, company, department],
    queryFn: () => timeApi.findEmployees(search, company, department),
  });

  return (
    <div className="card flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden lg:sticky lg:top-4 lg:min-h-64">
      <div className="border-b border-line p-3">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input
            className="input pl-9" placeholder="Search name or ID" aria-label="Search people"
            value={query} onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      {/* On a phone the list folds away once someone is chosen, until you search again. */}
      {isError && <div className="p-3"><Notice title="Couldn’t load people" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
        Try loading the employee list again.
      </Notice></div>}
      <ul role="listbox" aria-label="People" className={`flex-1 overflow-y-auto p-1.5 max-lg:max-h-72 ${selectedId && !query ? "max-lg:hidden" : ""}`}>
        {isPending ? (
          Array.from({ length: 6 }).map((_, i) => <li key={i} className="p-2"><Skeleton className="h-9 rounded-lg" /></li>)
        ) : isError ? null : people.length === 0 ? (
          <li className="flex flex-col items-center gap-1 px-3 py-8 text-center text-[13px] text-fg-subtle">
            <Users size={18} /> {query.trim() ? `No one matches “${query.trim()}” with these filters.` : "No people in this selection."}
          </li>
        ) : people.map((e) => {
          const active = e.employment_id === selectedId;
          return (
            <li key={e.employment_id}>
              <button
                type="button" role="option" aria-selected={active} onClick={() => onChoose(e)}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${active ? "bg-brand-500/10" : "hover:bg-muted"}`}
              >
                <Avatar name={e.name} size="sm" employmentId={e.employment_id} />
                <span className="min-w-0 leading-tight">
                  <span className={`block truncate text-[13px] font-medium ${active ? "text-accent" : "text-fg"}`}>{e.name}</span>
                  <span className="block truncate text-xs text-fg-subtle">{e.employee_number}{e.department ? ` · ${e.department}` : ""}</span>
                  <span className="block truncate text-[11px] text-fg-subtle">{e.company}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {!isPending && !isError && (
        <p role="status" className="border-t border-line px-3 py-2 text-[11px] text-fg-subtle">
          {people.length} {people.length === 1 ? "employee" : "employees"}
        </p>
      )}
    </div>
  );
}
