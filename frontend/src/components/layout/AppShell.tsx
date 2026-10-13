import { createElement, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import {
  Search, Bell, PanelLeft, ChevronRight, ChevronsUpDown, LogOut, Sun, Moon,
  Umbrella, FilePenLine, CheckCheck, CircleCheck, CircleX, UserCircle, ExternalLink, BookOpen,
  Palette,
} from "../icons/ThemeIcons";
import type { LucideIcon, LucideProps } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { PreferencesSync, useChangeColorTheme } from "../../lib/preferences";
import type { UserRole } from "../../context/AuthContext";
import { COLOR_THEMES, useTheme } from "../../context/ThemeContext";
import type { ColorTheme } from "../../context/ThemeContext";

const colorThemeName = (id: ColorTheme) => COLOR_THEMES.find((t) => t.id === id)?.name ?? id;
import { DECISION_STATUSES, leaveApi } from "../../api/leave";
import { correctionsApi } from "../../api/corrections";
import { Avatar } from "../ui/Avatar";
import { AppearanceControls } from "./AppearanceControls";
import { humanize } from "../ui/StatusBadge";
import { usePopover } from "../ui/Popover";
import { CommandPalette } from "./CommandPalette";
import { LoginCelebration } from "./LoginCelebration";
import { navFor, findNav, hasNestedNav } from "./nav";
import type { NavItem } from "./nav";
import { API_DOCS_URL } from "../../lib/runtimeConfig";
import { useModal } from "../../lib/useModal";

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
  const { colorTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("hrms_sidebar") === "collapsed"; } catch { return false; }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const mobilePanelRef = useModal<HTMLElement>(mobileOpen, () => setMobileOpen(false));

  useEffect(() => {
    const desktop = matchMedia("(min-width: 1024px)");
    const onChange = () => { if (desktop.matches) setMobileOpen(false); };
    desktop.addEventListener("change", onChange);
    return () => desktop.removeEventListener("change", onChange);
  }, []);

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

  const isHrmsTheme = colorTheme === "midnight-blue";

  return (
    <div className="app-shell flex h-dvh overflow-hidden bg-canvas">
      <PreferencesSync />
      <aside
        className={`app-sidebar hidden shrink-0 flex-col transition-[width] duration-200 ease-out lg:flex ${collapsed ? "w-[68px]" : "w-60"}`}
        style={isHrmsTheme ? { background: "var(--sidebar-bg, #0A1F4E)" } : undefined}
      >
        <SidebarContent collapsed={collapsed} onSearch={openPalette} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={() => setMobileOpen(false)} />
          <aside
            ref={mobilePanelRef}
            role="dialog"
            aria-label="Main navigation"
            aria-modal="true"
            tabIndex={-1}
            className={`app-sidebar absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-canvas shadow-pop animate-slide-in-left ${
              isHrmsTheme ? "border-[#1C3A75]" : ""
            }`}
            style={isHrmsTheme ? { background: "var(--sidebar-bg, #0A1F4E)" } : undefined}
          >
            <SidebarContent collapsed={false} onSearch={openPalette} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:py-2 lg:pr-2">
        <div className="app-workspace flex min-h-0 flex-1 flex-col overflow-hidden bg-panel lg:rounded-xl lg:border lg:border-line lg:shadow-xs">
          <TopBar onToggleSidebar={toggleSidebar} onSearch={openPalette} />
          <main ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
          </main>
        </div>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <LoginCelebration />
    </div>
  );
}

/* ── Sidebar ── */
function ItemIcon({ item, ...props }: { item: NavItem } & LucideProps) {
  return createElement(item.icon, props);
}

