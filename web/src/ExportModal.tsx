import { useEffect, useState } from "react";
import { api } from "./api";
import { Modal } from "./Modal";

type ExportModalProps = {
  open: boolean;
  onClose: () => void;
  dsl: string;
  onQueued: (jobId: string) => void;
};

const EXPORT_COLUMNS = [
  { id: "batch_id", label: "Batch ID" },
  { id: "row_in_batch", label: "Row in batch" },
  { id: "ingest_ts", label: "Ingested" },
  { id: "phone_norm", label: "Phone normalized" },
  { id: "phone_raw", label: "Phone raw" },
  { id: "email_norm", label: "Email normalized" },
  { id: "email_raw", label: "Email raw" },
  { id: "email_local", label: "Email local" },
  { id: "email_domain", label: "Email domain" },
  { id: "username", label: "Username" },
  { id: "id_card", label: "ID card" },
  { id: "full_name", label: "Full name" },
  { id: "first_name", label: "First name" },
  { id: "last_name", label: "Last name" },
  { id: "dob", label: "DOB" },
  { id: "gender", label: "Gender" },
  { id: "address", label: "Address" },
  { id: "city", label: "City" },
  { id: "country", label: "Country" },
  { id: "zip", label: "ZIP" },
  { id: "ip", label: "IP" },
  { id: "user_agent", label: "User agent" },
  { id: "isp", label: "ISP" },
  { id: "phone_carrier", label: "Carrier" },
  { id: "password", label: "Password" },
  { id: "password_hash", label: "Password hash" },
  { id: "last_seen", label: "Last seen" },
  { id: "extras", label: "Extras" },
] as const;

const ALL_EXPORT_COLUMN_IDS = EXPORT_COLUMNS.map((column) => column.id);

export function ExportModal({ open, onClose, dsl, onQueued }: ExportModalProps) {
  const [format, setFormat] = useState<"csv" | "jsonl">("csv");
  const [limitStr, setLimitStr] = useState("");
  const [selectedColumns, setSelectedColumns] = useState<string[]>(ALL_EXPORT_COLUMN_IDS);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFormat("csv");
    setLimitStr("");
    setSelectedColumns(ALL_EXPORT_COLUMN_IDS);
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
    if (selectedColumns.length === 0) {
      setErr("Choose at least one column.");
      return;
    }
    setBusy(true);
    try {
      const payload: {
        dsl: string;
        format: "csv" | "jsonl";
        row_limit?: number;
        columns: string[];
      } = { dsl, format, columns: selectedColumns };
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

  function toggleColumn(columnId: string) {
    setSelectedColumns((prev) => {
      if (prev.includes(columnId)) return prev.filter((id) => id !== columnId);
      return ALL_EXPORT_COLUMN_IDS.filter((id) => id === columnId || prev.includes(id));
    });
  }

  return (
    <Modal open={open} title="Export leads" onClose={handleClose} wide>
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
        <div className="field">
          <div className="label-row">
            <span>Columns</span>
            <span className="export-columns-count">
              {selectedColumns.length}/{EXPORT_COLUMNS.length}
            </span>
            <div className="label-row__tools">
              <button
                type="button"
                className="link-btn"
                onClick={() => setSelectedColumns(ALL_EXPORT_COLUMN_IDS)}
                disabled={busy || selectedColumns.length === EXPORT_COLUMNS.length}
              >
                Select all
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={() => setSelectedColumns([])}
                disabled={busy || selectedColumns.length === 0}
              >
                Clear
              </button>
            </div>
          </div>
          <div className="export-columns-grid">
            {EXPORT_COLUMNS.map((column) => (
              <label key={column.id} className="export-column-option">
                <input
                  type="checkbox"
                  checked={selectedColumns.includes(column.id)}
                  onChange={() => toggleColumn(column.id)}
                  disabled={busy}
                />
                <span>{column.label}</span>
              </label>
            ))}
          </div>
        </div>
        {err ? <p className="error">{err}</p> : null}
        <div className="btn-row">
          <button type="submit" disabled={busy}>
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
