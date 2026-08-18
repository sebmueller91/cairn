import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Layers } from "lucide-react";
import type { AllocationTimeseriesPoint } from "../../lib/api";
import {
  ASSET_CLASSES,
  ASSET_CLASS_COLORS,
  assetClassLabelKey,
  type AssetClass,
} from "../../lib/assetClasses";
import { formatCurrency } from "../../lib/format";
import { StackedAreaChart, type StackSeries } from "../charts/StackedAreaChart";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";

/**
 * Composition over time for the selected classes.
 *
 * Reads the *same* allocation query as the curve card above it — the page
 * owns the period state and hands both cards the identical points array, so
 * switching to 6M refetches once, not twice, and the two charts can never
 * disagree about which window is on screen.
 */
export function ClassMixCard({
  points,
  selected,
  isLoading,
}: {
  points: AllocationTimeseriesPoint[] | undefined;
  selected: Set<AssetClass>;
  isLoading: boolean;
}) {
  const { t, i18n } = useTranslation(["wealth", "common"]);

  // ASSET_CLASSES order, not selection order: the bands must not reshuffle
  // when a chip is toggled off and back on.
  const classes = useMemo(
    () => ASSET_CLASSES.filter((c) => selected.has(c)),
    [selected],
  );

  const series: StackSeries[] = useMemo(
    () =>
      classes.map((cls) => ({
        key: cls,
        color: ASSET_CLASS_COLORS[cls],
        label: t(assetClassLabelKey(cls), { ns: "common" }),
      })),
    [classes, t],
  );

  const data = useMemo(
    () =>
      (points ?? []).map((point) => {
        const row: { date: string } & Record<string, string | number> = {
          date: point.date,
        };
        for (const cls of classes) {
          const n = Number(point.values[cls] ?? 0);
          row[cls] = Number.isFinite(n) ? n : 0;
        }
        return row;
      }),
    [points, classes],
  );

  const formatValue = useCallback(
    (n: number) => formatCurrency(n, i18n.language),
    [i18n.language],
  );

  return (
    <GlassCard className="flex flex-col">
      <h2 className="text-sm font-medium text-text-muted">{t("mix.title")}</h2>

      {isLoading ? (
        <Skeleton className="mt-4 h-[280px] w-full" />
      ) : data.length === 0 ? (
        <EmptyState
          icon={<Layers className="size-8" aria-hidden />}
          title={t("empty.title")}
          hint={t("empty.hint")}
        />
      ) : (
        <>
          <div className="mt-4">
            <StackedAreaChart
              data={data}
              series={series}
              formatValue={formatValue}
            />
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
            {series.map((s) => (
              <li
                key={s.key}
                className="flex items-center gap-1.5 text-xs text-text-muted"
              >
                <span
                  aria-hidden
                  className="size-2 rounded-full"
                  style={{ backgroundColor: s.color }}
                />
                {s.label}
              </li>
            ))}
          </ul>
        </>
      )}
    </GlassCard>
  );
}
