import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { KeyRound, Loader2, LogOut, TriangleAlert } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { passwordProblem } from "../lib/password";
import { useToast } from "../components/ui/Toast";

/**
 * Replace your password. Reached two ways: voluntarily (from your profile), or forcibly — an imported
 * or admin-reset account is refused everywhere else until this is done (the API enforces that; the
 * app just routes you here). While forced, the rest of the app's navigation is not shown.
 */
export function ChangePasswordPage() {
  const { user, changePassword, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const forced = !!user?.mustChangePassword;

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problem = next ? passwordProblem(next, current) : null;
  const mismatch = confirm !== "" && confirm !== next;
  const valid = !!current && !!next && !problem && next === confirm;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setError(null);
    setBusy(true);
    try {
      await changePassword(current, next);
      toast.success("Password changed", "You're signed in with your new password.");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change your password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-6 py-12">
      <div className="w-full max-w-[440px]">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white">
            <KeyRound size={17} />
          </div>
          <div className="leading-tight">
            <h1 className="text-xl font-semibold tracking-tight text-fg">
              {forced ? "Choose a new password" : "Change password"}
            </h1>
            {user && <p className="text-[13px] text-fg-subtle">{user.name}</p>}
          </div>
        </div>

        {forced && (
          <p className="mb-4 flex gap-2.5 rounded-lg border border-warning/25 bg-warning/[0.06] px-3 py-2.5 text-[13px] text-fg" role="status">
            <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <span>
              You're signed in with a temporary password. Pick your own before continuing — you'll use it
              from now on, and only you will know it.
            </span>
          </p>
        )}

        {error && (
          <p role="alert" className="mb-4 rounded-lg border border-danger/25 bg-danger/[0.06] px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}

        <form onSubmit={submit} className="card space-y-3.5 p-5" noValidate>
          <div>
            <label className="label" htmlFor="cp-current">{forced ? "Temporary password" : "Current password"}</label>
            <input id="cp-current" type="password" className="input" value={current} autoFocus
              autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="cp-new">New password</label>
            <input id="cp-new" type="password" className="input" value={next} autoComplete="new-password"
              aria-invalid={!!problem} aria-describedby="cp-new-hint" onChange={(e) => setNext(e.target.value)} />
            <p id="cp-new-hint" className={`mt-1 text-xs ${problem ? "text-danger" : "text-fg-subtle"}`}>
              {problem ?? "At least 8 characters."}
            </p>
          </div>
          <div>
            <label className="label" htmlFor="cp-confirm">Confirm new password</label>
            <input id="cp-confirm" type="password" className="input" value={confirm} autoComplete="new-password"
              aria-invalid={mismatch} onChange={(e) => setConfirm(e.target.value)} />
            {mismatch && <p className="mt-1 text-xs text-danger">The two passwords don't match.</p>}
          </div>
          <button type="submit" className="btn-primary h-10 w-full" disabled={!valid || busy}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : forced ? "Set password and continue" : "Change password"}
          </button>
        </form>

        <p className="mt-5 text-center text-[13px] text-fg-muted">
          {forced ? (
            <button className="inline-flex items-center gap-1.5 hover:text-fg hover:underline" onClick={logout}>
              <LogOut size={13} /> Sign out instead
            </button>
          ) : (
            <Link to="/profile" className="hover:text-fg hover:underline">Cancel</Link>
          )}
        </p>
      </div>
    </div>
  );
}
