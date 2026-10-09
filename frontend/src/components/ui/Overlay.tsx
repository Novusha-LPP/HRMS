import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X, TriangleAlert } from "lucide-react";

/** Esc-to-close, initial focus, and focus restore for modal surfaces. */
// Open modals, innermost last: Escape closes only the top one (a dialog opened from a sheet).
const openModals: object[] = [];

function useModal(open: boolean, onClose: () => void) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; });

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const token = {};
    openModals.push(token);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && openModals[openModals.length - 1] === token) onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    const first = panelRef.current?.querySelector<HTMLElement>(
      "[autofocus], input:not([type=hidden]), select, textarea, [data-autofocus]",
    );
    (first ?? panelRef.current)?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      openModals.splice(openModals.indexOf(token), 1);
      previous?.focus?.();
    };
  }, [open]);

  return panelRef;
}

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
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`absolute inset-y-0 right-0 flex w-full flex-col border-l border-line bg-surface shadow-pop outline-none animate-slide-in-right sm:inset-y-2 sm:right-2 sm:rounded-2xl sm:border ${className}`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-fg-subtle">{description}</p>}
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

export function Dialog({ open, onClose, children, className = "max-w-md", labelledBy, describedBy }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
  describedBy?: string;
}) {
  const panelRef = useModal(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
      <div className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={`relative w-full overflow-hidden rounded-2xl border border-line bg-surface shadow-pop outline-none animate-scale-in ${className}`}
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
  return (
    <Dialog open={open} onClose={onClose}>
      <div className="flex gap-4 p-6">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-danger/10 text-danger">
          <TriangleAlert size={18} />
        </div>
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-fg">{title}</h2>
          {description && <p className="mt-1 text-[13px] text-fg-muted">{description}</p>}
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
