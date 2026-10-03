import { useId } from "react";
import { useTheme } from "../../context/ThemeContext";
import type { PlatformRole } from "../../api/platform";
import { BookOpen, ChevronsUpDown, LogOut } from "../icons/ThemeIcons";
import { Avatar } from "../ui/Avatar";
import { usePopover } from "../ui/Popover";
import { AppearanceControls } from "./AppearanceControls";
import { API_DOCS_URL } from "../../lib/runtimeConfig";

export function PlatformAccountMenu({ name, email, role, onSignOut }: {
  name: string;
  email: string;
  role: PlatformRole;
  onSignOut: () => void;
}) {
  const { colorTheme } = useTheme();
  const midnight = colorTheme === "midnight-blue";
  const { open, setOpen, ref } = usePopover();
  const id = useId();
  const roleLabel = role === "ADMIN" ? "Platform administrator" : "Platform viewer";
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-expanded={open} aria-haspopup="dialog" aria-controls={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
        className={`flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors ${
          midnight ? `hover:bg-white/10 ${open ? "bg-white/10" : ""}` : `hover:bg-fg/[0.045] ${open ? "bg-fg/[0.045]" : ""}`
        }`}>
        <Avatar name={name} size="md" />
        <span className="min-w-0 flex-1 leading-tight">
          <span title={name} className={`block truncate text-[13px] font-medium ${midnight ? "text-white" : "text-fg"}`}>{name}</span>
          <span className={`block truncate text-[11px] ${midnight ? "text-[#B0BBD0]" : "text-fg-subtle"}`}>{roleLabel}</span>
        </span>
        <ChevronsUpDown size={14} className={midnight ? "text-[#B0BBD0]" : "text-fg-subtle"} />
      </button>
      {open && (
        <div id={id} role="dialog" aria-label="Platform account menu" className="popover absolute bottom-full left-0 mb-2 w-64">
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <Avatar name={name} size="lg" />
            <div className="min-w-0 leading-tight">
              <p title={name} className="truncate text-[13px] font-medium text-fg">{name}</p>
              <p title={email} className="truncate text-xs text-fg-subtle">{email}</p>
              <p className="mt-1 text-[11px] text-fg-subtle">{roleLabel}</p>
            </div>
          </div>
          <div className="my-1 h-px bg-line" />
          <a href={API_DOCS_URL} target="_blank" rel="noopener noreferrer" onClick={() => setOpen(false)} className="menu-item">
            <BookOpen size={15} /> API Documentation
          </a>
          <div className="my-1 h-px bg-line" />
          <AppearanceControls />
          <div className="my-1 h-px bg-line" />
          <button type="button" onClick={onSignOut} className="menu-item hover:text-danger"><LogOut size={15} /> Sign out</button>
          <p className="px-2.5 pb-1 pt-1.5 text-[11px] tabular-nums text-fg-subtle">Version {__APP_VERSION__} · {__GIT_SHA__}</p>
        </div>
      )}
    </div>
  );
}
