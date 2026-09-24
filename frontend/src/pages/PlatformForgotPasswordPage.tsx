import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, Loader2, ShieldAlert, TriangleAlert } from "lucide-react";
import { platformTenantsApi } from "../api/platform";
import { PlatformApiError } from "../api/platformClient";

export function PlatformForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ message: string; dev_reset_url: string | null } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email || busy) return;
    setError(null);
    setBusy(true);
    try {
      setResult(await platformTenantsApi.forgotPassword(email));
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
            <p className="text-xs text-fg-subtle">Reset your password</p>
          </div>
        </div>

        {result ? (
          <div className="mt-6 space-y-4">
            <p className="rounded-lg border border-success/25 bg-success/[0.08] px-3 py-2.5 text-[13px] text-success">
              {result.message}
            </p>
            {result.dev_reset_url && (
              <div className="rounded-lg border border-warning/25 bg-warning/[0.08] px-3 py-2.5 text-[13px] text-warning">
                <p className="flex items-center gap-1.5 font-medium"><TriangleAlert size={14} /> Dev mode — no email provider is wired up.</p>
                <Link to={result.dev_reset_url} className="mt-1.5 block break-all underline underline-offset-2">{result.dev_reset_url}</Link>
              </div>
            )}
            <Link to="/platform/login" className="flex items-center justify-center gap-1.5 text-[13px] font-medium text-fg-subtle hover:text-fg-muted">
              <ArrowLeft size={14} /> Back to sign in
            </Link>
          </div>
        ) : (
          <>
            <h1 className="mt-6 text-xl font-semibold tracking-tight text-fg">Forgot password</h1>
            <p className="mt-1 text-[13px] text-fg-subtle">We'll generate a reset link for this account, if it exists.</p>

            {error && <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">{error}</p>}

            <form onSubmit={submit} className="mt-5 space-y-3.5">
              <div>
                <label className="label" htmlFor="fp-email">Email</label>
                <input id="fp-email" type="email" autoComplete="username" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <button type="submit" disabled={!email || busy} className="btn-primary h-10 w-full">
                {busy ? <Loader2 size={15} className="animate-spin" /> : <>Send reset link <ArrowRight size={15} /></>}
              </button>
              <Link to="/platform/login" className="flex items-center justify-center gap-1.5 text-[13px] font-medium text-fg-subtle hover:text-fg-muted">
                <ArrowLeft size={14} /> Back to sign in
              </Link>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
