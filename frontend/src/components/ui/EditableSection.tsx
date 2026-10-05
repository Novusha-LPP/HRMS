import type { FormEvent, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Pencil } from "lucide-react";

/**
 * A card that reads as a definition list until the user chooses Edit, then
 * turns into a form with its own Save / Cancel. Used by the profile and KYC
 * screens so details are viewed first and only edited on purpose.
 */
export function EditableSection({
  icon: Icon,
  title,
  description,
  editing,
  canEdit,
  editDisabled,
  onEdit,
  onCancel,
  onSubmit,
  saving,
  saveDisabled,
  editNotice,
  headerExtra,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  editing: boolean;
  canEdit: boolean;
  /** Another section is mid-edit; keep one form open at a time. */
  editDisabled?: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  saving?: boolean;
  saveDisabled?: boolean;
  /** Shown beside the Save button while editing. */
  editNotice?: ReactNode;
  headerExtra?: ReactNode;
  children: ReactNode;
}) {
  const header = (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-500/10 text-accent">
            <Icon size={15} />
          </div>
        )}
        <div className="min-w-0">
          <h3 className="card-title">{title}</h3>
          {description && <p className="card-desc">{description}</p>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {headerExtra}
        {canEdit && !editing && (
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={onEdit}
            disabled={editDisabled}
            title={editDisabled ? "Finish the section you're editing first" : undefined}
          >
            <Pencil size={12} /> Edit
          </button>
        )}
      </div>
    </div>
  );

  if (!editing) {
    return (
      <section className="card">
        {header}
        <div className="px-5 py-4">{children}</div>
      </section>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <form
      onSubmit={submit}
      onKeyDown={(e) => { if (e.key === "Escape" && !saving) onCancel(); }}
      className="card ring-4 ring-brand-500/10 border-brand-500/40"
    >
      {header}
      <div className="px-5 py-4">{children}</div>
      <div className="flex flex-col gap-3 border-t border-line bg-panel px-5 py-3 sm:flex-row sm:items-center sm:justify-between rounded-b-xl">
        <div className="min-w-0 text-xs text-fg-subtle">{editNotice}</div>
        <div className="flex shrink-0 items-center justify-end gap-2">
          <button type="button" className="btn-ghost btn-sm" onClick={onCancel} disabled={saving}>Cancel</button>
          <button type="submit" className="btn-primary btn-sm" disabled={saving || saveDisabled}>
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </form>
  );
}

/** Responsive grid that sizes by the container, so it also works inside sheets. */
export function DetailGrid({ children, min = 200 }: { children: ReactNode; min?: number }) {
  return (
    <dl className="grid gap-x-6 gap-y-4" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(${min}px, 100%), 1fr))` }}>
      {children}
    </dl>
  );
}

export function DetailItem({ label, children, required, wide }: {
  label: ReactNode;
  children: ReactNode;
  required?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={`min-w-0 ${wide ? "col-span-full" : ""}`}>
      <dt className="text-xs text-fg-subtle">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </dt>
      <dd className="mt-1 break-words text-[13px] font-medium text-fg">{children}</dd>
    </div>
  );
}

export function EmptyValue({ required }: { required?: boolean }) {
  return required
    ? <span className="font-normal text-warning">Not provided</span>
    : <span className="font-normal text-fg-subtle">—</span>;
}

export function FieldGrid({ children, min = 200 }: { children: ReactNode; min?: number }) {
  return (
    <div className="grid gap-x-4 gap-y-4" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(${min}px, 100%), 1fr))` }}>
      {children}
    </div>
  );
}
