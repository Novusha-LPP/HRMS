import { useState } from "react";
import { api } from "../api/client";
import { platformApi } from "../api/platformClient";

export function MfaSetupPage({ platform = false }: { platform?: boolean }) {
  const [password, setPassword] = useState("");
  const [secret, setSecret] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const client = platform ? platformApi : api;
  const base = platform ? "/v1/platform" : "/v1/auth";
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      if (!secret) {
        const result = await client.post<{ secret: string }>(`${base}/mfa/enroll`, { password });
        setSecret(result.secret); setPassword("");
      } else {
        await client.post(`${base}/mfa/confirm`, { code });
        window.location.assign((platform ? "/platform/login" : "/login") + "?mfa=enrolled");
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Authenticator setup failed"); }
    finally { setBusy(false); }
  };
  return <main className="mx-auto max-w-lg p-6">
    <h1 className="text-xl font-semibold">Set up your authenticator</h1>
    <p className="mt-3">Privileged access requires an authenticator. After confirming, sign in again using the next code.</p>
    <form onSubmit={submit} className="mt-5 space-y-4">
      {!secret ? <div><label className="label" htmlFor="mfa-password">Current password</label>
        <input id="mfa-password" type="password" autoComplete="current-password" className="input"
          value={password} onChange={e => setPassword(e.target.value)} required /></div> : <>
        <p>Add an account in your authenticator app using this setup key. Keep it private.</p>
        <code className="block break-all rounded bg-surface p-3">{secret}</code>
        <label className="label" htmlFor="mfa-code">Six-digit authenticator code</label>
        <input id="mfa-code" className="input" inputMode="numeric" autoComplete="one-time-code"
          pattern="[0-9]{6}" maxLength={6} value={code} onChange={e => setCode(e.target.value)} required />
      </>}
      {error && <p role="alert">{error}</p>}
      <button className="btn-primary" disabled={busy}>{busy ? "Please wait…" : secret ? "Confirm authenticator" : "Create setup key"}</button>
    </form>
  </main>;
}
