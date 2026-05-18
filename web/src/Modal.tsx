import { useEffect, useId } from "react";

type ModalProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  wide?: boolean;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
};

export function Modal({ open, title, onClose, wide, headerActions, children }: ModalProps) {
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-root" role="presentation">
      <button type="button" className="modal-backdrop" aria-label="Close dialog" onClick={onClose} />
      <div className={`modal${wide ? " modal--wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="modal__head">
          <h2 id={titleId}>{title}</h2>
          <div className="modal__head-actions">
            {headerActions}
            <button type="button" className="secondary modal__close" onClick={onClose} aria-label="Close">
              Close
            </button>
          </div>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  );
}
