import { useQuery } from "@tanstack/react-query";
import { orgApi } from "../../api/org";
import { peopleApi } from "../../api/people";
import { Skeleton } from "../ui/Feedback";

export interface PlacementValues {
  orgUnitId: string;
  jobId: string;
  locationId: string;
  managerEmploymentId: string;
}

/** Shared department/designation/location/manager picker used by hiring, transferring and rehiring. */
export function PlacementFields({ legalEntityId, values, onChange, excludeEmploymentId }: {
  legalEntityId: string;
  values: PlacementValues;
  onChange: (v: Partial<PlacementValues>) => void;
  excludeEmploymentId?: string;
}) {
  const orgUnits = useQuery({ queryKey: ["org-units"], queryFn: () => orgApi.listOrgUnits() });
  const locations = useQuery({ queryKey: ["locations"], queryFn: () => orgApi.listLocations() });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs() });
  const employees = useQuery({ queryKey: ["employees"], queryFn: () => peopleApi.listAllEmployees() });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => peopleApi.listAllPersons(), enabled: !!employees.data?.length });
  const personName = new Map((persons.data ?? []).map((p) => [p.id, `${p.preferred_name || p.legal_first_name} ${p.legal_last_name}`]));

  const departments = (orgUnits.data ?? []).filter((o) => o.type === "DEPARTMENT" && o.legal_entity_id === legalEntityId);
  const selectedUnit = orgUnits.data?.find((o) => o.id === values.orgUnitId);
  const departmentId = selectedUnit?.type === "TEAM" ? selectedUnit.parent_id ?? "" : values.orgUnitId;
  const teams = (orgUnits.data ?? []).filter((o) => o.type === "TEAM" && o.parent_id === departmentId && o.legal_entity_id === legalEntityId);
  const entityLocations = (locations.data ?? []).filter((l) => !l.legal_entity_id || l.legal_entity_id === legalEntityId);
  const managers = (employees.data ?? []).filter((e) => e.legal_entity_id === legalEntityId && e.id !== excludeEmploymentId);

  const loading = orgUnits.isPending || locations.isPending || jobs.isPending;
  if (loading) return <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>;

  return (
    <>
      <div>
        <label className="label" htmlFor="pl-dept">Department</label>
        <select id="pl-dept" className="input" value={departmentId} onChange={(e) => onChange({ orgUnitId: e.target.value })}>
          <option value="">{departments.length ? "Choose department…" : "No departments yet for this company"}</option>
          {departments.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </div>
      {departmentId && <div>
        <label className="label" htmlFor="pl-team">Team (optional)</label>
        <select id="pl-team" className="input" value={selectedUnit?.type === "TEAM" ? values.orgUnitId : departmentId}
          onChange={(e) => onChange({ orgUnitId: e.target.value })}>
          <option value={departmentId}>No team</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="pl-job">Designation</label>
          <select id="pl-job" className="input" value={values.jobId} onChange={(e) => onChange({ jobId: e.target.value })}>
            <option value="">{jobs.data?.length ? "Choose…" : "No jobs yet"}</option>
            {jobs.data?.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="pl-loc">Location</label>
          <select id="pl-loc" className="input" value={values.locationId} onChange={(e) => onChange({ locationId: e.target.value })}>
            <option value="">{entityLocations.length ? "Choose…" : "No locations yet"}</option>
            {entityLocations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="pl-mgr">Reports to <span className="font-normal text-fg-subtle">(optional)</span></label>
        <select id="pl-mgr" className="input" value={values.managerEmploymentId} onChange={(e) => onChange({ managerEmploymentId: e.target.value })}>
          <option value="">No manager</option>
          {managers.map((m) => <option key={m.id} value={m.id}>{personName.has(m.person_id) ? `${personName.get(m.person_id)} · ${m.employee_number}` : m.employee_number}</option>)}
        </select>
      </div>
    </>
  );
}
