import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import {
  Search, Bell, PanelLeft, ChevronRight, ChevronsUpDown, LogOut, Sun, Moon, Monitor,
  Umbrella, FilePenLine, CheckCheck, CircleCheck, CircleX, UserCircle, ExternalLink, BookOpen,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import type { UserRole } from "../../context/AuthContext";
import { useTheme } from "../../context/ThemeContext";
import { DECISION_STATUSES, leaveApi } from "../../api/leave";
import { correctionsApi } from "../../api/corrections";
import { Avatar } from "../ui/Avatar";
import { Segmented } from "../ui/Tabs";
import { humanize } from "../ui/StatusBadge";
import { usePopover } from "../ui/Popover";
import { CommandPalette } from "./CommandPalette";
import { navFor, findNav } from "./nav";

const ROLE_LABEL: Record<UserRole, string> = {
  EMPLOYEE: "Employee",
  MANAGER: "Manager",
  HR: "HR Manager",
  SUPER_ADMIN: "Super Admin",
};

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
const MOD_KEY = isMac ? "⌘" : "Ctrl";

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const scrollRef = useRef<HTMLElement>(null);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("hrms_sidebar") === "collapsed"; } catch { return false; }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [location.pathname]);

  const { user } = useAuth();
  useEffect(() => {
    document.title = user?.tenantName ? `${user.tenantName} · HRMS` : "HRMS";
  }, [user?.tenantName]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const toggleSidebar = () => {
    if (matchMedia("(min-width: 1024px)").matches) {
      setCollapsed((c) => {
        try { localStorage.setItem("hrms_sidebar", c ? "expanded" : "collapsed"); } catch { /* ignore */ }
        return !c;
      });
    } else {
      setMobileOpen(true);
    }
  };

  const openPalette = () => { setMobileOpen(false); setPaletteOpen(true); };

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <aside
        className={`hidden shrink-0 flex-col transition-[width] duration-200 ease-out lg:flex ${collapsed ? "w-[68px]" : "w-60"}`}
      >
        <SidebarContent collapsed={collapsed} onSearch={openPalette} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-canvas shadow-pop animate-slide-in-left">
            <SidebarContent collapsed={false} onSearch={openPalette} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:py-2 lg:pr-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-panel lg:rounded-xl lg:border lg:border-line lg:shadow-xs">
          <TopBar onToggleSidebar={toggleSidebar} onSearch={openPalette} />
          <main ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
          </main>
        </div>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

/* ── Sidebar ── */
function SidebarContent({ collapsed, onSearch, onNavigate }: { collapsed: boolean; onSearch: () => void; onNavigate?: () => void }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <div className={`flex h-14 shrink-0 items-center gap-2.5 ${collapsed ? "justify-center" : "px-4"}`}>
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-[15px] font-bold text-white shadow-xs ring-1 ring-inset ring-white/15">
          {user.tenantName.charAt(0).toUpperCase()}
        </div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-semibold text-fg">{user.tenantName}</p>
            <p className="truncate text-[11px] text-fg-subtle">People Platform</p>
          </div>
        )}
      </div>

      <div className={collapsed ? "flex justify-center pb-2" : "px-3 pb-2"}>
        <button
          onClick={onSearch}
          title={collapsed ? `Search (${MOD_KEY}+K)` : undefined}
          className={`flex h-8 items-center gap-2 rounded-lg border border-line bg-surface text-[13px] text-fg-subtle shadow-xs transition-colors hover:border-line-strong hover:text-fg-muted ${
            collapsed ? "w-8 justify-center" : "w-full px-2.5"
          }`}
        >
          <Search size={14} />
          {!collapsed && (
            <>
              <span>Search…</span>
              <span className="ml-auto flex gap-0.5"><kbd className="kbd">{MOD_KEY}</kbd><kbd className="kbd">K</kbd></span>
            </>
          )}
        </button>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-2" aria-label="Main">
        {navFor(user).map((section, idx) => (
          <div key={section.label}>
            {collapsed ? (
              idx > 0 && <div className="mx-2 mb-3 h-px bg-line" />
            ) : (
              <p className="px-2 pb-1.5 text-[11px] font-medium text-fg-subtle">{section.label}</p>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) =>
                item.external ? (
                  <a
                    key={item.to}
                    href={item.to}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={`group flex h-8 items-center gap-2.5 rounded-lg text-[13px] font-medium transition-colors ${
                      collapsed ? "justify-center" : "px-2.5"
                    } text-fg-muted hover:bg-fg/[0.045] hover:text-fg`}
                  >
                    <item.icon
                      size={16}
                      strokeWidth={1.9}
                      className="text-fg-subtle transition-colors group-hover:text-fg-muted"
                    />
                    {!collapsed && (
                      <span className="flex flex-1 items-center justify-between truncate">
                        <span className="truncate">{item.label}</span>
                        <ExternalLink size={12} className="shrink-0 opacity-40 group-hover:opacity-80" />
                      </span>
                    )}
                  </a>
                ) : (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      `group flex h-8 items-center gap-2.5 rounded-lg text-[13px] font-medium transition-colors ${
                        collapsed ? "justify-center" : "px-2.5"
                      } ${
                        isActive
                          ? "bg-surface text-fg shadow-xs ring-1 ring-line"
                          : "text-fg-muted hover:bg-fg/[0.045] hover:text-fg"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <item.icon
                          size={16}
                          strokeWidth={isActive ? 2.2 : 1.9}
                          className={isActive ? "text-accent" : "text-fg-subtle transition-colors group-hover:text-fg-muted"}
                        />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </>
                    )}
                  </NavLink>
                )
              )}
            </div>
          </div>
        ))}
      </nav>

      <div className="shrink-0 p-3">
        <UserMenu collapsed={collapsed} />
      </div>
    </>
  );
}

function UserMenu({ collapsed }: { collapsed: boolean }) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { open, setOpen, ref } = usePopover();
  if (!user) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`flex w-full items-center gap-2.5 rounded-lg text-left transition-colors hover:bg-fg/[0.045] ${
          collapsed ? "justify-center p-1" : "p-1.5"
        } ${open ? "bg-fg/[0.045]" : ""}`}
      >
        <Avatar name={user.name} size="md" />
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[13px] font-medium text-fg">{user.name}</span>
              <span className="block truncate text-[11px] text-fg-subtle">{ROLE_LABEL[user.role]}</span>
            </span>
            <ChevronsUpDown size={14} className="text-fg-subtle" />
          </>
        )}
      </button>

      {open && (
        <div className="popover absolute bottom-full left-0 mb-2 w-64">
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <Avatar name={user.name} size="lg" />
            <div className="min-w-0 leading-tight">
              <p className="truncate text-[13px] font-medium text-fg">{user.name}</p>
              <p className="truncate text-xs text-fg-subtle">{ROLE_LABEL[user.role]} · {user.tenantName}</p>
            </div>
          </div>
          <div className="my-1 h-px bg-line" />
          <Link to="/profile" onClick={() => setOpen(false)} className="menu-item">
            <UserCircle size={15} /> My profile
          </Link>
          <a
            href="https://hrmsapi.alvision.in/docs"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className="menu-item"
          >
            <BookOpen size={15} /> API Documentation
          </a>
          <div className="my-1 h-px bg-line" />
          <div className="flex items-center justify-between gap-2 px-2.5 py-2">
            <span className="text-[13px] text-fg-muted">Theme</span>
            <Segmented
              value={theme}
              onChange={setTheme}
              items={[
                { value: "light", label: "", icon: Sun },
                { value: "dark", label: "", icon: Moon },
                { value: "system", label: "", icon: Monitor },
              ]}
            />
          </div>
          <div className="my-1 h-px bg-line" />
          <button onClick={logout} className="menu-item hover:text-danger">
            <LogOut size={15} /> Sign out
          </button>
          <p className="px-2.5 pb-1 pt-1.5 text-[11px] text-fg-subtle tabular-nums">
            Version {__APP_VERSION__} · {__GIT_SHA__}
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Top bar ── */
function TopBar({ onToggleSidebar, onSearch }: { onToggleSidebar: () => void; onSearch: () => void }) {
  const { pathname } = useLocation();
  const { resolved, setTheme } = useTheme();
  const match = findNav(pathname);

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4 sm:px-6">
      <button onClick={onToggleSidebar} className="btn-icon -ml-1.5" aria-label="Toggle sidebar">
        <PanelLeft size={16} />
      </button>
      <div className="h-4 w-px bg-line" />
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
        {match && (
          <>
            <span className="hidden text-fg-subtle sm:inline">{match.section}</span>
            <ChevronRight size={14} className="hidden text-fg-subtle/70 sm:inline" />
            <span className="truncate font-medium text-fg">{match.item.label}</span>
          </>
        )}
      </nav>

      <div className="ml-auto flex items-center gap-1">
        <button onClick={onSearch} className="btn-icon lg:hidden" aria-label="Search">
          <Search size={16} />
        </button>
        <button
          onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
          className="btn-icon"
          aria-label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={resolved === "dark" ? "Light theme" : "Dark theme"}
        >
          {resolved === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <Notifications />
      </div>
    </header>
  );
}

/* ── Notifications (derived from real pending approvals) ── */
interface InboxItem { id: string; icon: LucideIcon; tone: string; title: string; detail: string; to: string; when: string | null }

function useInbox() {
  const { user } = useAuth();
  const role = user?.role ?? "EMPLOYEE";
  const empId = user?.employmentId ?? "";
  const isHR = role === "HR" || role === "SUPER_ADMIN";
  const isApprover = role !== "EMPLOYEE";

  // Only what the inbox shows: decisions waiting on an approver, or an employee's own
  // resolved requests — never the whole (paged) list.
  const leave = useQuery({
    queryKey: ["leave-applications", "inbox", isApprover, isHR ? "all" : empId],
    queryFn: () =>
      leaveApi.listApplications({
        employmentId: isHR ? undefined : empId,
        statuses: isApprover ? DECISION_STATUSES : ["APPROVED", "REJECTED"],
        limit: 50,
      }),
    enabled: !!user,
  });
  const cors = useQuery({
    queryKey: ["corrections"],
    queryFn: () => correctionsApi.list(isApprover ? undefined : empId),
    enabled: !!user,
  });

  const items: InboxItem[] = [];
  const range = (a: string, b: string) =>
    a === b ? format(new Date(a), "d MMM") : `${format(new Date(a), "d MMM")} – ${format(new Date(b), "d MMM")}`;

  if (isApprover) {
    for (const a of leave.data ?? []) {
      if (!a.status.includes("PENDING")) continue;
      items.push({
        id: a.id, icon: Umbrella, tone: "bg-warning/10 text-warning",
        title: a.status.startsWith("CANCEL") ? "Leave cancellation needs approval" : "Leave request needs approval",
        detail: `${a.leave_type_name} · ${range(a.from_date, a.to_date)} · ${a.days_requested}d`,
        to: "/leave?tab=approvals", when: a.applied_at,
      });
    }
    for (const c of cors.data ?? []) {
      if (!c.status.startsWith("PENDING")) continue;
      items.push({
        id: c.id, icon: FilePenLine, tone: "bg-info/10 text-info",
        title: "Attendance correction needs approval",
        detail: `${humanize(c.correction_type)} · ${format(new Date(c.work_date), "d MMM")}`,
        to: "/corrections?tab=approvals", when: c.submitted_at,
      });
    }
  } else {
    for (const a of leave.data ?? []) {
      if (a.status !== "APPROVED" && a.status !== "REJECTED") continue;
      const ok = a.status === "APPROVED";
      items.push({
        id: a.id, icon: ok ? CircleCheck : CircleX, tone: ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
        title: `Your leave was ${ok ? "approved" : "rejected"}`,
        detail: `${a.leave_type_name} · ${range(a.from_date, a.to_date)}`,
        to: "/leave", when: a.applied_at,
      });
    }
    for (const c of cors.data ?? []) {
      if (c.status !== "APPROVED" && c.status !== "REJECTED") continue;
      const ok = c.status === "APPROVED";
      items.push({
        id: c.id, icon: ok ? CircleCheck : CircleX, tone: ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
        title: `Correction ${ok ? "approved" : "rejected"}`,
        detail: `${humanize(c.correction_type)} · ${format(new Date(c.work_date), "d MMM")}`,
        to: "/corrections", when: c.submitted_at,
      });
    }
  }

  items.sort((a, b) => (b.when ?? "").localeCompare(a.when ?? ""));
  return { items, isLoading: leave.isPending || cors.isPending, isError: leave.isError && cors.isError, isApprover };
}

function Notifications() {
  const { open, setOpen, ref } = usePopover();
  const { items, isLoading, isError, isApprover } = useInbox();

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`btn-icon relative ${open ? "bg-muted text-fg" : ""}`}
        aria-label={`Notifications${items.length ? ` (${items.length})` : ""}`}
        aria-expanded={open}
      >
        <Bell size={16} />
        {items.length > 0 && (
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-danger ring-2 ring-panel" />
        )}
      </button>

      {open && (
        <div className="popover absolute right-0 top-full mt-2 w-[min(380px,calc(100vw-2rem))] p-0">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="text-sm font-semibold text-fg">Notifications</p>
            {items.length > 0 && <span className="badge badge-neutral">{items.length} new</span>}
          </div>
          <div className="max-h-[380px] overflow-y-auto p-1.5">
            {isLoading ? (
              <p className="px-3 py-8 text-center text-[13px] text-fg-subtle">Loading…</p>
            ) : isError ? (
              <p className="px-3 py-8 text-center text-[13px] text-fg-subtle">Couldn’t reach the server. Try again shortly.</p>
            ) : items.length === 0 ? (
              <div className="flex flex-col items-center px-3 py-10 text-center">
                <div className="grid h-10 w-10 place-items-center rounded-full bg-success/10 text-success"><CheckCheck size={18} /></div>
                <p className="mt-3 text-[13px] font-medium text-fg">You’re all caught up</p>
                <p className="mt-0.5 text-xs text-fg-subtle">{isApprover ? "No approvals are waiting on you." : "No new updates on your requests."}</p>
              </div>
            ) : (
              items.slice(0, 8).map((n) => (
                <Link
                  key={n.id}
                  to={n.to}
                  onClick={() => setOpen(false)}
                  className="flex items-start gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-muted"
                >
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${n.tone}`}><n.icon size={15} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-fg">{n.title}</span>
                    <span className="block truncate text-xs text-fg-subtle">{n.detail}</span>
                  </span>
                  {n.when && (
                    <span className="shrink-0 text-[11px] text-fg-subtle">
                      {formatDistanceToNow(new Date(n.when), { addSuffix: false })}
                    </span>
                  )}
                </Link>
              ))
            )}
          </div>
          {isApprover && items.length > 0 && (
            <div className="border-t border-line px-4 py-2.5">
              <Link to="/leave?tab=approvals" onClick={() => setOpen(false)} className="link text-xs">Review all approvals →</Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
