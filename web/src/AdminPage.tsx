import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { DateRange } from "react-day-picker";
import { api } from "./api";
import { AuditDateRangeCalendar } from "./AuditDateRangeCalendar";
import { DocTip } from "./DocTip";
import { Modal } from "./Modal";

type UserRow = {
  id: string;
  username: string;
  email: string | null;
  is_active: boolean;
  roles: string[];
};

type AuditRow = {
  id: number;
  ts: string;
  actor_kind: string;
  actor_username: string | null;
  action: string;
  target_kind: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
};

type Me = { id: string; username: string; roles: string[]; llm_nl_enabled?: boolean };
type ApiKey = { id: string; name: string; created_at: string; last_used_at: string | null };

type ModalKind = "createUser" | "changePassword" | "createApiKey" | null;

const AUDIT_PAGE = 40;

const auditTsDisplay = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatAuditTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : auditTsDisplay.format(d);
}

/** Inclusive local calendar days as UTC bounds for the API. */
function auditDateRangeToIsoBounds(range: DateRange | undefined): { isoFrom: string | null; isoTo: string | null } {
  if (!range?.from) return { isoFrom: null, isoTo: null };
  const fromD = range.from;
  const toD = range.to ?? range.from;
  const start = new Date(fromD.getFullYear(), fromD.getMonth(), fromD.getDate(), 0, 0, 0, 0);
  const end = new Date(toD.getFullYear(), toD.getMonth(), toD.getDate(), 23, 59, 59, 999);
  return { isoFrom: start.toISOString(), isoTo: end.toISOString() };
}

