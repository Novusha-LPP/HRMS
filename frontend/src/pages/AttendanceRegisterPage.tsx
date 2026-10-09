import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Search, CalendarDays, Users } from "lucide-react";
import { timeApi, type RegisterEmployee } from "../api/time";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Avatar } from "../components/ui/Avatar";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
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
 */
export function AttendanceRegisterPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const employmentId = params.get("employee");
  const month = params.get("month");
  const editDate = params.get("edit");
  const canEdit = !!user && (user.permissions.includes("*") || user.permissions.includes("corrections.write"));

  const clearEdit = () => setParams((p) => { const n = new URLSearchParams(p); n.delete("edit"); return n; }, { replace: true });

  return (
    <>
      <PageHeader
        title="Attendance register"
        description={canEdit
          ? "Pick a person to see their attendance day by day — and fix any day in a few clicks."
          : "Pick a person to see their attendance day by day."}
      />
      <div className="grid items-start gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <PeopleList selectedId={employmentId} onChoose={(e) => setParams({ employee: e.employment_id })} />
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
              description="Select someone from the list to open their attendance for the month."
            />
          </div>
        )}
      </div>
    </>
  );
}

function PeopleList({ selectedId, onChoose }: { selectedId: string | null; onChoose: (e: RegisterEmployee) => void }) {
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 250);
  const { data: people = [], isPending } = useQuery({
    queryKey: ["register-employees", search],
    queryFn: () => timeApi.findEmployees(search),
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
      <ul role="listbox" aria-label="People" className={`flex-1 overflow-y-auto p-1.5 max-lg:max-h-72 ${selectedId && !query ? "max-lg:hidden" : ""}`}>
        {isPending ? (
          Array.from({ length: 6 }).map((_, i) => <li key={i} className="p-2"><Skeleton className="h-9 rounded-lg" /></li>)
        ) : people.length === 0 ? (
          <li className="flex flex-col items-center gap-1 px-3 py-8 text-center text-[13px] text-fg-subtle">
            <Users size={18} /> No one matches “{query}”.
          </li>
        ) : people.map((e) => {
          const active = e.employment_id === selectedId;
          return (
            <li key={e.employment_id}>
              <button
                type="button" role="option" aria-selected={active} onClick={() => onChoose(e)}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${active ? "bg-brand-500/10" : "hover:bg-muted"}`}
              >
                <Avatar name={e.name} size="sm" />
                <span className="min-w-0 leading-tight">
                  <span className={`block truncate text-[13px] font-medium ${active ? "text-accent" : "text-fg"}`}>{e.name}</span>
                  <span className="block truncate text-xs text-fg-subtle">{e.employee_number}{e.department ? ` · ${e.department}` : ""}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {people.length >= 50 && (
        <p className="border-t border-line px-3 py-2 text-[11px] text-fg-subtle">Showing the first 50 — search to narrow down.</p>
      )}
    </div>
  );
}
