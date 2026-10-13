import { useEffect, useMemo, useRef } from "react";

interface ModalEntry {
  panel: HTMLElement;
  previousFocus: HTMLElement | null;
}

// Every modal surface shares one stack, including the mobile navigation drawer.
const openModals: ModalEntry[] = [];
let previousBodyOverflow = "";

const focusableSelector = [
  "a[href]", "area[href]", "button", "input:not([type=hidden])", "select", "textarea",
  "iframe", "audio[controls]", "video[controls]", "[contenteditable]:not([contenteditable=false])", "[tabindex]",
].join(", ");

function isAvailable(element: HTMLElement) {
  return element.isConnected && !element.matches(":disabled") &&
    !element.closest("[hidden], [inert], [aria-hidden='true']") &&
    element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";
}

function focusableControls(panel: HTMLElement) {
  return [...panel.querySelectorAll<HTMLElement>(focusableSelector)]
    .filter(element => element.tabIndex >= 0 && isAvailable(element))
    .sort((a, b) => (a.tabIndex > 0 ? a.tabIndex : Infinity) - (b.tabIndex > 0 ? b.tabIndex : Infinity));
}

function initialTarget(panel: HTMLElement) {
  const preferred = [...panel.querySelectorAll<HTMLElement>("[autofocus], [data-autofocus]")].find(isAvailable);
  const controls = focusableControls(panel);
  return preferred ?? controls.find(element => element.matches("input, select, textarea")) ?? controls[0] ?? panel;
}

/** Keep keyboard focus and Escape in the top modal, then restore the opening control. */
export function useModal<T extends HTMLElement = HTMLDivElement>(open: boolean, onClose: () => void) {
  const panelRef = useRef<T>(null);
  const onCloseRef = useRef(onClose);
  // Capture the opener before a child's React autoFocus runs during the commit.
  const previousFocus = useMemo(() => open && document.activeElement instanceof HTMLElement ? document.activeElement : null, [open]);
  useEffect(() => { onCloseRef.current = onClose; });

  useEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    const entry: ModalEntry = {
      panel,
      previousFocus,
    };
    if (openModals.length === 0) {
      previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    openModals.push(entry);
    let lastFocus = initialTarget(panel);
    const isTop = () => openModals.at(-1) === entry;
    const focusInside = () => {
      const target = panel.contains(lastFocus) && isAvailable(lastFocus) ? lastFocus : initialTarget(panel);
      target.focus();
    };
    const onFocus = (event: FocusEvent) => {
      if (!isTop() || !(event.target instanceof HTMLElement)) return;
      if (panel.contains(event.target)) lastFocus = event.target;
      else focusInside();
    };
    const onKey = (event: KeyboardEvent) => {
      if (!isTop() || event.defaultPrevented) return;
      if (event.key === "Escape") {
        // Inline popovers have their own Escape listener; dismiss that menu first.
        if ([...panel.querySelectorAll<HTMLElement>(".popover")].some(isAvailable)) return;
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = focusableControls(panel);
      const first = controls[0], last = controls.at(-1);
      const active = document.activeElement;
      if (!first || !last) {
        event.preventDefault();
        panel.focus({ preventScroll: true });
      } else if (!controls.includes(active as HTMLElement) || (event.shiftKey ? active === first : active === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocus);
    focusInside();

    return () => {
      const wasTop = isTop();
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocus);
      const index = openModals.indexOf(entry);
      // If a parent closes before its child, retain the original opening control.
      for (const remaining of openModals.slice(index + 1)) {
        if (remaining.previousFocus && panel.contains(remaining.previousFocus)) remaining.previousFocus = entry.previousFocus;
      }
      openModals.splice(index, 1);
      const remaining = openModals.at(-1);
      if (!remaining) document.body.style.overflow = previousBodyOverflow;
      if (!wasTop) return;
      const previous = entry.previousFocus;
      if (previous && isAvailable(previous) && (!remaining || remaining.panel.contains(previous))) {
        previous.focus({ preventScroll: true });
      } else if (remaining) {
        initialTarget(remaining.panel).focus({ preventScroll: true });
      }
    };
  }, [open, previousFocus]);

  return panelRef;
}
