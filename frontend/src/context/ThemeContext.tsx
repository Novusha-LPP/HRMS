import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export type Theme = "light" | "dark" | "system";
export type ColorTheme = "classic-teal" | "midnight-blue" | "ember-sand";

export interface ColorThemeOption {
  id: ColorTheme;
  name: string;
  description: string;
}

export const COLOR_THEMES: ColorThemeOption[] = [
  { id: "classic-teal", name: "Classic Teal", description: "The original teal and neutral palette" },
  { id: "midnight-blue", name: "Midnight Blue", description: "Luminous blue and violet details with an orbital navy backdrop" },
  { id: "ember-sand", name: "Ember Sand", description: "Warm terracotta, sand surfaces and editorial headings" },
];

interface ThemeContextValue {
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (t: Theme) => void;
  colorTheme: ColorTheme;
  setColorTheme: (ct: ColorTheme) => void;
  availableColorThemes: ColorThemeOption[];
}

const STORAGE_KEY = "hrms_theme";
const COLOR_THEME_STORAGE_KEY = "hrms_color_theme";
const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): Theme {
  try {
    const t = localStorage.getItem(STORAGE_KEY);
    return t === "dark" || t === "system" ? t : "light";
  } catch {
    return "light";
  }
}

function readStoredColorTheme(): ColorTheme {
  try {
    const ct = localStorage.getItem(COLOR_THEME_STORAGE_KEY);
    // "hrms-dashboard" is what Midnight Blue was stored as before it had a proper name.
    if (ct === "hrms-dashboard") return "midnight-blue";
    return COLOR_THEMES.find((palette) => palette.id === ct)?.id ?? "classic-teal";
  } catch {
    return "classic-teal";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStored);
  const [colorTheme, setColorThemeState] = useState<ColorTheme>(readStoredColorTheme);
  const [systemDark, setSystemDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);

  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved]);

  useEffect(() => {
    document.documentElement.setAttribute("data-color-theme", colorTheme);
  }, [colorTheme]);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem(STORAGE_KEY, t); } catch { /* storage unavailable */ }
  };

  const setColorTheme = (ct: ColorTheme) => {
    setColorThemeState(ct);
    try { localStorage.setItem(COLOR_THEME_STORAGE_KEY, ct); } catch { /* storage unavailable */ }
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        resolved,
        setTheme,
        colorTheme,
        setColorTheme,
        availableColorThemes: COLOR_THEMES,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
