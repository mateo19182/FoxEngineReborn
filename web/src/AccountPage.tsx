import { useEffect, useState } from "react";
import { api } from "./api";
import { DocTip } from "./DocTip";

type Me = { id: string; username: string; roles: string[] };
type ApiKey = { id: string; name: string; created_at: string; last_used_at: string | null };

export function AccountPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [cur, setCur] = useState("");
  const [newPw, setNewPw] = useState("");
  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const m = await api<Me>("/auth/me");
    setMe(m);
    const k = await api<ApiKey[]>("/api-keys");
    setKeys(k);
  }

  useEffect(() => {
    void (async () => {
      try {
        await load();
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, []);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/auth/password", {
        method: "POST",
        json: { current_password: cur, new_password: newPw },
      });
      setCur("");
      setNewPw("");
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setNewKey(null);
    try {
      const r = await api<{ key: string }>("/api-keys", {
        method: "POST",
        json: { name: keyName },
      });
      setNewKey(r.key);
      setKeyName("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this API key?")) return;
    setErr(null);
    try {
      await api(`/api-keys/${id}`, { method: "DELETE" });
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Account</h1>
          <p className="lead">Session identity, password rotation, and long-lived API keys.</p>
        </div>
      </header>

      {err ? <p className="error">{err}</p> : null}

      {me ? (
        <section className="panel">
          <div className="panel__head">
            <h2>Signed in</h2>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            <strong>{me.username}</strong>
            <span className="muted"> ({me.roles.join(", ")})</span>
          </p>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel__head">
          <h2>Change password</h2>
        </div>
        <form onSubmit={changePassword}>
          <div className="field">
            <label htmlFor="pw-cur">Current password</label>
            <input
              id="pw-cur"
              type="password"
              value={cur}
              onChange={(e) => setCur(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="pw-new">New password</label>
            <input
              id="pw-new"
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <div className="btn-row">
            <button type="submit">Update password</button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>API keys</h2>
        </div>
        {newKey ? (
          <div className="field">
            <div className="label-row">
              <label htmlFor="new-key-plain">New key (copy now)</label>
              <DocTip text="The server never shows this secret again. Copy it into a password manager or env file before you leave this page." />
            </div>
            <textarea id="new-key-plain" readOnly rows={2} value={newKey} />
          </div>
        ) : null}
        <form onSubmit={createKey}>
          <div className="field">
            <label htmlFor="key-name">Key name</label>
            <input id="key-name" value={keyName} onChange={(e) => setKeyName(e.target.value)} required />
          </div>
          <div className="btn-row">
            <button type="submit">Create key</button>
          </div>
        </form>
        <ul className="key-list">
          {keys.map((k) => (
            <li key={k.id}>
              <span>
                {k.name}
                <span className="muted">, created {k.created_at}</span>
                {k.last_used_at ? <span className="muted">, last used {k.last_used_at}</span> : null}
              </span>
              <button type="button" className="secondary" onClick={() => revoke(k.id)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
