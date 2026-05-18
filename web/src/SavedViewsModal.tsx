import { useEffect, useMemo, useState } from "react";
import { type SavedView } from "./api";
import { Modal } from "./Modal";

type SavedViewsModalProps = {
  open: boolean;
  onClose: () => void;
  savedViews: SavedView[];
  selectedSavedViewId: string;
  onSelectSavedView: (id: string) => void;
  onCreate: (name: string) => Promise<void>;
  onLoadSelected: () => void;
  onUpdateSelected: () => Promise<void>;
  onRenameSelected: (name: string) => Promise<void>;
  onDeleteSelected: () => Promise<void>;
  error: string | null;
};

export function SavedViewsModal({
  open,
  onClose,
  savedViews,
  selectedSavedViewId,
  onSelectSavedView,
  onCreate,
  onLoadSelected,
  onUpdateSelected,
  onRenameSelected,
  onDeleteSelected,
  error,
}: SavedViewsModalProps) {
  const [busy, setBusy] = useState(false);

  const selectedSavedView = useMemo(
    () => savedViews.find((item) => item.id === selectedSavedViewId) ?? null,
    [savedViews, selectedSavedViewId],
  );

  useEffect(() => {
    if (!open) return;
    setBusy(false);
  }, [open]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Saved views"
      onClose={onClose}
      wide
      headerActions={
        <>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              const nameRaw = prompt("New saved view name");
              if (nameRaw === null) return;
              const name = nameRaw.trim();
              if (!name) return;
              void run(() => onCreate(name));
            }}
          >
            New view
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedSavedView}
            onClick={() => {
              if (!selectedSavedView) return;
              const nameRaw = prompt("Rename saved view", selectedSavedView.name);
              if (nameRaw === null) return;
              const name = nameRaw.trim();
              if (!name) return;
              void run(() => onRenameSelected(name));
            }}
          >
            Rename
          </button>
        </>
      }
    >
      <div className="saved-views-modal">
        {error ? <p className="error">{error}</p> : null}
        <div className="saved-views-modal__toolbar">
          <select
            id="saved-view-select"
            aria-label="Existing saved views"
            value={selectedSavedViewId}
            onChange={(e) => onSelectSavedView(e.target.value)}
            disabled={busy || savedViews.length === 0}
          >
            <option value="">{savedViews.length ? "Select a saved view…" : "No saved views yet"}</option>
            {savedViews.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedSavedView}
            onClick={() => {
              onLoadSelected();
              onClose();
            }}
          >
            Load into query
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedSavedView}
            onClick={() => void run(onUpdateSelected)}
          >
            Update from current query
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedSavedView}
            onClick={() => void run(onDeleteSelected)}
          >
            Delete
          </button>
        </div>

        {selectedSavedView ? (
          <div className="saved-views-modal__preview">
            <p className="hint saved-views-modal__hint">
              Selected: <strong>{selectedSavedView.name}</strong> ({selectedSavedView.view}) - load keeps manual run.
            </p>
            <pre className="saved-views-modal__dsl-preview">
              {selectedSavedView.dsl}
            </pre>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
