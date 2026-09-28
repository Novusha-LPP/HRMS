import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { peopleApi } from "../api/people";

/** Maps employment IDs to display names. Shares cache with the Employees page. */
export function usePeopleDirectory(enabled: boolean) {
  const emps = useQuery({ queryKey: ["employees"], queryFn: () => peopleApi.listAllEmployees(), enabled });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => peopleApi.listAllPersons(), enabled: enabled && !!emps.data?.length });

  return useMemo(() => {
    const personName = new Map(
      (persons.data ?? []).map((p) => [p.id, `${p.preferred_name || p.legal_first_name} ${p.legal_last_name}`]),
    );
    const map = new Map<string, string>();
    for (const e of emps.data ?? []) map.set(e.id, personName.get(e.person_id) ?? e.employee_number);
    return map;
  }, [emps.data, persons.data]);
}
