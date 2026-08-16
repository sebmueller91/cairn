import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type Account,
  type Instrument,
  type Transaction,
  type TransactionType,
} from "../../lib/api";
import { formatCurrency, formatDate } from "../../lib/format";
import { DataTable, type Column } from "../ui/DataTable";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { SearchField } from "./SearchField";
import { TableSkeleton } from "./TableSkeleton";

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

const PAGE_SIZE = 50;

/** Read-only transaction ledger — filters + "load more", no create form
 * (spec: the cash-balance modal is the only write action left in the UI). */
export function LedgerView() {
  const { t, i18n } = useTranslation(["data", "assets", "common"]);
  const [accountId, setAccountId] = useState("");
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const { data: transactions, isLoading } = useQuery({
    queryKey: ["transactions", accountId, limit],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (accountId) params.set("account_id", accountId);
      return api.get<Transaction[]>(`/api/transactions?${params}`);
    },
  });

  const accountName = (id: number | null) =>
    accounts?.find((a) => a.id === id)?.name ?? (id ? `#${id}` : "—");
  const instrumentName = (id: number | null) =>
    id ? (instruments?.find((i) => i.id === id)?.name ?? `#${id}`) : null;

  const rows = useMemo(() => {
    if (!transactions) return [];
    const q = search.trim().toLowerCase();
    return transactions.filter((tx) => {
      if (type && tx.type !== type) return false;
      if (!q) return true;
      const haystack = [
        accountName(tx.account_id),
        instrumentName(tx.instrument_id) ?? "",
        tx.note ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactions, type, search, accounts, instruments]);

  const columns: Column<Transaction>[] = [
    {
      key: "date",
      header: t("data:ledger.date"),
      render: (tx) => formatDate(tx.date, i18n.language),
    },
    {
      key: "type",
      header: t("data:ledger.type"),
      render: (tx) => t(`assets:transactions.types.${tx.type}`),
    },
    {
      key: "who",
      header: t("data:ledger.accountInstrument"),
      render: (tx) => {
        const instrument = instrumentName(tx.instrument_id);
        return (
          <span>
            {accountName(tx.account_id)}
            {instrument && <span className="text-text-muted"> · {instrument}</span>}
          </span>
        );
      },
    },
    {
      key: "amount",
      header: t("data:ledger.amount"),
      align: "right",
      // A booking's amount is a magnitude, not a gain: the ledger stores
      // every type as a positive figure and the type column carries the
      // direction. Colouring it green with an up-arrow would read as
      // profit on rows that are purchases.
      render: (tx) => <span className="tnum">{formatCurrency(tx.amount_eur, i18n.language)}</span>,
    },
    {
      key: "note",
      header: t("data:ledger.note"),
      render: (tx) => (
        <span className="block max-w-48 truncate text-text-muted" title={tx.note ?? undefined}>
          {tx.note ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder={t("data:search")}
          className="min-w-40 flex-1"
        />
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          className="rounded-md border border-border bg-bg-subtle px-3 py-1.5 text-sm text-text"
        >
          <option value="">{t("data:allAccounts")}</option>
          {accounts?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded-md border border-border bg-bg-subtle px-3 py-1.5 text-sm text-text"
        >
          <option value="">{t("data:allTypes")}</option>
          {TRANSACTION_TYPES.map((tt) => (
            <option key={tt} value={tt}>
              {t(`assets:transactions.types.${tt}`)}
            </option>
          ))}
        </select>
      </div>

      <GlassCard className="p-0">
        {isLoading ? (
          <TableSkeleton />
        ) : !rows.length ? (
          <EmptyState title={t("data:ledger.empty")} />
        ) : (
          <>
            <DataTable columns={columns} rows={rows} rowKey={(tx) => String(tx.id)} maxHeight="32rem" />
            {transactions && transactions.length >= limit && (
              <div className="flex justify-center border-t border-border p-3">
                <button
                  type="button"
                  onClick={() => setLimit((l) => l + PAGE_SIZE)}
                  className="rounded-full border border-border px-4 py-1.5 text-xs font-medium text-text-muted hover:text-text"
                >
                  {t("data:loadMore")}
                </button>
              </div>
            )}
          </>
        )}
      </GlassCard>
    </div>
  );
}
