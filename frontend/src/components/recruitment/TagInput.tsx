import { useState } from "react";
import type { KeyboardEvent } from "react";
import { X } from "lucide-react";

/** Free-text tags (skills): Enter or comma adds, Backspace on empty removes the last. */
export function TagInput({ id, value, onChange, placeholder, max = 50 }: {
  id?: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  max?: number;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const parts = raw.split(",").map((p) => p.trim().replace(/\s+/g, " ")).filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    for (const part of parts) {
      if (next.length >= max) break;
      if (!next.some((t) => t.toLowerCase() === part.toLowerCase())) next.push(part.slice(0, 60));
    }
    onChange(next);
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1.5 shadow-xs transition-[border-color,box-shadow] focus-within:border-brand-500 focus-within:ring-4 focus-within:ring-brand-500/15 hover:border-line-strong">
      {value.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-fg">
          {tag}
          <button
            type="button"
            className="text-fg-subtle hover:text-fg"
            onClick={() => onChange(value.filter((t) => t !== tag))}
            aria-label={`Remove ${tag}`}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        id={id}
        className="min-w-[8rem] flex-1 bg-transparent px-1 text-[13px] text-fg outline-none placeholder:text-fg-subtle"
        value={draft}
        placeholder={value.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => add(draft)}
      />
    </div>
  );
}
