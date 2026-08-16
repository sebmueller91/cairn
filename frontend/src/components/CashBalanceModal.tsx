import { Modal } from "./ui/Modal";

/** The one write action left in the UI: set a cash account's current
 * balance (books a BALANCE_STATEMENT via POST /api/transactions).
 * Stub — the real form lands with the Data-section phase; pages may
 * already import it and wire their trigger buttons against this API. */
export function CashBalanceModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose}>
      <div />
    </Modal>
  );
}
