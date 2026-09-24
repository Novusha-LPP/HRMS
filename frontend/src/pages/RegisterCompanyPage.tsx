import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, ArrowLeft, Loader2, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export function RegisterCompanyPage() {
  const { registerCompany } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ companyName: "", country: "IN", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = form.companyName.trim().length >= 2 && /\S+@\S+\.\S+/.test(form.email) && form.password.length >= 8;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setError(null);
    setBusy(true);
    try {
      await registerCompany({
        company_name: form.companyName.trim(),
        country_code: form.country,
        admin_email: form.email.trim(),
        admin_password: form.password,
      });
      navigate("/organization");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't register company");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-6 py-12">
      <div className="w-full max-w-[420px]">
        <Link to="/login" className="mb-8 flex items-center gap-1.5 text-[13px] font-medium text-fg-muted hover:text-fg">
          <ArrowLeft size={14} /> Back to sign in
        </Link>

        <h1 className="text-2xl font-semibold tracking-tight text-fg">Register your company</h1>
        <p className="mt-1.5 text-[13px] text-fg-muted">
          This creates a brand-new, fully isolated workspace — separate from every other company on
          this platform, with its own users, departments and data. If you're adding a sister company
          to a group you already administer, sign in and use Organization → Add company instead.
        </p>

        {error && (
          <p className="mt-4 rounded-lg border border-danger/25 bg-danger/[0.06] px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}

        <form onSubmit={submit} className="mt-6 space-y-3.5">
          <div>
            <label className="label" htmlFor="rc-name">Company name</label>
            <input
              id="rc-name" className="input" placeholder="e.g. Brightpath Logistics"
              value={form.companyName} onChange={(e) => setForm((f) => ({ ...f, companyName: e.target.value }))}
            />
          </div>
          <div>
            <label className="label" htmlFor="rc-country">Country</label>
            <input
              id="rc-country" className="input" maxLength={2} value={form.country}
              onChange={(e) => setForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))}
            />
          </div>
          <div className="border-t border-line pt-3.5">
            <label className="label" htmlFor="rc-email">Your email</label>
            <input
              id="rc-email" type="email" className="input" placeholder="you@company.com" autoComplete="username"
              value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            />
          </div>
          <div>
            <label className="label" htmlFor="rc-password">Password</label>
            <input
              id="rc-password" type="password" className="input" placeholder="At least 8 characters" autoComplete="new-password"
              value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            />
            <p className="mt-1 text-xs text-fg-subtle">You'll be signed in as this company's Super Admin.</p>
          </div>
          <button type="submit" className="btn-primary h-10 w-full" disabled={!valid || busy}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <>Create company & sign in <ArrowRight size={15} /></>}
          </button>
        </form>

        <p className="mt-8 flex items-center justify-center gap-2 text-xs text-fg-subtle">
          <ShieldCheck size={14} /> A separate tenant — never visible to any other company
        </p>
      </div>
    </div>
  );
}
