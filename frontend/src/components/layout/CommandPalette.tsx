import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { Search, Umbrella, FilePenLine, Moon, Sun, LogOut, CornerDownLeft, ArrowRight } from "lucide-react";
import { Dialog } from "../ui/Overlay";
import { useAuth } from "../../context/AuthContext";
import { useTheme } from "../../context/ThemeContext";
import { navFor } from "./nav";

interface Command {
  id: string;
  group: string;
  label: string;
  icon: LucideIcon;
  hint?: string;
  run: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} className="max-w-xl">
      {open && <PaletteBody onClose={onClose} />}
    </Dialog>
  );
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { resolved, setTheme } = useTheme();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo<Command[]>(() => {
    if (!user) return [];
    const go = (to: string) => () => navigate(to);
    const pages = navFor(user).flatMap((s) =>
      s.items.map((i) => ({
        id: `page:${i.to}`,
        group: i.external ? "Resources" : "Go to",
        label: i.label,
        icon: i.icon,
        hint: s.label,
        run: i.external
          ? () => {
              onClose();
              window.open(i.to, "_blank", "noopener,noreferrer");
            }
          : go(i.to),
      })),
    );
    const actions: Command[] = [
      { id: "leave", group: "Actions", label: "Apply for leave", icon: Umbrella, run: go("/leave?new=1") },
      { id: "cor", group: "Actions", label: "Request attendance correction", icon: FilePenLine, run: go("/corrections?new=1") },
      {
        id: "theme", group: "Actions",
        label: resolved === "dark" ? "Switch to light theme" : "Switch to dark theme",
        icon: resolved === "dark" ? Sun : Moon,
        run: () => setTheme(resolved === "dark" ? "light" : "dark"),
      },
      { id: "logout", group: "Actions", label: "Sign out", icon: LogOut, run: logout },
    ];
    const q = query.trim().toLowerCase();
    const all = [...pages, ...actions].filter((c) => !q || c.label.toLowerCase().includes(q));
    const canSearchPeople = user.role !== "EMPLOYEE";
    if (q && canSearchPeople) {
      all.push({
        id: "people", group: "Employees", label: `Search employees for “${query.trim()}”`, icon: Search,
        run: go(`/employees?q=${encodeURIComponent(query.trim())}`),
      });
    }
    return all;
  }, [user, query, resolved, navigate, setTheme, logout]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (c?: Command) => {
    if (!c) return;
    onClose();
    c.run();
  };

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, commands.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    if (e.key === "Enter") { e.preventDefault(); run(commands[active]); }
  };

  let lastGroup = "";
  return (
    <div onKeyDown={onKeyDown}>
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={16} className="shrink-0 text-fg-subtle" />
        <input
          autoFocus
          value={query}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          placeholder="Search pages, actions, employees…"
          className="h-12 w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
          aria-label="Command search"
        />
        <kbd className="kbd">Esc</kbd>
      </div>
      <div ref={listRef} className="max-h-[min(60vh,420px)] overflow-y-auto p-2" role="listbox">
        {commands.length === 0 && (
          <p className="px-3 py-10 text-center text-[13px] text-fg-subtle">No results for “{query}”</p>
        )}
        {commands.map((c, i) => {
          const header = c.group !== lastGroup ? c.group : null;
          lastGroup = c.group;
          return (
            <div key={c.id}>
              {header && <p className="px-2.5 pb-1 pt-2.5 text-[11px] font-medium text-fg-subtle">{header}</p>}
              <button
                data-index={i}
                role="option"
                aria-selected={i === active}
                onMouseMove={() => setActive(i)}
                onClick={() => run(c)}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13px] ${
                  i === active ? "bg-muted text-fg" : "text-fg-muted"
                }`}
              >
                <c.icon size={16} className={i === active ? "text-accent" : "text-fg-subtle"} />
                <span className="flex-1 truncate">{c.label}</span>
                {c.hint && <span className="text-xs text-fg-subtle">{c.hint}</span>}
                {i === active && <ArrowRight size={14} className="text-fg-subtle" />}
              </button>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-4 border-t border-line bg-panel px-4 py-2.5 text-[11px] text-fg-subtle">
        <span className="flex items-center gap-1"><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> Navigate</span>
        <span className="flex items-center gap-1"><kbd className="kbd"><CornerDownLeft size={10} /></kbd> Open</span>
        <span className="ml-auto">HRMS</span>
      </div>
    </div>
  );
}
