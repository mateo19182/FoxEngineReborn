import { useState } from "react";
import { api, setToken } from "./api";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const res = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        json: { username, password },
      });
      setToken(res.access_token);
      onLoggedIn();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <div className="layout main-area auth-card">
      <header className="page-head">
        <div>
          <h1>Sign in</h1>
          <p className="lead">Use the credentials issued during setup or by an administrator.</p>
        </div>
      </header>

      <section className="panel">
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="login-user">Username</label>
            <input id="login-user" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="login-pass">Password</label>
            <input
              id="login-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {err ? <p className="error">{err}</p> : null}
          <div className="btn-row">
            <button type="submit">Login</button>
          </div>
        </form>
      </section>
    </div>
  );
}
