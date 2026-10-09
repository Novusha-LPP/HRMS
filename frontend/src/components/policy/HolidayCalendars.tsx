import { useMemo, useState } from "react";
import type { ElementType } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  CalendarDays, ChevronLeft, ChevronRight, Plus, Trash2, Pencil, Building2, Landmark, Users, UserRound,
  X, Check, ArrowRight, ListChecks, TriangleAlert,
} from "lucide-react";
import { ApiError } from "../../api/client";
import { holidayApi, type CalendarTarget, type HolidayCalendar, type ListHoliday } from "../../api/holidays";
import { orgApi } from "../../api/org";
import { Tabs } from "../ui/Tabs";
import { ConfirmDialog, Sheet } from "../ui/Overlay";
import { Skeleton, EmptyState } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

type Step = "list" | "calendars" | "assign";

const TARGET_ICON: Record<CalendarTarget, ElementType> = {
  COMPANY: Building2, LEGAL_ENTITY: Landmark, DEPARTMENT: Users, EMPLOYEE: UserRound,
};
const TARGET_LABEL: Record<CalendarTarget, string> = {
  COMPANY: "Whole company", LEGAL_ENTITY: "Company entity", DEPARTMENT: "Department", EMPLOYEE: "Person",
};

const dateLabel = (iso: string) => format(new Date(`${iso}T00:00:00`), "d MMM");
const weekday = (iso: string) => format(new Date(`${iso}T00:00:00`), "EEEE");
const people = (n: number) => `${n} ${n === 1 ? "person" : "people"}`;

/**
 * Holidays in three steps:
 *  1. Holiday list — every holiday of the year, entered once.
 *  2. Calendars — named sets ("HO", "Operations"), each a tick-list from the holiday list.
 *  3. Who gets which — each calendar goes to the whole company, a company entity or a department.
 */
