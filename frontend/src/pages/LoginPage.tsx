import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, ChevronDown, Clock, ShieldCheck, Workflow, BarChart3, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { Avatar } from "../components/ui/Avatar";

const DEMO_PASSWORD = "Passw0rd!";

// Mirrors backend/scripts/seed_demo.py — SFPL Group, three sister companies,
// a shared accountant and a regional HR manager, so the scoping story (who
// can see which company) is visible from the login screen itself.
const DEMO_USERS = [
  { email: "kavita.singh@sfplgroup.in", label: "Super Admin", name: "Kavita Singh", desc: "Every company · platform admin" },
  { email: "rahul.iyer@sfplgroup.in", label: "Group HR", name: "Rahul Iyer", desc: "Every company · HR authority" },
  { email: "meera.joshi@sfplgroup.in", label: "Regional HR", name: "Meera Joshi", desc: "SRCC + Novusha only" },
  { email: "suresh.kumar@sfplgroup.in", label: "Accountant", name: "Suresh Kumar", desc: "Shared across SFPL + Novusha" },
  { email: "priya.menon@sfplgroup.in", label: "Manager", name: "Priya Menon", desc: "Her team at SFPL only" },
  { email: "arjun.sharma@sfplgroup.in", label: "Employee", name: "Arjun Sharma", desc: "Self-service at SFPL" },
  { email: "neha.patil@sfplgroup.in", label: "Employee", name: "Neha Patil", desc: "Self-service at SRCC" },
];

const FEATURES = [
  { icon: Clock, title: "Attendance that runs itself", desc: "Policy-driven shifts, grace periods and overtime." },
  { icon: Workflow, title: "Multi-level approvals", desc: "Leave and corrections routed to the right people." },
  { icon: BarChart3, title: "Live workforce insight", desc: "Dashboards and reports scoped to your companies." },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [showManual, setShowManual] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const signIn = async (who: string, addr: string, pw: string) => {
    setError(null);
    setBusy(who);
    try {
      await login(addr, pw);
      navigate("/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed");
    } finally {
      setBusy(null);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (email && password) void signIn("manual", email, password);
  };

  return (
    <div className="flex min-h-screen bg-surface">
      {/* Brand panel */}
      <div className="relative hidden w-[46%] max-w-[640px] flex-col justify-between overflow-hidden bg-zinc-950 p-12 text-white lg:flex">
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
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-700 text-base font-bold ring-1 ring-inset ring-white/20">S</div>
          <div className="leading-tight">
            <p className="text-sm font-semibold">SFPL Group</p>
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
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white">S</div>
            <p className="text-sm font-semibold text-fg">SFPL Group</p>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight text-fg">Sign in</h1>
          <p className="mt-1.5 text-[13px] text-fg-muted">
            Demo accounts below share one password — each shows a different slice of the company.
          </p>

          {error && (
            <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.06] px-3 py-2 text-[13px] text-danger">
              {error}
            </p>
          )}

          <div className="mt-5 space-y-2">
            {DEMO_USERS.map((u) => (
              <button
                key={u.email}
                onClick={() => void signIn(u.email, u.email, DEMO_PASSWORD)}
                disabled={busy !== null}
                className="group flex w-full items-center gap-3.5 rounded-xl border border-line bg-surface px-4 py-3 text-left shadow-xs transition-all hover:border-brand-500/50 hover:shadow-card hover:ring-4 hover:ring-brand-500/10 disabled:opacity-60"
              >
                <Avatar name={u.name} size="lg" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-[13px] font-semibold text-fg">{u.name}</span>
                    <span className="badge badge-neutral">{u.label}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-fg-subtle">{u.desc}</span>
                </span>
                {busy === u.email
                  ? <Loader2 size={16} className="shrink-0 animate-spin text-fg-subtle" />
                  : <ArrowRight size={16} className="shrink-0 text-fg-subtle transition-all group-hover:translate-x-0.5 group-hover:text-accent" />}
              </button>
            ))}
          </div>

          <div className="mt-8 border-t border-line pt-5">
            <button
              onClick={() => setShowManual((s) => !s)}
              className="flex w-full items-center justify-between text-[13px] font-medium text-fg-muted hover:text-fg"
              aria-expanded={showManual}
            >
              Sign in with email and password
              <ChevronDown size={15} className={`transition-transform ${showManual ? "rotate-180" : ""}`} />
            </button>

            {showManual && (
              <form onSubmit={handleSubmit} className="mt-4 space-y-3.5 animate-fade-in">
                <div>
                  <label className="label" htmlFor="li-email">Email</label>
                  <input
                    id="li-email" type="email" className="input" value={email}
                    onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="username"
                  />
                </div>
                <div>
                  <label className="label" htmlFor="li-password">Password</label>
                  <input
                    id="li-password" type="password" className="input" value={password}
                    onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password"
                  />
                </div>
                <button type="submit" className="btn-primary h-10 w-full" disabled={!email || !password || busy !== null}>
                  {busy === "manual" ? <Loader2 size={15} className="animate-spin" /> : <>Sign in <ArrowRight size={15} /></>}
                </button>
              </form>
            )}
          </div>

          <p className="mt-8 text-center text-xs text-fg-subtle">
            New company? <Link to="/register" className="font-medium text-accent hover:underline">Register here</Link> — a separate, isolated workspace.
          </p>
          <p className="mt-2 text-center text-xs text-fg-subtle">Development build · seeded demo tenant</p>
        </div>
      </div>
    </div>
  );
}
