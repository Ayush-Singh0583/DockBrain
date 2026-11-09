import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface ConfirmDialogProps {
  open: boolean;
  /** Names what will be lost, e.g. Start over with “report.pdf”? */
  title: string;
  children: ReactNode;
  /** A destructive verb, e.g. "Clear and start over". */
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmation for an action that loses work. A native modal <dialog>: it traps focus, Esc
 * cancels, and the rest of the page is inert while it's open. Focus starts on the safe
 * choice and returns to whatever opened the dialog when it's cancelled.
 */
export function ConfirmDialog({ open, title, children, confirmLabel, cancelLabel = 'Keep working', onConfirm, onCancel }: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
      keepRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const cancel = () => {
    onCancel();
    if (returnTo.current?.isConnected) returnTo.current.focus();
  };

  // Rendered on <body>, not where it was declared: styles of the stage it was opened from don't reach it.
  return createPortal(
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault(); // Esc: close through React state, so focus goes back too
        cancel();
      }}
    >
      <h2 id={titleId} className="confirm-dialog__title">
        {title}
      </h2>
      <div className="confirm-dialog__body">{children}</div>
      <div className="confirm-dialog__actions">
        <button ref={keepRef} type="button" className="btn btn--secondary" onClick={cancel}>
          {cancelLabel}
        </button>
        <button type="button" className="btn btn--danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
