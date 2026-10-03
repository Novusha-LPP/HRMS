/**
 * The HR/admin dashboard, arranged by each person for themselves: which widgets, in what
 * order, at what width. The layout and the catalog of widgets they may add come from
 * GET /v1/dashboard/layout; the figures from /v1/dashboard/hr, limited to the sections the
 * layout's widgets read, so a lean dashboard is also a fast one.
 */
import { useState } from "react";
import type { PointerEvent as ReactPointerEvent, TouchEvent as ReactTouchEvent, ReactNode } from "react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import type { Announcements, DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { SortableContext, useSortable } from "@dnd-kit/sortable";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GripVertical, LayoutGrid, Plus, RotateCcw, X } from "../icons/ThemeIcons";
import { dashboardApi } from "../../api/dashboard";
import type { DashboardLayout, LayoutItem, WidgetInfo, WidgetSize } from "../../api/dashboard";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { ConfirmDialog, Sheet } from "../ui/Overlay";
import { useToast, errorMessage } from "../ui/Toast";
import { WIDGETS } from "./registry";
import { dashboardCollisionDetection, dashboardKeyboardCoordinates } from "./dashboardDrag";

// Literal class names so Tailwind generates them. A phone is always one column.
const SPAN: Record<WidgetSize, string> = {
  quarter: "col-span-12 sm:col-span-6 xl:col-span-3",
  third: "col-span-12 md:col-span-6 lg:col-span-4",
  half: "col-span-12 lg:col-span-6",
  full: "col-span-12",
};
const SIZE_LABEL: Record<WidgetSize, string> = { quarter: "¼", third: "⅓", half: "½", full: "Full" };
const SIZE_NAME: Record<WidgetSize, string> = {
  quarter: "Quarter width", third: "Third width", half: "Half width", full: "Full width",
};

const DRAG_HELP =
  "To move a card, focus its grip and press Space. Use the arrow keys to move it, Space to drop it, or Escape to cancel.";
// Mixed-width cards reflow after a swap; translating them into each other's old
// rectangles gives a misleading, overlapping preview. Show a target outline instead.
const stationaryStrategy = () => null;
const noLayoutAnimation = () => false;

function isCardDragTarget(target: EventTarget | null) {
  return target instanceof Element && (Boolean(target.closest("[data-grip]")) ||
    !target.closest("button, a, input, select, textarea, [contenteditable]"));
}

/** A pointer sensor that ignores presses on the card's own buttons and links. */
class CardPointerSensor extends PointerSensor {
  static activators = [{
    eventName: "onPointerDown" as const,
    handler: ({ nativeEvent: e }: ReactPointerEvent) =>
      e.pointerType !== "touch" && e.isPrimary && e.button === 0 && isCardDragTarget(e.target),
  }];
}

// Touch has its own hold delay; the pointer sensor must not activate it first.
class CardTouchSensor extends TouchSensor {
  static activators = [{
    eventName: "onTouchStart" as const,
    handler: ({ nativeEvent: e }: ReactTouchEvent) =>
      e.touches.length === 1 && isCardDragTarget(e.target),
  }];
}

/** One card in the editable grid; the whole card is the drag surface, the grip the keyboard handle. */
function SortableCard({ item, title, editing, children }: {
  item: LayoutItem;
  title: string;
  editing: boolean;
  children: (grip: ReactNode) => ReactNode;
}) {
  const { setNodeRef, setActivatorNodeRef, attributes, listeners, isDragging, isOver, active } =
    useSortable({ id: item.widget, disabled: !editing, animateLayoutChanges: noLayoutAnimation });
  const dropTarget = isOver && active?.id !== item.widget;
  return (
    <div
      ref={setNodeRef}
      data-widget={item.widget}
      {...(editing ? listeners : {})}
      className={`${SPAN[item.size]} relative ${
        editing ? "cursor-grab rounded-xl outline-dashed outline-2 outline-offset-2 outline-line" : ""
      } ${isDragging ? "rounded-xl !outline-brand-500 bg-brand-500/5 [&>*]:opacity-30" : ""}
      ${dropTarget ? "!outline !outline-brand-500 ring-2 ring-brand-500 ring-offset-2 ring-offset-surface" : ""}`}
    >
      {children(
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          data-grip
          aria-label={`Move ${title}`}
          className="-m-1 grid h-6 w-6 shrink-0 cursor-grab place-items-center rounded text-fg-subtle hover:bg-muted focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <GripVertical size={14} aria-hidden />
        </button>,
      )}
    </div>
  );
}

