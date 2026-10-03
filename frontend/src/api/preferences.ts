import { api } from "./client";
import type { ColorTheme } from "../context/ThemeContext";

/** "widgets": the customisable widget grid. "overview": the fixed HRMS overview layout. */
export type DashboardStyle = "widgets" | "overview";

export interface Preferences {
  color_theme: ColorTheme;
  dashboard_style: DashboardStyle;
}

export const preferencesApi = {
  get: () => api.get<Preferences>("/v1/me/preferences"),
  update: (changes: Partial<Preferences>) => api.patch<Preferences>("/v1/me/preferences", changes),
};
