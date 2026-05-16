import { useState } from "react";
import { api } from "./api";
import { DocTip } from "./DocTip";

export function SetupPage({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const res = await api<{ api_key: string }>("/setup/complete", {
        method: "POST",
        json: { username, password },
      });
      setKey(res.api_key);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  if (key) {
    return (
      <div className="layout main-area auth-card">
        <header className="page-head">
          <div>
            <h1>Setup complete</h1>
            <p className="lead">Save the bootstrap API key before continuing.</p>
          </div>
        </header>
        <section className="panel">
          <div className="field">
            <div className="label-row">
              <label htmlFor="setup-key">Initial API key</label>
              <DocTip text="Same as a normal API key: full access for automation. Shown only this once; copy it before you continue." />
            </div>
            <textarea id="setup-key" readOnly rows={3} value={key} />
          </div>
          <div className="btn-row">
            <button type="button" onClick={() => onDone()}>
              Continue to login
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="layout main-area auth-card">
      <header className="page-head">
        <div>
          <h1>First run setup</h1>
          <p className="lead">Shown only while /setup/status reports that an administrator account is required.</p>
        </div>
      </header>

      <section className="panel">
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="setup-user">Username</label>
            <input id="setup-user" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="setup-pass">Password</label>
            <input
              id="setup-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          {err ? <p className="error">{err}</p> : null}
          <div className="btn-row">
            <button type="submit">Create admin</button>
          </div>
        </form>
      </section>
    </div>
  );
}
