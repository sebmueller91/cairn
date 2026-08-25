import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type CalendarYearsResponse } from "../../lib/api";
import { formatNumber, formatPercent } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { DataTable, type Column } from "../ui/DataTable";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { useIsLoading } from "../../lib/queryState";

type Row = CalendarYearsResponse["years"][number];

/**
 * TWR per calendar year, against the same benchmark shadow portfolio the
 * chart above overlays. Years chain: multiply them together and you land
 * on the since-inception figure, which is why each one is measured from
 * the previous 31 December rather than from its own first snapshot.
 *
 * Always TWR — the period selector above does not apply, because the
 * whole point is the fixed calendar cut. MWR is deliberately absent: it
 * is an annualised rate shaped by when money arrived, and a column of
 * them read top to bottom invites a comparison the number cannot carry.
 */
export function CalendarYearsCard({
  scope,
  benchmarkId,
  benchmarkName,
  assetClassParam,
}: {
  scope: string;
  benchmarkId: string;
  benchmarkName?: string;
  assetClassParam: string | null;
}) {
  const { t, i18n } = useTranslation(["performance", "common"]);

  const { data, isPending, isError } = useQuery({
    queryKey: ["performance", "calendar-years", scope, benchmarkId, assetClassParam],
    queryFn: () => {
      const params = new URLSearchParams({ scope });
      if (benchmarkId) params.set("benchmark_instrument_id", benchmarkId);
      if (assetClassParam) params.set("asset_classes", assetClassParam);
      return api.get<CalendarYearsResponse>(`/api/performance/calendar-years?${params}`);
    },
  });
  const pending = useIsLoading(isPending);

  const signedPercent = (value: number | null) =>
    value == null ? (
      <span className="text-text-muted">—</span>
    ) : (
      <span className={value >= 0 ? "text-positive" : "text-negative"}>
        {formatPercent(value, i18n.language, { signDisplay: "always" })}
      </span>
    );

  const columns: Column<Row>[] = [
    {
      key: "year",
      header: t("calendarYears.year"),
      render: (row) => (
        <span className="flex items-baseline gap-2">
          <span className="tnum font-medium">{row.year}</span>
          {row.partial && (
            // The honest caveat, inline rather than in a footnote: a
            // seven-month stub next to a full year is only comparable if
            // you can see that it is one.
            <span
              className="rounded-full bg-bg-subtle px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-muted"
              title={t("calendarYears.partialHint")}
            >
              {t("calendarYears.partial")}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "return",
      header: t("calendarYears.portfolio"),
      align: "right",
      render: (row) => signedPercent(row.return_pct),
    },
  ];

  if (benchmarkId) {
    columns.push(
      {
        key: "benchmark",
        header: benchmarkName ?? t("benchmark"),
        align: "right",
        render: (row) => signedPercent(row.benchmark_return_pct),
      },
      {
        key: "excess",
        header: t("calendarYears.excess"),
        align: "right",
        render: (row) => {
          if (row.return_pct == null || row.benchmark_return_pct == null) {
            return <span className="text-text-muted">—</span>;
          }
          // A difference of two percentages, so percentage points — the
          // same unit the hero above uses. Sign and digits left to Intl
          // rather than hand-assembled: a manual "−" is a different
          // character from the one Intl puts in front of the percentages
          // in the neighbouring columns, and a fixed single decimal keeps
          // "+19,0 pp" from sitting next to "−1,2 pp" as "+19 pp".
          const pp = (row.return_pct - row.benchmark_return_pct) * 100;
          return (
            <span className={pp >= 0 ? "text-positive" : "text-negative"}>
              {formatNumber(pp, i18n.language, {
                signDisplay: "always",
                minimumFractionDigits: 1,
                maximumFractionDigits: 1,
              })}{" "}
              pp
            </span>
          );
        },
      },
    );
  }

  // Most recent first: the year you are living in is the one you look at.
  const rows = [...(data?.years ?? [])].sort((a, b) => b.year - a.year);

  return (
    <GlassCard>
      <h2 className="mb-4 font-medium">{t("calendarYears.title")}</h2>
      {pending ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={t("calendarYears.empty")} />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => String(row.year)} />
      )}
    </GlassCard>
  );
}
