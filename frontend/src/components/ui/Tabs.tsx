import { useEffect, useRef, useState } from "react";
import type { ElementType } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface TabItem<T extends string> {
  value: T;
  label: string;
  count?: number;
}

const FADE = 32;

export function Tabs<T extends string>({ value, onChange, items, className = "" }: {
  value: T;
  onChange: (v: T) => void;
  items: TabItem<T>[];
  className?: string;
}) {
  // The scrollbar is hidden, so when the tabs don't fit, fade the cut-off edge and show an
  // arrow: otherwise tabs past the edge are invisible to anyone using a mouse.
  const listRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const update = () =>
      setEdges({ left: el.scrollLeft > 2, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2 });
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, [items.length]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [value]);

  const nudge = (direction: -1 | 1) => {
    const el = listRef.current;
    if (el) el.scrollBy({ left: direction * Math.max(el.clientWidth * 0.6, 120), behavior: "smooth" });
  };
  const mask = `linear-gradient(to right, ${edges.left ? "transparent" : "black"}, black ${FADE}px, black calc(100% - ${FADE}px), ${edges.right ? "transparent" : "black"})`;

  return (
    <div className={`relative ${className}`}>
      <div
        ref={listRef}
        role="tablist"
        className="no-scrollbar flex items-center gap-5 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_rgb(var(--line))]"
        style={edges.left || edges.right ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
      >
        {items.map((it) => {
          const active = it.value === value;
          return (
            <button
              key={it.value}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(it.value)}
              className={`relative flex h-10 shrink-0 items-center gap-2 border-b-2 text-[13px] font-medium transition-colors ${
                active ? "border-fg text-fg" : "border-transparent text-fg-subtle hover:text-fg-muted"
              }`}
            >
              {it.label}
              {it.count !== undefined && (
                <span
                  className={`rounded-full px-1.5 py-px text-[11px] tabular-nums ${
                    active ? "bg-fg text-surface" : "bg-muted text-fg-muted"
                  }`}
                >
                  {it.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {edges.left && (
        <button type="button" aria-label="Show earlier tabs" onClick={() => nudge(-1)}
          className="absolute inset-y-0 left-0 flex w-7 items-center justify-start text-fg-muted hover:text-fg">
          <ChevronLeft size={16} />
        </button>
      )}
      {edges.right && (
        <button type="button" aria-label="Show more tabs" onClick={() => nudge(1)}
          className="absolute inset-y-0 right-0 flex w-7 items-center justify-end text-fg-muted hover:text-fg">
          <ChevronRight size={16} />
        </button>
      )}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, items }: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: string; icon?: ElementType }[];
}) {
  return (
    <div className="seg" role="radiogroup">
      {items.map(({ value: v, label, icon: Icon }) => (
        <button
          key={v}
          role="radio"
          aria-checked={v === value}
          aria-label={label || v}
          title={label ? undefined : v.charAt(0).toUpperCase() + v.slice(1)}
          data-active={v === value}
          onClick={() => onChange(v)}
          className="seg-item"
        >
          {Icon && <Icon size={13} />}
          {label}
        </button>
      ))}
    </div>
  );
}
