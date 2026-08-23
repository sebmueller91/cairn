import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { DonutChart, type DonutSlice } from "../charts/DonutChart";
import { HBarList, type HBarItem } from "../charts/HBarList";
import { formatCurrency, formatPercent } from "../../lib/format";
import { ASSET_CLASS_COLORS } from "../../lib/assetClasses";
import { useAssetFilter } from "../../lib/assetFilter";
import {
  usePositionsWithInstruments,
  type PositionWithInstrument,
} from "./usePositionsWithInstruments";
import { SignedAmount } from "./SignedAmount";

const TOP_N = 8;
const VISIBLE_CAP = 15;

/** Section 2 — value by instrument: donut of the top holdings + a full ranked list. */
export function InstrumentDistributionCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { selected } = useAssetFilter();
  const { rows, isPending, isError } = usePositionsWithInstruments();
  const [expanded, setExpanded] = useState(false);

  const filtered = useMemo(() => {
    if (!rows) return undefined;
    return rows
      .filter(
        (p) =>
          p.instrument &&
          selected.has(p.instrument.asset_class) &&
          p.value_eur !== null &&
          // A fully sold position stays in /api/positions so its realized
          // P/L survives, but it holds nothing and therefore has no share
          // of a distribution — it would only ever render as a 0,00 € row
          // at the bottom of the ranking.
          Number(p.value_eur) > 0,
      )
      .sort((a, b) => Number(b.value_eur) - Number(a.value_eur));
  }, [rows, selected]);

  const slices: DonutSlice[] = useMemo(() => {
    if (!filtered) return [];
    const top = filtered.slice(0, TOP_N);
    const rest = filtered.slice(TOP_N);
    const result: DonutSlice[] = top.map((p) => ({
      name: p.instrument!.name,
      value: Number(p.value_eur),
      color: ASSET_CLASS_COLORS[p.instrument!.asset_class],
    }));
    const otherTotal = rest.reduce((sum, p) => sum + Number(p.value_eur), 0);
    if (otherTotal > 0) {
      result.push({
        name: t("instrumentDistribution.other"),
        value: otherTotal,
        color: "var(--text-muted)",
      });
    }
    return result;
  }, [filtered, t]);

  // Absolute gain and the same gain as a share of what was paid — the
  // percentage is what makes two positions comparable when one is a house
  // and the other is 200 EUR of silver. Cost basis of zero has no
  // percentage to give (a position that arrived by transfer rather than
  // purchase), so that case shows the amount alone rather than a division
  // by zero rendered as Infinity.
  const plSecondary = useCallback(
    (p: PositionWithInstrument) => {
      if (p.unrealized_pl_eur === null) return undefined;
      const cost = Number(p.cost_basis_eur);
      const pl = Number(p.unrealized_pl_eur);
      const pct = cost > 0 ? pl / cost : null;
      return (
        <span className="flex items-baseline gap-1.5">
          <SignedAmount value={p.unrealized_pl_eur} lang={i18n.language} className="text-xs" />
          {pct !== null && (
            <span
              className={`tnum text-xs ${
                pl > 0 ? "text-positive" : pl < 0 ? "text-negative" : "text-text-muted"
              }`}
            >
              {pl >= 0 ? "+" : ""}
              {formatPercent(pct, i18n.language)}
            </span>
          )}
        </span>
      );
    },
    [i18n.language],
  );

  const barItems: HBarItem[] = useMemo(() => {
    if (!filtered) return [];
    const visible = expanded ? filtered : filtered.slice(0, VISIBLE_CAP);
    return visible.map((p) => ({
      key: `${p.instrument_id}`,
      label: p.instrument!.name,
      value: Number(p.value_eur),
      color: ASSET_CLASS_COLORS[p.instrument!.asset_class],
      secondary: plSecondary(p),
    }));
  }, [filtered, expanded, plSecondary]);

  return (
    <GlassCard>
      <h2 className="mb-4 font-medium">{t("instrumentDistribution.title")}</h2>
      {isPending ? (
        <div className="space-y-4">
          <Skeleton className="mx-auto h-56 w-56 rounded-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : !filtered || filtered.length === 0 ? (
        <EmptyState title={t("common:status.empty")} />
      ) : (
        <>
          <DonutChart data={slices} height={220} formatValue={(n) => formatCurrency(n, i18n.language)}>
            <div className="tnum text-xl font-[650] tracking-tight">{filtered.length}</div>
            <div className="mt-0.5 text-xs text-text-muted">
              {t("instrumentDistribution.instrumentsLabel")}
            </div>
          </DonutChart>

          <HBarList
            items={barItems}
            formatValue={(n) => formatCurrency(n, i18n.language)}
            className="mt-4"
          />

          {filtered.length > VISIBLE_CAP && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-3 text-sm font-medium text-accent hover:underline"
            >
              {expanded
                ? t("instrumentDistribution.showLess")
                : t("instrumentDistribution.showAll", { count: filtered.length })}
            </button>
          )}
        </>
      )}
    </GlassCard>
  );
}
