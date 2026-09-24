import type { ElementType } from "react";

export interface TabItem<T extends string> {
  value: T;
  label: string;
  count?: number;
}

export function Tabs<T extends string>({ value, onChange, items, className = "" }: {
  value: T;
  onChange: (v: T) => void;
  items: TabItem<T>[];
  className?: string;
}) {
  return (
    <div role="tablist" className={`no-scrollbar flex items-center gap-5 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_rgb(var(--line))] ${className}`}>
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
