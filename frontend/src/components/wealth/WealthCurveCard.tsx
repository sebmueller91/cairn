import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { TrendingUp } from "lucide-react";
import type { AllocationTimeseriesPoint, CpiIndexPointRead } from "../../lib/api";
import type { AssetClass } from "../../lib/assetClasses";
import { deflateSeries, sumSelected } from "../../lib/allocationSeries";
import { formatCurrency, formatPercent } from "../../lib/format";
import { GradientAreaChart } from "../charts/GradientAreaChart";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Skeleton } from "../ui/Skeleton";
import { StatHero } from "../ui/StatHero";
import { PERIODS, type Period } from "./util";

/**
 * Nominal/real switch.
 *
 * Not a SegmentedControl: real terms are server-side CPI deflation of the
 * *total* net worth, so the option has to be disabled — with a reason the
 * user can actually read — whenever the asset filter is narrowed.
 * SegmentedControl has no per-option disabled state, and giving it one
 * would change a primitive four other pages share.
 */
function ModeToggle({
  real,
  onChange,
  disabled,
  disabledHint,
}: {
  real: boolean;
  onChange: (real: boolean) => void;
  disabled: boolean;
  disabledHint: string;
}) {
  const { t } = useTranslation("wealth");
  const options: { value: boolean; label: string }[] = [
    { value: false, label: t("mode.nominal") },
    { value: true, label: t("mode.real") },
  ];

  return (
    <div
      role="tablist"
      title={disabled ? disabledHint : undefined}
      className="inline-flex shrink-0 gap-1 rounded-full border border-border bg-bg-subtle p-1"
    >
      {options.map((opt) => {
        const active = opt.value === real;
        const locked = disabled && opt.value;
        return (
          <button
            key={String(opt.value)}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={locked}
            title={locked ? disabledHint : undefined}
            onClick={() => onChange(opt.value)}
            className={`min-h-8 shrink-0 rounded-full px-3 text-xs font-medium transition-colors ${
              active
                ? "bg-accent text-accent-fg shadow-glow-accent"
                : locked
                  ? "cursor-not-allowed text-text-muted/45"
                  : "text-text-muted hover:text-text"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** The hero panel: one curve, the value it ends on, and how it got there. */
export function WealthCurveCard({
  points,
  cpiPoints,
  selected,
  allSelected,
  isLoading,
  period,
  onPeriodChange,
  real,
  onRealChange,
}: {
  points: AllocationTimeseriesPoint[] | undefined;
  cpiPoints: CpiIndexPointRead[] | undefined;
  selected: Set<AssetClass>;
  allSelected: boolean;
  isLoading: boolean;
  period: Period;
  onPeriodChange: (p: Period) => void;
  real: boolean;
  onRealChange: (real: boolean) => void;
}) {
  const { t, i18n } = useTranslation("wealth");

  const nominal = useMemo(
    () => sumSelected(points ?? [], selected),
    [points, selected],
  );
  // Deflating the already-filtered sum, rather than asking the server for a
  // deflated total, is what lets real terms follow the asset filter:
  // CPI(latest)/CPI(t) is a scalar per date, so it distributes over whatever
  // subset of classes went into the sum. With no CPI loaded this returns the
  // series untouched, which is why the toggle used to look broken.
  const deflated = useMemo(
    () => deflateSeries(nominal, cpiPoints ?? []),
    [nominal, cpiPoints],
  );

  const realActive = real && (cpiPoints?.length ?? 0) > 0;
  const series = realActive ? deflated : nominal;
  const loading = isLoading;

  const formatValue = useCallback(
    (n: number) => formatCurrency(n, i18n.language),
    [i18n.language],
  );

  const first = series.length > 0 ? series[0].value : 0;
  const last = series.length > 0 ? series[series.length - 1].value : 0;
  const delta = last - first;
  // A percentage off a zero (or sign-flipping) base is noise, not information.
  const pct =
    series.length > 1 && first !== 0 && Math.sign(first) === Math.sign(last)
      ? delta / Math.abs(first)
      : null;

  return (
    <GlassCard glow className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-text-muted">
          {t("curve.title")}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <ModeToggle
            real={realActive}
            onChange={onRealChange}
            disabled={(cpiPoints?.length ?? 0) === 0}
            disabledHint={t("mode.realDisabled")}
          />
          <SegmentedControl
            options={PERIODS.map((p) => ({ value: p, label: t(`period.${p}`) }))}
            value={period}
            onChange={onPeriodChange}
          />
        </div>
      </div>

      {loading ? (
        <div className="mt-5 space-y-4">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-12 w-64" />
          <Skeleton className="h-[280px] w-full" />
        </div>
      ) : series.length === 0 ? (
        <EmptyState
          icon={<TrendingUp className="size-8" aria-hidden />}
          title={t("empty.title")}
          hint={t("empty.hint")}
        />
      ) : (
        <>
          <StatHero
            className="mt-4"
            label={
              realActive
                ? t("curve.labelReal")
                : allSelected
                  ? t("curve.labelNet")
                  : t("curve.labelSelection")
            }
            value={last}
            format={formatValue}
            sensitive
            delta={series.length > 1 ? delta : undefined}
            formatDelta={(n) =>
              `${n >= 0 ? "+" : "−"}${formatCurrency(Math.abs(n), i18n.language)}`
            }
          >
            <div className="text-xs text-text-muted">
              {t("curve.window", { period: t(`period.${period}`) })}
              {pct !== null && (
                <span
                  className={`tnum ml-2 font-medium ${
                    delta >= 0 ? "text-positive" : "text-negative"
                  }`}
                >
                  {pct >= 0 ? "+" : ""}
                  {formatPercent(pct, i18n.language)}
                </span>
              )}
            </div>
          </StatHero>

          <div className="mt-4">
            <GradientAreaChart data={series} formatValue={formatValue} />
          </div>
        </>
      )}
    </GlassCard>
  );
}
