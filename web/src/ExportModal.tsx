import { useEffect, useState } from "react";
import { api } from "./api";
import { Modal } from "./Modal";

type ExportModalProps = {
  open: boolean;
  onClose: () => void;
  dsl: string;
  onQueued: (jobId: string) => void;
};

export function ExportModal({ open, onClose, dsl, onQueued }: ExportModalProps) {
  const [format, setFormat] = useState<"csv" | "jsonl">("csv");
  const [limitStr, setLimitStr] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFormat("csv");
    setLimitStr("");
    setErr(null);
    setBusy(false);
  }, [open]);

  function handleClose() {
    setErr(null);
    setBusy(false);
    onClose();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const t = limitStr.trim();
    let row_limit: number | undefined;
    if (t) {
      const n = Number(t);
      if (!Number.isInteger(n) || n < 1) {
        setErr("Row limit must be a positive integer.");
        return;
      }
      row_limit = n;
    }
    setBusy(true);
    try {
      const payload: { dsl: string; format: "csv" | "jsonl"; row_limit?: number } = { dsl, format };
      if (row_limit !== undefined) payload.row_limit = row_limit;
      const { job_id } = await api<{ job_id: string }>("/export", {
        method: "POST",
        json: payload,
      });
      onQueued(job_id);
      handleClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="Export leads" onClose={handleClose}>
      <form onSubmit={submit}>
        <p className="hint" style={{ marginTop: 0 }}>
          Queues a background job that streams every row matching the current DSL (not only the preview page). Download
          from Jobs when the job is done. The server applies its own maximum row cap even if you leave the limit blank.
        </p>
        <div className="field">
          <div className="label-row">
            <span>Format</span>
          </div>
          <div className="export-format-switch" role="group" aria-label="Export file format">
            <button
              type="button"
              className={format === "csv" ? "export-format-switch__active" : undefined}
              aria-pressed={format === "csv"}
              title="Comma-separated values; best for spreadsheets"
              onClick={() => setFormat("csv")}
            >
              CSV
            </button>
            <button
              type="button"
              className={format === "jsonl" ? "export-format-switch__active" : undefined}
              aria-pressed={format === "jsonl"}
              title="Newline-delimited JSON; one object per line"
              onClick={() => setFormat("jsonl")}
            >
              JSONL
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="export-limit">Max leads (optional)</label>
          <input
            id="export-limit"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="All matches up to server cap"
            value={limitStr}
            onChange={(e) => setLimitStr(e.target.value)}
          />
        </div>
        {err ? <p className="error">{err}</p> : null}
        <div className="btn-row">
          <button type="submit" disabled={busy || !dsl.trim()}>
            {busy ? "Queueing…" : "Queue export"}
          </button>
          <button type="button" className="secondary" onClick={handleClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
