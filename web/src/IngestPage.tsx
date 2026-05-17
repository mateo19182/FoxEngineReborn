import { useState } from "react";
import { Link } from "react-router-dom";
import { getToken } from "./api";
import { DocTip } from "./DocTip";

type FormatOpt = "auto" | "jsonl" | "csv" | "combo";

type IngestItem = {
  batch_id: string;
  job_id: string;
  inner_name: string;
  format: string;
  detect_confidence?: number;
};

type IngestResponse = {
  batch_id?: string;
  job_id?: string;
  items: IngestItem[];
};

export function IngestPage() {
  const [format, setFormat] = useState<FormatOpt>("auto");
  const [mergeArchive, setMergeArchive] = useState(false);
  const [tagNames, setTagNames] = useState("");
  const [batchName, setBatchName] = useState("");
  const [columnMapJson, setColumnMapJson] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function preview(e?: React.MouseEvent) {
    e?.preventDefault();
    setErr(null);
    setPreviewText(null);
    if (!file) {
      setErr("Choose a file for preview");
      return;
    }
    const token = getToken();
    if (!token) {
      setErr("Not logged in");
      return;
    }
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("merge_archive", mergeArchive ? "true" : "false");
      const r = await fetch("/api/ingest/preview", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const text = await r.text();
      if (!r.ok) throw new Error(text || r.statusText);
      const data = JSON.parse(text) as unknown;
      setPreviewText(JSON.stringify(data, null, 2));
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!file) {
      setErr("Choose a file");
      return;
    }
    const token = getToken();
    if (!token) {
      setErr("Not logged in");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("format", format);
      fd.append("tag_names", tagNames);
      fd.append("merge_archive", mergeArchive ? "true" : "false");
      if (batchName.trim()) fd.append("batch_name", batchName.trim());
      if (columnMapJson.trim()) {
        fd.append("column_map_json", columnMapJson.trim());
      }
      const r = await fetch("/api/ingest/file", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const text = await r.text();
      if (!r.ok) {
        let detail = text;
        try {
          const j = JSON.parse(text) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const data = JSON.parse(text) as IngestResponse;
      const items = data.items ?? [];
      if (items.length === 1) {
        setMsg(`Queued job ${items[0].job_id} (${items[0].format}). Check Jobs.`);
      } else {
        setMsg(`Queued ${items.length} ingest jobs. First job ${items[0]?.job_id}. Check Jobs.`);
      }
      setFile(null);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Ingest file</h1>
          <p className="lead">
            Operator uploads. Supports JSONL, CSV, combo lines, and common archives with optional detection preview.
          </p>
        </div>
      </header>

      <section className="panel">
        <p className="hint" style={{ marginTop: 0 }}>
          Supports JSONL, CSV (sniffed delimiter), email:password lines (combo), and archives (.zip, .tar / .tar.gz, .gz, .7z). Use
          format <strong>auto</strong> for detection. Each archive member becomes its own batch unless you merge.
        </p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="ing-file">File</label>
            <input id="ing-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </div>
          <div className="field">
            <label htmlFor="ing-format">Format</label>
            <select id="ing-format" value={format} onChange={(e) => setFormat(e.target.value as FormatOpt)}>
              <option value="auto">auto (detect)</option>
              <option value="jsonl">jsonl</option>
              <option value="csv">csv</option>
              <option value="combo">combo (email:password lines)</option>
            </select>
          </div>
          <div className="field">
            <div className="label-row">
              <span>Merge archive</span>
              <DocTip text="When on, all files inside an archive are concatenated into one ingest with section headers instead of one job per member." />
            </div>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", fontWeight: 400 }}>
              <input type="checkbox" checked={mergeArchive} onChange={(e) => setMergeArchive(e.target.checked)} />
              <span>
                Merge all files from archive into one ingest (concatenated with section headers)
              </span>
            </label>
          </div>
          <div className="field">
            <label htmlFor="ing-tags">Tag names (comma-separated, created if missing)</label>
            <input id="ing-tags" value={tagNames} onChange={(e) => setTagNames(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ing-batch">Batch name (optional)</label>
            <input id="ing-batch" value={batchName} onChange={(e) => setBatchName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ing-map">Column map JSON (optional CSV override)</label>
            <textarea
              id="ing-map"
              rows={3}
              value={columnMapJson}
              onChange={(e) => setColumnMapJson(e.target.value)}
              placeholder='{"Email":"email","user":"username"}'
            />
          </div>
          {err ? <p className="error">{err}</p> : null}
          {msg ? <p className="hint">{msg}</p> : null}
          <div className="btn-row">
            <button type="button" className="secondary" onClick={(e) => preview(e)}>
              Preview detection
            </button>
            <span className="btn-with-tip">
              <button type="submit" disabled={loading}>
                {loading ? "Uploading…" : "Upload and queue ingest"}
              </button>
              <DocTip text="Parsing runs asynchronously. Archives usually spawn one job per file unless merge is enabled; follow progress under Jobs and Batches." />
            </span>
          </div>
        </form>
      </section>

      {previewText ? (
        <section className="panel">
          <div className="panel__head">
            <h2>Preview JSON</h2>
          </div>
          <pre className="code-block">{previewText}</pre>
        </section>
      ) : null}
    </div>
  );
}
