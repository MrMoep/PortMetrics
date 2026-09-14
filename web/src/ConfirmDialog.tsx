import { useEffect, useId, useRef } from "react";

export type ConfirmOptions = {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Primary button uses danger styling (e.g. discard). */
  danger?: boolean;
};

export type ConfirmRequest = ConfirmOptions & {
  resolve: (ok: boolean) => void;
};

export function ConfirmDialog({
  request,
  onSettle,
}: {
  request: ConfirmRequest | null;
  onSettle: (ok: boolean) => void;
}) {
  const titleId = useId();
  const messageId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!request) return;
    const focusTarget = request.danger ? cancelRef.current : confirmRef.current;
    focusTarget?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onSettle(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [request, onSettle]);

  if (!request) return null;

  const title = request.title ?? "Bestätigung";
  const confirmLabel = request.confirmLabel ?? "OK";
  const cancelLabel = request.cancelLabel ?? "Abbrechen";

  return (
    <div
      className="modal-backdrop modal-backdrop-confirm"
      role="presentation"
      onClick={() => onSettle(false)}
    >
      <div
        className="modal-panel"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id={titleId}>{title}</h3>
        <p id={messageId} className="muted confirm-message">
          {request.message}
        </p>
        <div className="row-actions">
          <button
            ref={confirmRef}
            className={request.danger ? "danger" : "primary"}
            type="button"
            onClick={() => onSettle(true)}
          >
            {confirmLabel}
          </button>
          <button ref={cancelRef} type="button" onClick={() => onSettle(false)}>
            {cancelLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
