import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type InstrumentReturnsResponse } from "../../lib/api";
import { formatDate, formatNumber, formatPercent } from "../../lib/format";
import { ASSET_CLASS_COLORS } from "../../lib/assetClasses";
import { GlassCard } from "../ui/GlassCard";
import { DataTable, type Column } from "../ui/DataTable";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { useIsLoading } from "../../lib/queryState";

type Row = InstrumentReturnsResponse["instruments"][number];

/**
 * Every holding's own return over the selected period, ranked.
 *
 * Deliberately not the unrealised P/L percentage the Portfolio page
 * already shows: that one compares a lot against what was paid for it and
 * is therefore dominated by *when* it was bought. This is TWR (or MWR),
 * the figure that is actually comparable between two positions and
 * against a benchmark.
 *
 * Clicking a row narrows the whole tab to that instrument — the ranking
 * is the natural way to pick one, so it doubles as navigation.
 */
export function InstrumentReturnsCard({
  period,
  method,
  assetClassParam,
  onSelectInstrument,
  selectedInstrumentId,
}: {
  period: string;
  method: string;
  assetClassParam: string | null;
  onSelectInstrument: (instrumentId: number) => void;
  selectedInstrumentId: number | null;
}) {
  const { t, i18n } = useTranslation(["performance", "common"]);

  const { data, isPending, isError } = useQuery({
    queryKey: ["performance", "by-instrument", period, method, assetClassParam],
    queryFn: () => {
      const params = new URLSearchParams({ period, method });
      if (assetClassParam) params.set("asset_classes", assetClassParam);
      return api.get<InstrumentReturnsResponse>(`/api/performance/by-instrument?${params}`);
    },
  });
  const pending = useIsLoading(isPending);

  const windowStart = data?.start_date;

  const columns: Column<Row>[] = [
    {
      key: "name",
      header: t("byInstrument.instrument"),
      render: (row) => (
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full"
            style={{ background: ASSET_CLASS_COLORS[row.asset_class] }}
          />
          {/* Bounded so a long fund name truncates instead of pushing the
              return column — the one figure the card exists for — off a
              phone screen. The table still scrolls horizontally the way
              every other DataTable in the app does; this just keeps the
              scroll from being necessary in the common case. */}
          <span className="min-w-0 max-w-[10rem] sm:max-w-none">
            <span
              className={`block truncate ${
                row.instrument_id === selectedInstrumentId ? "font-medium text-accent" : ""
              }`}
            >
              {row.name}
            </span>
            {row.start_date !== windowStart && (
              // Only where it carries information. A holding younger than
              // the requested period covers less of it, and reporting that
              // under a "1Y" heading without saying so would overstate
              // what the figure is comparable with. When every row starts
              // on the same day — the normal case — the same note on every
              // row would say nothing and cost a column.
              <span className="block text-xs text-text-muted">
                {t("byInstrument.onlyFrom", {
                  date: formatDate(row.start_date, i18n.language),
                })}
              </span>
            )}
          </span>
        </span>
      ),
    },
    {
      key: "value",
      header: t("byInstrument.value"),
      align: "right",
      render: (row) => (
        // Whole euros: this column is scale, not an amount anyone reads to
        // the cent, and the two digits it saves are what keep the return
        // column on screen next to it.
        <span className="text-text-muted">
          {formatNumber(row.value_eur, i18n.language, {
            style: "currency",
            currency: "EUR",
            maximumFractionDigits: 0,
          })}
        </span>
      ),
    },
    {
      key: "return",
      header: t(`methods.${method}`),
      align: "right",
      render: (row) =>
        row.return_pct == null ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span
            className={`font-medium ${row.return_pct >= 0 ? "text-positive" : "text-negative"}`}
          >
            {formatPercent(row.return_pct, i18n.language, { signDisplay: "always" })}
          </span>
        ),
    },
  ];

  const rows = data?.instruments ?? [];

  return (
    <GlassCard>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">{t("byInstrument.title")}</h2>
        <span className="text-xs text-text-muted">
          {t(`periods.${period}`)} · {t(`methods.${method}`)}
        </span>
      </div>
      <p className="mb-4 text-xs text-text-muted">{t("byInstrument.hint")}</p>
      {pending ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={t("byInstrument.empty")} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => String(row.instrument_id)}
          onRowClick={(row) => onSelectInstrument(row.instrument_id)}
          maxHeight="26rem"
        />
      )}
    </GlassCard>
  );
}