function CardToolbar({ meta, item, grip, first, last, onResize, onMove, onRemove }: {
  meta: WidgetInfo;
  item: LayoutItem;
  grip: ReactNode;
  first: boolean;
  last: boolean;
  onResize: (size: WidgetSize) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}) {
  return (
    <div className="absolute inset-x-2 top-2 z-10 flex items-center gap-1 rounded-lg border border-line bg-panel/95 px-1.5 py-1 shadow-sm backdrop-blur">
      {grip}
      {/* A quarter card is too narrow for its name as well as the controls; the card itself
          shows the name right below. */}
      <span className={item.size === "quarter" ? "sr-only" : "min-w-0 flex-1 truncate text-xs font-medium text-fg"}>
        {meta.title}
      </span>
      {item.size === "quarter" && <span className="flex-1" />}
      {meta.sizes.length > 1 && (
        <div className="flex rounded-md bg-muted p-0.5" role="radiogroup" aria-label={`${meta.title} width`}>
          {meta.sizes.map((s) => (
            <button key={s} role="radio" aria-checked={item.size === s} title={SIZE_NAME[s]}
              onClick={() => onResize(s)}
              className={`rounded px-1.5 text-[11px] leading-5 ${item.size === s ? "bg-panel font-semibold text-fg shadow-sm" : "text-fg-subtle hover:text-fg"}`}>
              {SIZE_LABEL[s]}
            </button>
          ))}
        </div>
      )}
      <button className="grid h-6 w-6 place-items-center rounded text-fg-subtle hover:bg-muted hover:text-fg disabled:opacity-30"
        onClick={() => onMove(-1)} disabled={first} aria-label={`Move ${meta.title} earlier`}>
        <ArrowUp size={13} />
      </button>
      <button className="grid h-6 w-6 place-items-center rounded text-fg-subtle hover:bg-muted hover:text-fg disabled:opacity-30"
        onClick={() => onMove(1)} disabled={last} aria-label={`Move ${meta.title} later`}>
        <ArrowDown size={13} />
      </button>
      <button className="grid h-6 w-6 place-items-center rounded text-fg-subtle hover:bg-danger/10 hover:text-danger"
        onClick={onRemove} aria-label={`Remove ${meta.title}`}>
        <X size={13} />
      </button>
    </div>
  );
}

