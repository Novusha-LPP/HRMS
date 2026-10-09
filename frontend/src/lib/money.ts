import { useEffect, useState } from "react";

const RUPEES = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const RUPEES_PAISE = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹6,00,000 — whole rupees unless `paise` (shows .00 too, for payslip lines). */
export function inr(value: string | number | null | undefined, paise = false): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return (paise ? RUPEES_PAISE : RUPEES).format(n);
}

/** "6 L" / "1.25 Cr" for compact CTC labels. */
export function lakhs(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (n >= 1e7) return `${+(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `${+(n / 1e5).toFixed(2)} L`;
  return inr(n);
}

/** A typed money amount: digits with at most two decimals, commas allowed. */
export function parseAmount(text: string): string | null {
  const clean = text.replace(/[,\s₹]/g, "");
  return /^\d+(\.\d{1,2})?$/.test(clean) && Number(clean) > 0 ? clean : null;
}

export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
