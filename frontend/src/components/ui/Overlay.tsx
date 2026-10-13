import { useId } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X, TriangleAlert } from "lucide-react";
import { useModal } from "../../lib/useModal";

export function Sheet({ open, onClose, title, description, children, footer, className = "max-w-md" }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  const panelRef = useModal(open, onClose);
  const titleId = useId();
  const descriptionId = useId();
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`sheet-panel absolute inset-y-0 right-0 flex w-full flex-col border-l border-line bg-surface shadow-pop outline-none animate-slide-in-right sm:inset-y-2 sm:right-2 sm:rounded-2xl sm:border ${className}`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
            {description && <p id={descriptionId} className="mt-0.5 text-[13px] text-fg-subtle">{description}</p>}
          </div>
          <button onClick={onClose} className="btn-icon -mr-2" aria-label="Close"><X size={16} /></button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <footer className="flex items-center justify-end gap-2 border-t border-line bg-panel px-6 py-3.5 sm:rounded-b-2xl">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function Dialog({ open, onClose, children, className = "max-w-md", labelledBy, describedBy, ariaLabel }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
  describedBy?: string;
  ariaLabel?: string;
}) {
  const panelRef = useModal(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12dvh]">
      <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        aria-label={ariaLabel}
        tabIndex={-1}
        className={`dialog-panel relative max-h-[calc(88dvh-2rem)] w-full overflow-y-auto rounded-2xl border border-line bg-surface shadow-pop outline-none animate-scale-in ${className}`}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({ open, onClose, onConfirm, title, description, confirmLabel = "Delete", loading }: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  loading?: boolean;
}) {
  const titleId = useId(), descriptionId = useId();
  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId} describedBy={description ? descriptionId : undefined}>
      <div className="flex gap-4 p-6">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-danger/10 text-danger">
          <TriangleAlert size={18} />
        </div>
        <div className="min-w-0">
          <h2 id={titleId} className="text-[15px] font-semibold text-fg">{title}</h2>
          {description && <p id={descriptionId} className="mt-1 text-[13px] text-fg-muted">{description}</p>}
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
        <button className="btn-secondary" onClick={onClose} data-autofocus>Cancel</button>
        <button className="btn-danger" onClick={onConfirm} disabled={loading}>
          {loading ? "Working…" : confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
