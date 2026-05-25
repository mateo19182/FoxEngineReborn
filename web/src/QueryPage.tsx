import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  createSavedView,
  deleteSavedView,
  listSavedViews,
  listDslFields,
  listTagFamilies,
  patchSavedView,
  type DslField,
  type QueryView,
  type SavedView,
  type TagFamily,
} from "./api";
import { DslTextarea } from "./DslTextarea";
import { DslHelpModal } from "./DslHelpModal";
import { ExportModal } from "./ExportModal";
import { ConfirmModal } from "./ConfirmModal";
import { Modal } from "./Modal";
import { QueryNlModal } from "./QueryNlModal";
import { SavedViewsModal } from "./SavedViewsModal";
import { applyQueryDslAppend, type QueryLocationState } from "./queryNavigation";
import {
  detailLabel,
  formatDetailValue,
  populatedDetailKeys,
  type ResultsLayout,
  type TagLookup,
  visibleResultColumns,
} from "./queryResultsDisplay";
import { QueryResultsBody } from "./QueryResultsBody";
import { applySavedViewToQuery } from "./querySavedViewUtils";

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
  family: string | null;
  breach_date: string | null;
};

type Me = { roles: string[]; llm_nl_enabled?: boolean };

const QUERY_PAGE = 50;

export function QueryPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [dsl, setDsl] = useState("");
  const [view, setView] = useState<QueryView>("rows");
  const [res, setRes] = useState<QueryResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMoreResults, setHasMoreResults] = useState(false);
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  const queryFetchingRef = useRef(false);
  const queryNextOffsetRef = useRef(0);
  const queryTotalRef = useRef(0);
  const querySentinelRef = useRef<HTMLDivElement | null>(null);

  const [tags, setTags] = useState<Tag[]>([]);
  const [families, setFamilies] = useState<TagFamily[]>([]);
  const [dslFields, setDslFields] = useState<DslField[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [savedViewsOpen, setSavedViewsOpen] = useState(false);
  const [dslHelpOpen, setDslHelpOpen] = useState(false);
  const [nlModalOpen, setNlModalOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [detailRowIndex, setDetailRowIndex] = useState<number | null>(null);
  const [resultsLayout, setResultsLayout] = useState<ResultsLayout>("table");
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [selectedSavedViewId, setSelectedSavedViewId] = useState("");
  const [confirmSavedViewDeleteOpen, setConfirmSavedViewDeleteOpen] = useState(false);
  const [deletingSavedView, setDeletingSavedView] = useState(false);

  const tagLookup = useMemo<TagLookup>(() => new Map(tags.map((t) => [t.id, t])), [tags]);

  const resultColumns = useMemo(() => {
    if (!res?.rows.length) return [];
    return visibleResultColumns(res.rows, { relatedView: res.view === "related" });
  }, [res]);

  const detailKeys = useMemo(() => {
    if (detailRowIndex === null || !res?.rows[detailRowIndex]) return [];
    return populatedDetailKeys(res.rows[detailRowIndex]);
  }, [res, detailRowIndex]);

  useEffect(() => {
    setDetailRowIndex(null);
  }, [res]);

  const nlUi = me?.llm_nl_enabled !== false;

  async function loadPageData() {
    const [t, f, fields, m, views] = await Promise.all([
      api<Tag[]>("/tags"),
      listTagFamilies(),
      listDslFields(),
      api<Me>("/auth/me"),
      listSavedViews(),
    ]);
    setTags(t);
    setFamilies(f);
    setDslFields(fields);
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

  useEffect(() => {
    const state = location.state as QueryLocationState | null;
    if (!state?.dslAppend) return;
    setDsl((prev) => applyQueryDslAppend(prev, state.dslAppend!));
    setErr(null);
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

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

  const fetchResults = useCallback(
    async (reset: boolean) => {
      if (queryFetchingRef.current) return;
      if (!reset && queryNextOffsetRef.current >= queryTotalRef.current) return;

      queryFetchingRef.current = true;
      const offset = reset ? 0 : queryNextOffsetRef.current;
      if (reset) {
        queryNextOffsetRef.current = 0;
        setHasMoreResults(false);
        setErr(null);
        setExportMsg(null);
        setLoading(true);
      } else {
        setLoadingMore(true);
      }

      try {
        const data = await api<QueryResponse>("/query", {
          method: "POST",
          json: { dsl, limit: QUERY_PAGE, offset, view },
        });
        queryTotalRef.current = data.total;
        if (data.rows.length === 0) {
          queryNextOffsetRef.current = data.total;
        } else {
          queryNextOffsetRef.current = data.offset + data.limit;
        }
        setHasMoreResults(queryNextOffsetRef.current < data.total);
        if (reset) {
          setRes(data);
        } else {
          setRes((prev) => {
            if (!prev) return data;
            const seen = new Set(prev.rows.map((row) => rowKey(row)));
            const merged = [...prev.rows];
            for (const row of data.rows) {
              const key = rowKey(row);
              if (!seen.has(key)) {
                seen.add(key);
                merged.push(row);
              }
            }
            return { ...prev, total: data.total, rows: merged, view: data.view };
          });
        }
      } catch (ex) {
        setErr(String(ex));
      } finally {
        queryFetchingRef.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [dsl, view],
  );

  async function executeQuery() {
    await fetchResults(true);
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    await executeQuery();
  }

  useEffect(() => {
    if (!res || loading) return;
    const el = querySentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        void fetchResults(false);
      },
      { root: null, rootMargin: "200px", threshold: 0 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [fetchResults, hasMoreResults, loading, res]);

  useLayoutEffect(() => {
    const el = querySentinelRef.current;
    if (!el || !res || loading || queryFetchingRef.current) return;
    if (queryNextOffsetRef.current >= queryTotalRef.current) return;
    const rect = el.getBoundingClientRect();
    const vh = window.innerHeight || document.documentElement.clientHeight;
    if (rect.top < vh + 240) {
      void fetchResults(false);
    }
  }, [fetchResults, hasMoreResults, loading, res?.rows.length]);

  const panelErr = err && !dslHelpOpen && !savedViewsOpen && !nlModalOpen ? <p className="error">{err}</p> : null;

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
                <Link to="/tags" className="link-btn">
                  Tags
                </Link>
                <button type="button" className="link-btn" onClick={() => setSavedViewsOpen(true)}>
                  Saved views
                </button>
              </span>
            </div>
            <DslTextarea
              id="q-dsl"
              rows={4}
              value={dsl}
              onChange={setDsl}
              onRun={() => void executeQuery()}
              tags={tags}
              families={families}
              fields={dslFields}
            />
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
            <div className="panel__head-actions">
              {res.rows.length > 0 ? (
                <div
                  className="query-view-switch query-view-switch--toolbar"
                  role="group"
                  aria-label="Results layout"
                >
                  <button
                    type="button"
                    className={resultsLayout === "table" ? "query-view-switch__active" : undefined}
                    aria-pressed={resultsLayout === "table"}
                    onClick={() => setResultsLayout("table")}
                  >
                    Table
                  </button>
                  <button
                    type="button"
                    className={resultsLayout === "cards" ? "query-view-switch__active" : undefined}
                    aria-pressed={resultsLayout === "cards"}
                    onClick={() => setResultsLayout("cards")}
                  >
                    Cards
                  </button>
                </div>
              ) : null}
              {res.total > 0 ? (
                <button type="button" className="secondary" onClick={() => setExportOpen(true)}>
                  Export…
                </button>
              ) : null}
            </div>
          </div>
          {exportMsg ? <p className="hint">{exportMsg}</p> : null}
          <p className="hint" style={{ marginTop: 0 }}>
            {res.view === "related"
              ? `Total DSL matches: ${res.total}. Showing ${res.rows.length} linked row(s)`
              : `Total matching: ${res.total}. Showing ${res.rows.length} row(s)`}
            {hasMoreResults ? " (scroll for more)" : ""}. View: {res.view}.
          </p>
          {res.rows.length > 0 ? (
            <>
              <QueryResultsBody
                rows={res.rows}
                columns={resultColumns}
                layout={resultsLayout}
                tagLookup={tagLookup}
                relatedView={res.view === "related"}
                activeIndex={detailRowIndex}
                onSelectRow={setDetailRowIndex}
                rowKey={rowKey}
                rowClassName={rowClassName}
              />
              {hasMoreResults ? <div ref={querySentinelRef} className="audit-sentinel" aria-hidden /> : null}
              {loadingMore ? <p className="hint audit-loading-more">Loading more…</p> : null}
              <p className="hint" style={{ marginTop: "0.65rem", marginBottom: 0 }}>
                Click a {resultsLayout === "cards" ? "card" : "row"} for all populated fields.
              </p>
            </>
          ) : (
            <p className="hint" style={{ marginTop: "0.65rem", marginBottom: 0 }}>
              No rows in this preview.
            </p>
          )}
        </section>
      ) : null}

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
            Row {detailRowIndex + 1} of {res.rows.length} loaded (view {res.view}).
          </p>
          <dl className="row-detail-dl">
            {detailKeys.map((k) => (
              <Fragment key={k}>
                <dt>{detailLabel(k)}</dt>
                <dd>{formatDetailValue(k, res.rows[detailRowIndex][k], tagLookup)}</dd>
              </Fragment>
            ))}
          </dl>
        </Modal>
      ) : null}
    </div>
  );
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
