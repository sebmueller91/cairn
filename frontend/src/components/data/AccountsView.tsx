import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Wallet } from "lucide-react";
import { api, type Account } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { DataTable, type Column } from "../ui/DataTable";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { CashBalanceModal } from "../CashBalanceModal";
import { SearchField } from "./SearchField";
import { TableSkeleton } from "./TableSkeleton";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

export function AccountsView() {
  const { t, i18n } = useTranslation(["data", "assets", "common"]);
  const [search, setSearch] = useState("");
  const [cashAccountId, setCashAccountId] = useState<number | undefined>(undefined);
  const [modalOpen, setModalOpen] = useState(false);

  const { data: accounts, isPending, isError } = useCachedQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const pending = useIsLoading(isPending);

  const rows = useMemo(() => {
    if (!accounts) return [];
    const q = search.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((a) =>
      [a.name, a.institution ?? ""].join(" ").toLowerCase().includes(q),
    );
  }, [accounts, search]);

  function openCashModal(accountId: number) {
    setCashAccountId(accountId);
    setModalOpen(true);
  }

  const columns: Column<Account>[] = [
    { key: "name", header: t("data:accounts.name"), render: (a) => a.name },
    {
      key: "type",
      header: t("data:accounts.type"),
      render: (a) => t(`assets:accounts.types.${a.type}`),
    },
    { key: "currency", header: t("data:accounts.currency"), render: (a) => a.currency },
    {
      key: "institution",
      header: t("data:accounts.institution"),
      render: (a) => <span className="text-text-muted">{a.institution ?? "—"}</span>,
    },
    {
      key: "created",
      header: t("common:fields.date"),
      render: (a) => (
        <span className="tnum text-text-muted">{formatDate(a.created_at, i18n.language)}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (a) =>
        a.type === "CASH" ? (
          <button
            type="button"
            onClick={() => openCashModal(a.id)}
            aria-label={t("data:accounts.updateBalance")}
            title={t("data:accounts.updateBalance")}
            className="inline-flex size-7 items-center justify-center rounded-full text-text-muted transition-colors hover:text-accent"
          >
            <Wallet className="size-4" aria-hidden />
          </button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-3">
      <SearchField value={search} onChange={setSearch} placeholder={t("data:search")} />

      <GlassCard className="p-0">
        {pending ? (
          <TableSkeleton />
        ) : isError ? (
          <p className="p-4 text-sm text-text-muted">{t("common:status.error")}</p>
        ) : !rows.length ? (
          <EmptyState title={t("data:accounts.empty")} />
        ) : (
          <DataTable columns={columns} rows={rows} rowKey={(a) => String(a.id)} maxHeight="32rem" />
        )}
      </GlassCard>

      <CashBalanceModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        defaultAccountId={cashAccountId}
      />
    </div>
  );
}
