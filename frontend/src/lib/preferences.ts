/**
 * Each person's two independent choices, saved to their account (/v1/me/preferences) so
 * they follow them to any device:
 *   - the colour theme, for the whole app (ThemeContext applies it);
 *   - the dashboard style, for the HR/admin dashboard.
 * Changing one never touches the other.
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { preferencesApi } from "../api/preferences";
import type { Preferences } from "../api/preferences";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useToast, errorMessage } from "../components/ui/Toast";
import type { ColorTheme } from "../context/ThemeContext";

const KEY = ["preferences"];

export function usePreferences() {
  const { user } = useAuth();
  return useQuery({ queryKey: [...KEY, user?.id], queryFn: preferencesApi.get, enabled: !!user, staleTime: Infinity });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const key = [...KEY, user?.id];
  return useMutation({
    mutationFn: (changes: Partial<Preferences>) => preferencesApi.update(changes),
    // Apply straight away; the server's answer replaces it, and a failure rolls it back.
    onMutate: async (changes) => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<Preferences>(key);
      if (previous) qc.setQueryData(key, { ...previous, ...changes });
      return { previous };
    },
    onError: (e, _changes, context) => {
      if (context?.previous) qc.setQueryData(key, context.previous);
      toast.error("Couldn’t save your preference", errorMessage(e));
    },
    onSuccess: (saved) => qc.setQueryData(key, saved),
  });
}

/** Change the colour theme now, and remember it on the account. */
export function useChangeColorTheme() {
  const { setColorTheme } = useTheme();
  const update = useUpdatePreferences();
  return (theme: ColorTheme) => {
    setColorTheme(theme);
    update.mutate({ color_theme: theme });
  };
}

/** Applies the signed-in person's saved colour theme. Rendered once, inside the app shell. */
export function PreferencesSync() {
  const { data } = usePreferences();
  const { colorTheme, setColorTheme } = useTheme();
  useEffect(() => {
    if (data && data.color_theme !== colorTheme) setColorTheme(data.color_theme);
    // Only when the saved value arrives or changes — not when the user switches locally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.color_theme]);
  return null;
}
