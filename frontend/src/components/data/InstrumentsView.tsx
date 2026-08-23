import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useIsRestoring, useQuery } from "@tanstack/react-query";
import { api, type Instrument } from "../../lib/api";
import { ASSET_CLASS_COLORS, assetClassLabelKey } from "../../lib/assetClasses";
import { DataTable, type Column } from "../ui/DataTable";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { SearchField } from "./SearchField";
import { TableSkeleton } from "./TableSkeleton";

export function InstrumentsView() {
  const { t } = useTranslation(["data", "common"]);
  const isRestoring = useIsRestoring();
  const [search, setSearch] = useState("");

  const { data: instruments, isPending, isError } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const pending = isRestoring || isPending;

  const rows = useMemo(() => {
    if (!instruments) return [];
    const q = search.trim().toLowerCase();
    if (!q) return instruments;
    return instruments.filter((i) =>
      [i.name, i.ticker ?? "", i.isin ?? ""].join(" ").toLowerCase().includes(q),
    );
  }, [instruments, search]);

  const columns: Column<Instrument>[] = [
    { key: "name", header: t("data:instruments.name"), render: (i) => i.name },
    {
      key: "assetClass",
      header: t("data:instruments.assetClass"),
      render: (i) => (
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: ASSET_CLASS_COLORS[i.asset_class] }}
          />
          {t(`common:${assetClassLabelKey(i.asset_class)}`)}
        </span>
      ),
    },
    {
      key: "identifier",
      header: t("data:instruments.identifier"),
      render: (i) => <span className="text-text-muted">{i.ticker ?? i.isin ?? "—"}</span>,
    },
    { key: "currency", header: t("data:instruments.currency"), render: (i) => i.currency },
    {
      key: "region",
      header: t("data:instruments.region"),
      render: (i) => <span className="text-text-muted">{i.region ?? "—"}</span>,
    },
    {
      key: "sector",
      header: t("data:instruments.sector"),
      render: (i) => <span className="text-text-muted">{i.sector ?? "—"}</span>,
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
          <EmptyState title={t("data:instruments.empty")} />
        ) : (
          <DataTable columns={columns} rows={rows} rowKey={(i) => String(i.id)} maxHeight="32rem" />
        )}
      </GlassCard>
    </div>
  );
}
