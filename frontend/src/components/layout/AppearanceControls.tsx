import { COLOR_THEMES, useTheme } from "../../context/ThemeContext";
import type { ColorTheme } from "../../context/ThemeContext";
import { Monitor, Moon, Sun } from "../icons/ThemeIcons";
import { Segmented } from "../ui/Tabs";

/** Shared account-menu controls; callers choose browser or account persistence. */
export function AppearanceControls({ className = "", onColorThemeChange }: {
  className?: string;
  onColorThemeChange?: (theme: ColorTheme) => void;
}) {
  const { theme, setTheme, colorTheme, setColorTheme } = useTheme();
  return (
    <div className={className} role="group" aria-label="Appearance settings">
      <div className="flex items-center justify-between gap-2 px-2.5 py-2">
        <span className="shrink-0 text-[13px] text-fg-muted">Theme</span>
        <Segmented value={theme} onChange={setTheme} items={[
          { value: "light", label: "", icon: Sun },
          { value: "dark", label: "", icon: Moon },
          { value: "system", label: "", icon: Monitor },
        ]} />
      </div>
      <label className="flex items-center justify-between gap-2 px-2.5 py-2">
        <span className="shrink-0 whitespace-nowrap text-[13px] text-fg-muted">Colour theme</span>
        <select value={colorTheme} onChange={(event) => (onColorThemeChange ?? setColorTheme)(event.target.value as ColorTheme)}
          className="h-7 w-[132px] shrink-0 cursor-pointer rounded-md border border-line bg-surface px-2 text-xs font-medium text-fg">
          {COLOR_THEMES.map((palette) => <option key={palette.id} value={palette.id} title={palette.description}>{palette.name}</option>)}
        </select>
      </label>
    </div>
  );
}
