import { useState } from "react";
import {
  createTagFamily,
  deleteTagFamily,
  patchTagFamily,
  type TagFamily,
} from "./api";
import { ConfirmModal } from "./ConfirmModal";

export type FamilyFilter = "all" | "unassigned" | string;

type TagFamiliesAsideProps = {
  families: TagFamily[];
  familyFilter: FamilyFilter;
  onSelectFamily: (filter: FamilyFilter) => void;
  counts: { all: number; unassigned: number; byCode: Map<string, number> };
  canWrite: boolean;
  onChanged: () => void | Promise<void>;
  onError: (message: string | null) => void;
};

export function TagFamiliesAside({
  families,
  familyFilter,
  onSelectFamily,
  counts,
  canWrite,
  onChanged,
  onError,
}: TagFamiliesAsideProps) {
  const [newCode, setNewCode] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editCode, setEditCode] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function addFamily(e: React.FormEvent) {
    e.preventDefault();
    const code = newCode.trim();
    if (!code) return;
    onError(null);
    setCreating(true);
    try {
      await createTagFamily({ code });
      setNewCode("");
      await onChanged();
    } catch (ex) {
      onError(String(ex));
    } finally {
      setCreating(false);
    }
  }

  async function saveRename(familyId: string) {
    const code = editCode.trim();
    if (!code) return;
    onError(null);
    try {
      await patchTagFamily(familyId, { code });
      setEditingId(null);
      setEditCode("");
      await onChanged();
    } catch (ex) {
      onError(String(ex));
    }
  }

  async function confirmDelete() {
    if (!pendingDeleteId) return;
    onError(null);
    setDeletingId(pendingDeleteId);
    try {
      await deleteTagFamily(pendingDeleteId);
      setPendingDeleteId(null);
      if (familyFilter !== "all" && familyFilter !== "unassigned") {
        const deleted = families.find((f) => f.id === pendingDeleteId);
        if (deleted?.code === familyFilter) onSelectFamily("all");
      }
      await onChanged();
    } catch (ex) {
      onError(String(ex));
    } finally {
      setDeletingId(null);
    }
  }

  const navItems: { id: FamilyFilter; label: string; count: number }[] = [
    { id: "all", label: "All tags", count: counts.all },
  ];
  for (const family of families) {
    navItems.push({
      id: family.code,
      label: family.code,
      count: counts.byCode.get(family.code) ?? 0,
    });
  }
  if (counts.unassigned > 0) {
    navItems.push({ id: "unassigned", label: "No family", count: counts.unassigned });
  }

  return (
    <>
      <nav className="tags-aside__nav" aria-label="Families">
        <ul>
          {navItems.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={
                  familyFilter === item.id ? "tags-aside__nav-btn tags-aside__nav-btn--active" : "tags-aside__nav-btn"
                }
                onClick={() => onSelectFamily(item.id)}
              >
                <span className="tags-aside__nav-label">{item.label}</span>
                <span className="tags-aside__nav-count">{item.count}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {canWrite ? (
        <>
          <ul className="tags-aside__manage">
            {families.map((family) => (
              <li key={family.id} className="tags-aside__manage-row">
                {editingId === family.id ? (
                  <form
                    className="tags-aside__edit"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void saveRename(family.id);
                    }}
                  >
                    <input
                      value={editCode}
                      onChange={(e) => setEditCode(e.target.value)}
                      aria-label={`Rename ${family.code}`}
                      autoFocus
                    />
                    <button type="submit">Save</button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setEditingId(null);
                        setEditCode("");
                      }}
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <code>{family.code}</code>
                    <span className="tags-aside__manage-actions">
                      <button
                        type="button"
                        className="link-btn"
                        onClick={() => {
                          setEditingId(family.id);
                          setEditCode(family.code);
                        }}
                      >
                        Rename
                      </button>
                      <button type="button" className="link-btn" onClick={() => setPendingDeleteId(family.id)}>
                        Delete
                      </button>
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
          <form className="tags-aside__add" onSubmit={addFamily}>
            <input
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              placeholder="New family code"
              aria-label="New family code"
            />
            <button type="submit" disabled={creating}>
              {creating ? "Adding…" : "Add"}
            </button>
          </form>
        </>
      ) : null}

      <ConfirmModal
        open={pendingDeleteId !== null}
        title="Delete family"
        message="Delete this family? Tags keep their names but lose this family code."
        confirmLabel="Delete"
        pending={deletingId !== null}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (deletingId) return;
          setPendingDeleteId(null);
        }}
      />
    </>
  );
}
