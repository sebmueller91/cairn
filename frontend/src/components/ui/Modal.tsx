import { useEffect, useRef, type ReactNode } from "react";

/**
 * Native `<dialog>` modal: centred glass panel on desktop, bottom sheet on
 * phones. Escape and backdrop clicks both close it.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  // showModal() is what puts the element in the top layer and gives us the
  // ::backdrop, focus trapping and Escape handling for free — the `open`
  // attribute alone does none of that, so never render it declaratively.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      // Escape closes the dialog natively; this is how the parent finds out.
      onClose={onClose}
      // The backdrop is painted by the dialog itself, so a click that lands
      // outside the inner panel has the dialog element as its target.
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="m-0 mt-auto max-h-[92dvh] w-full max-w-none bg-transparent p-0 text-text backdrop:bg-black/60 backdrop:backdrop-blur-sm md:m-auto md:w-[min(34rem,calc(100vw-2rem))]"
    >
      <div
        className="animate-sheet-up overflow-y-auto rounded-t-2xl border border-border bg-bg-subtle/90 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop-blur-glass md:animate-none md:rounded-card md:p-5 md:pb-5"
      >
        {/* Grab handle, sheet affordance only — hidden once it is centred. */}
        <div
          aria-hidden
          className="mx-auto mb-3 h-1 w-10 rounded-full bg-border md:hidden"
        />
        {title && (
          <div className="mb-3 text-lg font-semibold tracking-tight">{title}</div>
        )}
        {children}
      </div>
    </dialog>
  );
}
