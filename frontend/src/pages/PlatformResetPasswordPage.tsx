import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, CircleCheck, Loader2, ShieldAlert } from "../components/icons/ThemeIcons";
import { AppearanceControls } from "../components/layout/AppearanceControls";
import { platformTenantsApi } from "../api/platform";
import { PlatformApiError } from "../api/platformClient";

export function PlatformResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token || password.length < 8 || busy) return;
    setError(null);
    setBusy(true);
    try {
      await platformTenantsApi.resetPassword(token, password);
      setDone(true);
    } catch (e) {
      setError(e instanceof PlatformApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6 py-12">
      <div className="card w-full max-w-[380px] animate-scale-in p-7">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-xs ring-1 ring-inset ring-white/15">
            <ShieldAlert size={17} />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-fg">Platform Console</p>
            <p className="text-xs text-fg-subtle">Set a new password</p>
          </div>
        </div>

        {!token ? (
          <p className="mt-6 rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">
            This link is missing its reset token. Request a new one.
          </p>
        ) : done ? (
          <div className="mt-6 space-y-4">
            <p className="flex items-center gap-2 rounded-lg border border-success/25 bg-success/[0.08] px-3 py-2.5 text-[13px] text-success">
              <CircleCheck size={15} /> Password updated.
            </p>
            <button onClick={() => navigate("/platform/login")} className="btn-primary h-10 w-full">
              Sign in <ArrowRight size={15} />
            </button>
          </div>
        ) : (
          <>
            {error && <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">{error}</p>}
            <form onSubmit={submit} className="mt-5 space-y-3.5">
              <div>
                <label className="label" htmlFor="rp-password">New password</label>
                <input id="rp-password" type="password" autoComplete="new-password" placeholder="At least 8 characters" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
              <button type="submit" disabled={password.length < 8 || busy} className="btn-primary h-10 w-full">
                {busy ? <Loader2 size={15} className="animate-spin" /> : <>Update password <ArrowRight size={15} /></>}
              </button>
            </form>
          </>
        )}

        <Link to="/platform/login" className="mt-5 block text-center text-[13px] font-medium text-fg-subtle hover:text-fg-muted">Back to sign in</Link>
        <AppearanceControls className="mt-5 border-t border-line pt-3" />
      </div>
    </div>
  );
}
