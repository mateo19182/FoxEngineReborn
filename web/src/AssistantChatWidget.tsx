import { useEffect, useRef, useState } from "react";
import "./assistantChat.css";
import { getToken } from "./api";

type Turn = { role: "user" | "assistant"; content: string };

const STORAGE_KEY = "foxengine_assistant_transcript_v1";

function isValidTurn(t: Turn): boolean {
  return t.content.trim().length > 0;
}

function loadTurnsFromStorage(): Turn[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    const out: Turn[] = [];
    for (const row of data) {
      if (!row || typeof row !== "object") continue;
      const r = row as Record<string, unknown>;
      if (r.role !== "user" && r.role !== "assistant") continue;
      if (typeof r.content !== "string") continue;
      const turn: Turn = { role: r.role, content: r.content };
      if (isValidTurn(turn)) out.push(turn);
    }
    return out;
  } catch {
    return [];
  }
}

export function AssistantChatWidget() {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>(loadTurnsFromStorage);
  const [streamBuf, setStreamBuf] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [waitingStream, setWaitingStream] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(turns.filter(isValidTurn)));
    } catch {
      /* quota or private mode */
    }
  }, [turns]);

  useEffect(() => {
    if (!open) return;
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, streamBuf, open, busy, waitingStream]);

  function newConversation() {
    abortRef.current?.abort();
    abortRef.current = null;
    setTurns([]);
    setStreamBuf("");
    setDraft("");
    setBusy(false);
    setWaitingStream(false);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    const messages: Turn[] = [...turns, { role: "user" as const, content: text }].filter(isValidTurn);
    setTurns(messages);
    setStreamBuf("");
    setBusy(true);
    setWaitingStream(true);

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const token = getToken();
    let assembled = "";

    try {
      const res = await fetch("/api/assistant/chat/stream", {
        method: "POST",
        signal: ac.signal,
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ messages }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let carry = "";
      let finished = false;

      const processPayload = (payload: string): boolean => {
        if (payload === "[DONE]") {
          setWaitingStream(false);
          if (assembled.trim().length > 0) {
            setTurns((prev) => [...prev, { role: "assistant", content: assembled.trim() }]);
            assembled = "";
          }
          setStreamBuf("");
          return true;
        }
        let ev: { type?: string; text?: string; message?: string };
        try {
          ev = JSON.parse(payload) as { type?: string; text?: string; message?: string };
        } catch {
          return false;
        }
        if (ev.type === "delta" && typeof ev.text === "string" && ev.text.length > 0) {
          assembled += ev.text;
          setWaitingStream(false);
          setStreamBuf(assembled);
          return false;
        }
        if (ev.type === "error") {
          setWaitingStream(false);
          const msg = typeof ev.message === "string" ? ev.message : "Request failed";
          setTurns((prev) => [...prev, { role: "assistant", content: msg }]);
          assembled = "";
          setStreamBuf("");
          return true;
        }
        if (ev.type === "done") {
          setWaitingStream(false);
          const body = assembled.trim().length > 0 ? assembled : "(No text returned.)";
          setTurns((prev) => [...prev, { role: "assistant", content: body }]);
          assembled = "";
          setStreamBuf("");
          return true;
        }
        return false;
      };

      const feedCarry = (chunk: string) => {
        carry += chunk;
        const lines = carry.split("\n");
        carry = lines.pop() ?? "";
        for (const raw of lines) {
          const trimmed = raw.replace(/\r$/, "").trim();
          if (!trimmed.startsWith("data:")) continue;
          const payload = trimmed.slice(5).trim();
          if (processPayload(payload)) {
            finished = true;
            return;
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (value) {
          feedCarry(decoder.decode(value, { stream: true }));
        }
        if (finished) {
          await reader.cancel().catch(() => {});
          break;
        }
        if (done) {
          if (carry.trim()) {
            const tailLines = carry.split("\n");
            for (const raw of tailLines) {
              const trimmed = raw.replace(/\r$/, "").trim();
              if (!trimmed.startsWith("data:")) continue;
              if (processPayload(trimmed.slice(5).trim())) {
                finished = true;
                break;
              }
            }
            carry = "";
          }
          break;
        }
      }

      if (!finished && assembled.trim().length > 0) {
        setWaitingStream(false);
        setTurns((prev) => [...prev, { role: "assistant", content: assembled.trim() }]);
        setStreamBuf("");
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        return;
      }
      setWaitingStream(false);
      setTurns((prev) => [...prev, { role: "assistant", content: `Error: ${String(e)}` }]);
      setStreamBuf("");
    } finally {
      if (abortRef.current === ac) {
        abortRef.current = null;
      }
      setBusy(false);
      setWaitingStream(false);
      setStreamBuf("");
    }
  }

  const showEmptyHint = turns.length === 0 && !streamBuf && !(busy && waitingStream);

  return (
    <div className="assistant-dock" aria-live="polite">
      {open ? (
        <div className="assistant-dock__panel" role="dialog" aria-label="Assistant chat">
          <div className="assistant-dock__head">
            <div>
              <div className="assistant-dock__title">Assistant</div>
              <div className="assistant-dock__subtitle">Jobs, batches, tags · saved locally</div>
            </div>
            <div className="assistant-dock__head-actions">
              <button
                type="button"
                className="secondary assistant-dock__icon-btn"
                onClick={newConversation}
                aria-label="New conversation"
                title="New conversation"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                </svg>
              </button>
              <button type="button" className="secondary assistant-dock__close" onClick={() => setOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div ref={listRef} className="assistant-dock__messages">
            {showEmptyHint ? (
              <p className="muted assistant-dock__empty">
                Ask about jobs, batches, or tags. History is kept until you start a new conversation.
              </p>
            ) : (
              <>
                {turns.map((t, i) => (
                  <div
                    key={`m-${i}`}
                    className={
                      t.role === "user" ? "assistant-dock__msg assistant-dock__msg--user" : "assistant-dock__msg"
                    }
                  >
                    {t.content}
                  </div>
                ))}
                {busy && waitingStream && !streamBuf ? (
                  <div className="assistant-dock__loading" aria-label="Waiting for response">
                    <span className="assistant-dock__spinner" />
                  </div>
                ) : null}
                {streamBuf ? <div className="assistant-dock__msg assistant-dock__streaming">{streamBuf}</div> : null}
              </>
            )}
          </div>
          <div className="assistant-dock__composer">
            <textarea
              rows={2}
              value={draft}
              disabled={busy}
              placeholder="Ask anything…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="assistant-dock__composer-actions">
              <button type="button" disabled={busy || !draft.trim()} onClick={() => void send()}>
                {busy ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <button
        type="button"
        className="assistant-dock__launcher"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? "Close assistant" : "Open assistant"}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </button>
    </div>
  );
}