export function CustomizableDashboard() {
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<LayoutItem[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const editing = draft !== null;
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeSize, setActiveSize] = useState<{ width: number; height: number } | null>(null);
  const sensors = useSensors(
    // A few pixels of movement before a drag starts, so clicks on the card's controls stay clicks.
    useSensor(CardPointerSensor, { activationConstraint: { distance: 6 } }),
    // On touch, press and hold, so a swipe still scrolls the page.
    useSensor(CardTouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: dashboardKeyboardCoordinates }),
  );
  const layout = useQuery({ queryKey: ["dash-layout"], queryFn: () => dashboardApi.layout() });
  // While editing, fetch everything so any widget added to the draft renders right away.
  const sections = editing ? undefined : layout.data?.sections;
  const hr = useQuery({
    queryKey: ["dash-hr", sections ?? "all"],
    queryFn: () => dashboardApi.hr(sections),
    enabled: layout.isSuccess,
  });

  const applied = (saved: DashboardLayout) => {
    qc.setQueryData(["dash-layout"], saved);
    setDraft(null);
  };
  const save = useMutation({
    mutationFn: (items: LayoutItem[]) => dashboardApi.saveLayout(items),
    onSuccess: (saved) => { applied(saved); toast.success("Dashboard saved", "Your layout is kept for next time."); },
    onError: (e) => toast.error("Couldn’t save your dashboard", errorMessage(e)),
  });
  const reset = useMutation({
    mutationFn: () => dashboardApi.resetLayout(),
    onSuccess: (saved) => { applied(saved); setConfirmReset(false); toast.success("Dashboard reset", "You’re back to the default layout."); },
    onError: (e) => toast.error("Couldn’t reset your dashboard", errorMessage(e)),
  });

  if (layout.isPending) {
    return (
      <div className="grid grid-cols-12 gap-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className={`${SPAN.quarter} h-28 rounded-xl`} />)}
        {[0, 1].map((i) => <Skeleton key={i} className={`${SPAN.half} h-64 rounded-xl`} />)}
      </div>
    );
  }
  if (layout.isError) {
    return (
      <Notice title="Your dashboard couldn’t be loaded"
        action={<button onClick={() => layout.refetch()} className="btn-secondary btn-sm shrink-0">Retry</button>}>
        {errorMessage(layout.error)}
      </Notice>
    );
  }

  const catalog = layout.data.catalog;
  const info = new Map(catalog.map((w) => [w.id, w]));
  const items = (draft ?? layout.data.widgets).filter((it) => WIDGETS[it.widget] && info.has(it.widget));
  const onBoard = new Set(items.map((it) => it.widget));

  const update = (next: LayoutItem[]) => setDraft(next);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length || from === to) return;
    const next = [...items];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    update(next);
  };
  const resize = (index: number, size: WidgetSize) =>
    update(items.map((it, i) => (i === index ? { ...it, size } : it)));
  const remove = (index: number) => update(items.filter((_, i) => i !== index));
  const add = (w: WidgetInfo) => update([...items, { widget: w.id, size: w.default_size }]);

  // ── Drag and drop (dnd-kit): mouse, touch and keyboard, announced to screen readers ──
  const activeItem = activeId ? items.find((it) => it.widget === activeId) : undefined;
  const title = (id: string | number | undefined) => (id ? info.get(String(id))?.title ?? "" : "");
  const position = (id: string | number) => items.findIndex((it) => it.widget === id) + 1;
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${title(active.id)}, position ${position(active.id)} of ${items.length}.`,
    onDragOver: ({ active, over }) =>
      over && over.id !== active.id ? `Drop to swap ${title(active.id)} with ${title(over.id)}.` : `${title(active.id)} has no new drop target.`,
    onDragEnd: ({ active, over }) =>
      over && over.id !== active.id ? `Swapped ${title(active.id)} with ${title(over.id)}.` : `${title(active.id)} stays where it was.`,
    onDragCancel: ({ active }) => `Moving ${title(active.id)} was cancelled; it is back where it was.`,
  };
  const onDragStart = ({ active }: DragStartEvent) => {
    setActiveId(String(active.id));
    const rect = active.rect.current.initial;
    setActiveSize(rect ? { width: rect.width, height: rect.height } : null);
  };
  // Swap the two positions in the saved order and let the responsive grid reflow.
  // Targets stay in place during the drag so mixed-width cards cannot obscure them.
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setActiveId(null);
    if (!over || active.id === over.id) return;
    setDraft((prev) => {
      if (!prev) return prev;
      const a = prev.findIndex((it) => it.widget === active.id);
      const b = prev.findIndex((it) => it.widget === over.id);
      if (a < 0 || b < 0) return prev;
      const next = [...prev];
      [next[a], next[b]] = [next[b], next[a]];
      return next;
    });
  };
  const onDragCancel = () => setActiveId(null);

  return (
    <div className="space-y-4">
      {hr.isError && (
        <Notice title="Live data is unavailable"
          action={<button onClick={() => hr.refetch()} className="btn-secondary btn-sm shrink-0">Retry</button>}>
          The figures below aren’t current. {errorMessage(hr.error)}
        </Notice>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        {editing ? (
          <>
            <p className="mr-auto text-[13px] text-fg-muted">
              Drag a card onto another to swap them (or focus a grip: Space, arrow keys, Space), pick a width, or remove what you don’t need.
            </p>
            <button className="btn-secondary btn-sm" onClick={() => setAdding(true)}>
              <Plus size={14} /> Add widget
            </button>
            {!layout.data.is_default && (
              <button className="btn-secondary btn-sm" onClick={() => setConfirmReset(true)}>
                <RotateCcw size={14} /> Reset to default
              </button>
            )}
            <button className="btn-secondary btn-sm" onClick={() => setDraft(null)} disabled={save.isPending}>Cancel</button>
            <button className="btn-primary btn-sm" onClick={() => save.mutate(items)} disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save layout"}
            </button>
          </>
        ) : (
          <button className="btn-secondary btn-sm" onClick={() => setDraft(layout.data.widgets)}>
            <LayoutGrid size={14} /> Customize dashboard
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <div className="card">
          <EmptyState icon={LayoutGrid} title="Your dashboard is empty"
            description="Add the widgets you want to see here."
            action={<button className="btn-primary" onClick={() => { if (!editing) setDraft([]); setAdding(true); }}>
              <Plus size={15} /> Add widgets
            </button>} />
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={dashboardCollisionDetection}
          accessibility={{ announcements, screenReaderInstructions: { draggable: DRAG_HELP } }}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={onDragCancel}
        >
          <SortableContext items={items.map((it) => it.widget)} strategy={stationaryStrategy}>
            <div className="grid grid-cols-12 gap-4">
              {items.map((it, index) => (
                <SortableCard key={it.widget} item={it} title={info.get(it.widget)!.title} editing={editing}>
                  {(grip) => (
                    <>
                      {editing && (
                        <CardToolbar
                          meta={info.get(it.widget)!} item={it} grip={grip}
                          first={index === 0} last={index === items.length - 1}
                          onResize={(size) => resize(index, size)}
                          onMove={(by) => move(index, index + by)}
                          onRemove={() => remove(index)}
                        />
                      )}
                      <div className={`h-full ${editing ? "pointer-events-none select-none pt-10" : ""}`}>
                        {(() => {
                          const Widget = WIDGETS[it.widget];
                          return <Widget data={hr.data} loading={hr.isPending} size={it.size} />;
                        })()}
                      </div>
                    </>
                  )}
                </SortableCard>
              ))}
            </div>
          </SortableContext>
          <DragOverlay dropAnimation={null}>
            {activeItem && (
              <div
                className="flex h-full w-full cursor-grabbing flex-col rounded-xl border-2 border-brand-500 bg-panel p-4 shadow-pop"
                style={{ height: activeSize?.height, width: activeSize?.width }}
              >
                <div className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                  <GripVertical size={14} className="text-brand-500" aria-hidden />
                  {info.get(activeItem.widget)?.title}
                </div>
                <p className="mt-1 text-xs text-fg-subtle">{info.get(activeItem.widget)?.description}</p>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}

      <Sheet open={adding} onClose={() => setAdding(false)} title="Add a widget"
        description="Widgets you can see with your access. Each one appears at the end of your dashboard.">
        <WidgetPicker catalog={catalog} onBoard={onBoard} onAdd={(w) => add(w)} />
      </Sheet>

      <ConfirmDialog open={confirmReset} onClose={() => setConfirmReset(false)} onConfirm={() => reset.mutate()}
        title="Reset your dashboard?" description="Your layout will go back to the default set of widgets. This can’t be undone."
        confirmLabel="Reset" loading={reset.isPending} />
    </div>
  );
}

function WidgetPicker({ catalog, onBoard, onAdd }: {
  catalog: WidgetInfo[];
  onBoard: Set<string>;
  onAdd: (w: WidgetInfo) => void;
}) {
  const categories = [...new Set(catalog.map((w) => w.category))];
  const available = catalog.filter((w) => WIDGETS[w.id]);
  if (available.every((w) => onBoard.has(w.id))) {
    return <EmptyState icon={LayoutGrid} title="Everything’s on your dashboard" description="Remove a widget to add it back later." />;
  }
  return (
    <div className="space-y-5">
      {categories.map((category) => {
        const choices = available.filter((w) => w.category === category && !onBoard.has(w.id));
        if (choices.length === 0) return null;
        return (
          <section key={category}>
            <p className="eyebrow mb-2">{category}</p>
            <ul className="space-y-2">
              {choices.map((w) => (
                <li key={w.id} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-fg">{w.title}</p>
                    <p className="text-xs text-fg-subtle">{w.description}</p>
                  </div>
                  <button className="btn-secondary btn-sm shrink-0" onClick={() => onAdd(w)}>
                    <Plus size={13} /> Add
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
