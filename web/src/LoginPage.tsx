import { useState } from "react";
import { api, setToken } from "./api";
import { InformaticEyeMark } from "./InformaticEyeMark";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const res = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        json: { username, password },
      });
      setToken(res.access_token);
      onLoggedIn();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-gate" aria-labelledby="login-title">
      <div className="auth-gate__ambient" aria-hidden />
      <div className="auth-gate__card">
        <header className="auth-gate__brand">
          <span className="auth-gate__mark" aria-hidden>
            <InformaticEyeMark />
          </span>
          <h1 id="login-title" className="auth-gate__title">
            FoxEngine
          </h1>
        </header>

        <form className="auth-gate__form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="login-user">Username</label>
            <input
              id="login-user"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="login-pass">Password</label>
            <input
              id="login-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {err ? <p className="error auth-gate__error">{err}</p> : null}
          <button type="submit" className="auth-gate__submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
