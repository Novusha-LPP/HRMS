import { useQuery } from "@tanstack/react-query";
import { integrationsApi } from "../../api/integrations";
import type { FieldControl } from "../../api/integrations";

/** Which of an employee's fields a connected app (e.g. the ERP) owns. Empty when none. */
export function useFieldControl(employmentId: string | null | undefined) {
  return useQuery({
    queryKey: ["field-control", employmentId],
    queryFn: () => integrationsApi.fieldControl(employmentId!),
    enabled: !!employmentId,
    staleTime: 60_000,
  });
}

export function lockedFields(control: FieldControl[] | undefined) {
  return (control ?? []).filter((f) => f.locked);
}
