import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { DslHelpModal } from "./DslHelpModal";
import { ExportModal } from "./ExportModal";
import { Modal } from "./Modal";
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
  family: string | null;
  breach_date: string | null;
};

type Me = { roles: string[]; llm_nl_enabled?: boolean };

type QueryView = "rows" | "related";

export function QueryPage() {
  const [dsl, setDsl] = useState("email:*@example.com");
  const [view, setView] = useState<QueryView>("rows");
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
  const [exportOpen, setExportOpen] = useState(false);
  const [detailRowIndex, setDetailRowIndex] = useState<number | null>(null);

  const columns = useMemo(() => {
    if (!res?.rows.length) return [];
    const keys = new Set<string>();
    for (const r of res.rows) {
      for (const k of Object.keys(r)) keys.add(k);
    }
    return Array.from(keys).toSorted();
  }, [res]);

  const detailKeys = useMemo(() => {
    if (detailRowIndex === null || !res?.rows[detailRowIndex]) return [];
    return Object.keys(res.rows[detailRowIndex]).toSorted();
  }, [res, detailRowIndex]);

  useEffect(() => {
    setDetailRowIndex(null);
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
          {panelErr}
          <div className="btn-row query-actions">
            <button type="submit" disabled={loading}>
              {loading ? "Running…" : "Run"}
            </button>
            <div className="query-actions__view">
              <span className="query-actions__view-label" id="q-view-label">
                View
              </span>
              <div
                className="query-view-switch query-view-switch--toolbar"
                role="group"
                aria-labelledby="q-view-label"
              >
                <button
                  type="button"
                  className={view === "rows" ? "query-view-switch__active" : undefined}
                  aria-pressed={view === "rows"}
                  title="One table row per stored lead"
                  onClick={() => setView("rows")}
                >
                  Rows
                </button>
                <button
                  type="button"
                  className={view === "related" ? "query-view-switch__active" : undefined}
                  aria-pressed={view === "related"}
                  title="DSL matches plus rows sharing email, phone, username, or id card"
                  onClick={() => setView("related")}
                >
                  Related
                </button>
              </div>
            </div>
          </div>
          <p className="hint query-actions__hint">
            Related keeps raw rows and groups DSL matches with rows sharing email, phone, username, or id card.
          </p>
        </form>
      </section>

      {res ? (
        <section className="panel">
          <div className="panel__head">
            <h2>Results</h2>
            {res.total > 0 ? (
              <button type="button" className="secondary" onClick={() => setExportOpen(true)}>
                Export…
              </button>
            ) : null}
          </div>
          {exportMsg ? <p className="hint">{exportMsg}</p> : null}
          <p className="hint" style={{ marginTop: 0 }}>
            {res.view === "related"
              ? `Total DSL matches: ${res.total}. Showing ${res.rows.length} linked row(s).`
              : `Total matching: ${res.total}. Showing ${res.rows.length} row(s).`}{" "}
            View: {res.view}.
          </p>
          {res.rows.length > 0 ? (
            <>
              <div className="results-table-wrap">
                <table className="results-table">
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {res.rows.map((r, i) => (
                      <tr
                        key={rowKey(r)}
                        className={rowClassName(r, detailRowIndex === i)}
                        tabIndex={0}
                        onClick={() => setDetailRowIndex(i)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setDetailRowIndex(i);
                          }
                        }}
                      >
                        {columns.map((c) => (
                          <td key={c}>{fmt(r[c])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="hint" style={{ marginTop: "0.65rem", marginBottom: 0 }}>
                Click a row for full fields and values.
              </p>
            </>
          ) : (
            <p className="hint" style={{ marginTop: "0.65rem", marginBottom: 0 }}>
              No rows in this preview.
            </p>
          )}
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
      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        dsl={dsl}
        onQueued={(jobId) => {
          setErr(null);
          setExportMsg(`Export job ${jobId} queued. Open Jobs to download when state is done.`);
        }}
      />
      {res && detailRowIndex !== null && res.rows[detailRowIndex] ? (
        <Modal
          open
          wide
          title="Row detail"
          onClose={() => setDetailRowIndex(null)}
        >
          <p className="hint" style={{ marginTop: 0 }}>
            View {detailRowIndex + 1} of {res.rows.length} in this preview (offset {res.offset}, view {res.view}).
          </p>
          <dl className="row-detail-dl">
            {detailKeys.map((k) => (
              <Fragment key={k}>
                <dt>{k}</dt>
                <dd>{fmt(res.rows[detailRowIndex][k])}</dd>
              </Fragment>
            ))}
          </dl>
        </Modal>
      ) : null}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function rowClassName(row: Record<string, unknown>, active: boolean): string | undefined {
  const classes = [];
  if (active) classes.push("results-table__row--active");
  if (row._related_is_match === false) classes.push("results-table__row--related-only");
  return classes.length ? classes.join(" ") : undefined;
}

function rowKey(row: Record<string, unknown>): string {
  return `${String(row.batch_id)}:${String(row.row_in_batch)}`;
}
