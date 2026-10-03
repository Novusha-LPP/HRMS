import {
  LayoutGrid, NavigationUsers as Users, Clock, NavigationLeave as Umbrella, FilePenLine, ClipboardCheck, BarChart3, ShieldCheck, Building2, UserCheck, BookOpen,
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
      { to: "/attendance", label: "Attendance", icon: Clock },
      { to: "/leave", label: "Leave", icon: Umbrella },
      { to: "/corrections", label: "Corrections", icon: FilePenLine },
      { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
    ],
  },
  {
    label: "Talent",
    items: [
      { to: "/onboarding", label: "Onboarding", icon: ClipboardCheck, permission: "onboarding.read" },
    ],
  },
  {
    label: "Settings",
    items: [
      { to: "/organization", label: "Organization", icon: Building2, permission: "org.write" },
      { to: "/policy", label: "Policies", icon: ShieldCheck, roles: HR_ROLES },
      { to: "/approval-flows", label: "Approval flows", icon: ClipboardCheck, permission: "approvals.manage" },
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
  return true;
}

export function navFor(user: NavUser): NavSection[] {
  return NAV_SECTIONS
    .map((s) => ({ ...s, items: s.items.filter((i) => canSee(i, user)) }))
    .filter((s) => s.items.length > 0);
}

export function findNav(pathname: string) {
  for (const s of NAV_SECTIONS) {
    const item = s.items.find((i) => !i.external && pathname.startsWith(i.to));
    if (item) return { section: s.label, item };
  }
  return null;
}
