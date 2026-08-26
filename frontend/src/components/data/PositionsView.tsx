import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Account, type Instrument, type Position } from "../../lib/api";
import { formatCurrency, formatNumber } from "../../lib/format";
import { DataTable, type Column } from "../ui/DataTable";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { SearchField } from "./SearchField";
import { SignedAmount } from "./SignedAmount";
import { TableSkeleton } from "./TableSkeleton";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

type GroupBy = "account" | "instrument";

export function PositionsView() {
  const { t, i18n } = useTranslation(["data", "common"]);
  const [groupBy, setGroupBy] = useState<GroupBy>("account");
  const [search, setSearch] = useState("");

  const { data: positions, isPending, isError } = useCachedQuery({
    queryKey: ["positions", groupBy],
    queryFn: () => api.get<Position[]>(`/api/positions?group_by=${groupBy}`),
  });
  const pending = useIsLoading(isPending);
  const { data: accounts } = useCachedQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const { data: instruments } = useCachedQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const accountName = (id: number | null) =>
    accounts?.find((a) => a.id === id)?.name ?? (id ? `#${id}` : "—");
  const instrumentName = (id: number) =>
    instruments?.find((i) => i.id === id)?.name ?? `#${id}`;

  const rows = useMemo(() => {
    if (!positions) return [];
    const q = search.trim().toLowerCase();
    if (!q) return positions;
    return positions.filter((p) => {
      const haystack = [instrumentName(p.instrument_id), accountName(p.account_id)]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions, search, accounts, instruments]);

  const columns: Column<Position>[] = [
    {
      key: "name",
      header: t("data:positions.name"),
      render: (p) => instrumentName(p.instrument_id),
    },
    ...(groupBy === "account"
      ? [
          {
            key: "account",
            header: t("data:positions.groupByAccount"),
            render: (p: Position) => (
              <span className="text-text-muted">{accountName(p.account_id)}</span>
            ),
          } satisfies Column<Position>,
        ]
      : []),
    {
      key: "quantity",
      header: t("data:positions.quantity"),
      align: "right",
      render: (p) => formatNumber(p.quantity, i18n.language, { maximumFractionDigits: 8 }),
    },
    {
      key: "costBasis",
      header: t("data:positions.costBasis"),
      align: "right",
      render: (p) =>
        formatNumber(p.cost_basis_eur, i18n.language, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }),
    },
    {
      key: "value",
      header: t("data:positions.value"),
      align: "right",
      render: (p) => (
        <span className="sensitive">
          {p.value_eur ? formatCurrency(p.value_eur, i18n.language) : "—"}
        </span>
      ),
    },
    {
      key: "unrealizedPl",
      header: t("data:positions.unrealizedPl"),
      align: "right",
      render: (p) => <SignedAmount value={p.unrealized_pl_eur} lang={i18n.language} />,
    },
    {
      key: "realizedPl",
      header: t("data:positions.realizedPl"),
      align: "right",
      render: (p) => <SignedAmount value={p.realized_pl_eur} lang={i18n.language} />,
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
        <SegmentedControl
          options={[
            { value: "account", label: t("data:positions.groupByAccount") },
            { value: "instrument", label: t("data:positions.groupByInstrument") },
          ]}
          value={groupBy}
          onChange={setGroupBy}
        />
      </div>

      <GlassCard className="p-0">
        {pending ? (
          <TableSkeleton />
        ) : isError ? (
          <p className="p-4 text-sm text-text-muted">{t("common:status.error")}</p>
        ) : !rows.length ? (
          <EmptyState title={t("data:positions.empty")} />
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(p) => `${p.account_id ?? "x"}-${p.instrument_id}`}
            maxHeight="32rem"
          />
        )}
      </GlassCard>
    </div>
  );
}
