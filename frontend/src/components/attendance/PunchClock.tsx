import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut, MapPinOff } from "lucide-react";
import { format } from "date-fns";
import { ApiError } from "../../api/client";
import { timeApi } from "../../api/time";
import type { TodayStatus } from "../../api/time";
import { StatusBadge } from "../ui/StatusBadge";
import { Skeleton } from "../ui/Feedback";
import { ConfirmDialog } from "../ui/Overlay";
import { useToast, errorMessage } from "../ui/Toast";

function fmtMins(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtTime(iso: string | null | undefined) {
  return iso ? format(new Date(iso), "hh:mm a") : "—";
}

function useNow(intervalMs = 10_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function PunchClock({ employmentId }: { employmentId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const now = useNow();
  const [noGps, setNoGps] = useState(false);
  // Set when the server asks to confirm a check-out over 16 h after check-in.
  const [longDay, setLongDay] = useState<string | null>(null);

  const { data, isPending: isLoading, isError } = useQuery<TodayStatus>({
    queryKey: ["today", employmentId],
    queryFn: () => timeApi.today(employmentId),
    refetchInterval: 30_000,
  });

  const mutation = useMutation({
    mutationFn: async ({ type, confirm = false }: { type: "IN" | "OUT"; confirm?: boolean }) => {
      let lat: number | undefined;
      let lng: number | undefined;
      try {
        const pos = await new Promise<GeolocationPosition>((res, rej) =>
          navigator.geolocation.getCurrentPosition(res, rej, { timeout: 5000 }),
        );
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
        setNoGps(false);
      } catch {
        setNoGps(true);
      }
      return timeApi.punch(employmentId, type, lat, lng, confirm);
    },
    onSuccess: (_, { type, confirm }) => {
      setLongDay(null);
      qc.invalidateQueries({ queryKey: ["today", employmentId] });
      // Everything that counts today's punch: the month grid and the dashboards.
      qc.invalidateQueries({ queryKey: ["attendance-days"] });
      qc.invalidateQueries({ queryKey: ["attendance-register", employmentId] });
      qc.invalidateQueries({ queryKey: ["dash-emp", employmentId] });
      qc.invalidateQueries({ queryKey: ["dash-mgr", employmentId] });
      qc.invalidateQueries({ queryKey: ["dash-hr"] });
      toast.success(
        type === "IN" ? "Checked in" : "Checked out",
        confirm ? "Recorded — HR will review this day" : `Recorded at ${format(new Date(), "hh:mm a")}`,
      );
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "LONG_DAY_CONFIRM") {
        setLongDay(e.message);
        return;
      }
      toast.error("Couldn’t record your punch", errorMessage(e));
    },
  });

  const punchedIn = data?.is_punched_in ?? false;
  const status = isError ? "Unavailable" : punchedIn ? "Checked in" : data?.last_punch_out ? "Checked out" : "Not checked in";
  const tone = isError ? "neutral" : punchedIn ? "success" : data?.last_punch_out ? "neutral" : "warning";

  return (
    <div className="card flex flex-col">
      <div className="card-header">
        <div>
          <h3 className="card-title">Time clock</h3>
          <p className="card-desc">{format(now, "EEEE, d MMMM")}</p>
        </div>
        {isLoading ? <Skeleton className="h-5 w-24 rounded-full" /> : <StatusBadge tone={tone} label={status} />}
      </div>

      <div className="px-5 pb-5">
        <p className="text-[44px] font-semibold leading-none tracking-tight tabular-nums text-fg">
          {format(now, "hh:mm")}
          <span className="ml-1.5 text-lg font-medium text-fg-subtle">{format(now, "a")}</span>
        </p>

        <dl className="mt-5 grid grid-cols-3 divide-x divide-line rounded-lg border border-line bg-panel">
          {[
            { label: "First in", value: fmtTime(data?.first_punch_in) },
            { label: "Last out", value: fmtTime(data?.last_punch_out) },
            { label: "Worked", value: fmtMins(data?.effective_minutes ?? 0) },
          ].map(({ label, value }) => (
            <div key={label} className="px-3 py-2.5">
              <dt className="text-[11px] text-fg-subtle">{label}</dt>
              <dd className="mt-0.5 text-[13px] font-semibold tabular-nums text-fg">{isLoading ? "…" : value}</dd>
            </div>
          ))}
        </dl>

        {punchedIn && data?.first_punch_in && (
          <p className="mt-3 text-xs text-fg-muted">
            Active check-in from {format(new Date(data.first_punch_in), "d MMM, hh:mm a")}.
            {format(new Date(data.first_punch_in), "yyyy-MM-dd") !== format(now, "yyyy-MM-dd") &&
              " This session is from a previous day. If you forgot to check out, request an attendance correction."}
          </p>
        )}

        <button
          onClick={() => mutation.mutate({ type: punchedIn ? "OUT" : "IN" })}
          disabled={mutation.isPending || isLoading}
          className={`${punchedIn ? "btn-secondary" : "btn-primary"} mt-4 h-10 w-full`}
        >
          {punchedIn ? <LogOut size={16} /> : <LogIn size={16} />}
          {mutation.isPending ? "Recording…" : punchedIn ? "Check out" : "Check in"}
        </button>

        <ConfirmDialog
          open={longDay !== null}
          onClose={() => setLongDay(null)}
          onConfirm={() => mutation.mutate({ type: "OUT", confirm: true })}
          title="Check out after a very long day?"
          description={longDay}
          confirmLabel="Check out anyway"
          loading={mutation.isPending}
        />

        {noGps && (
          <p className="mt-2.5 flex items-center gap-1.5 text-xs text-warning">
            <MapPinOff size={12} /> Location unavailable — punch recorded without GPS.
          </p>
        )}

        {!!data?.punches?.length && (
          <div className="mt-5 border-t border-line pt-4">
            <p className="eyebrow mb-3">Today’s timeline</p>
            <ol className="relative space-y-3 border-l border-line pl-4">
              {data.punches.map((p) => (
                <li key={p.id} className="relative text-[13px]">
                  <span
                    className={`absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-surface ${p.punch_type === "IN" ? "bg-success" : "bg-fg-subtle"
                      }`}
                  />
                  <span className="font-medium text-fg">{p.punch_type === "IN" ? "Checked in" : p.punch_type === "OUT" ? "Checked out" : p.punch_type.replace("_", " ").toLowerCase()}</span>
                  <span className="ml-2 tabular-nums text-fg-subtle">{fmtTime(p.punched_at)}</span>
                  {p.is_corrected && <span className="badge badge-warning ml-2">Corrected</span>}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}
