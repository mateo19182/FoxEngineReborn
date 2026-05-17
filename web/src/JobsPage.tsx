import { useEffect, useState } from "react";
import { api, getToken } from "./api";
import { DocTip } from "./DocTip";

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
  if (!r.ok) throw new Error(await r.text());
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
          <div className="panel__head">
            <h2>Queue</h2>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>File</th>
                  <th>Accepted</th>
                  <th>Rejected</th>
                  <th>Dup</th>
                  <th>State</th>
                  <th>Rows</th>
                  <th>Error</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{j.batch_name ?? (j.type !== "ingest" ? j.id.slice(0, 8) : "")}</td>
                    <td>{j.source_filename ?? ""}</td>
                    <td>{j.accepted_rows ?? 0}</td>
                    <td>{j.rejected_rows ?? 0}</td>
                    <td>{j.duplicate_rows ?? 0}</td>
                    <td>{j.state}</td>
                    <td>{j.processed_rows}</td>
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
                      ) : j.type === "ingest" && j.batch_id && j.rejected_rows && j.rejected_rows > 0 ? (
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
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}