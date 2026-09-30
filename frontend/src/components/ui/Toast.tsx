import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CircleCheck, CircleAlert, Info, X } from "lucide-react";

type Tone = "success" | "error" | "info";
interface ToastItem { id: number; tone: Tone; title: string; description?: string }

interface ToastApi {
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICON = {
  success: <CircleCheck size={18} className="text-success" />,
  error: <CircleAlert size={18} className="text-danger" />,
  info: <Info size={18} className="text-info" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);

  const push = useCallback((tone: Tone, title: string, description?: string) => {
    const id = ++nextId.current;
    setItems((xs) => [...xs.slice(-3), { id, tone, title, description }]);
    setTimeout(() => dismiss(id), tone === "error" ? 6000 : 4000);
  }, [dismiss]);

  const api = useMemo<ToastApi>(() => ({
    success: (t, d) => push("success", t, d),
    error: (t, d) => push("error", t, d),
    info: (t, d) => push("info", t, d),
  }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className="pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-pop animate-toast-in"
          >
            <span className="mt-px shrink-0">{ICON[t.tone]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-fg">{t.title}</p>
              {t.description && <p className="mt-0.5 text-xs text-fg-subtle">{t.description}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} className="-m-1 rounded-md p-1 text-fg-subtle hover:bg-muted hover:text-fg" aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

export function errorMessage(e: unknown) {
  if (e instanceof Error && e.message) {
    const reqId = (e as { requestId?: string }).requestId;
    if (reqId) {
      return `${e.message} (Ref: ${reqId.slice(0, 16)})`;
    }
    return e.message;
  }
  return "Something went wrong. Please try again.";
}
