import type { ReactNode } from "react";
import { Inbox, TriangleAlert, Info, UserX } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function EmptyState({ icon: Icon = Inbox, title, description, action, className = "" }: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center justify-center px-6 py-14 text-center ${className}`}>
      <div className="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface text-fg-subtle shadow-xs">
        <Icon size={20} strokeWidth={1.75} />
      </div>
      <p className="mt-4 text-sm font-medium text-fg">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[13px] text-fg-subtle">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "warning", title, children, action }: {
  tone?: "warning" | "info";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const Icon = tone === "warning" ? TriangleAlert : Info;
  const color = tone === "warning" ? "border-warning/25 bg-warning/[0.06] text-warning" : "border-info/20 bg-info/[0.06] text-info";
  return (
    <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${color}`} role="status">
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 text-[13px]">
        <p className="font-medium">{title}</p>
        {children && <div className="mt-0.5 text-fg-muted">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

/**
 * Shown on self-service pages when the signed-in account has no employee
 * record — e.g. a company administrator login created when the company was
 * set up. Those accounts can configure the platform but have no personal
 * attendance, leave or profile of their own.
 */
export function NoEmployeeRecord({ feature }: { feature: string }) {
  return (
    <div className="card">
      <EmptyState
        icon={UserX}
        title="This account isn’t linked to an employee record"
        description={`You’re signed in with an administrator account that isn’t tied to an employee, so there’s no ${feature} to show. Ask HR to link an employee record if you also work here.`}
      />
    </div>
  );
}
