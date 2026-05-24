import { Fragment, useEffect, useMemo, useState } from "react";
import {
  api,
  createSavedView,
  deleteSavedView,
  listSavedViews,
  patchSavedView,
  type QueryView,
  type SavedView,
} from "./api";
import { DslHelpModal } from "./DslHelpModal";
import { ExportModal } from "./ExportModal";
import { ConfirmModal } from "./ConfirmModal";
import { Modal } from "./Modal";
import { QueryNlModal } from "./QueryNlModal";
import { SavedViewsModal } from "./SavedViewsModal";
import { TagAddModal } from "./TagAddModal";
import { TagFamiliesModal } from "./TagFamiliesModal";
import { TagsModal } from "./TagsModal";
import { appendTagFamilyFilter, appendTagFilter } from "./queryDsl";
import { applySavedViewToQuery } from "./querySavedViewUtils";

type QueryResponse = {
  total: number;
  total_exact?: boolean;
  rows: Record<string, unknown>[];
  limit: number;
  offset: number;
  view: string;
};

function formatTotal(res: QueryResponse): string {
  const n = res.total.toLocaleString();
  if (res.total_exact === false) return `${n}+`;
  return n;
}

type Tag = {
  id: string;
  name: string;
  family: string | null;
  breach_date: string | null;
};

type Me = { roles: string[]; llm_nl_enabled?: boolean };

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
  const [familiesOpen, setFamiliesOpen] = useState(false);
  const [tagsModalOpen, setTagsModalOpen] = useState(false);
  const [savedViewsOpen, setSavedViewsOpen] = useState(false);
  const [dslHelpOpen, setDslHelpOpen] = useState(false);
  const [nlModalOpen, setNlModalOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [detailRowIndex, setDetailRowIndex] = useState<number | null>(null);
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [selectedSavedViewId, setSelectedSavedViewId] = useState("");
  const [pendingDeleteTagId, setPendingDeleteTagId] = useState<string | null>(null);
  const [removingTagId, setRemovingTagId] = useState<string | null>(null);
  const [confirmSavedViewDeleteOpen, setConfirmSavedViewDeleteOpen] = useState(false);
  const [deletingSavedView, setDeletingSavedView] = useState(false);

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

  async function loadPageData() {
    const [t, m, views] = await Promise.all([
      api<Tag[]>("/tags"),
      api<Me>("/auth/me"),
      listSavedViews(),
    ]);
    setTags(t);
    setMe(m);
    setSavedViews(views);
    setSelectedSavedViewId((prev) => {
      if (!views.length) return "";
      if (prev && views.some((v) => v.id === prev)) return prev;
      return views[0]!.id;
    });
  }

  useEffect(() => {
    void loadPageData().catch((e) => setErr(String(e)));
  }, []);

  function applyTagFilter(tagName: string) {
    setDsl((prev) => appendTagFilter(prev, tagName));
  }

  function applyFamilyFilter(familyCode: string) {
    setDsl((prev) => appendTagFamilyFilter(prev, familyCode));
  }

  function requestRemoveTag(id: string) {
    setPendingDeleteTagId(id);
  }

  async function confirmRemoveTag() {
    if (!pendingDeleteTagId) return;
    setErr(null);
    setRemovingTagId(pendingDeleteTagId);
    try {
      await api(`/tags/${pendingDeleteTagId}`, { method: "DELETE" });
      setPendingDeleteTagId(null);
      await loadPageData();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setRemovingTagId(null);
    }
  }

  const selectedSavedView = savedViews.find((item) => item.id === selectedSavedViewId) ?? null;

  async function saveCurrentView(name: string) {
    if (!name) {
      setErr("Saved view name is required.");
      return;
    }
    setErr(null);
    try {
      const created = await createSavedView({ name, dsl, view });
      await loadPageData();
      setSelectedSavedViewId(created.id);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  function loadSelectedSavedView() {
    if (!selectedSavedView) return;
    const next = applySavedViewToQuery(selectedSavedView);
    setErr(null);
    setExportMsg(null);
    setDsl(next.dsl);
    setView(next.view);
  }

  async function updateSelectedSavedView() {
    if (!selectedSavedView) return;
    setErr(null);
    try {
      await patchSavedView(selectedSavedView.id, { dsl, view });
      await loadPageData();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function renameSelectedSavedViewByName(name: string) {
    if (!selectedSavedView) return;
    if (!name) {
      setErr("Saved view name is required.");
      return;
    }
    setErr(null);
    try {
      await patchSavedView(selectedSavedView.id, { name });
      await loadPageData();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function requestDeleteSelectedSavedView() {
    if (!selectedSavedView) return;
    setConfirmSavedViewDeleteOpen(true);
  }

  async function confirmDeleteSelectedSavedView() {
    if (!selectedSavedView) return;
    setErr(null);
    setDeletingSavedView(true);
    try {
      await deleteSavedView(selectedSavedView.id);
      setConfirmSavedViewDeleteOpen(false);
      await loadPageData();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setDeletingSavedView(false);
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
    err && !addTagOpen && !dslHelpOpen && !tagsModalOpen && !savedViewsOpen && !nlModalOpen ? (
      <p className="error">{err}</p>
    ) : null;

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
                <button type="button" className="link-btn" onClick={() => setSavedViewsOpen(true)}>
                  Saved views
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
              ? `Total DSL matches: ${formatTotal(res)}. Showing ${res.rows.length} linked row(s).`
              : `Total matching: ${formatTotal(res)}. Showing ${res.rows.length} row(s).`}{" "}
            View: {res.view}.
            {res.total_exact === false ? " Count capped for speed; export still returns all matches." : null}
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
        onApplyFamily={applyFamilyFilter}
        onRemoveTag={requestRemoveTag}
        isAdmin={!!isAdmin}
        canWrite={!!canWrite}
        onAddTag={() => setAddTagOpen(true)}
        onManageFamilies={() => setFamiliesOpen(true)}
        error={err}
      />
      <TagAddModal open={addTagOpen} onClose={() => setAddTagOpen(false)} onCreated={loadPageData} />
      <TagFamiliesModal open={familiesOpen} onClose={() => setFamiliesOpen(false)} onChanged={loadPageData} />
      <SavedViewsModal
        open={savedViewsOpen}
        onClose={() => setSavedViewsOpen(false)}
        savedViews={savedViews}
        selectedSavedViewId={selectedSavedViewId}
        onSelectSavedView={setSelectedSavedViewId}
        onCreate={saveCurrentView}
        onLoadSelected={loadSelectedSavedView}
        onUpdateSelected={updateSelectedSavedView}
        onRenameSelected={renameSelectedSavedViewByName}
        onDeleteSelected={requestDeleteSelectedSavedView}
        error={err}
      />
      <ConfirmModal
        open={pendingDeleteTagId !== null}
        title="Delete tag"
        message="Delete this tag?"
        confirmLabel="Delete tag"
        pending={removingTagId !== null}
        onConfirm={() => void confirmRemoveTag()}
        onCancel={() => {
          if (removingTagId) return;
          setPendingDeleteTagId(null);
        }}
      />
      <ConfirmModal
        open={confirmSavedViewDeleteOpen}
        title="Delete saved view"
        message={selectedSavedView ? `Delete saved view "${selectedSavedView.name}"?` : "Delete selected saved view?"}
        confirmLabel="Delete saved view"
        pending={deletingSavedView}
        onConfirm={() => void confirmDeleteSelectedSavedView()}
        onCancel={() => {
          if (deletingSavedView) return;
          setConfirmSavedViewDeleteOpen(false);
        }}
      />
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
