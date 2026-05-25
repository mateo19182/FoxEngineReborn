import { useState } from "react";
import { api } from "./api";

type BatchTagFormProps = {
  batchId: string;
  onQueued?: (jobId: string) => void;
};

export function BatchTagForm({ batchId, onQueued }: BatchTagFormProps) {
  const [tagInput, setTagInput] = useState("");
  const [pending, setPending] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const tag_names = tagInput
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!tag_names.length) {
      setErr("Enter at least one tag name.");
      return;
    }
    setPending(true);
    setErr(null);
    setMsg(null);
    try {
      const res = await api<{ job_id: string }>(`/batches/${batchId}/tags`, {
        method: "POST",
        json: { tag_names },
      });
      setMsg(`Tag job queued (${res.job_id.slice(0, 8)}…).`);
      setTagInput("");
      onQueued?.(res.job_id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="batch-tag-form" onSubmit={(e) => void submit(e)}>
      <label htmlFor={`batch-tags-${batchId}`}>Add tags to all rows in this batch</label>
      <div className="btn-row" style={{ marginTop: "0.35rem", flexWrap: "wrap" }}>
        <input
          id={`batch-tags-${batchId}`}
          type="text"
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          placeholder="tag-one, tag-two"
          disabled={pending}
          style={{ flex: "1 1 12rem", minWidth: "10rem" }}
        />
        <button type="submit" disabled={pending}>
          {pending ? "Queueing…" : "Apply tags"}
        </button>
      </div>
      {err ? <p className="error" style={{ marginTop: "0.5rem" }}>{err}</p> : null}
      {msg ? <p className="hint" style={{ marginTop: "0.5rem" }}>{msg}</p> : null}
    </form>
  );
}
