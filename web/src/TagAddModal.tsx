import { useEffect, useState } from "react";
import { api, getToken, onUnauthorized, type TagFamily } from "./api";
import { DocTip } from "./DocTip";
import { Modal } from "./Modal";

type AddMode = "single" | "csv";

type TagAddModalProps = {
  open: boolean;
  onClose: () => void;
  families: TagFamily[];
  defaultFamily: string;
  onCreated: () => void | Promise<void>;
  onBulkQueued: (message: string) => void;
};

export function TagAddModal({
  open,
  onClose,
  families,
  defaultFamily,
  onCreated,
  onBulkQueued,
}: TagAddModalProps) {
  const [mode, setMode] = useState<AddMode>("single");
  const [name, setName] = useState("");
  const [family, setFamily] = useState("");
  const [bulkTags, setBulkTags] = useState("");
  const [bulkFile, setBulkFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function reset() {
    setMode("single");
    setName("");
    setFamily(defaultFamily);
    setBulkTags("");
    setBulkFile(null);
    setErr(null);
    setPending(false);
  }

  function handleClose() {
    reset();
    onClose();
  }

  useEffect(() => {
    if (!open) return;
    setFamily(defaultFamily);
    setErr(null);
  }, [open, defaultFamily]);

  async function submitSingle(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setErr(null);
    setPending(true);
    try {
      await api("/tags", {
        method: "POST",
        json: {
          name: trimmed,
          ...(family ? { family } : {}),
        },
      });
      await onCreated();
      handleClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setPending(false);
    }
  }

  async function submitCsv(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!bulkFile) {
      setErr("Choose a CSV file");
      return;
    }
    const token = getToken();
    if (!token) {
      setErr("Not logged in");
      return;
    }
    setPending(true);
    try {
      const fd = new FormData();
      fd.append("file", bulkFile);
      fd.append("tag_names", bulkTags);
      const r = await fetch("/api/tags/bulk-apply", {
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
        onUnauthorized(r.status, true);
        throw new Error(detail);
      }
      const data = JSON.parse(text) as { job_id: string };
      await onCreated();
      onBulkQueued(`Job ${data.job_id} queued. Check Jobs when it finishes.`);
      handleClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal open={open} title="Add tag" onClose={handleClose}>
      {err ? <p className="error">{err}</p> : null}
      <div className="mode-tabs">
        <button
          type="button"
          className={mode === "single" ? "mode-tabs__active" : "secondary"}
          onClick={() => {
            setMode("single");
            setErr(null);
          }}
        >
          Single tag
        </button>
        <button
          type="button"
          className={mode === "csv" ? "mode-tabs__active" : "secondary"}
          onClick={() => {
            setMode("csv");
            setErr(null);
          }}
        >
          CSV import
        </button>
      </div>

      {mode === "single" ? (
        <form onSubmit={submitSingle}>
          <div className="field">
            <label htmlFor="tag-add-name">Name</label>
            <input
              id="tag-add-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tag name"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tag-add-family">Family</label>
            <select id="tag-add-family" value={family} onChange={(e) => setFamily(e.target.value)}>
              <option value="">None</option>
              {families.map((f) => (
                <option key={f.id} value={f.code}>
                  {f.code}
                </option>
              ))}
            </select>
          </div>
          <div className="btn-row">
            <button type="submit" disabled={pending}>
              {pending ? "Adding…" : "Create"}
            </button>
            <button type="button" className="secondary" onClick={handleClose}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={submitCsv}>
          <p className="hint" style={{ marginTop: 0 }}>
            CSV with email, phone, username, or id_card. Comma-separated tag names to apply to matching rows.
          </p>
          <div className="field">
            <label htmlFor="tag-add-bulk-names">Tag names</label>
            <input
              id="tag-add-bulk-names"
              value={bulkTags}
              onChange={(e) => setBulkTags(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tag-add-bulk-file">CSV file</label>
            <input
              id="tag-add-bulk-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setBulkFile(e.target.files?.[0] ?? null)}
              required
            />
          </div>
          <div className="btn-row">
            <span className="btn-with-tip">
              <button type="submit" disabled={pending}>
                {pending ? "Queuing…" : "Queue job"}
              </button>
              <DocTip text="Runs in the background. Download unmatched rows from Jobs when done." />
            </span>
            <button type="button" className="secondary" onClick={handleClose}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
