import { useId, useRef, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { useTheme } from "../../context/ThemeContext";
import { CHART } from "./chartPalette";

function svgId(raw: string) {
  return raw.replace(/[^a-zA-Z0-9_-]/g, "");
}

export function Sparkline({ data, className = "", width = 88, height = 32 }: {
  data: number[];
  className?: string;
  width?: number;
  height?: number;
}) {
  const id = svgId(useId());
  const min = Math.min(...data);
  const span = Math.max(...data) - min || 1;
  const pts = data.map((d, i) => [
    (i / (data.length - 1)) * width,
    height - 3 - ((d - min) / span) * (height - 6),
  ]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity="0.2" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export interface AreaPoint { label: string; value: number; detail?: ReactNode }

export function AreaChart({ data, min, max, height = 220, unit = "", color = CHART.brand }: {
  data: AreaPoint[];
  min: number;
  max: number;
  height?: number;
  unit?: string;
  color?: string;
}) {
  const id = svgId(useId());
  const [hover, setHover] = useState<number | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const W = 1000;
  const H = 100;
  const x = (i: number) => (i / (data.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / (max - min)) * H;
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.value).toFixed(2)}`).join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * (1 - t));

  const onMove = (e: MouseEvent) => {
    const r = plotRef.current?.getBoundingClientRect();
    if (!r) return;
    const i = Math.round(((e.clientX - r.left) / r.width) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  };

  const h = hover !== null ? data[hover] : null;
  const hx = hover !== null ? (hover / (data.length - 1)) * 100 : 0;

  return (
    <div className="flex gap-3">
      <div className="flex shrink-0 flex-col justify-between pb-6 text-right text-[11px] tabular-nums text-fg-subtle" style={{ height }}>
        {ticks.map((t) => <span key={t} className="-translate-y-1/2 leading-none first:translate-y-0 last:translate-y-0">{Math.round(t)}{unit}</span>)}
      </div>
      <div className="min-w-0 flex-1">
        <div ref={plotRef} className="relative" style={{ height: height - 24 }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          {ticks.map((t, i) => (
            <div key={t} className="absolute inset-x-0 border-t border-dashed border-line" style={{ top: `${i * 25}%` }} />
          ))}
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden>
            <defs>
              <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor={color} stopOpacity="0.22" />
                <stop offset="1" stopColor={color} stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={`${line} L${W},${H} L0,${H} Z`} fill={`url(#${id})`} />
            <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
          </svg>
          {h && (
            <>
              <div className="pointer-events-none absolute inset-y-0 w-px bg-line-strong" style={{ left: `${hx}%` }} />
              <div
                className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface shadow"
                style={{ left: `${hx}%`, top: `${(y(h.value) / H) * 100}%`, background: color }}
              />
              <div
                className="pointer-events-none absolute top-0 z-10 min-w-[140px] rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop"
                style={hx > 60 ? { right: `${100 - hx}%`, marginRight: 12 } : { left: `${hx}%`, marginLeft: 12 }}
              >
                <p className="font-medium text-fg">{h.label}</p>
                <p className="mt-0.5 tabular-nums text-fg-muted">
                  <span className="font-semibold text-fg">{h.value}{unit}</span> attendance
                </p>
                {h.detail && <div className="mt-1.5 border-t border-line pt-1.5 text-fg-subtle">{h.detail}</div>}
              </div>
            </>
          )}
        </div>
        <div className="mt-2 flex justify-between text-[11px] text-fg-subtle">
          {data.map((d, i) => (
            <span key={d.label} className={i % 2 ? "hidden sm:inline" : ""}>{d.label}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

export interface DonutSegment { label: string; value: number; color: string }

export function Donut({ segments, size = 152, thickness = 14, children }: {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  children?: ReactNode;
}) {
  const { colorTheme } = useTheme();
  const midnight = colorTheme === "midnight-blue";
  const id = svgId(useId());
  const ringWidth = midnight ? Math.max(thickness, size * .1) : thickness;
  const r = (size - ringWidth) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((a, s) => a + s.value, 0);
  const visible = segments.filter((s) => s.value > 0);
  const gap = !midnight && visible.length > 1 ? 3 : 0;
  let offset = 0;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        {midnight && <defs>{visible.map((s, i) => (
          <radialGradient key={s.label} id={`${id}-${i}`}>
            <stop offset="75%" stopColor={s.color} />
            <stop offset="100%" stopColor={s.color} stopOpacity=".88" />
          </radialGradient>
        ))}</defs>}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={CHART.track} strokeWidth={ringWidth} />
        {total > 0 && visible.map((s, i) => {
          const len = (s.value / total) * c;
          const el = (
            <circle
              key={s.label}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={midnight ? `url(#${id}-${i})` : s.color}
              strokeWidth={ringWidth}
              strokeDasharray={`${Math.max(len - gap, 0.5)} ${c}`}
              strokeDashoffset={-offset}
              className="transition-[stroke-dasharray] duration-500"
            />
          );
          offset += len;
          return el;
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

type BarItem = { label: string; value: number; color?: string };

/** Reference-style columns; the dashboard's card order and grid spans stay shared. */
export function DepartmentColumns({ items, height = 208 }: { items: BarItem[]; height?: number }) {
  const id = svgId(useId());
  const highest = Math.max(...items.map((item) => item.value), 1);
  const magnitude = 10 ** Math.floor(Math.log10(highest));
  const ceiling = Math.ceil(highest / magnitude) * magnitude;
  const left = 32, top = 24, bottom = height - 35, plot = bottom - top;
  const width = 600, cell = (width - left - 12) / Math.max(items.length, 1);
  const barWidth = Math.min(30, cell * .45);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-labelledby={`${id}-title ${id}-description`} className="department-columns">
      <title id={`${id}-title`}>Headcount by department</title>
      <desc id={`${id}-description`}>{items.map((item) => `${item.label}: ${item.value}`).join("; ")}</desc>
      <defs>
        <linearGradient id={`${id}-bar`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--chart-column-top, #4095ff)" />
          <stop offset="1" stopColor="var(--chart-column-bottom, #2476ed)" />
        </linearGradient>
      </defs>
      {[0, 1, 2, 3, 4].map((tick) => {
        const y = top + tick * plot / 4;
        return <g key={tick}>
          <line x1={left} x2={width - 12} y1={y} y2={y} stroke="rgb(var(--line))" strokeWidth=".7" />
          <text x={left - 8} y={y + 3} textAnchor="end" fill="rgb(var(--fg-subtle))" fontSize="10">{Number((ceiling * (1 - tick / 4)).toFixed(2))}</text>
        </g>;
      })}
      {items.map((item, i) => {
        const x = left + cell * (i + .5);
        const barHeight = Math.max(0, item.value) / ceiling * plot;
        return <g key={item.label}>
          <title>{`${item.label}: ${item.value}`}</title>
          <rect x={x - barWidth / 2} y={bottom - barHeight} width={barWidth} height={barHeight} rx="3" fill={`url(#${id}-bar)`} />
          <text x={x} y={bottom - barHeight - 7} textAnchor="middle" fill="rgb(var(--fg))" fontWeight="600" fontSize="11">{item.value}</text>
          <text x={x} y={bottom + 18} textAnchor="middle" fill="rgb(var(--fg-subtle))" fontSize="10">{item.label.length > Math.max(7, Math.floor(cell / 5)) ? `${item.label.slice(0, Math.max(6, Math.floor(cell / 5) - 1))}…` : item.label}</text>
        </g>;
      })}
    </svg>
  );
}

export function DepartmentChart({ items }: { items: BarItem[] }) {
  const { colorTheme } = useTheme();
  return colorTheme === "midnight-blue"
    ? <DepartmentColumns items={items} height={Math.max(112, items.length * 38 - 6)} />
    : <BarList items={items} />;
}

export function DepartmentProgress({ items, formatValue = String }: { items: BarItem[]; formatValue?: (value: number) => string }) {
  const { colorTheme } = useTheme();
  const max = Math.max(...items.map((item) => item.value), 1);
  if (colorTheme !== "midnight-blue") return <BarList items={items} formatValue={formatValue} />;
  return <ul className="space-y-1.5 department-progress">
    {items.map((item) => <li key={item.label} className="flex h-8 items-center gap-3 text-xs">
      <span className="w-[28%] shrink-0 truncate text-fg-muted" title={item.label}>{item.label}</span>
      <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <span className="block h-full rounded-full bg-brand-700" style={{ width: `${Math.max(0, item.value) / max * 100}%` }} />
      </span>
      <span className="w-12 shrink-0 text-right tabular-nums text-fg-muted">{formatValue(item.value)}</span>
    </li>)}
  </ul>;
}

export function BarList({ items, formatValue = (v) => String(v) }: {
  items: { label: string; value: number; color?: string }[];
  formatValue?: (v: number) => string;
}) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="space-y-1.5">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-3">
          <div className="relative h-8 flex-1 overflow-hidden rounded-md">
            <div
              className="absolute inset-y-0 left-0 rounded-md bg-brand-500/15 transition-[width] duration-500 dark:bg-brand-400/15"
              style={{ width: `${(it.value / max) * 100}%`, background: it.color }}
            />
            <span className="relative flex h-full items-center px-2.5 text-[13px] text-fg">{it.label}</span>
          </div>
          <span className="w-10 text-right text-[13px] font-medium tabular-nums text-fg">{formatValue(it.value)}</span>
        </li>
      ))}
    </ul>
  );
}

export function Legend({ items }: { items: { label: string; color: string; value?: ReactNode }[] }) {
  return (
    <ul className="space-y-2.5">
      {items.map((it) => (
        <li key={it.label} className="flex items-center justify-between gap-6 text-[13px]">
          <span className="flex items-center gap-2 text-fg-muted">
            <span className="h-2 w-2 rounded-full" style={{ background: it.color }} />
            {it.label}
          </span>
          {it.value !== undefined && <span className="font-medium tabular-nums text-fg">{it.value}</span>}
        </li>
      ))}
    </ul>
  );
}
