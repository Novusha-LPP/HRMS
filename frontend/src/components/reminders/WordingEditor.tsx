import { useEffect, useRef, useState } from "react";
import { Bold, Italic, Link2, List, Repeat, Underline } from "lucide-react";

/**
 * A small rich-text editor for a reminder's wording. It edits HTML directly in the page
 * (contentEditable) and offers formatting, a link, a bullet list, the variable picker and the
 * repeat block. The server cuts whatever it produces down to a safe set of tags on save, so this
 * is for convenience, not a security boundary.
 */
export function WordingEditor({ value, onChange, variables, allowRepeat, label }: {
  value: string;
  onChange: (html: string) => void;
  /** name → what it fills in */
  variables: Record<string, string>;
  /** Show the “repeat for each person” button (the team mail, which can list several people). */
  allowRepeat: boolean;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // The link field is inline, so the editor selection is kept while the person types the address.
  const [link, setLink] = useState<string | null>(null);
  const selection = useRef<Range | null>(null);

  // Load the value once, and again only when it was replaced from outside (a starter template,
  // switching rule); re-writing it on every keystroke would move the caret.
  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) ref.current.innerHTML = value;
  }, [value]);

  const emit = () => onChange(ref.current?.innerHTML ?? "");
  const run = (command: string, arg?: string) => {
    ref.current?.focus();
    document.execCommand(command, false, arg);
    emit();
  };
  const insert = (text: string) => run("insertText", text);
  const openLink = () => {
    const sel = window.getSelection();
    selection.current = sel && sel.rangeCount > 0 ? sel.getRangeAt(0).cloneRange() : null;
    setLink("https://");
  };
  const applyLink = () => {
    const url = (link ?? "").trim();
    setLink(null);
    if (!/^(https?:\/\/|mailto:)\S+$/i.test(url) || url === "https://") return;
    const sel = window.getSelection();
    if (selection.current && sel) { sel.removeAllRanges(); sel.addRange(selection.current); }
    run("createLink", url);
  };
  // Keep the selection in the editor when a toolbar button is pressed.
  const keep = (e: React.MouseEvent) => e.preventDefault();

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-1" role="toolbar" aria-label={`${label} formatting`}>
        <button type="button" className="btn-icon" aria-label="Bold" onMouseDown={keep} onClick={() => run("bold")}><Bold size={15} /></button>
        <button type="button" className="btn-icon" aria-label="Italic" onMouseDown={keep} onClick={() => run("italic")}><Italic size={15} /></button>
        <button type="button" className="btn-icon" aria-label="Underline" onMouseDown={keep} onClick={() => run("underline")}><Underline size={15} /></button>
        <button type="button" className="btn-icon" aria-label="Bullet list" onMouseDown={keep} onClick={() => run("insertUnorderedList")}><List size={15} /></button>
        <button type="button" className="btn-icon" aria-label="Link" onMouseDown={keep} onClick={openLink}><Link2 size={15} /></button>
        {allowRepeat && (
          <button type="button" className="btn-ghost btn-sm" onMouseDown={keep}
            title="Everything between the markers is repeated once for each person in the mail"
            onClick={() => insert("{#each}  {/each}")}>
            <Repeat size={14} /> Repeat for each person
          </button>
        )}
        <select className="input ml-auto h-8 w-auto py-0 text-xs" aria-label="Insert a field" value=""
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => { if (e.target.value) { insert(`{${e.target.value}}`); } }}>
          <option value="">Insert field…</option>
          {Object.entries(variables).map(([name, help]) => (
            <option key={name} value={name}>{name.replace(/_/g, " ")} — {help}</option>
          ))}
        </select>
      </div>
      {link !== null && (
        <div className="mb-2 flex items-center gap-2">
          <input className="input h-8 flex-1 text-xs" autoFocus aria-label="Link address" value={link} placeholder="https://example.com"
            onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyLink(); } if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setLink(null); } }} />
          <button type="button" className="btn-primary btn-sm" onClick={applyLink}>Add link</button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setLink(null)}>Cancel</button>
        </div>
      )}
      <div
        ref={ref}
        role="textbox"
        aria-multiline="true"
        aria-label={label}
        contentEditable
        suppressContentEditableWarning
        onInput={emit}
        onBlur={emit}
        className="input h-auto min-h-[9rem] overflow-y-auto py-2 leading-relaxed [&_a]:text-accent [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5"
      />
    </div>
  );
}
