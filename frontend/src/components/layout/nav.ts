import {
  LayoutGrid, NavigationUsers as Users, Clock, NavigationLeave as Umbrella, FilePenLine, ClipboardCheck, BarChart3, ShieldCheck, Building2, UserCheck, BookOpen,
  Briefcase, CalendarCheck, UserCircle as UserRound, IdCard, Wallet, Cable,
} from "../icons/ThemeIcons";
import type { LucideIcon } from "lucide-react";
import type { UserRole } from "../../context/AuthContext";
import { API_DOCS_URL } from "../../lib/runtimeConfig";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles?: UserRole[];
  /** Gate on a fine-grained permission instead of/in addition to a coarse role. */
  permission?: string;
  /** Visible when the user holds any one of these permissions. */
  anyPermission?: string[];
  /** Whether this link points to an external destination (e.g. Swagger API docs). */
  external?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

const HR_ROLES: UserRole[] = ["HR", "SUPER_ADMIN"];

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Overview",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: LayoutGrid },
      { to: "/daily-analysis", label: "Daily Analysis", icon: UserCheck, roles: [...HR_ROLES, "MANAGER"] },
      { to: "/reports", label: "Reports", icon: BarChart3 },
    ],
  },
  {
    label: "Workforce",
    items: [
      { to: "/employees", label: "Employees", icon: Users, roles: [...HR_ROLES, "MANAGER"] },
      { to: "/team", label: "My team", icon: UserRound, roles: ["MANAGER"] },
      { to: "/attendance", label: "Attendance", icon: Clock },
      { to: "/attendance/register", label: "Attendance register", icon: CalendarCheck, roles: [...HR_ROLES, "MANAGER"] },
      // Attendance groups (guards, drivers…): their days are marked by whoever was given the group.
      { to: "/attendance/marking", label: "Mark attendance", icon: ClipboardCheck, anyPermission: ["attendance.view", "attendance.mark", "attendance.groups.manage"] },
      { to: "/leave", label: "Leave", icon: Umbrella },
      { to: "/corrections", label: "Corrections", icon: FilePenLine },
      { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
      { to: "/statutory", label: "PF & ESIC", icon: IdCard },
    ],
  },
  {
    label: "Pay",
    items: [
      // Payroll roles only (granted by the Admin); HR managers don't hold payroll.read.
      { to: "/payroll", label: "Payroll", icon: Wallet, permission: "payroll.read" },
    ],
  },
  {
    label: "Talent",
    items: [
      // Department heads, team leads and PMs get recruitment.request from /auth/me too.
      { to: "/recruitment", label: "Recruitment", icon: Briefcase, anyPermission: ["recruitment.request", "recruitment.read", "recruitment.manage"] },
      { to: "/onboarding", label: "Onboarding", icon: ClipboardCheck, permission: "onboarding.read" },
    ],
  },
  {
    label: "Settings",
    items: [
      { to: "/organization", label: "Organization", icon: Building2, permission: "org.write" },
      { to: "/policy", label: "Policies", icon: ShieldCheck, roles: HR_ROLES },
      { to: "/attendance/groups", label: "Attendance groups", icon: Users, permission: "attendance.groups.manage" },
      { to: "/approval-flows", label: "Approval flows", icon: ClipboardCheck, permission: "approvals.manage" },
      // Connected apps (ERP, CRM): the company administrator only.
      { to: "/integrations", label: "Integrations", icon: Cable, permission: "integrations.manage" },
    ],
  },
  {
    label: "Developers",
    items: [
      { to: API_DOCS_URL, label: "API Docs", icon: BookOpen, external: true },
    ],
  },
];

interface NavUser {
  role: UserRole;
  permissions: string[];
}

function canSee(item: NavItem, user: NavUser): boolean {
  if (item.roles && !item.roles.includes(user.role)) return false;
  if (item.permission && !user.permissions.includes(item.permission) && !user.permissions.includes("*")) return false;
  if (item.anyPermission && !user.permissions.includes("*") && !item.anyPermission.some((p) => user.permissions.includes(p))) return false;
  return true;
}

export function navFor(user: NavUser): NavSection[] {
  return NAV_SECTIONS
    .map((s) => ({ ...s, items: s.items.filter((i) => canSee(i, user)) }))
    .filter((s) => s.items.length > 0);
}

/** The most specific nav entry for a path ("/attendance/register" over "/attendance"). */
export function findNav(pathname: string) {
  let best: { section: string; item: NavItem } | null = null;
  for (const s of NAV_SECTIONS) {
    for (const item of s.items) {
      const matches = !item.external && pathname.startsWith(item.to);
      if (matches && (!best || item.to.length > best.item.to.length)) best = { section: s.label, item };
    }
  }
  return best;
}

/** Whether another nav entry sits under this one, so this one must match its path exactly. */
export function hasNestedNav(to: string) {
  return NAV_SECTIONS.some((s) => s.items.some((i) => i.to !== to && i.to.startsWith(`${to}/`)));
}