export function AdminPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [auditItems, setAuditItems] = useState<AuditRow[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditLoadingInitial, setAuditLoadingInitial] = useState(true);
  const [auditLoadingMore, setAuditLoadingMore] = useState(false);
  const [auditActorId, setAuditActorId] = useState<string>("");
  const [auditActionType, setAuditActionType] = useState<string>("");
  const [auditDateRange, setAuditDateRange] = useState<DateRange | undefined>(undefined);
  const [auditActionOptions, setAuditActionOptions] = useState<string[]>([]);
  const [auditDetail, setAuditDetail] = useState<AuditRow | null>(null);
  const auditSentinelRef = useRef<HTMLDivElement | null>(null);
  const auditNextOffsetRef = useRef(0);
  const auditTotalRef = useRef(0);
  const auditFetchingRef = useRef(false);
  const [me, setMe] = useState<Me | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [modal, setModal] = useState<ModalKind>(null);
  const [err, setErr] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"viewer" | "manager">("viewer");

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");

  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);

  function auditQuerySummary(row: AuditRow): string | null {
    if (row.action === "query.nl_translate") {
      const parts: string[] = [];
      if (typeof row.details.dsl === "string" && row.details.dsl) parts.push(row.details.dsl);
      if (typeof row.details.error === "string" && row.details.error) parts.push(`error: ${row.details.error}`);
      if (typeof row.details.nl_len === "number") parts.push(`nl_len=${row.details.nl_len}`);
      return parts.length ? parts.join(" · ") : null;
    }
    if (row.action === "assistant.chat") {
      const parts: string[] = [];
      if (typeof row.details.turns === "number") parts.push(`turns=${row.details.turns}`);
      if (typeof row.details.reply_len === "number") parts.push(`reply_len=${row.details.reply_len}`);
      return parts.length ? parts.join(" · ") : null;
    }
    const q = row.details.query ?? row.details.dsl;
    if (typeof q !== "string" || !q) return null;
    if (row.action !== "query.run" && row.action !== "export.start") return null;
    const parts = [q];
    if (typeof row.details.view === "string") parts.push(`view=${row.details.view}`);
    if (typeof row.details.limit === "number") parts.push(`limit=${row.details.limit}`);
    if (typeof row.details.offset === "number" && row.details.offset > 0) {
      parts.push(`offset=${row.details.offset}`);
    }
    if (typeof row.details.total_matching === "number") parts.push(`total=${row.details.total_matching}`);
    if (typeof row.details.result_count === "number") parts.push(`rows=${row.details.result_count}`);
    return parts.join(" · ");
  }

  function auditEntrySummary(row: AuditRow): string {
    const q = auditQuerySummary(row);
    if (q) return q;
    const d = row.details;
    const keys = Object.keys(d);
    if (keys.length === 0) return "No details";
    const preview = keys.slice(0, 3).map((k) => `${k}: ${fmtDetailValue(d[k])}`);
    return preview.join(" · ");
  }

  const fetchAudit = useCallback(
    async (reset: boolean) => {
      if (auditFetchingRef.current) return;
      if (!reset && auditNextOffsetRef.current >= auditTotalRef.current) {
        return;
      }
      auditFetchingRef.current = true;
      const offset = reset ? 0 : auditNextOffsetRef.current;
      if (reset) {
        auditNextOffsetRef.current = 0;
        setAuditItems([]);
        setAuditLoadingInitial(true);
        setErr(null);
      } else {
        setAuditLoadingMore(true);
      }
      try {
        const { isoFrom, isoTo } = auditDateRangeToIsoBounds(auditDateRange);
        if (isoFrom && isoTo && isoFrom > isoTo) {
          setErr("Date range is invalid: start must be before or equal to end.");
          return;
        }

        const params = new URLSearchParams();
        params.set("limit", String(AUDIT_PAGE));
        params.set("offset", String(offset));
        if (auditActionType) {
          params.append("actions", auditActionType);
        }
        if (auditActorId) params.set("actor_id", auditActorId);
        if (isoFrom) params.set("ts_from", isoFrom);
        if (isoTo) params.set("ts_to", isoTo);
        const r = await api<{ total: number; items: AuditRow[] }>(`/audit-log?${params.toString()}`);
        auditTotalRef.current = r.total;
        setAuditTotal(r.total);
        if (r.items.length === 0) {
          auditNextOffsetRef.current = r.total;
        } else {
          auditNextOffsetRef.current = offset + r.items.length;
        }
        if (reset) {
          setAuditItems(r.items);
        } else {
          setAuditItems((prev) => {
            const seen = new Set(prev.map((x) => x.id));
            const merged = [...prev];
            for (const row of r.items) {
              if (!seen.has(row.id)) {
                seen.add(row.id);
                merged.push(row);
              }
            }
            return merged;
          });
        }
      } catch (e) {
        setErr(String(e));
      } finally {
        auditFetchingRef.current = false;
        setAuditLoadingInitial(false);
        setAuditLoadingMore(false);
      }
    },
    [auditActorId, auditActionType, auditDateRange],
  );

  useEffect(() => {
    auditNextOffsetRef.current = 0;
    auditTotalRef.current = 0;
    void fetchAudit(true);
  }, [fetchAudit]);

  useEffect(() => {
    if (auditLoadingInitial) return;
    const el = auditSentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        void fetchAudit(false);
      },
      { root: null, rootMargin: "200px", threshold: 0 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [fetchAudit, auditLoadingInitial]);

  useLayoutEffect(() => {
    const el = auditSentinelRef.current;
    if (!el || auditFetchingRef.current || auditLoadingInitial) return;
    if (auditNextOffsetRef.current >= auditTotalRef.current) return;
    const rect = el.getBoundingClientRect();
    const vh = window.innerHeight || document.documentElement.clientHeight;
    if (rect.top < vh + 240) {
      void fetchAudit(false);
    }
  }, [auditItems, auditLoadingInitial, fetchAudit]);

  async function loadUsers() {
    const u = await api<UserRow[]>("/users");
    setUsers(u);
  }

  async function loadAccount() {
    const m = await api<Me>("/auth/me");
    setMe(m);
    const k = await api<ApiKey[]>("/api-keys");
    setKeys(k);
  }

  useEffect(() => {
    void (async () => {
      setErr(null);
      try {
        await Promise.all([loadUsers(), loadAccount()]);
      } catch (e) {
        setErr(String(e));
      }
      try {
        const actions = await api<string[]>("/audit-log/actions");
        setAuditActionOptions(actions);
      } catch {
        setAuditActionOptions([]);
      }
    })();
  }, []);

  function closeModal() {
    setModal(null);
    setErr(null);
  }

  function openCreateUser() {
    setUsername("");
    setPassword("");
    setEmail("");
    setRole("viewer");
    setErr(null);
    setModal("createUser");
  }

  function openChangePassword() {
    setCurPw("");
    setNewPw("");
    setErr(null);
    setModal("changePassword");
  }

  function openCreateApiKey() {
    setKeyName("");
    setNewKey(null);
    setErr(null);
    setModal("createApiKey");
  }

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/users", {
        method: "POST",
        json: {
          username,
          password,
          email: email.trim() || null,
          roles: [role],
        },
      });
      closeModal();
      await loadUsers();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/auth/password", {
        method: "POST",
        json: { current_password: curPw, new_password: newPw },
      });
      closeModal();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api<{ key: string }>("/api-keys", {
        method: "POST",
        json: { name: keyName },
      });
      setNewKey(r.key);
      setKeyName("");
      await loadAccount();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function revokeKey(id: string) {
    if (!confirm("Revoke this API key?")) return;
    setErr(null);
    try {
      await api(`/api-keys/${id}`, { method: "DELETE" });
      await loadAccount();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Administration</h1>
          <p className="lead">
            Manage users and API keys, change your password, and review the security audit log.
          </p>
        </div>
      </header>

      {err && !modal && !auditDetail ? <p className="error">{err}</p> : null}

      {me ? (
        <section className="panel">
          <div className="panel__head">
            <h2>Your account</h2>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            <strong>{me.username}</strong>
            <span className="muted"> ({me.roles.join(", ")})</span>
          </p>
          <div className="btn-row" style={{ marginTop: 0 }}>
            <button type="button" onClick={openChangePassword}>
              Change password
            </button>
            <button type="button" onClick={openCreateApiKey}>
              Create API key
            </button>
          </div>
          {keys.length > 0 ? (
            <ul className="key-list">
              {keys.map((k) => (
                <li key={k.id}>
                  <span>
                    {k.name}
                    <span className="muted">, created {k.created_at}</span>
                    {k.last_used_at ? <span className="muted">, last used {k.last_used_at}</span> : null}
                  </span>
                  <button type="button" className="secondary" onClick={() => void revokeKey(k.id)}>
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">No API keys yet.</p>
          )}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel__head">
          <h2>Users</h2>
          <button type="button" onClick={openCreateUser}>
            Create user
          </button>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Active</th>
                <th>Roles</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.username}</td>
                  <td>{u.email ?? "—"}</td>
                  <td>{u.is_active ? "yes" : "no"}</td>
                  <td>{u.roles.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Audit log</h2>
        </div>
        <div className="audit-filters">
          <div className="audit-toolbar">
            <div className="audit-toolbar__field">
              <label htmlFor="audit-action-type">Action type</label>
              <select
                id="audit-action-type"
                value={auditActionType}
                onChange={(e) => setAuditActionType(e.target.value)}
              >
                <option value="">Any</option>
                {auditActionOptions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="audit-toolbar__field">
              <label htmlFor="audit-user">User</label>
              <select
                id="audit-user"
                value={auditActorId}
                onChange={(e) => setAuditActorId(e.target.value)}
              >
                <option value="">Any</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <AuditDateRangeCalendar value={auditDateRange} onChange={setAuditDateRange} />
        </div>
        <p className="hint audit-hint">
          {auditLoadingInitial
            ? "Loading…"
            : auditTotal === 0
              ? "No matching entries."
              : `Showing ${auditItems.length} of ${auditTotal} (newest first). Scroll to load more.`}
        </p>
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {auditItems.map((a) => (
                <tr
                  key={a.id}
                  className="audit-row"
                  tabIndex={0}
                  onClick={() => setAuditDetail(a)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setAuditDetail(a);
                    }
                  }}
                >
                  <td className="audit-table__time">{formatAuditTs(a.ts)}</td>
                  <td className="mono audit-table__action">{a.action}</td>
                  <td className="audit-table__actor">
                    {a.actor_username ?? "—"}
                    <span className="muted"> ({a.actor_kind})</span>
                  </td>
                  <td className="muted audit-table__summary">{auditEntrySummary(a)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div ref={auditSentinelRef} className="audit-sentinel" aria-hidden />
        {auditLoadingMore ? <p className="hint audit-loading-more">Loading more…</p> : null}
      </section>

      <Modal open={modal === "createUser"} title="Create user" onClose={closeModal}>
        {err ? <p className="error">{err}</p> : null}
        <p className="hint" style={{ marginTop: 0 }}>
          Viewers can query, browse batches, and export. Managers can also ingest files, edit tags, and run bulk tag
          jobs.
        </p>
        <form onSubmit={createUser}>
          <div className="field">
            <label htmlFor="adm-user">Username</label>
            <input id="adm-user" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="adm-pw">Password</label>
            <input
              id="adm-pw"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <div className="field">
            <label htmlFor="adm-email">Email (optional)</label>
            <input id="adm-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="adm-role">Role</label>
            <select id="adm-role" value={role} onChange={(e) => setRole(e.target.value as "viewer" | "manager")}>
              <option value="viewer">Viewer</option>
              <option value="manager">Manager</option>
            </select>
          </div>
          <div className="btn-row">
            <button type="submit">Create user</button>
            <button type="button" className="secondary" onClick={closeModal}>
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={modal === "changePassword"} title="Change password" onClose={closeModal}>
        {err ? <p className="error">{err}</p> : null}
        <form onSubmit={changePassword}>
          <div className="field">
            <label htmlFor="pw-cur">Current password</label>
            <input
              id="pw-cur"
              type="password"
              value={curPw}
              onChange={(e) => setCurPw(e.target.value)}
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
            <button type="button" className="secondary" onClick={closeModal}>
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={auditDetail !== null} title="Audit entry" onClose={() => setAuditDetail(null)} wide>
        {auditDetail ? (
          <div className="audit-detail">
            <dl className="audit-detail__dl">
              <dt>Time</dt>
              <dd>{formatAuditTs(auditDetail.ts)}</dd>
              <dt>Action</dt>
              <dd>{auditDetail.action}</dd>
              <dt>Actor</dt>
              <dd>
                {auditDetail.actor_username ?? "—"}
                <span className="muted"> ({auditDetail.actor_kind})</span>
              </dd>
              <dt>Target</dt>
              <dd className="muted">
                {auditDetail.target_kind ?? "—"}
                {auditDetail.target_id ? `: ${auditDetail.target_id}` : ""}
              </dd>
              <dt>IP</dt>
              <dd className="mono muted">{auditDetail.ip ?? "—"}</dd>
              <dt>User agent</dt>
              <dd className="mono muted" style={{ wordBreak: "break-word" }}>
                {auditDetail.user_agent ?? "—"}
              </dd>
              <dt>Details</dt>
              <dd>
                <pre className="audit-detail__json mono">{JSON.stringify(auditDetail.details, null, 2)}</pre>
              </dd>
            </dl>
          </div>
        ) : null}
      </Modal>

      <Modal open={modal === "createApiKey"} title="Create API key" onClose={closeModal}>
        {err ? <p className="error">{err}</p> : null}
        {newKey ? (
          <>
            <div className="field">
              <div className="label-row">
                <label htmlFor="new-key-plain">New key (copy now)</label>
                <DocTip text="The server never shows this secret again. Copy it into a password manager or env file before you close this dialog." />
              </div>
              <textarea id="new-key-plain" readOnly rows={2} value={newKey} />
            </div>
            <div className="btn-row">
              <button type="button" onClick={closeModal}>
                Done
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={createKey}>
            <div className="field">
              <label htmlFor="key-name">Key name</label>
              <input id="key-name" value={keyName} onChange={(e) => setKeyName(e.target.value)} required />
            </div>
            <div className="btn-row">
              <button type="submit">Create key</button>
              <button type="button" className="secondary" onClick={closeModal}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}

function fmtDetailValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
