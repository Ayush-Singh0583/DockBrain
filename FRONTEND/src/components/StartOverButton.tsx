import { useState, type ReactNode } from 'react';
import { ConfirmDialog } from './ConfirmDialog';

/**
 * "Start over" clears the selection and every result. When there is progress to lose
 * (questions asked, quiz answers, marked cards), it asks first, naming the document.
 */
export function StartOverButton({
  hasProgress,
  subject,
  onConfirm,
  icon,
}: {
  hasProgress: boolean;
  /** The document or folder being worked on, named in the confirmation. */
  subject: string;
  onConfirm: () => void;
  icon?: ReactNode;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <button
        type="button"
        className="btn btn--secondary btn--sm"
        onClick={() => (hasProgress ? setConfirming(true) : onConfirm())}
      >
        {icon}
        Start over
      </button>
      <ConfirmDialog
        open={confirming}
        title={`Start over and clear “${subject}”?`}
        confirmLabel="Clear and start over"
        onConfirm={onConfirm}
        onCancel={() => setConfirming(false)}
      >
        Your questions, quiz answers and marked cards will be cleared. This can’t be undone.
      </ConfirmDialog>
    </>
  );
}
