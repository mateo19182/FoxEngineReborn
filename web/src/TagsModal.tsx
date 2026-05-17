import { useEffect, useMemo, useState } from "react";
import { Modal } from "./Modal";

export type TagRow = {
  id: string;
  name: string;
  type: string | null;
  family: string | null;
};

type TagsModalProps = {
  open: boolean;
  onClose: () => void;
  tags: TagRow[];
  onApplyTag: (name: string) => void;
  onRemoveTag: (id: string) => void;
  isAdmin: boolean;
  canWrite: boolean;
  onAddTag: () => void;
  error: string | null;
};

export function TagsModal({
  open,
  onClose,
  tags,
  onApplyTag,
  onRemoveTag,
  isAdmin,
  canWrite,
  onAddTag,
  error,
}: TagsModalProps) {
  const [tagFilter, setTagFilter] = useState("");

  useEffect(() => {
    if (!open) setTagFilter("");
  }, [open]);

  const filteredTags = useMemo(() => {
    const q = tagFilter.trim().toLowerCase();
    if (!q) return tags;
    return tags.filter((t) => t.name.toLowerCase().includes(q));
  }, [tags, tagFilter]);

  return (
    <Modal open={open} title="Tags" onClose={onClose} wide>
      <div className="tags-modal">
        {error ? <p className="error">{error}</p> : null}
        <p className="tags-modal__hint hint">Click a tag to append <code>tag:name</code> to the DSL.</p>
        <div className="tag-filter-row">
          <label htmlFor="tags-modal-filter">Search</label>
          <div className="tag-filter-row__input">
            <input
              id="tags-modal-filter"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="Filter by name…"
              autoComplete="off"
            />
          </div>
        </div>
        {filteredTags.length > 0 ? (
          <div className="tag-chips-scroll tag-chips-scroll--modal">
            <ul className="tag-chips">
              {filteredTags.map((t) => (
                <li key={t.id} className="tag-chip-item">
                  <button type="button" className="tag-chip" onClick={() => onApplyTag(t.name)} title={`Add tag:${t.name}`}>
                    <span className="tag-chip__label">
                      {t.name}
                      {(() => {
                        const meta =
                          t.type && t.family ? `${t.type} (${t.family})` : (t.type ?? t.family ?? "");
                        return meta ? <span className="muted"> · {meta}</span> : null;
                      })()}
                    </span>
                  </button>
                  {isAdmin ? (
                    <button
                      type="button"
                      className="tag-chip__remove secondary"
                      aria-label={`Delete ${t.name}`}
                      onClick={() => onRemoveTag(t.id)}
                    >
                      ×
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="hint">{tags.length === 0 ? "No tags yet." : "No tags match your search."}</p>
        )}
        {canWrite ? (
          <div className="tags-modal__footer">
            <button type="button" onClick={onAddTag}>
              Add tag
            </button>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
