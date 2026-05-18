import { useEffect, useState } from "react";
import { createTagFamily, deleteTagFamily, listTagFamilies, patchTagFamily, type TagFamily } from "./api";
import { ConfirmModal } from "./ConfirmModal";
import { Modal } from "./Modal";

type TagFamiliesModalProps = {
  open: boolean;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

export function TagFamiliesModal({ open, onClose, onChanged }: TagFamiliesModalProps) {
  const [families, setFamilies] = useState<TagFamily[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [newCode, setNewCode] = useState("");
  const [editCode, setEditCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pendingDeleteFamilyId, setPendingDeleteFamilyId] = useState<string | null>(null);
  const [deletingFamilyId, setDeletingFamilyId] = useState<string | null>(null);

  async function refreshFamilies() {
    setLoading(true);
    try {
      const rows = await listTagFamilies();
      setFamilies(rows);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    setErr(null);
    setNewCode("");
    setEditingId(null);
    setEditCode("");
    setPendingDeleteFamilyId(null);
    setDeletingFamilyId(null);
    void refreshFamilies();
  }, [open]);

  async function createFamily(e: React.FormEvent) {
    e.preventDefault();
    if (!newCode.trim()) return;
    setErr(null);
    setCreating(true);
    try {
      await createTagFamily({ code: newCode.trim() });
      setNewCode("");
      await refreshFamilies();
      await onChanged();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setCreating(false);
    }
  }

  async function saveEdit(familyId: string) {
    if (!editCode.trim()) return;
    setErr(null);
    try {
      await patchTagFamily(familyId, { code: editCode.trim() });
      setEditingId(null);
      setEditCode("");
      await refreshFamilies();
      await onChanged();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  function requestRemoveFamily(familyId: string) {
    setPendingDeleteFamilyId(familyId);
  }

  async function confirmRemoveFamily() {
    if (!pendingDeleteFamilyId) return;
    setErr(null);
    setDeletingFamilyId(pendingDeleteFamilyId);
    try {
      await deleteTagFamily(pendingDeleteFamilyId);
      setPendingDeleteFamilyId(null);
      await refreshFamilies();
      await onChanged();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setDeletingFamilyId(null);
    }
  }

  return (
    <Modal open={open} title="Manage tag families" onClose={onClose}>
      {err ? <p className="error">{err}</p> : null}
      <p className="hint" style={{ marginTop: 0 }}>
        Families are reusable codes for DSL filters like <code>tag.family:YOUR_FAMILY</code>.
      </p>
      <form className="tag-family-create" onSubmit={createFamily}>
        <input
          value={newCode}
          onChange={(e) => setNewCode(e.target.value)}
          placeholder="New family code (example: DATA_LEAK)"
          aria-label="New family code"
          required
        />
        <button type="submit" disabled={creating}>
          {creating ? "Creating..." : "Add family"}
        </button>
      </form>
      <div className="tag-family-list">
        {loading ? (
          <p className="hint">Loading families...</p>
        ) : families.length > 0 ? (
          <ul>
            {families.map((family) => (
              <li key={family.id}>
                {editingId === family.id ? (
                  <>
                    <input
                      value={editCode}
                      onChange={(e) => setEditCode(e.target.value)}
                      aria-label={`Edit family ${family.code}`}
                    />
                    <button type="button" onClick={() => void saveEdit(family.id)}>
                      Save
                    </button>
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
                  </>
                ) : (
                  <>
                    <code>{family.code}</code>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setEditingId(family.id);
                        setEditCode(family.code);
                      }}
                    >
                      Rename
                    </button>
                    <button type="button" className="secondary" onClick={() => requestRemoveFamily(family.id)}>
                      Delete
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">No families yet. Add one to start organizing tags.</p>
        )}
      </div>
      <div className="btn-row">
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
      <ConfirmModal
        open={pendingDeleteFamilyId !== null}
        title="Delete family"
        message="Delete this family? Tags linked to it will keep their type but lose the family."
        confirmLabel="Delete family"
        pending={deletingFamilyId !== null}
        onConfirm={() => void confirmRemoveFamily()}
        onCancel={() => {
          if (deletingFamilyId) return;
          setPendingDeleteFamilyId(null);
        }}
      />
    </Modal>
  );
}
