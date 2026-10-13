import { Lock } from "lucide-react";
import { lockedFields, useFieldControl } from "./fieldControl";
import type { FieldControl } from "../../api/integrations";

/** "Managed by ERP · EMP-1042": shown on an employee managed by a connected app. */
export function ManagedByBadge({ employmentId }: { employmentId: string }) {
  const control = useFieldControl(employmentId);
  const locked = lockedFields(control.data);
  if (!locked.length) return null;
  const owners = [...new Set(locked.map((f) => f.owner))];
  const ids = control.data?.[0]?.external_ids ?? {};
  return (
    <>
      {owners.map((owner) => (
        <span key={owner} className="badge badge-info"
          title={`Managed in ${locked.find((f) => f.owner === owner)?.owner_name ?? owner}: ${locked
            .filter((f) => f.owner === owner).map((f) => f.label.toLowerCase()).join(", ")}`}>
          <Lock size={11} /> Managed by {owner}{ids[owner] ? ` · ${ids[owner]}` : ""}
        </span>
      ))}
    </>
  );
}

/** A small "managed in <app>" note under a field the employee can't edit here. */
export function LockedNote({ field }: { field: FieldControl | undefined }) {
  if (!field?.locked) return null;
  return (
    <p className="mt-1 flex items-center gap-1 text-[11px] text-fg-subtle">
      <Lock size={11} /> Managed in {field.owner_name ?? field.owner}. Ask HR to change it there.
    </p>
  );
}