function SidebarContent({ collapsed, onSearch, onNavigate }: { collapsed: boolean; onSearch: () => void; onNavigate?: () => void }) {
  const { user } = useAuth();
  const { colorTheme } = useTheme();
  if (!user) return null;

  const isHrmsTheme = colorTheme === "midnight-blue";

  return (
    <>
      <div className={`flex shrink-0 items-center gap-2.5 h-14 ${collapsed ? "justify-center" : "px-4"}`}>
        <div className="tenant-mark grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-[15px] font-bold text-white shadow-xs ring-1 ring-inset ring-white/15">
          {user.tenantName.charAt(0).toUpperCase()}
        </div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <p className={`truncate font-semibold ${isHrmsTheme ? "text-[13px] text-white" : "text-[13px] text-fg"}`}>{user.tenantName}</p>
            <p className={`truncate text-[11px] ${isHrmsTheme ? "text-[#9FB3D9]" : "text-fg-subtle"}`}>People Platform</p>
          </div>
        )}
      </div>

      {/* Palettes share the same sidebar structure and search placement. */}
      <div className={`${collapsed ? "flex justify-center pb-2" : "px-3 pb-2"}`}>
        <button
          onClick={onSearch}
          title={collapsed ? `Search (${MOD_KEY}+K)` : undefined}
          className={`sidebar-search flex h-8 items-center gap-2 rounded-lg border text-[13px] shadow-xs transition-colors ${
            isHrmsTheme
              ? "border-[#1C3A75] bg-white/5 text-[#9FB3D9] hover:border-blue-400 hover:text-white"
              : "border border-line bg-surface text-fg-subtle hover:border-line-strong hover:text-fg-muted"
          } ${
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
              idx > 0 && <div className={`mx-2 mb-3 h-px ${isHrmsTheme ? "bg-[#1C3A75]" : "bg-line"}`} />
            ) : (
              <p className={`sidebar-section-label pb-1.5 text-[11px] font-medium ${isHrmsTheme ? "px-2 text-[#9FB3D9]" : "px-2 text-fg-subtle"}`}>{section.label}</p>
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
                    className={`sidebar-nav-item group flex items-center rounded-lg font-medium transition-colors h-8 gap-2.5 text-[13px] ${
                      collapsed ? "justify-center" : "px-2.5"
                    } ${
                      isHrmsTheme
                        ? "text-[#DCE5F5] hover:bg-white/10 hover:text-white"
                        : "text-fg-muted hover:bg-fg/[0.045] hover:text-fg"
                    }`}
                  >
                    <ItemIcon
                      item={item}
                      size={16}
                      strokeWidth={1.9}
                      className={`transition-colors ${
                        isHrmsTheme
                          ? "text-[#C7D4EE] group-hover:text-white"
                          : "text-fg-subtle group-hover:text-fg-muted"
                      }`}
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
                    end={hasNestedNav(item.to)}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      `sidebar-nav-item group flex items-center rounded-lg font-medium transition-colors h-8 gap-2.5 text-[13px] ${
                        collapsed ? "justify-center" : "px-2.5"
                      } ${
                        isHrmsTheme
                          ? isActive
                            ? "bg-[#1D68E8] text-white font-semibold shadow-[0_4px_12px_-2px_rgba(29,104,232,0.55)]"
                            : "text-[#DCE5F5] hover:bg-white/10 hover:text-white"
                          : isActive
                            ? "bg-surface text-fg shadow-xs ring-1 ring-line"
                            : "text-fg-muted hover:bg-fg/[0.045] hover:text-fg"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <ItemIcon
                          item={item}
                          size={16}
                          strokeWidth={isActive ? 2.2 : 1.9}
                          className={
                            isHrmsTheme
                              ? isActive ? "text-white" : "text-[#C7D4EE] transition-colors group-hover:text-white"
                              : isActive ? "text-accent" : "text-fg-subtle transition-colors group-hover:text-fg-muted"
                          }
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
  const { colorTheme } = useTheme();
  const changeColorTheme = useChangeColorTheme();
  const { open, setOpen, ref } = usePopover();
  if (!user) return null;
  // Light text only where the menu sits on the navy sidebar.
  const isHrmsTheme = colorTheme === "midnight-blue";

  return (
    <div ref={ref} className="relative">
      <button
        aria-label="Account menu"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`flex w-full items-center gap-2.5 rounded-lg text-left transition-colors ${
          isHrmsTheme ? "hover:bg-white/10" : "hover:bg-fg/[0.045]"
        } ${collapsed ? "justify-center p-1" : "p-1.5"} ${open ? (isHrmsTheme ? "bg-white/10" : "bg-fg/[0.045]") : ""}`}
      >
        <Avatar name={user.name} size="md" />
        {!collapsed && (
          <>
            {/* Midnight's sidebar uses a dedicated foreground on its navy surface. */}
            <span className="min-w-0 flex-1 leading-tight">
              <span className={`block truncate text-[13px] font-medium ${isHrmsTheme ? "text-white" : "text-fg"}`}>{user.name}</span>
              <span className={`block truncate text-[11px] ${isHrmsTheme ? "text-[#B0BBD0]" : "text-fg-subtle"}`}>{ROLE_LABEL[user.role]}</span>
            </span>
            <ChevronsUpDown size={14} className={isHrmsTheme ? "text-[#B0BBD0]" : "text-fg-subtle"} />
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
            href={API_DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className="menu-item"
          >
            <BookOpen size={15} /> API Documentation
          </a>
          <div className="my-1 h-px bg-line" />
          <AppearanceControls onColorThemeChange={changeColorTheme} />
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
  const { resolved, setTheme, colorTheme } = useTheme();
  const changeColorTheme = useChangeColorTheme();
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
          onClick={() => changeColorTheme(COLOR_THEMES[(COLOR_THEMES.findIndex((palette) => palette.id === colorTheme) + 1) % COLOR_THEMES.length].id)}
          className="btn-icon"
          aria-label="Switch Theme Palette"
          title={`Colour theme: ${colorThemeName(colorTheme)} (click to switch)`}
        >
          <Palette size={16} />
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
        to: "/approvals?type=CORRECTION", when: c.submitted_at,
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