export function HolidayCalendars() {
  const qc = useQueryClient();
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [step, setStep] = useState<Step>("list");
  const holidays = useQuery({ queryKey: ["holiday-list", year], queryFn: () => holidayApi.listHolidays(year) });
  const calendars = useQuery({ queryKey: ["holiday-calendars", year], queryFn: () => holidayApi.list(year) });
  const refresh = () => {
    for (const key of ["holiday-list", "holiday-calendars", "holiday-coverage", "holidays", "attendance-register"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const assignments = (calendars.data ?? []).reduce((n, c) => n + c.assignments.length, 0);

  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
        <div>
          <h3 className="card-title flex items-center gap-2"><CalendarDays size={15} /> Holidays</h3>
          <p className="mt-0.5 text-xs text-fg-subtle">Add the year’s holidays, group them into calendars, then choose who follows each calendar.</p>
        </div>
        <div className="ml-auto flex items-center rounded-lg border border-line">
          <button className="btn-icon" aria-label="Previous year" onClick={() => setYear((y) => y - 1)}><ChevronLeft size={16} /></button>
          <span className="w-14 text-center text-[13px] font-semibold tabular-nums text-fg">{year}</span>
          <button className="btn-icon" aria-label="Next year" onClick={() => setYear((y) => y + 1)}><ChevronRight size={16} /></button>
        </div>
      </div>
      <div className="px-5 pt-3">
        <Tabs<Step>
          value={step}
          onChange={setStep}
          items={[
            { value: "list", label: "1 · Holiday list", count: holidays.data?.length },
            { value: "calendars", label: "2 · Calendars", count: calendars.data?.length },
            { value: "assign", label: "3 · Who gets which", count: assignments },
          ]}
        />
      </div>
      <div className="p-5">
        {step === "list" && (
          <HolidayList year={year} holidays={holidays.data} loading={holidays.isPending} onChanged={refresh} onNext={() => setStep("calendars")} />
        )}
        {step === "calendars" && (
          <CalendarsStep year={year} holidays={holidays.data ?? []} calendars={calendars.data} loading={calendars.isPending}
            onChanged={refresh} onAddHolidays={() => setStep("list")} onNext={() => setStep("assign")} />
        )}
        {step === "assign" && (
          <AssignStep calendars={calendars.data ?? []} loading={calendars.isPending} onChanged={refresh} onCreate={() => setStep("calendars")} />
        )}
      </div>
    </div>
  );
}

// ─── Step 1: the holiday list ────────────────────────────────────────────────

function HolidayList({ year, holidays, loading, onChanged, onNext }: {
  year: number; holidays?: ListHoliday[]; loading: boolean; onChanged: () => void; onNext: () => void;
}) {
  const toast = useToast();
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: string; date: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<ListHoliday | null>(null);
  const failed = (title: string) => (e: unknown) => toast.error(title, errorMessage(e));

  const add = useMutation({
    mutationFn: () => holidayApi.addHoliday({ holiday_date: date, name: name.trim() }),
    onSuccess: () => { setDate(""); setName(""); onChanged(); },
    onError: failed("Couldn’t add the holiday"),
  });
  const save = useMutation({
    mutationFn: (e: { id: string; date: string; name: string }) => holidayApi.updateHoliday(e.id, { holiday_date: e.date, name: e.name.trim() }),
    onSuccess: () => { setEditing(null); onChanged(); },
    onError: failed("Couldn’t save the holiday"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => holidayApi.deleteHoliday(id),
    onSuccess: () => { setDeleting(null); onChanged(); toast.success("Holiday deleted"); },
    onError: failed("Couldn’t delete the holiday"),
  });

  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-2 rounded-xl border border-line bg-panel p-3"
        onSubmit={(e) => { e.preventDefault(); if (date && name.trim()) add.mutate(); }}
      >
        <div>
          <label className="label" htmlFor="hl-date">Date</label>
          <input id="hl-date" type="date" className="input" min={`${year}-01-01`} max={`${year}-12-31`} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <div className="min-w-48 flex-1">
          <label className="label" htmlFor="hl-name">Holiday</label>
          <input id="hl-name" className="input" placeholder="e.g. Diwali" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <button className="btn-primary" disabled={!date || !name.trim() || add.isPending}><Plus size={14} /> Add holiday</button>
      </form>

      {loading ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : !holidays?.length ? (
        <EmptyState icon={CalendarDays} title={`No holidays for ${year} yet`}
          description="Add every holiday your company observes this year. Next you’ll choose which of them each calendar includes." />
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {holidays.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5 text-[13px]">
              {editing?.id === h.id ? (
                <form className="flex flex-1 flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(editing); }}>
                  <input type="date" className="input w-40" aria-label="Date" min={`${year}-01-01`} max={`${year}-12-31`}
                    value={editing.date} onChange={(e) => setEditing({ ...editing, date: e.target.value })} />
                  <input className="input min-w-40 flex-1" aria-label="Holiday" value={editing.name} autoFocus
                    onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
                  <button className="btn-primary btn-sm" disabled={!editing.name.trim() || save.isPending}><Check size={14} /> Save</button>
                  <button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <span className="w-16 font-semibold tabular-nums text-fg">{dateLabel(h.holiday_date)}</span>
                  <span className="w-24 text-xs text-fg-subtle">{weekday(h.holiday_date)}</span>
                  <span className="min-w-32 flex-1 font-medium text-fg">{h.name}</span>
                  <span className="flex flex-wrap gap-1">
                    {h.calendars.length === 0
                      ? <span className="text-xs text-fg-subtle">Not in a calendar yet</span>
                      : h.calendars.map((c) => <span key={c.id} className="badge badge-neutral text-[10px]">{c.name}{c.is_optional ? " · optional" : ""}</span>)}
                  </span>
                  <span className="flex">
                    <button className="btn-icon" aria-label={`Edit ${h.name}`} onClick={() => setEditing({ id: h.id, date: h.holiday_date, name: h.name })}><Pencil size={13} /></button>
                    <button className="btn-icon text-fg-subtle hover:text-danger" aria-label={`Delete ${h.name}`} onClick={() => setDeleting(h)}><Trash2 size={14} /></button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {!!holidays?.length && (
        <div className="flex justify-end">
          <button className="btn-secondary" onClick={onNext}>Next: calendars <ArrowRight size={14} /></button>
        </div>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        loading={remove.isPending}
        title={`Delete ${deleting?.name ?? ""}?`}
        description={deleting?.calendars.length
          ? `It is also removed from ${deleting.calendars.map((c) => c.name).join(", ")}.`
          : "It isn’t in any calendar."}
        confirmLabel="Delete holiday"
      />
    </div>
  );
}

// ─── Step 2: calendars ───────────────────────────────────────────────────────

function CalendarsStep({ year, holidays, calendars, loading, onChanged, onAddHolidays, onNext }: {
  year: number; holidays: ListHoliday[]; calendars?: HolidayCalendar[]; loading: boolean;
  onChanged: () => void; onAddHolidays: () => void; onNext: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<HolidayCalendar | "new" | null>(null);
  const [deleting, setDeleting] = useState<HolidayCalendar | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => holidayApi.archive(id),
    onSuccess: () => { setDeleting(null); onChanged(); toast.success("Calendar deleted"); },
    onError: (e) => toast.error("Couldn’t delete the calendar", errorMessage(e)),
  });

  if (!holidays.length) {
    return (
      <EmptyState icon={ListChecks} title="Add holidays first"
        description="Calendars are made by ticking holidays from the holiday list."
        action={<button className="btn-primary btn-sm" onClick={onAddHolidays}>Go to the holiday list</button>} />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-fg-subtle">A calendar is a named set of holidays — for example “HO” for the office and “Operations” for site staff.</p>
        <button className="btn-primary btn-sm" onClick={() => setEditing("new")}><Plus size={14} /> New calendar</button>
      </div>
      {loading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : !calendars?.length ? (
        <EmptyState icon={CalendarDays} title="No calendars yet"
          description="Create one, give it a name such as “HO”, and tick the holidays it includes." />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {calendars.map((c) => (
            <div key={c.id} className="flex flex-col rounded-xl border border-line p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[15px] font-semibold text-fg">{c.name}</p>
                  <p className="text-xs text-fg-subtle">{c.days.length} holidays · {people(c.people)} today</p>
                </div>
                <span className="flex">
                  <button className="btn-icon" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}><Pencil size={13} /></button>
                  <button className="btn-icon text-fg-subtle hover:text-danger" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)}><Trash2 size={14} /></button>
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1">
                {c.days.map((d) => (
                  <span key={d.id} className="badge badge-neutral text-[10px]" title={weekday(d.holiday_date)}>
                    {dateLabel(d.holiday_date)} · {d.name}{d.is_optional ? " (optional)" : ""}
                  </span>
                ))}
                {c.days.length === 0 && <span className="text-xs text-fg-subtle">No holidays ticked yet.</span>}
              </div>
              <p className="mt-auto pt-3 text-xs text-fg-muted">
                {c.assignments.length
                  ? <>Followed by: {c.assignments.map((a) => a.target === "EMPLOYEE" ? null : a.target_name).filter(Boolean).join(", ")}
                    {c.assignments.some((a) => a.target === "EMPLOYEE") && ` + ${people(c.assignments.filter((a) => a.target === "EMPLOYEE").length)}`}</>
                  : <span className="text-warning">Not given to anyone yet — see step 3.</span>}
              </p>
            </div>
          ))}
        </div>
      )}
      {!!calendars?.length && (
        <div className="flex justify-end">
          <button className="btn-secondary" onClick={onNext}>Next: who gets which <ArrowRight size={14} /></button>
        </div>
      )}

      <CalendarSheet
        year={year}
        holidays={holidays}
        calendar={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); onChanged(); }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        loading={remove.isPending}
        title={`Delete ${deleting?.name ?? ""}?`}
        description={`The ${people(deleting?.people ?? 0)} who follow it fall back to the next calendar that applies to them. The holidays stay on the list.`}
        confirmLabel="Delete calendar"
      />
    </div>
  );
}

/** Name the calendar and tick its holidays from the list. */
function CalendarSheet({ year, holidays, calendar, open, onClose, onSaved }: {
  year: number; holidays: ListHoliday[]; calendar: HolidayCalendar | null; open: boolean;
  onClose: () => void; onSaved: () => void;
}) {
  return (
    <Sheet open={open} onClose={onClose} className="max-w-lg"
      title={calendar ? `Edit ${calendar.name}` : "New calendar"}
      description={`Tick the ${year} holidays this calendar includes.`}>
      {open && <CalendarForm key={calendar?.id ?? "new"} year={year} holidays={holidays} calendar={calendar} onClose={onClose} onSaved={onSaved} />}
    </Sheet>
  );
}

function CalendarForm({ year, holidays, calendar, onClose, onSaved }: {
  year: number; holidays: ListHoliday[]; calendar: HolidayCalendar | null; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(calendar?.name ?? "");
  const [picked, setPicked] = useState<Map<string, boolean>>(
    () => new Map((calendar?.days ?? []).map((d) => [d.holiday_id, d.is_optional])),
  );
  const toggle = (id: string) => setPicked((m) => { const n = new Map(m); if (n.has(id)) n.delete(id); else n.set(id, false); return n; });
  const setOptional = (id: string, value: boolean) => setPicked((m) => new Map(m).set(id, value));
  const choices = () => [...picked].map(([holiday_id, is_optional]) => ({ holiday_id, is_optional }));

  const save = useMutation({
    mutationFn: async () => {
      if (!calendar) {
        const created = await holidayApi.create({ name: name.trim(), year });
        return holidayApi.setDays(created.id, choices());
      }
      if (name.trim() !== calendar.name) await holidayApi.rename(calendar.id, name.trim());
      return holidayApi.setDays(calendar.id, choices());
    },
    onSuccess: (c) => { toast.success(calendar ? `${c.name} saved` : `${c.name} created`, `${c.days.length} holidays`); onSaved(); },
    onError: (e) => toast.error("Couldn’t save the calendar", errorMessage(e)),
  });

  return (
    <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }}>
      <div>
        <label className="label" htmlFor="cal-name">Calendar name</label>
        <input id="cal-name" className="input" placeholder="e.g. HO, Operations, Plant" value={name} autoFocus={!calendar} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="eyebrow">Holidays · {picked.size} of {holidays.length} ticked</p>
          <span className="flex gap-3 text-xs">
            <button type="button" className="font-medium text-accent hover:underline" onClick={() => setPicked(new Map(holidays.map((h) => [h.id, picked.get(h.id) ?? false])))}>Tick all</button>
            <button type="button" className="font-medium text-fg-subtle hover:underline" onClick={() => setPicked(new Map())}>Clear</button>
          </span>
        </div>
        <ul className="divide-y divide-line rounded-xl border border-line">
          {holidays.map((h) => {
            const on = picked.has(h.id);
            return (
              <li key={h.id} className={`flex items-center gap-3 px-3.5 py-2 text-[13px] ${on ? "bg-brand-500/[0.04]" : ""}`}>
                <label className="flex flex-1 cursor-pointer items-center gap-3">
                  <input type="checkbox" className="checkbox" checked={on} onChange={() => toggle(h.id)} aria-label={h.name} />
                  <span className="w-14 font-semibold tabular-nums text-fg">{dateLabel(h.holiday_date)}</span>
                  <span className="flex-1 text-fg">{h.name}</span>
                </label>
                {on && (
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs text-fg-subtle" title="People may work or take it off">
                    <input type="checkbox" className="checkbox" checked={picked.get(h.id) ?? false} onChange={(e) => setOptional(h.id, e.target.checked)} />
                    Optional
                  </label>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={!name.trim() || save.isPending}>{save.isPending ? "Saving…" : calendar ? "Save" : "Create calendar"}</button>
      </div>
    </form>
  );
}

// ─── Step 3: who gets which ──────────────────────────────────────────────────

type Pick = "COMPANY" | "LEGAL_ENTITY" | "DEPARTMENT";

function AssignStep({ calendars, loading, onChanged, onCreate }: {
  calendars: HolidayCalendar[]; loading: boolean; onChanged: () => void; onCreate: () => void;
}) {
  const toast = useToast();
  const [target, setTarget] = useState<Pick>("COMPANY");
  const [targetId, setTargetId] = useState("");
  const [calendarId, setCalendarId] = useState("");
  const [replace, setReplace] = useState<string | null>(null);
  const coverage = useQuery({ queryKey: ["holiday-coverage"], queryFn: holidayApi.coverage });
  const entities = useQuery({ queryKey: ["legal-entities"], queryFn: orgApi.listLegalEntities });
  const units = useQuery({ queryKey: ["org-units"], queryFn: orgApi.listOrgUnits });
  const entityName = useMemo(() => new Map((entities.data ?? []).map((e) => [e.id, e.name])), [entities.data]);
  const departments = (units.data ?? [])
    .filter((u) => u.status === "ACTIVE")
    .map((u) => ({ id: u.id, label: `${u.name}${u.legal_entity_id ? ` — ${entityName.get(u.legal_entity_id) ?? ""}` : ""}` }))
    .sort((a, b) => a.label.localeCompare(b.label));
  const rules = calendars
    .flatMap((c) => c.assignments.map((a) => ({ ...a, calendar: c })))
    .sort((a, b) => ["COMPANY", "LEGAL_ENTITY", "DEPARTMENT", "EMPLOYEE"].indexOf(a.target) - ["COMPANY", "LEGAL_ENTITY", "DEPARTMENT", "EMPLOYEE"].indexOf(b.target) || a.target_name.localeCompare(b.target_name));
  const uncovered = coverage.data?.find((c) => c.calendar_id === null)?.people ?? 0;

  const assign = useMutation({
    mutationFn: (withReplace: boolean) => holidayApi.assign(calendarId, {
      target, target_id: target === "COMPANY" ? null : targetId, replace: withReplace,
    }),
    onSuccess: (c) => { setReplace(null); setTargetId(""); onChanged(); toast.success(`${c.name} assigned`); },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "CALENDAR_ASSIGNED") { setReplace(e.message); return; }
      toast.error("Couldn’t assign the calendar", errorMessage(e));
    },
  });
  const unassign = useMutation({
    mutationFn: ({ calendar, id }: { calendar: string; id: string }) => holidayApi.unassign(calendar, id),
    onSuccess: () => { onChanged(); toast.success("Removed"); },
    onError: (e) => toast.error("Couldn’t remove it", errorMessage(e)),
  });

  if (!loading && calendars.length === 0) {
    return (
      <EmptyState icon={CalendarDays} title="Create a calendar first"
        action={<button className="btn-primary btn-sm" onClick={onCreate}>Go to calendars</button>} />
    );
  }
  const ready = !!calendarId && (target === "COMPANY" || !!targetId);

  return (
    <div className="space-y-5">
      {!!coverage.data?.length && (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-fg-subtle">Following today:</span>
        {(coverage.data ?? []).filter((c) => c.calendar_id).map((c) => (
          <span key={c.calendar_id} className="badge badge-neutral">{c.name} · {people(c.people)}</span>
        ))}
        {uncovered > 0 && <span className="badge badge-warning"><TriangleAlert size={11} /> {people(uncovered)} without a calendar</span>}
      </div>
      )}

      <form
        className="rounded-xl border border-line bg-panel p-4"
        onSubmit={(e) => { e.preventDefault(); if (ready) assign.mutate(false); }}
      >
        <p className="mb-3 text-[13px] font-medium text-fg">Give a calendar to…</p>
        <div className="grid gap-3 sm:grid-cols-[11rem_minmax(0,1fr)_minmax(0,12rem)_auto] sm:items-end">
          <div>
            <label className="label" htmlFor="as-target">Who</label>
            <select id="as-target" className="input" value={target} onChange={(e) => { setTarget(e.target.value as Pick); setTargetId(""); }}>
              <option value="COMPANY">Whole company</option>
              <option value="LEGAL_ENTITY">A company entity</option>
              <option value="DEPARTMENT">A department</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="as-which">{target === "COMPANY" ? " " : target === "LEGAL_ENTITY" ? "Company entity" : "Department"}</label>
            {target === "COMPANY" ? (
              <p className="flex h-9 items-center text-xs text-fg-subtle">Everyone, unless their entity or department has its own</p>
            ) : (
              <select id="as-which" className="input" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                <option value="">Choose…</option>
                {target === "LEGAL_ENTITY"
                  ? (entities.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)
                  : departments.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="label" htmlFor="as-calendar">Gets calendar</label>
            <select id="as-calendar" className="input" value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>
              <option value="">Choose…</option>
              {calendars.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.days.length})</option>)}
            </select>
          </div>
          <button className="btn-primary" disabled={!ready || assign.isPending}>{assign.isPending ? "Saving…" : "Assign"}</button>
        </div>
      </form>

      <div>
        <p className="eyebrow mb-2">Current rules</p>
        {loading ? <Skeleton className="h-32 rounded-xl" /> : rules.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line px-4 py-4 text-[13px] text-fg-subtle">Nothing assigned yet — start with the whole company.</p>
        ) : (
          <ul className="divide-y divide-line rounded-xl border border-line">
            {rules.map((r) => {
              const Icon = TARGET_ICON[r.target];
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[13px]">
                  <Icon size={15} className="text-fg-subtle" />
                  <span className="min-w-40 flex-1">
                    <span className="font-medium text-fg">{r.target_name}</span>
                    {r.target !== "COMPANY" && (
                      <span className="ml-2 text-xs text-fg-subtle">
                        {TARGET_LABEL[r.target]}{r.target_detail ? ` · ${r.target_detail}` : ""}
                      </span>
                    )}
                  </span>
                  <ArrowRight size={13} className="text-fg-subtle" />
                  <span className="badge badge-brand">{r.calendar.name}</span>
                  {r.effective_to && <span className="text-[11px] text-fg-subtle">until {format(new Date(`${r.effective_to}T00:00:00`), "d MMM yyyy")}</span>}
                  <button className="btn-icon text-fg-subtle hover:text-danger" aria-label={`Remove ${r.target_name}`}
                    onClick={() => unassign.mutate({ calendar: r.calendar.id, id: r.id })}><X size={14} /></button>
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-2 text-xs text-fg-subtle">If more than one applies to someone, the most specific wins: person › department › company entity › whole company.</p>
      </div>

      <ConfirmDialog
        open={replace !== null}
        onClose={() => setReplace(null)}
        onConfirm={() => assign.mutate(true)}
        loading={assign.isPending}
        title="Switch calendar?"
        description={replace ?? ""}
        confirmLabel="Switch"
      />
    </div>
  );
}
