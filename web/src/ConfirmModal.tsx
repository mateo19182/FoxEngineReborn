import { Modal } from "./Modal";

type ConfirmModalProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel,
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      <p className="hint" style={{ marginTop: 0 }}>
        {message}
      </p>
      <div className="btn-row">
        <button type="button" className="secondary" onClick={onCancel} disabled={pending}>
          Cancel
        </button>
        <button type="button" onClick={onConfirm} disabled={pending}>
          {pending ? "Deleting..." : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
