import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type Account,
  type Instrument,
  type Transaction,
  type TransactionType,
} from "../lib/api";
import { formatCurrency, formatDate, formatNumber } from "../lib/format";
import { Card } from "../components/Card";

const TRANSACTION_TYPES: TransactionType[] = [
  "BUY",
  "SELL",
  "DIVIDEND",
  "INTEREST",
  "FEE",
  "TAX",
  "DEPOSIT",
  "WITHDRAWAL",
  "TRANSFER",
  "SPLIT",
  "OPENING_BALANCE",
  "BALANCE_STATEMENT",
];

const NEEDS_QUANTITY_PRICE: TransactionType[] = ["BUY", "SELL"];
// OPENING_BALANCE needs a quantity too (spec 2.3: "quantity, value,
// provisional") but not a price — its cost basis comes from `amount`
// directly, not quantity*price. Found live: the form only showed a
// quantity field for BUY/SELL/TRANSFER, so booking an opening balance
// silently submitted quantity=null and failed with missing_field.
const NEEDS_QUANTITY: TransactionType[] = ["BUY", "SELL", "TRANSFER", "OPENING_BALANCE"];
const NEEDS_INSTRUMENT: TransactionType[] = [
  "BUY",
  "SELL",
  "DIVIDEND",
  "TRANSFER",
  "SPLIT",
  "OPENING_BALANCE",
];
const NEEDS_AMOUNT: TransactionType[] = [
  "DIVIDEND",
  "INTEREST",
  "FEE",
  "TAX",
  "DEPOSIT",
  "WITHDRAWAL",
  "OPENING_BALANCE",
  "BALANCE_STATEMENT",
];

function newExternalId(): string {
  return `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function Transactions() {
  const { t, i18n } = useTranslation(["assets", "common", "errors"]);
  const queryClient = useQueryClient();

  const { data: transactions, isLoading } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get<Transaction[]>("/api/transactions"),
  });
  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const [type, setType] = useState<TransactionType>("BUY");
  const [accountId, setAccountId] = useState("");
  const [counterAccountId, setCounterAccountId] = useState("");
  const [instrumentId, setInstrumentId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [fees, setFees] = useState("0");
  const [splitRatio, setSplitRatio] = useState("2");
  const [error, setError] = useState<string | null>(null);

  const createTransaction = useMutation({
    mutationFn: () =>
      api.post<Transaction>("/api/transactions", {
        external_id: newExternalId(),
        date,
        type,
        account_id: Number(accountId),
        instrument_id: instrumentId ? Number(instrumentId) : null,
        counter_account_id: counterAccountId ? Number(counterAccountId) : null,
        quantity: NEEDS_QUANTITY.includes(type) ? quantity : null,
        price: NEEDS_QUANTITY_PRICE.includes(type) ? price : null,
        amount: NEEDS_AMOUNT.includes(type) ? amount : null,
        currency,
        fees: fees || "0",
        split_ratio: type === "SPLIT" ? splitRatio : null,
        source: "manual",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["networth"] });
      setQuantity("");
      setPrice("");
      setAmount("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`, err.params) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createTransaction.mutate();
  }

  const accountName = (id: number | null) => accounts?.find((a) => a.id === id)?.name ?? "—";
  const instrumentName = (id: number | null) =>
    id ? instruments?.find((i) => i.id === id)?.name ?? `#${id}` : "—";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("assets:transactions.title")}</h1>

      <Card>
        <h2 className="mb-3 font-medium">{t("assets:transactions.new")}</h2>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:transactions.type")}
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as TransactionType)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            >
              {TRANSACTION_TYPES.map((tt) => (
                <option key={tt} value={tt}>
                  {t(`assets:transactions.types.${tt}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.date")}
            </label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:positions.account")}
            </label>
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              required
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            >
              <option value="" disabled>
                —
              </option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          {type === "TRANSFER" && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">→</label>
              <select
                value={counterAccountId}
                onChange={(e) => setCounterAccountId(e.target.value)}
                required
                className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              >
                <option value="" disabled>
                  —
                </option>
                {accounts?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {NEEDS_INSTRUMENT.includes(type) && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">
                {t("assets:positions.instrument")}
              </label>
              <select
                value={instrumentId}
                onChange={(e) => setInstrumentId(e.target.value)}
                required
                className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              >
                <option value="" disabled>
                  —
                </option>
                {instruments?.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {NEEDS_QUANTITY.includes(type) && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">
                {t("common:fields.quantity")}
              </label>
              <input
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
                className="w-24 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              />
            </div>
          )}
          {NEEDS_QUANTITY_PRICE.includes(type) && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">
                {t("common:fields.price")}
              </label>
              <input
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                required
                className="w-24 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              />
            </div>
          )}
          {NEEDS_AMOUNT.includes(type) && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">
                {t("common:fields.amount")}
              </label>
              <input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
                className="w-28 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              />
            </div>
          )}
          {type === "SPLIT" && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">Ratio</label>
              <input
                value={splitRatio}
                onChange={(e) => setSplitRatio(e.target.value)}
                required
                className="w-16 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              />
            </div>
          )}
          {NEEDS_QUANTITY_PRICE.includes(type) && (
            <div>
              <label className="mb-1 block text-xs text-text-muted">
                {t("common:fields.fees")}
              </label>
              <input
                value={fees}
                onChange={(e) => setFees(e.target.value)}
                className="w-20 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.currency")}
            </label>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              maxLength={3}
              required
              className="w-16 rounded-md border border-border bg-bg px-3 py-1.5 text-sm uppercase"
            />
          </div>
          <button
            type="submit"
            disabled={createTransaction.isPending}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {t("common:actions.create")}
          </button>
        </form>
        {error && (
          <p className="mt-2 text-sm text-negative" role="alert">
            {error}
          </p>
        )}
      </Card>

      <Card className="p-0">
        {isLoading ? (
          <p className="p-5 text-text-muted">{t("common:status.loading")}</p>
        ) : !transactions?.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("common:fields.date")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:transactions.type")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:positions.account")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:positions.instrument")}</th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("common:fields.quantity")}
                </th>
                <th className="px-5 py-2 text-right font-medium">{t("common:fields.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx) => (
                <tr key={tx.id} className="border-b border-border last:border-0">
                  <td className="tnum px-5 py-2">{formatDate(tx.date, i18n.language)}</td>
                  <td className="px-5 py-2">{t(`assets:transactions.types.${tx.type}`)}</td>
                  <td className="px-5 py-2 text-text-muted">{accountName(tx.account_id)}</td>
                  <td className="px-5 py-2 text-text-muted">
                    {instrumentName(tx.instrument_id)}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {tx.quantity
                      ? formatNumber(tx.quantity, i18n.language, { maximumFractionDigits: 8 })
                      : "—"}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(tx.amount_eur, i18n.language)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
