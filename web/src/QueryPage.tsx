import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { DocTip } from "./DocTip";
import { DslHelpModal } from "./DslHelpModal";
import { QueryNlModal } from "./QueryNlModal";
import { TagAddModal } from "./TagAddModal";
import { TagsModal } from "./TagsModal";
import { appendTagFilter } from "./queryDsl";

type QueryResponse = {
  total: number;
  rows: Record<string, unknown>[];
  limit: number;
  offset: number;
  view: string;
};

type Tag = {
  id: string;
  name: string;
  type: string | null;
  breach_date: string | null;
};

type Me = { roles: string[]; llm_nl_enabled?: boolean };

export function QueryPage() {
  const [dsl, setDsl] = useState("email:*@example.com");
  const [view, setView] = useState<"rows" | "merged">("rows");
  const [res, setRes] = useState<QueryResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  const [tags, setTags] = useState<Tag[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [addTagOpen, setAddTagOpen] = useState(false);
  const [tagsModalOpen, setTagsModalOpen] = useState(false);
  const [dslHelpOpen, setDslHelpOpen] = useState(false);
  const [nlModalOpen, setNlModalOpen] = useState(false);

  const columns = useMemo(() => {
    if (!res?.rows.length) return [];
    const keys = new Set<string>();
    for (const r of res.rows) {
      for (const k of Object.keys(r)) keys.add(k);
    }
    return [...keys].sort();
  }, [res]);

  const canWrite = me?.roles.some((r) => r === "admin" || r === "operator" || r === "manager");
  const isAdmin = me?.roles.includes("admin");
  const nlUi = me?.llm_nl_enabled !== false;

  async function loadTags() {
    const [t, m] = await Promise.all([api<Tag[]>("/tags"), api<Me>("/auth/me")]);
    setTags(t);
    setMe(m);
  }

  useEffect(() => {
    void loadTags().catch((e) => setErr(String(e)));
  }, []);

  function applyTagFilter(tagName: string) {
    setDsl((prev) => appendTagFilter(prev, tagName));
  }

  async function removeTag(id: string) {
    if (!confirm("Delete this tag?")) return;
    setErr(null);
    try {
      await api(`/tags/${id}`, { method: "DELETE" });
      await loadTags();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setExportMsg(null);
    setLoading(true);
    try {
      const data = await api<QueryResponse>("/query", {
        method: "POST",
        json: { dsl, limit: 50, offset: 0, view },
      });
      setRes(data);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }

  async function exportResults(fmt: "csv" | "jsonl") {
    setErr(null);
    setExportMsg(null);
    try {
      const { job_id } = await api<{ job_id: string }>("/export", {
        method: "POST",
        json: { dsl, format: fmt },
      });
      setExportMsg(`Export job ${job_id} queued. Open Jobs to download when state is done.`);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  const panelErr =
    err && !addTagOpen && !dslHelpOpen && !tagsModalOpen && !nlModalOpen ? <p className="error">{err}</p> : null;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Query</h1>
          <p className="lead">
            Search leads with the DSL, filter by tags, and preview results. Heavy exports always go through Jobs.
          </p>
        </div>
      </header>

      <section className="panel">
        <form onSubmit={run}>
          <div className="field">
            <div className="label-row">
              <label htmlFor="q-dsl">DSL</label>
              <span className="label-row__tools">
                {nlUi ? (
                  <button type="button" className="link-btn" onClick={() => setNlModalOpen(true)}>
                    Natural language
                  </button>
                ) : null}
                <button type="button" className="link-btn" onClick={() => setDslHelpOpen(true)}>
                  DSL reference
                </button>
                <button type="button" className="link-btn" onClick={() => setTagsModalOpen(true)}>
                  Tags
                </button>
              </span>
            </div>
            <textarea id="q-dsl" rows={4} value={dsl} onChange={(e) => setDsl(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="q-view">View</label>
            <select id="q-view" value={view} onChange={(e) => setView(e.target.value as "rows" | "merged")}>
              <option value="rows">Per-row (raw leads)</option>
              <option value="merged">Merged profile (by identity_key)</option>
            </select>
          </div>
          {panelErr}
          {exportMsg ? <p className="hint">{exportMsg}</p> : null}
          <div className="btn-row">
            <button type="submit" disabled={loading}>
              {loading ? "Running…" : "Run"}
            </button>
            <span className="btn-with-tip">
              <button type="button" className="secondary" disabled={!dsl.trim()} onClick={() => exportResults("csv")}>
                Export CSV (job)
              </button>
              <button type="button" className="secondary" disabled={!dsl.trim()} onClick={() => exportResults("jsonl")}>
                Export JSONL (job)
              </button>
              <DocTip text="Queues a background export of every row matching the DSL (not the 50-row preview). Track the job and download from Jobs when it finishes." />
            </span>
          </div>
        </form>
      </section>

      {res ? (
        <section className="panel">
          <div className="panel__head">
            <h2>Results</h2>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            Total matching: {res.total}. Showing {res.rows.length} row(s). View: {res.view}.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {res.rows.map((r, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c}>{fmt(r[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <TagsModal
        open={tagsModalOpen}
        onClose={() => setTagsModalOpen(false)}
        tags={tags}
        onApplyTag={applyTagFilter}
        onRemoveTag={(id) => void removeTag(id)}
        isAdmin={!!isAdmin}
        canWrite={!!canWrite}
        onAddTag={() => setAddTagOpen(true)}
        error={err}
      />
      <TagAddModal open={addTagOpen} onClose={() => setAddTagOpen(false)} onCreated={loadTags} />
      <DslHelpModal open={dslHelpOpen} onClose={() => setDslHelpOpen(false)} />
      <QueryNlModal
        open={nlModalOpen}
        onClose={() => setNlModalOpen(false)}
        onApplyDsl={(next) => {
          setDsl(next);
          setErr(null);
        }}
      />
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
