import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Printer } from "lucide-react";
import { usersApi } from "../../api/users";
import type { SignInSlip } from "../../api/users";
import { Sheet } from "../ui/Overlay";
import { Notice } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

export interface SlipEmployee {
  id: string;
  name: string;
  employeeNumber: string;
}

const CHUNK = 100;

const escapeHtml = (v: string) =>
  v.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);

/**
 * Print one slip per person from a hidden frame in this page: no pop-up (often blocked), and no
 * script inside the printed document (the deployed CSP blocks inline scripts). The frame, and
 * the passwords in it, are removed once printing is done.
 */
function printSlips(slips: SignInSlip[]) {
  const signInAt = `${window.location.origin}/login`;
  const cards = slips.map((s) => `
    <section class="slip">
      <p class="company">${escapeHtml(s.company ?? "")}</p>
      <p class="name">${escapeHtml(s.name)}</p>
      <dl>
        <dt>Employee number</dt><dd>${escapeHtml(s.employee_number)}</dd>
        <dt>Temporary password</dt><dd class="pw">${escapeHtml(s.temporary_password ?? "")}</dd>
        <dt>Sign in at</dt><dd>${escapeHtml(signInAt)}</dd>
      </dl>
      <p class="note">Sign in with your employee number and this password. You will be asked to choose your own password straight away. Keep this slip private.</p>
    </section>`).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Sign-in slips</title>
    <style>
      body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 16px; color: #111; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .slip { border: 1px dashed #888; border-radius: 8px; padding: 14px 16px; break-inside: avoid; }
      .company { margin: 0; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #555; }
      .name { margin: 4px 0 8px; font-size: 16px; font-weight: 600; }
      dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
      dt { color: #555; } dd { margin: 0; font-weight: 600; word-break: break-all; }
      .pw { font-family: ui-monospace, Menlo, monospace; font-size: 18px; letter-spacing: .12em; }
      .note { margin: 10px 0 0; font-size: 11px; color: #444; }
      @media print { body { margin: 0; } }
    </style></head><body><div class="grid">${cards}</div></body></html>`;

  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.title = "Sign-in slips";
  Object.assign(frame.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
  const cleanup = () => frame.remove();
  frame.onload = () => {
    const win = frame.contentWindow;
    if (!win) return cleanup();
    win.addEventListener("afterprint", cleanup);
    // Safety net in case afterprint never fires.
    setTimeout(cleanup, 5 * 60_000);
    win.focus();
    win.print();
  };
  frame.srcdoc = html;
  document.body.appendChild(frame);
}

export function SignInSlipsSheet({ employees, onClose }: { employees: SlipEmployee[] | null; onClose: () => void }) {
  const toast = useToast();
  const [numeric, setNumeric] = useState(true);
  const [results, setResults] = useState<SignInSlip[] | null>(null);

  const issue = useMutation({
    mutationFn: async () => {
      const ids = (employees ?? []).map((e) => e.id);
      const out: SignInSlip[] = [];
      for (let i = 0; i < ids.length; i += CHUNK) out.push(...(await usersApi.issueSignInSlips(ids.slice(i, i + CHUNK), numeric)));
      return out;
    },
    onSuccess: (slips) => setResults(slips),
    onError: (e) => toast.error("Couldn’t issue sign-in details", errorMessage(e)),
  });

  const issued = (results ?? []).filter((r) => r.outcome !== "SKIPPED");
  const skipped = (results ?? []).filter((r) => r.outcome === "SKIPPED");
  const close = () => { setResults(null); onClose(); };

  return (
    <Sheet
      open={employees !== null}
      onClose={close}
      title="Sign-in slips"
      description="Temporary sign-in details for staff who sign in with their employee number instead of an email."
      className="max-w-2xl"
      footer={results ? <>
        <button className="btn-secondary" onClick={close}>Done</button>
        <button className="btn-primary" disabled={!issued.length} onClick={() => printSlips(issued)}>
          <Printer size={15} /> Print {issued.length} slip{issued.length === 1 ? "" : "s"}
        </button>
      </> : <>
        <button className="btn-secondary" onClick={close}>Cancel</button>
        <button className="btn-primary" disabled={!employees?.length || issue.isPending} onClick={() => issue.mutate()}>
          <KeyRound size={15} /> {issue.isPending ? "Issuing…" : `Issue for ${employees?.length ?? 0}`}
        </button>
      </>}
    >
      {!results ? (
        <div className="space-y-4 text-sm">
          <p className="text-fg-muted">
            Each selected employee gets a temporary password. They sign in with their <strong className="text-fg">employee number</strong> and must choose their own password straight away.
          </p>
          <ul className="list-disc space-y-1 pl-5 text-fg-muted">
            <li>Employees without a login get one (their own records only).</li>
            <li>Employees who already have an employee login get a new password, and are signed out everywhere.</li>
            <li>HR, manager and admin logins, people who have left, and your own login are skipped.</li>
          </ul>
          <label className="flex items-center gap-2 text-fg">
            <input type="checkbox" className="checkbox" checked={numeric} onChange={(e) => setNumeric(e.target.checked)} />
            Numbers only (8 digits), easier to type on a phone or kiosk
          </label>
        </div>
      ) : (
        <div className="space-y-4">
          <Notice title="These passwords are shown only now" tone="warning">
            Print or hand out the slips before you close this. They aren’t stored and can’t be shown again; issue new ones if a slip is lost.
          </Notice>
          {issued.length > 0 && (
            <div className="card overflow-hidden">
              <table className="tbl">
                <thead><tr><th>Employee</th><th>Number</th><th>Temporary password</th><th /></tr></thead>
                <tbody>
                  {issued.map((s) => (
                    <tr key={s.employment_id}>
                      <td className="font-medium text-fg">{s.name}</td>
                      <td className="font-mono text-xs">{s.employee_number}</td>
                      <td className="font-mono tracking-wider text-fg">{s.temporary_password}</td>
                      <td><span className="badge badge-neutral">{s.outcome === "CREATED" ? "New login" : "Reset"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {skipped.length > 0 && (
            <div>
              <p className="eyebrow mb-2">Skipped ({skipped.length})</p>
              <ul className="divide-y divide-line rounded-xl border border-line text-[13px]">
                {skipped.map((s) => (
                  <li key={s.employment_id} className="flex items-center justify-between gap-3 px-4 py-2">
                    <span className="truncate text-fg">{s.name || s.employment_id}</span>
                    <span className="shrink-0 text-xs text-fg-subtle">{s.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Sheet>
  );
}
