import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Clock, ShieldCheck, Workflow, BarChart3, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { SignInError } from "../lib/signInError";

const FEATURES = [
  { icon: Clock, title: "Attendance that runs itself", desc: "Policy-driven shifts, grace periods and overtime." },
  { icon: Workflow, title: "Multi-level approvals", desc: "Leave and corrections routed to the right people." },
  { icon: BarChart3, title: "Live workforce insight", desc: "Dashboards and reports scoped to your companies." },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  // Only shown once the API says the same code/phone is used by more than one company.
  const [company, setCompany] = useState("");
  const [needCompany, setNeedCompany] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!identifier || !password) return;
    setError(null);
    setBusy(true);
    try {
      await login(identifier, password, needCompany ? company : undefined, otp || undefined);
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof SignInError && err.code === "COMPANY_REQUIRED") setNeedCompany(true);
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-surface">
      {/* Brand panel */}
      <div className="login-brand-panel relative hidden w-[46%] max-w-[640px] flex-col justify-between overflow-hidden bg-zinc-950 p-12 text-white lg:flex">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: "linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage: "radial-gradient(ellipse at 30% 20%, black 20%, transparent 70%)",
          }}
        />
        <div className="pointer-events-none absolute -left-32 -top-32 h-[480px] w-[480px] rounded-full bg-brand-500/25 blur-[120px]" />
        <div className="pointer-events-none absolute -bottom-40 right-0 h-[360px] w-[360px] rounded-full bg-brand-700/30 blur-[120px]" />

        <div className="relative flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-700 text-base font-bold ring-1 ring-inset ring-white/20">H</div>
          <div className="leading-tight">
            <p className="text-sm font-semibold">HRMS</p>
            <p className="text-xs text-white/50">People Platform</p>
          </div>
        </div>

        <div className="relative">
          <h2 className="max-w-md text-[34px] font-semibold leading-[1.15] tracking-tight">
            One platform, <span className="text-brand-300">every sister company.</span>
          </h2>
          <ul className="mt-10 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-4">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/5 text-brand-300">
                  <f.icon size={16} />
                </span>
                <span>
                  <span className="block text-sm font-medium">{f.title}</span>
                  <span className="block text-[13px] text-white/50">{f.desc}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative flex items-center gap-2 text-xs text-white/40">
          <ShieldCheck size={14} /> Tenant-isolated · Row-level security · Scoped by company
        </p>
      </div>

      {/* Sign-in */}
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-[420px]">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white">H</div>
            <p className="text-sm font-semibold text-fg">HRMS</p>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight text-fg">Sign in</h1>
          <p className="mt-1.5 text-[13px] text-fg-muted">Sign in with your username, phone number, or email.</p>

          {error && (
            <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.06] px-3 py-2 text-[13px] text-danger">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-3.5">
            <div>
              <label className="label" htmlFor="li-identifier">Username, Phone, or Email</label>
              <input
                id="li-identifier" type="text" className="input" value={identifier}
                onChange={(e) => setIdentifier(e.target.value)} placeholder="Username, mobile number, or email" autoComplete="username" autoFocus
              />
            </div>
            <div>
              <label className="label" htmlFor="li-password">Password</label>
              <input
                id="li-password" type="password" className="input" value={password}
                onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password"
              />
            </div>
            {needCompany && (
              <div>
                <label className="label" htmlFor="li-company">Company code</label>
                <input
                  id="li-company" type="text" className="input" value={company} autoFocus
                  onChange={(e) => setCompany(e.target.value)} placeholder="e.g. suraj-group" autoComplete="organization"
                />
                <p className="mt-1 text-xs text-fg-subtle">Your HR team can tell you your company's code.</p>
              </div>
            )}
          <div>
            <label className="label" htmlFor="auth-otp">Authenticator code (if enabled)</label>
            <input id="auth-otp" className="input" inputMode="numeric" autoComplete="one-time-code"
              pattern="[0-9]{6}" maxLength={6} value={otp} onChange={e => setOtp(e.target.value)} />
          </div>
            <button type="submit" className="btn-primary h-10 w-full" disabled={!identifier || !password || (needCompany && !company.trim()) || busy}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <>Sign in <ArrowRight size={15} /></>}
            </button>
          </form>

          <p className="mt-8 text-center text-xs text-fg-subtle">
            New company? <Link to="/register" className="font-medium text-accent hover:underline">Register here</Link> — a separate, isolated workspace.
          </p>
        </div>
      </div>
    </div>
  );
}
