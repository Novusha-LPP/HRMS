import type { ReactNode } from "react";

export function PageHeader({ title, description, actions }: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-fg">{title}</h1>
        {description && <p className="page-header-description mt-1 text-[13px] text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="page-header-actions flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
