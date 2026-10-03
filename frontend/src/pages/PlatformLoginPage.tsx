import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Loader2, ShieldAlert } from "../components/icons/ThemeIcons";
import { AppearanceControls } from "../components/layout/AppearanceControls";
import { usePlatformAuth } from "../context/PlatformAuthContext";

export function PlatformLoginPage() {
  const { login } = usePlatformAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email || !password || busy) return;
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate("/platform");
    } catch {
      setError("Invalid email or password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas px-6 py-12">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          backgroundImage: "linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage: "radial-gradient(ellipse at 50% 0%, black 20%, transparent 70%)",
        }}
      />
      <div className="pointer-events-none absolute -left-32 -top-32 h-[420px] w-[420px] rounded-full bg-brand-500/15 blur-[120px]" />

      <div className="card relative w-full max-w-[380px] animate-scale-in p-7">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-xs ring-1 ring-inset ring-white/15">
            <ShieldAlert size={17} />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-fg">Platform Console</p>
            <p className="text-xs text-fg-subtle">Cross-tenant administration</p>
          </div>
        </div>

        <h1 className="mt-6 text-xl font-semibold tracking-tight text-fg">Sign in</h1>
        <p className="mt-1 text-[13px] text-fg-subtle">
          This is not a company account. Platform admins operate above every tenant.
        </p>

        {error && (
          <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.08] px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}

        <form onSubmit={submit} className="mt-5 space-y-3.5">
          <div>
            <label className="label" htmlFor="pl-email">Email</label>
            <input id="pl-email" type="email" autoComplete="username" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="pl-password">Password</label>
            <input id="pl-password" type="password" autoComplete="current-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button type="submit" disabled={!email || !password || busy} className="btn-primary h-10 w-full">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <>Sign in <ArrowRight size={15} /></>}
          </button>
          <Link to="/platform/forgot-password" className="block text-center text-[13px] font-medium text-fg-subtle hover:text-fg-muted">
            Forgot password?
          </Link>
        </form>
        <AppearanceControls className="mt-5 border-t border-line pt-3" />
      </div>
    </div>
  );
}
