import { useEffect, useMemo, useState } from "react";
import { Modal } from "./Modal";

export type TagRow = {
  id: string;
  name: string;
  family: string | null;
};

type TagsModalProps = {
  open: boolean;
  onClose: () => void;
  tags: TagRow[];
  onApplyTag: (name: string) => void;
  onApplyFamily: (familyCode: string) => void;
  onRemoveTag: (id: string) => void;
  isAdmin: boolean;
  canWrite: boolean;
  onAddTag: () => void;
  onManageFamilies: () => void;
  error: string | null;
};

export function TagsModal({
  open,
  onClose,
  tags,
  onApplyTag,
  onApplyFamily,
  onRemoveTag,
  isAdmin,
  canWrite,
  onAddTag,
  onManageFamilies,
  error,
}: TagsModalProps) {
  const [tagFilter, setTagFilter] = useState("");

  useEffect(() => {
    if (!open) setTagFilter("");
  }, [open]);

  const filteredTags = useMemo(() => {
    const q = tagFilter.trim().toLowerCase();
    if (!q) return tags;
    return tags.filter((t) => {
      if (t.name.toLowerCase().includes(q)) return true;
      if (t.family && t.family.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [tags, tagFilter]);

  const groupedTags = useMemo(() => {
    const byFamily = new Map<string, TagRow[]>();
    const unassigned: TagRow[] = [];
    for (const tag of filteredTags) {
      if (!tag.family) {
        unassigned.push(tag);
        continue;
      }
      if (!byFamily.has(tag.family)) byFamily.set(tag.family, []);
      byFamily.get(tag.family)!.push(tag);
    }
    const groups: { family: string | null; items: TagRow[] }[] = Array.from(byFamily.entries())
      .toSorted(([a], [b]) => a.localeCompare(b))
      .map(([family, items]) => ({
        family,
        items: items.toSorted((a, b) => a.name.localeCompare(b.name)),
      }));
    if (unassigned.length) {
      groups.push({
        family: null,
        items: unassigned.toSorted((a, b) => a.name.localeCompare(b.name)),
      });
    }
    return groups;
  }, [filteredTags]);

  return (
    <Modal open={open} title="Tags" onClose={onClose} wide>
      <div className="tags-modal">
        {error ? <p className="error">{error}</p> : null}
        <p className="tags-modal__hint hint">
          Click a family to append <code>tag.family:...</code>, or click a tag for <code>tag:name</code>.
        </p>
        <div className="tag-filter-row">
          <label htmlFor="tags-modal-filter">Search</label>
          <div className="tag-filter-row__input">
            <input
              id="tags-modal-filter"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="Filter by tag or family…"
              autoComplete="off"
            />
          </div>
        </div>
        {groupedTags.length > 0 ? (
          <div className="tag-chips-scroll tag-chips-scroll--modal">
            <div className="tag-family-groups">
              {groupedTags.map((group) => (
                <section
                  key={group.family ?? "__unassigned__"}
                  className="tag-family-group"
                  aria-label={group.family ? `Family ${group.family}` : "No family"}
                >
                  <div className="tag-family-group__head">
                    <strong>{group.family ?? "No family"}</strong>
                    {group.family ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => onApplyFamily(group.family!)}
                        title={`Add tag.family:${group.family}`}
                      >
                        Filter family
                      </button>
                    ) : null}
                  </div>
                  <ul className="tag-chips">
                    {group.items.map((t) => (
                      <li key={t.id} className="tag-chip-item">
                        <button
                          type="button"
                          className="tag-chip"
                          onClick={() => onApplyTag(t.name)}
                          title={`Add tag:${t.name}`}
                        >
                          <span className="tag-chip__label">{t.name}</span>
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
                </section>
              ))}
            </div>
          </div>
        ) : (
          <p className="hint">{tags.length === 0 ? "No tags yet." : "No tags match your search."}</p>
        )}
        {canWrite ? (
          <div className="tags-modal__footer">
            <button type="button" onClick={onAddTag}>
              Add tag
            </button>
            <button type="button" className="secondary" onClick={onManageFamilies}>
              Manage families
            </button>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
