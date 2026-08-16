import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api, ApiError, type Account, type Transaction } from "../lib/api";
import { parseDecimalInput } from "../lib/decimalInput";
import { useOnlineStatus } from "../lib/online";
import { Modal } from "./ui/Modal";
import { EmptyState } from "./ui/EmptyState";
import { OfflineNotice } from "./OfflineNotice";

// Same shape as Transactions.tsx's helper — external_id just needs to be
// unique per booking, not globally meaningful (ADR: every write is
// idempotent via a caller-supplied external id).
function newExternalId(): string {
  return `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * The one write action left in the UI: set a cash account's current
 * balance. Books a BALANCE_STATEMENT via POST /api/transactions — the
 * server derives everything else (holdings, net worth) from the ledger,
 * this never writes a balance directly anywhere else.
 */
export function CashBalanceModal({
  open,
  onClose,
  defaultAccountId,
}: {
  open: boolean;
  onClose: () => void;
  /** Preselects an account when opened from a specific row's action button. */
  defaultAccountId?: number;
}) {
  const { t } = useTranslation(["data", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const cashAccounts = accounts?.filter((a) => a.type === "CASH" && !a.archived) ?? [];

  const [accountId, setAccountId] = useState("");
  const [balance, setBalance] = useState("");
  const [date, setDate] = useState(today);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  // Reset the form each time the modal is (re)opened, not on every render —
  // an open->open re-render (e.g. accounts refetching) shouldn't wipe what
  // the user already typed.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setAccountId(defaultAccountId != null ? String(defaultAccountId) : "");
      setBalance("");
      setDate(today());
      setError(null);
      setSuccess(false);
    }
    wasOpen.current = open;
  }, [open, defaultAccountId]);

  // Falls back to the first cash account once the list has loaded, if
  // nothing was preselected.
  useEffect(() => {
    if (open && !accountId && cashAccounts.length > 0) {
      setAccountId(String(cashAccounts[0].id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, cashAccounts.length]);

  const selectedAccount = cashAccounts.find((a) => String(a.id) === accountId);

  const submitBalance = useMutation({
    mutationFn: () => {
      if (!selectedAccount) throw new Error("no_account_selected");
      // Whatever the user typed becomes a plain decimal string here (ADR
      // 0001: money never becomes a float). Grouping separators included —
      // "12.345,67" is what a German keyboard produces naturally.
      const normalized = parseDecimalInput(balance);
      if (normalized === null) throw new ApiError(400, "invalid_amount", {});
      return api.post<Transaction>("/api/transactions", {
        external_id: newExternalId(),
        date,
        type: "BALANCE_STATEMENT",
        account_id: selectedAccount.id,
        amount: normalized,
        currency: selectedAccount.currency,
        source: "manual",
      });
    },
    onSuccess: () => {
      // Broad invalidation on purpose: a single manual balance booking
      // touches net worth, allocation and positions derivations along with
      // the ledger itself, and the app has few enough queries overall that
      // refetching everything is cheaper than maintaining a precise key
      // list here that silently rots as new views land.
      queryClient.invalidateQueries();
      setSuccess(true);
      setError(null);
      closeTimer.current = setTimeout(() => {
        onClose();
      }, 1000);
    },
    onError: (err) => {
      setSuccess(false);
      setError(err instanceof ApiError ? t(`errors:${err.code}`, err.params) : t("errors:generic"));
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    submitBalance.mutate();
  }

  const canSubmit = online && !!selectedAccount && balance.trim() !== "" && !submitBalance.isPending;

  return (
    <Modal open={open} onClose={onClose} title={t("common:actions.updateCash")}>
      {cashAccounts.length === 0 ? (
        <EmptyState title={t("data:cashModal.noAccounts")} hint={t("data:cashModal.noAccountsHint")} />
      ) : success ? (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <span
            className="flex size-12 items-center justify-center rounded-full bg-positive/15 text-positive"
            style={{ boxShadow: "var(--glow-positive)" }}
          >
            <Check className="size-6" aria-hidden />
          </span>
          <p className="text-sm font-medium">{t("data:cashModal.success")}</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("data:cashModal.account")}</label>
            <select
              value={accountId}
              onChange={(e) => {
                setAccountId(e.target.value);
                setError(null);
              }}
              required
              className="w-full rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm text-text outline-none focus:border-accent"
            >
              {cashAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("data:cashModal.balance")}</label>
            <input
              type="text"
              inputMode="decimal"
              value={balance}
              onChange={(e) => {
                setBalance(e.target.value);
                setError(null);
              }}
              placeholder={selectedAccount ? `0,00 ${selectedAccount.currency}` : "0,00"}
              required
              className="w-full rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("data:cashModal.date")}</label>
            <input
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setError(null);
              }}
              required
              className="w-full rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </div>

          {!online && <OfflineNotice />}
          {error && (
            <p className="text-sm text-negative" role="alert">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-4 py-2 text-sm font-medium text-text-muted hover:text-text"
            >
              {t("data:cashModal.cancel")}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg shadow-glow-accent disabled:opacity-50 disabled:shadow-none"
            >
              {t("data:cashModal.submit")}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
