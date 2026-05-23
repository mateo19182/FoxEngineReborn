import { useEffect, useMemo, useState } from "react";
import { api, getToken, onUnauthorized } from "./api";
import { DocTip } from "./DocTip";
import { jobProgressView } from "./jobProgress";
import { ProgressBar } from "./ProgressBar";

function jobTypeLabel(type: string): string {
  switch (type) {
    case "ingest_file":
      return "Ingest";
    case "export":
      return "Export";
    case "bulk_tag":
      return "Bulk tag";
    default:
      return type;
  }
}

function isIngestJob(type: string): boolean {
  return type === "ingest_file";
}

function isExportJob(type: string): boolean {
  return type === "export";
}

function exportDslSummary(checkpoint: Record<string, unknown>): string {
  const dsl = checkpoint.dsl;
  if (typeof dsl !== "string" || !dsl.trim()) return "";
  const oneLine = dsl.replace(/\s+/g, " ").trim();
  return oneLine.length > 48 ? `${oneLine.slice(0, 45)}…` : oneLine;
}

type Job = {
  id: string;
  type: string;
  state: string;
  batch_id: string | null;
  processed_rows: number;
  total_rows: number | null;
  result_uri: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  checkpoint: Record<string, unknown>;
  batch_name: string | null;
  source_filename: string | null;
  accepted_rows: number | null;
  rejected_rows: number | null;
  duplicate_rows: number | null;
  ingest_ts: string | null;
};

async function downloadRejections(batchId: string) {
  const token = getToken();
  if (!token) return;
  const r = await fetch(`/api/batches/${batchId}/rejections.csv`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    const text = await r.text();
    onUnauthorized(r.status, true);
    throw new Error(text);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `rejections-${batchId}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadJob(id: string, filename: string) {
  const token = getToken();
  if (!token) return;
  const r = await fetch(`/api/jobs/${id}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    const t = await r.text();
    onUnauthorized(r.status, true);
    throw new Error(t || r.statusText);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("");

  const typeOptions = useMemo(() => {
    const types = new Set(jobs.map((j) => j.type));
    return [...types].sort((a, b) => jobTypeLabel(a).localeCompare(jobTypeLabel(b)));
  }, [jobs]);

  const filteredJobs = useMemo(
    () => (typeFilter ? jobs.filter((j) => j.type === typeFilter) : jobs),
    [jobs, typeFilter],
  );

  async function load() {
    const j = await api<Job[]>("/jobs");
    setJobs(j);
  }

  useEffect(() => {
    void (async () => {
      try {
        await load();
      } catch (e) {
        setErr(String(e));
      }
    })();
    const id = window.setInterval(() => {
      void (async () => {
        try {
          await load();
        } catch (e) {
          setErr(String(e));
        }
      })();
    }, 3000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Jobs</h1>
          <p className="lead">Background work refreshes every few seconds while this page is open.</p>
        </div>
      </header>

      {err ? <p className="error">{err}</p> : null}

      {jobs.length > 0 && (
        <section className="panel">
          <div className="panel__head" style={{ alignItems: "flex-end", flexWrap: "wrap", gap: "0.75rem 1.1rem" }}>
            <h2>Queue</h2>
            {typeOptions.length > 0 ? (
              <div className="audit-toolbar" style={{ marginBottom: 0, marginLeft: "auto" }}>
                <div className="audit-toolbar__field">
                  <label htmlFor="jobs-type-filter">Kind</label>
                  <select
                    id="jobs-type-filter"
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                  >
                    <option value="">Any</option>
                    {typeOptions.map((t) => (
                      <option key={t} value={t}>
                        {jobTypeLabel(t)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ) : null}
          </div>
          {filteredJobs.length === 0 ? (
            <p className="hint">No jobs match this filter.</p>
          ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>File</th>
                  <th>Accepted</th>
                  <th>Rejected</th>
                  <th>Dup</th>
                  <th>Progress</th>
                  <th>State</th>
                  <th>Error</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((j) => {
                  const progress = jobProgressView(j);
                  const exportJob = isExportJob(j.type);
                  return (
                  <tr key={j.id}>
                    <td>
                      {j.batch_name ??
                        (exportJob ? exportDslSummary(j.checkpoint) || j.id.slice(0, 8) : !isIngestJob(j.type) ? j.id.slice(0, 8) : "")}
                    </td>
                    <td>{jobTypeLabel(j.type)}</td>
                    <td>
                      {exportJob
                        ? (j.checkpoint.format === "jsonl" ? "JSONL" : "CSV")
                        : (j.source_filename ?? "")}
                    </td>
                    <td>{exportJob ? "—" : (j.accepted_rows ?? 0)}</td>
                    <td>{exportJob ? "—" : (j.rejected_rows ?? 0)}</td>
                    <td>{exportJob ? "—" : (j.duplicate_rows ?? 0)}</td>
                    <td className="jobs-progress-cell">
                      <ProgressBar
                        value={progress.mode === "determinate" ? progress.value : null}
                        indeterminate={progress.mode === "indeterminate"}
                        label={progress.label}
                      />
                    </td>
                    <td>{j.state}</td>
                    <td>{j.error ?? ""}</td>
                    <td>
                      {j.state === "done" && j.result_uri ? (
                        <span className="btn-with-tip">
                          <button
                            type="button"
                            className="secondary"
                            onClick={() =>
                              downloadJob(
                                j.id,
                                j.type === "export"
                                  ? `export-${j.id}.${(j.checkpoint.format as string) === "jsonl" ? "jsonl" : "csv"}`
                                  : `download-${j.id}.csv`,
                              ).catch((e) => setErr(String(e)))
                            }
                          >
                            Download
                          </button>
                        </span>
                      ) : isIngestJob(j.type) && j.batch_id && j.rejected_rows && j.rejected_rows > 0 ? (
                        <span className="btn-with-tip">
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => downloadRejections(j.batch_id!).catch((e) => setErr(String(e)))}
                          >
                            Rejections CSV
                          </button>
                          <DocTip text="Rows from this ingest that failed validation." />
                        </span>
                      ) : null}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
        </section>
      )}
    </div>
  );
}