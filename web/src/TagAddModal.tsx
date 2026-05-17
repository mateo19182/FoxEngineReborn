import { useEffect, useState } from "react";
import { api, getToken, onUnauthorized } from "./api";
import { DocTip } from "./DocTip";
import { Modal } from "./Modal";

type AddMode = "manual" | "bulk";

type TagTaxonomy = {
  types: { code: string; family: string }[];
  families: { code: string; types: string[] }[];
};

type TagAddModalProps = {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
};

export function TagAddModal({ open, onClose, onCreated }: TagAddModalProps) {
  const [addMode, setAddMode] = useState<AddMode>("manual");
  const [name, setName] = useState("");
  const [tagType, setTagType] = useState("");
  const [taxonomy, setTaxonomy] = useState<TagTaxonomy | null>(null);
  const [bulkTags, setBulkTags] = useState("");
  const [bulkFile, setBulkFile] = useState<File | null>(null);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function reset() {
    setAddMode("manual");
    setName("");
    setTagType("");
    setBulkTags("");
    setBulkFile(null);
    setBulkMsg(null);
    setErr(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  useEffect(() => {
    if (!open) return;
    void api<TagTaxonomy>("/tags/taxonomy")
      .then(setTaxonomy)
      .catch(() => setTaxonomy(null));
  }, [open]);

  async function createManual(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/tags", {
        method: "POST",
        json: { name, ...(tagType ? { type: tagType } : {}) },
      });
      await onCreated();
      handleClose();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function bulkSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBulkMsg(null);
    if (!bulkFile) {
      setErr("Choose a CSV file");
      return;
    }
    const token = getToken();
    if (!token) {
      setErr("Not logged in");
      return;
    }
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
      setBulkMsg(`Queued job ${data.job_id}. Open Jobs to download unmatched rows when finished.`);
      setBulkFile(null);
      await onCreated();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <Modal open={open} title="Add tag" onClose={handleClose}>
      {err ? <p className="error">{err}</p> : null}
      <div className="mode-tabs">
        <button
          type="button"
          className={addMode === "manual" ? "mode-tabs__active" : "secondary"}
          onClick={() => {
            setAddMode("manual");
            setErr(null);
            setBulkMsg(null);
          }}
        >
          Manual
        </button>
        <button
          type="button"
          className={addMode === "bulk" ? "mode-tabs__active" : "secondary"}
          onClick={() => {
            setAddMode("bulk");
            setErr(null);
            setBulkMsg(null);
          }}
        >
          Bulk CSV
        </button>
      </div>

      {addMode === "manual" ? (
        <form onSubmit={createManual}>
          <div className="field">
            <label htmlFor="tag-name">Name</label>
            <input id="tag-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="tag-type">Type</label>
            <select id="tag-type" value={tagType} onChange={(e) => setTagType(e.target.value)}>
              <option value="">None</option>
              {taxonomy?.types.map((row) => (
                <option key={row.code} value={row.code}>
                  {row.code} ({row.family})
                </option>
              ))}
            </select>
            {!taxonomy ? <p className="hint" style={{ marginTop: "0.35rem" }}>Taxonomy unavailable.</p> : null}
          </div>
          <div className="btn-row">
            <button type="submit">Create</button>
            <button type="button" className="secondary" onClick={handleClose}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="hint" style={{ marginTop: 0 }}>
            CSV with columns such as email, phone, username, or id_card. Comma-separated tag names to apply.
          </p>
          <form onSubmit={bulkSubmit}>
            <div className="field">
              <label htmlFor="bulk-tags">Tag names (comma-separated)</label>
              <input id="bulk-tags" value={bulkTags} onChange={(e) => setBulkTags(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="bulk-csv">CSV file</label>
              <input
                id="bulk-csv"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setBulkFile(e.target.files?.[0] ?? null)}
                required
              />
            </div>
            <div className="btn-row">
              <span className="btn-with-tip">
                <button type="submit">Queue bulk apply</button>
                <DocTip text="Runs in the background. When the job finishes, use Jobs to download rows that did not match any lead." />
              </span>
              <button type="button" className="secondary" onClick={handleClose}>
                {bulkMsg ? "Done" : "Cancel"}
              </button>
            </div>
          </form>
          {bulkMsg ? <p className="hint">{bulkMsg}</p> : null}
        </>
      )}
    </Modal>
  );
}
