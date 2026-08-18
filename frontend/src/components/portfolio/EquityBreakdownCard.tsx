import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { DonutChart, type DonutSlice } from "../charts/DonutChart";
import { ChartLegend, type LegendItem } from "../charts/ChartLegend";
import { OTHER_COLOR, SERIES_COLORS } from "../charts/chartTheme";
import { formatCurrency } from "../../lib/format";
import {
  usePositionsWithInstruments,
  type PositionWithInstrument,
} from "./usePositionsWithInstruments";

/** Distinct hues available before the tail has to collapse into "other". */
const NAMED_SLICES = SERIES_COLORS.length;

/**
 * Section 3 — the equity book on its own: every holding as a share of the
 * whole, and how much of it is funds rather than single companies.
 *
 * Deliberately ignores the asset-class filter. The card *is* an asset-class
 * view (EQUITY), so intersecting it with the chip row could only ever
 * produce the same thing or nothing at all.
 *
 * Fund vs. single company comes from the `etf` tag, written by
 * scripts/apply-compositions.py out of docs/etf-compositions.json — the file
 * that already draws that line, since only a fund has a look-through.
 * Guessing from the name ("... UCITS ETF") would break silently the first
 * time a fund is named differently.
 */
export function EquityBreakdownCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { rows, isLoading, isError } = usePositionsWithInstruments();

  const holdings = useMemo(
    () =>
      (rows ?? [])
        .filter(
          (p) =>
            p.instrument?.asset_class === "EQUITY" &&
            p.value_eur !== null &&
            Number(p.value_eur) > 0,
        )
        .sort((a, b) => Number(b.value_eur) - Number(a.value_eur)),
    [rows],
  );

  const total = holdings.reduce((sum, p) => sum + Number(p.value_eur), 0);
  const money = (n: number) => formatCurrency(n, i18n.language);

  // Largest holdings keep their own hue; the tail becomes one neutral slice
  // rather than a second lap of the palette.
  const bySlice: DonutSlice[] = useMemo(() => {
    const named: DonutSlice[] = holdings.slice(0, NAMED_SLICES).map((p, i) => ({
      name: p.instrument!.name,
      value: Number(p.value_eur),
      color: SERIES_COLORS[i],
    }));
    const tail = holdings.slice(NAMED_SLICES);
    if (tail.length > 0) {
      named.push({
        name: t("equityBreakdown.other", { count: tail.length }),
        value: tail.reduce((sum, p) => sum + Number(p.value_eur), 0),
        color: OTHER_COLOR,
      });
    }
    return named;
  }, [holdings, t]);

  const byKind: DonutSlice[] = useMemo(() => {
    const isFund = (p: PositionWithInstrument) => p.instrument!.tags.includes("etf");
    const isDirect = (p: PositionWithInstrument) =>
      p.instrument!.tags.includes("direct");
    const bucket = (test: (p: PositionWithInstrument) => boolean) =>
      holdings.filter(test).reduce((sum, p) => sum + Number(p.value_eur), 0);

    const funds = bucket(isFund);
    const direct = bucket(isDirect);
    // Anything carrying neither tag is a gap in the classification, not a
    // single company — showing it as one would quietly overstate them.
    const unknown = bucket((p) => !isFund(p) && !isDirect(p));

    return [
      { name: t("equityBreakdown.funds"), value: funds, color: SERIES_COLORS[0] },
      { name: t("equityBreakdown.direct"), value: direct, color: SERIES_COLORS[1] },
      { name: t("equityBreakdown.unclassified"), value: unknown, color: OTHER_COLOR },
    ].filter((s) => s.value > 0);
  }, [holdings, t]);

  const toLegend = (slices: DonutSlice[]): LegendItem[] =>
    slices.map((s) => ({ key: s.name, label: s.name, color: s.color, value: s.value }));

  if (isLoading) {
    return (
      <GlassCard>
        <Skeleton className="h-5 w-48" />
        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <Skeleton className="mx-auto h-48 w-48 rounded-full" />
          <Skeleton className="mx-auto h-48 w-48 rounded-full" />
        </div>
      </GlassCard>
    );
  }

  if (isError) {
    return (
      <GlassCard>
        <h2 className="mb-2 font-medium">{t("equityBreakdown.title")}</h2>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  if (holdings.length === 0) {
    return (
      <GlassCard>
        <h2 className="mb-4 font-medium">{t("equityBreakdown.title")}</h2>
        <EmptyState title={t("common:status.empty")} />
      </GlassCard>
    );
  }

  return (
    <GlassCard>
      <h2 className="font-medium">{t("equityBreakdown.title")}</h2>
      <div className="mt-4 grid gap-8 md:grid-cols-2">
        <section>
          <h3 className="mb-2 text-sm text-text-muted">
            {t("equityBreakdown.byInstrument")}
          </h3>
          <DonutChart data={bySlice} height={200} formatValue={money}>
            <div className="tnum sensitive text-lg font-[650] tracking-tight">{money(total)}</div>
            <div className="mt-0.5 text-xs text-text-muted">
              {t("equityBreakdown.holdings", { count: holdings.length })}
            </div>
          </DonutChart>
          <ChartLegend
            items={toLegend(bySlice)}
            language={i18n.language}
            formatValue={money}
            className="mt-3"
          />
        </section>

        <section>
          <h3 className="mb-2 text-sm text-text-muted">{t("equityBreakdown.byKind")}</h3>
          <DonutChart data={byKind} height={200} formatValue={money} />
          <ChartLegend
            items={toLegend(byKind)}
            language={i18n.language}
            formatValue={money}
            className="mt-3"
          />
        </section>
      </div>
    </GlassCard>
  );
}
