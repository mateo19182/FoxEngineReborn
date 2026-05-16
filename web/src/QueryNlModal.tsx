import { useState } from "react";
import { api } from "./api";
import { DocTip } from "./DocTip";
import { Modal } from "./Modal";

type QueryNlResponse = {
  ok: boolean;
  dsl: string | null;
  error: string | null;
  attempted: string | null;
};

type QueryNlModalProps = {
  open: boolean;
  onClose: () => void;
  onApplyDsl: (dsl: string) => void;
};

export function QueryNlModal({ open, onClose, onApplyDsl }: QueryNlModalProps) {
  const [nl, setNl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [translating, setTranslating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function reset() {
    setNl("");
    setMsg(null);
    setErr(null);
    setTranslating(false);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function translate() {
    const text = nl.trim();
    if (!text) return;
    setErr(null);
    setMsg(null);
    setTranslating(true);
    try {
      const data = await api<QueryNlResponse>("/query/nl", {
        method: "POST",
        json: { nl: text },
      });
      if (data.ok && data.dsl) {
        onApplyDsl(data.dsl);
        setMsg("DSL was copied to the query form. Review it there, then Run.");
      } else {
        const bits = [data.error ?? "Could not translate this request."];
        if (data.attempted) bits.push(`Attempted: ${data.attempted}`);
        setMsg(bits.join(" "));
      }
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setTranslating(false);
    }
  }

  return (
    <Modal open={open} title="Natural language to DSL" onClose={handleClose} wide>
      <p className="hint" style={{ marginTop: 0 }}>
        Describe the search in plain language. The configured OpenAI-compatible model returns DSL only; it is
        validated before use. See <code>docs/LLM.md</code>.
      </p>
      <div className="field">
        <div className="label-row">
          <label htmlFor="nl-q">Question</label>
          <DocTip text="Example: outlook.com emails with tag smoke-tag" />
        </div>
        <textarea
          id="nl-q"
          rows={4}
          value={nl}
          onChange={(e) => setNl(e.target.value)}
          placeholder="e.g. Spanish phone numbers from last year’s breach tag"
        />
      </div>
      {err ? <p className="error">{err}</p> : null}
      {msg ? <p className="hint">{msg}</p> : null}
      <div className="btn-row">
        <button type="button" disabled={!nl.trim() || translating} onClick={() => void translate()}>
          {translating ? "Translating…" : "Translate"}
        </button>
        <button type="button" className="secondary" onClick={handleClose}>
          Done
        </button>
      </div>
    </Modal>
  );
}
