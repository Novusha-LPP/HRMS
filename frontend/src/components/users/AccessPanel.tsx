/**
 * Login / access management, shared between Organization → Users & access (the
 * tenant-wide list — including admin-only logins with no employment, e.g. a
 * company's HR admin, which is why that list still exists on its own) and the
 * Employee profile's "Access" tab (one specific person, alongside their KYC and
 * employment history — so HR doesn't have to leave the employee they're looking
 * at to find their login in a separate company-wide table).
 *
 * Both consume the same `["users"]` query and the same setStatus/resetPassword
 * mutations, so a change made from either page is instantly consistent in the
 * other — the account is one row, looked up by id, not two separate views that
 * could drift.
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { KeyRound, UserRoundX, UserRoundCheck, Copy, Sparkles, ShieldPlus } from "lucide-react";
import { usersApi } from "../../api/users";
import type { ScopeType, UserAccount } from "../../api/users";
import { generateTempPassword, passwordProblem } from "../../lib/password";
import { StatusBadge } from "../ui/StatusBadge";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { useAuth } from "../../context/AuthContext";

export const SCOPE_LABEL: Record<ScopeType, string> = {
  ALL: "All companies",
  LEGAL_ENTITY: "Specific companies",
  SELF: "Self only",
  DIRECT_REPORTS: "Direct reports",
  ALL_REPORTS: "Full reporting chain",
};

/** What this login can actually do right now — an ACTIVE account of a separated employee can't sign in. */
export function SignInChip({ u }: { u: UserAccount }) {
  if (u.status !== "ACTIVE") return <span className="badge badge-neutral">Disabled</span>;
  if (!u.can_sign_in) return <span className="badge badge-warning" title="The linked employee has left the company">Left company</span>;
  if (u.must_change_password) return <span className="badge badge-info" title="Has a temporary password">Must set password</span>;
  return <span className="badge badge-success">Active</span>;
}

export function ResetPasswordSheet({ target, onClose }: { target: UserAccount | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const problem = password ? passwordProblem(password) : null;

  const reset = useMutation({
    mutationFn: () => usersApi.resetPassword(target!.id, password),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("Password reset", `${u.email ?? "The account"} was signed out and must choose a new password at next sign-in.`);
      setPassword("");
      onClose();
    },
    onError: (e) => toast.error("Couldn’t reset the password", errorMessage(e)),
  });

  const close = () => { setPassword(""); onClose(); };
  const submit = (e: FormEvent) => { e.preventDefault(); if (password && !problem) reset.mutate(); };

  return (
    <Sheet
      open={!!target}
      onClose={close}
      title="Reset password"
      description={target ? `Set a temporary password for ${target.email ?? "this account"}.` : undefined}
      footer={
        <>
          <button className="btn-secondary" onClick={close}>Cancel</button>
          <button className="btn-primary" type="submit" form="reset-password" disabled={!password || !!problem || reset.isPending}>
            {reset.isPending ? "Resetting…" : "Reset password"}
          </button>
        </>
      }
    >
      <form id="reset-password" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="rp-password">Temporary password</label>
          <div className="flex gap-2">
            <input id="rp-password" type="text" className="input font-mono" value={password} autoComplete="off"
              spellCheck={false} aria-invalid={!!problem} onChange={(e) => setPassword(e.target.value)} />
            <button type="button" className="btn-secondary shrink-0" onClick={() => setPassword(generateTempPassword())}>
              <Sparkles size={14} /> Generate
            </button>
            <button type="button" className="btn-secondary shrink-0" disabled={!password} aria-label="Copy password"
              onClick={() => navigator.clipboard?.writeText(password).then(() => toast.success("Copied", "Share it with them directly."))}>
              <Copy size={14} />
            </button>
          </div>
          <p className={`mt-1 text-xs ${problem ? "text-danger" : "text-fg-subtle"}`}>{problem ?? "At least 8 characters. Share it with them directly, not by email."}</p>
        </div>
        <p className="rounded-lg border border-line bg-panel px-3 py-2.5 text-[13px] text-fg-muted">
          They'll be signed out everywhere right away, and asked to choose their own password the next time they sign in.
        </p>
      </form>
    </Sheet>
  );
}

/**
 * One employee's login — the KYC-section-style counterpart for access. Reuses the
 * same ["users"] list the Organization tab reads (no new query, one source of
 * truth), filtered to this employment. If nothing matches, offers to grant a
 * SELF-scoped EMPLOYEE login for exactly this person — the create path the
 * Organization tab's "Add user" never actually covers (it only grants
 * company-wide admin-tier roles).
 */
