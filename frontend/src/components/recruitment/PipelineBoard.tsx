import { useState } from "react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { Briefcase, FileText, MessageSquare, Star } from "lucide-react";
import type { Application, Stage } from "../../api/recruitment";
import { Avatar } from "../ui/Avatar";
import { STAGE_DOT, daysSince, years } from "./meta";

function CardBody({ app }: { app: Application }) {
  const c = app.candidate;
  return (
    <>
      <div className="flex items-start gap-2.5">
        <Avatar name={c.full_name} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-fg">{c.full_name}</p>
          <p className="truncate text-xs text-fg-subtle">
            {[c.current_title, c.current_company].filter(Boolean).join(" · ") || c.email || "—"}
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex items-center gap-3 text-[11px] text-fg-subtle">
        {c.total_experience_years && <span className="inline-flex items-center gap-1"><Briefcase size={11} />{years(c.total_experience_years)}</span>}
        {app.rating && <span className="inline-flex items-center gap-0.5 text-warning"><Star size={11} className="fill-warning" />{app.rating}</span>}
        {app.notes_count > 0 && <span className="inline-flex items-center gap-1"><MessageSquare size={11} />{app.notes_count}</span>}
        {c.resume && <span className="inline-flex items-center" title="Resume attached"><FileText size={11} /></span>}
        <span className="ml-auto" title="Time in this stage">{daysSince(app.stage_changed_at)}</span>
      </div>
    </>
  );
}

function Card({ app, draggable, onOpen }: { app: Application; draggable: boolean; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: app.id, disabled: !draggable });
  return (
    <div
      ref={setNodeRef}
      {...(draggable ? listeners : {})}
      {...(draggable ? attributes : {})}
      role="button"
      tabIndex={0}
      aria-roledescription={draggable ? "Draggable candidate" : undefined}
      aria-label={`${app.candidate.full_name}, ${app.stage_name}${draggable ? ". Space to move, Enter to open" : ""}`}
      onClick={onOpen}
      onKeyDown={(e) => {
        // Space picks the card up (keyboard sensor); Enter opens it.
        if (e.key === "Enter" && !isDragging) { e.preventDefault(); onOpen(); return; }
        if (draggable) listeners?.onKeyDown?.(e);
      }}
      className={`rounded-lg border border-line bg-surface p-3 text-left shadow-xs outline-none transition-[box-shadow,opacity,border-color] hover:border-line-strong hover:shadow-card focus-visible:ring-4 focus-visible:ring-brand-500/20 ${draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"} ${isDragging ? "opacity-40" : ""}`}
    >
      <CardBody app={app} />
    </div>
  );
}

function Column({ stage, apps, children, droppable }: { stage: Stage; apps: Application[]; children: React.ReactNode; droppable: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id, disabled: !droppable });
  return (
    <div role="group" aria-label={`${stage.name} stage, ${apps.length} candidate${apps.length === 1 ? "" : "s"}`}
      className="flex w-[17rem] shrink-0 flex-col rounded-xl border border-line bg-panel">
      <div className="flex items-center gap-2 px-3 pb-2 pt-3">
        <span className={`h-2 w-2 rounded-full ${STAGE_DOT[stage.color]}`} />
        <span className="truncate text-[13px] font-semibold text-fg">{stage.name}</span>
        {!stage.is_active && <span className="text-[10px] text-fg-subtle">(archived)</span>}
        <span className="ml-auto rounded-full bg-muted px-1.5 py-px text-[11px] font-medium tabular-nums text-fg-muted">{apps.length}</span>
      </div>
      <div
        ref={setNodeRef}
        className={`flex min-h-[8rem] flex-1 flex-col gap-2 rounded-b-xl p-2 transition-colors ${isOver ? "bg-brand-500/[0.07] ring-2 ring-inset ring-brand-500/30" : ""}`}
      >
        {children}
        {apps.length === 0 && (
          <p className="grid flex-1 place-items-center rounded-lg border border-dashed border-line px-3 py-6 text-center text-[11px] text-fg-subtle">
            {droppable ? "Drop a candidate here" : "No candidates"}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Kanban of an opening's candidates by stage. Recruiters drag cards between columns
 * (mouse, touch or keyboard); everyone else can open a card to read it.
 */
export function PipelineBoard({ stages, applications, canMove, onOpen, onMove }: {
  stages: Stage[];
  applications: Application[];
  canMove: boolean;
  onOpen: (app: Application) => void;
  onMove: (app: Application, stage: Stage) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { keyboardCodes: { start: ["Space"], cancel: ["Escape"], end: ["Space", "Enter"] } }),
  );
  const [dragging, setDragging] = useState<Application | null>(null);

  // Active stages always; an archived stage only while candidates still sit in it.
  const columns = stages.filter((s) => s.is_active || applications.some((a) => a.stage_id === s.id));

  const onDragStart = (e: DragStartEvent) => setDragging(applications.find((a) => a.id === e.active.id) ?? null);
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null);
    const app = applications.find((a) => a.id === e.active.id);
    const stage = stages.find((s) => s.id === e.over?.id);
    if (app && stage && stage.id !== app.stage_id && stage.is_active) onMove(app, stage);
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(null)}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Picked up ${applications.find((a) => a.id === active.id)?.candidate.full_name ?? "candidate"}.`,
          onDragOver: ({ over }) => (over ? `Over ${stages.find((s) => s.id === over.id)?.name}.` : "Not over a stage."),
          onDragEnd: ({ over }) => (over ? `Dropped in ${stages.find((s) => s.id === over.id)?.name}.` : "Dropped."),
          onDragCancel: () => "Move cancelled.",
        },
      }}
    >
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-3">
        {columns.map((stage) => {
          const apps = applications.filter((a) => a.stage_id === stage.id);
          return (
            <Column key={stage.id} stage={stage} apps={apps} droppable={canMove && stage.is_active}>
              {apps.map((app) => (
                <Card key={app.id} app={app} draggable={canMove && !app.hired_employment_id} onOpen={() => onOpen(app)} />
              ))}
            </Column>
          );
        })}
      </div>
      <DragOverlay dropAnimation={null}>
        {dragging && (
          <div className="w-[16rem] rotate-[1.5deg] rounded-lg border border-brand-500/40 bg-surface p-3 shadow-pop">
            <CardBody app={dragging} />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