export function AccessSection({ employmentId, employeeName, canManage }: {
  employmentId: string; employeeName: string; canManage: boolean;
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [granting, setGranting] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [resetting, setResetting] = useState<UserAccount | null>(null);

  const users = useQuery({ queryKey: ["users"], queryFn: () => usersApi.listUsers() });
  const account = users.data?.find((u) => u.employment_id === employmentId);
  const isSelf = !!account && account.id === user?.id;

  const setStatus = useMutation({
    mutationFn: () => usersApi.setStatus(account!.id, account!.status === "ACTIVE" ? "INACTIVE" : "ACTIVE"),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(u.status === "ACTIVE" ? "Login re-enabled" : "Login disabled", u.status === "ACTIVE"
        ? `${employeeName} can sign in again.`
        : `${employeeName} is signed out and can't sign in.`);
      setToggling(false);
    },
    onError: (e) => toast.error("Couldn’t change the login", errorMessage(e)),
  });

  if (users.isError) {
    return <div className="card"><EmptyState icon={KeyRound} title="Couldn’t load access" description="The users API isn’t responding." /></div>;
  }
  if (users.isPending) {
    return <Skeleton className="h-40 rounded-xl" />;
  }

  if (!account) {
    return (
      <div className="card">
        <EmptyState
          icon={KeyRound}
          title="No portal login yet"
          description={`${employeeName} can’t sign in yet — grant them their own self-service login to change that.`}
          action={canManage ? <button className="btn-primary" onClick={() => setGranting(true)}><ShieldPlus size={15} /> Grant access</button> : undefined}
        />
        <GrantAccessSheet open={granting} onClose={() => setGranting(false)} employmentId={employmentId} employeeName={employeeName} />
      </div>
    );
  }

  const fields: [string, string][] = [
    ["Email", account.email ?? "—"],
    ["Role", account.role],
    ["Access", account.scope_type === "LEGAL_ENTITY" ? "Specific companies" : SCOPE_LABEL[account.scope_type]],
    ["Last signed in", account.last_login_at ? format(new Date(account.last_login_at), "d MMM yyyy, h:mm a") : "Never"],
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <StatusBadge status={account.status} />
        <SignInChip u={account} />
      </div>
      <dl className="divide-y divide-line rounded-xl border border-line">
        {fields.map(([label, value]) => (
          <div key={label} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
            <dt className="w-32 shrink-0 text-fg-subtle">{label}</dt>
            <dd className="min-w-0 truncate font-medium text-fg">{value}</dd>
          </div>
        ))}
      </dl>
      {isSelf ? (
        <p className="text-xs text-fg-subtle">This is your own login — manage it from your profile instead.</p>
      ) : canManage ? (
        <div className="flex gap-2">
          <button className="btn-secondary btn-sm" onClick={() => setResetting(account)}>
            <KeyRound size={13} /> Reset password
          </button>
          <button className="btn-secondary btn-sm" onClick={() => setToggling(true)}>
            {account.status === "ACTIVE" ? <><UserRoundX size={13} /> Disable</> : <><UserRoundCheck size={13} /> Enable</>}
          </button>
        </div>
      ) : null}
      <ConfirmDialog
        open={toggling}
        onClose={() => setToggling(false)}
        onConfirm={() => setStatus.mutate()}
        loading={setStatus.isPending}
        title={account.status === "ACTIVE" ? "Disable this login?" : "Re-enable this login?"}
        confirmLabel={account.status === "ACTIVE" ? "Disable login" : "Re-enable"}
        description={account.status === "ACTIVE"
          ? `${employeeName} will be signed out immediately and won't be able to sign in until you re-enable it.`
          : `${employeeName} will be able to sign in again.`}
      />
      <ResetPasswordSheet target={resetting} onClose={() => setResetting(null)} />
    </div>
  );
}

function GrantAccessSheet({ open, onClose, employmentId, employeeName }: {
  open: boolean; onClose: () => void; employmentId: string; employeeName: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const empty = { email: "", password: "", mustChange: true };
  const [form, setForm] = useState(empty);

  const create = useMutation({
    mutationFn: () =>
      usersApi.createUser({
        email: form.email.trim(),
        password: form.password,
        role: "EMPLOYEE",
        scope_type: "SELF",
        employment_id: employmentId,
        must_change_password: form.mustChange,
      }),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("Access granted", `${u.email} can now sign in as ${employeeName}.`);
      setForm(empty);
      onClose();
    },
    onError: (e) => toast.error("Couldn’t grant access", errorMessage(e)),
  });

  const valid = /\S+@\S+\.\S+/.test(form.email) && form.password.length >= 8;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) create.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Grant portal access"
      description={`A self-service login for ${employeeName} — their own attendance, leave and profile only, nothing else in the company.`}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="grant-access" disabled={!valid || create.isPending}>
            {create.isPending ? "Granting…" : "Grant access"}
          </button>
        </>
      }
    >
      <form id="grant-access" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="ga-email">Email</label>
          <input id="ga-email" type="email" className="input" placeholder="e.g. name@company.in" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="ga-password">Temporary password</label>
          <input id="ga-password" type="password" className="input" placeholder="At least 8 characters" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
          <label className="mt-2 flex items-center gap-2 text-[13px] text-fg">
            <input type="checkbox" className="checkbox" checked={form.mustChange}
              onChange={(e) => setForm((f) => ({ ...f, mustChange: e.target.checked }))} />
            Ask them to choose their own password when they first sign in
          </label>
          <p className="mt-1 text-xs text-fg-subtle">Share this with them directly, not by email.</p>
        </div>
      </form>
    </Sheet>
  );
}
