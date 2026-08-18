import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { History, Pause, Play } from "lucide-react";
import type { AllocationTimeseriesPoint } from "../../lib/api";
import { latestMix, sumSelected } from "../../lib/allocationSeries";
import {
  ASSET_CLASS_COLORS,
  assetClassLabelKey,
  type AssetClass,
} from "../../lib/assetClasses";
import { formatCurrency } from "../../lib/format";
import { prefersReducedMotion } from "../../lib/motion";
import { GradientAreaChart } from "../charts/GradientAreaChart";
import { CHART_MARGINS } from "../charts/chartTheme";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { formatMonthYear } from "./util";

/**
 * The whole point of this card is a value that changes ~60 times a second
 * while the chart underneath it does not move at all. `memo` is what makes
 * that true: every prop handed to it below is referentially stable across
 * frames (`useMemo` data, `useCallback` formatter, literal height), so the
 * shallow compare short-circuits and Recharts never re-runs its layout.
 * Without this, scrubbing would re-render an SVG with hundreds of nodes on
 * every frame and drop to single-digit fps on a phone.
 */
const ReplayChart = memo(GradientAreaChart);

const CHART_HEIGHT = 220;

/**
 * Width of GradientAreaChart's `<YAxis orientation="right" width={56}>`.
 *
 * DEVIATION, deliberate: chartTheme's note says the plot area is the
 * container minus CHART_MARGINS, but Recharts also insets the plot by the
 * axis width on whichever side the axis lives. Using margins alone puts the
 * cursor up to 56px right of its data point at the end of the series —
 * exactly the "looks like a data problem" failure that note warns about.
 * The margins are still the left/right terms; this is the third one.
 */
const Y_AXIS_WIDTH = 56;

/** Milliseconds a full replay may take, however long the history is. */
const MAX_REPLAY_MS = 12_000;
/** ...and how long a single step gets when the history is short. */
const MS_PER_STEP = 80;

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Scrub through the whole history and watch the mix rearrange itself. */
export function Replay({
  points,
  selected,
  isLoading,
}: {
  /** The *selected* window, at whatever granularity that period uses —
   * same series the curve above it draws. Replaying a range the page is not
   * showing made the scrubber disagree with the chart beside it. */
  points: AllocationTimeseriesPoint[] | undefined;
  selected: Set<AssetClass>;
  isLoading: boolean;
}) {
  const { t, i18n } = useTranslation(["wealth", "common"]);

  const series = useMemo(
    () => sumSelected(points ?? [], selected),
    [points, selected],
  );
  const total = series.length;
  const maxFrame = Math.max(total - 1, 0);

  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  // The rAF loop reads the current position without re-subscribing itself to
  // `frame`; re-running the effect 60x a second would restart the animation.
  const frameRef = useRef(0);
  const initialised = useRef(false);

  const setFrameBoth = useCallback((next: number) => {
    frameRef.current = next;
    setFrame(next);
  }, []);

  // First real data: rewind and play. Reduced motion parks at the present
  // instead — the scrubber below still works, it just never moves on its own.
  useEffect(() => {
    if (maxFrame <= 0) return;
    if (initialised.current) {
      if (frameRef.current > maxFrame) setFrameBoth(maxFrame);
      return;
    }
    initialised.current = true;
    if (prefersReducedMotion()) {
      setFrameBoth(maxFrame);
      return;
    }
    setFrameBoth(0);
    setPlaying(true);
  }, [maxFrame, setFrameBoth]);

  useEffect(() => {
    if (!playing || maxFrame <= 0) return;

    // Pressing play at the end replays from the start rather than doing
    // nothing, which is what every media control in the world does.
    const start = frameRef.current >= maxFrame ? 0 : frameRef.current;
    const fullSpan = Math.min(MAX_REPLAY_MS, total * MS_PER_STEP);
    // Resuming from halfway takes half as long — a constant duration would
    // make a short remainder crawl.
    const duration = Math.max(fullSpan * ((maxFrame - start) / maxFrame), 250);

    let raf = 0;
    let t0: number | null = null;
    const step = (now: number) => {
      if (t0 === null) t0 = now;
      const progress = Math.min((now - t0) / duration, 1);
      setFrameBoth(start + (maxFrame - start) * progress);
      if (progress < 1) raf = requestAnimationFrame(step);
      else setPlaying(false);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, maxFrame, total, setFrameBoth]);

  // --- driven readouts -----------------------------------------------------

  const lower = Math.min(Math.floor(frame), maxFrame);
  const upper = Math.min(lower + 1, maxFrame);
  const t01 = frame - lower;

  const value =
    total > 0 ? lerp(series[lower].value, series[upper].value, t01) : 0;
  // The date snaps to the nearest bucket: an interpolated month label would
  // read as false precision on a month-granularity series.
  const dateLabel =
    total > 0
      ? formatMonthYear(series[Math.round(frame)].date, i18n.language)
      : "—";

  const mix = useMemo(() => {
    if (!points || points.length === 0) return [];
    const a = latestMix(points[lower], selected);
    const b = latestMix(points[upper], selected);
    return a.map((entry, i) => ({
      cls: entry.cls,
      value: lerp(entry.value, b[i]?.value ?? entry.value, t01),
    }));
  }, [points, selected, lower, upper, t01]);

  const positives = mix.filter((m) => m.value > 0);
  const positiveTotal = positives.reduce((sum, m) => sum + m.value, 0);
  const liability = mix.find((m) => m.cls === "LIABILITY")?.value ?? 0;
  // Debt is drawn against the same baseline as the mix bar, so "half the bar
  // wide" reads as "debt is half of what you own".
  const liabilityShare =
    positiveTotal > 0 ? Math.min(Math.abs(liability) / positiveTotal, 1) : 0;

  // --- cursor geometry -----------------------------------------------------

  const plotRef = useRef<HTMLDivElement>(null);
  const [plotWidth, setPlotWidth] = useState(0);

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    setPlotWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setPlotWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const plotLeft = CHART_MARGINS.left;
  const plotRight = Math.max(
    plotWidth - CHART_MARGINS.right - Y_AXIS_WIDTH,
    plotLeft,
  );
  const cursorX =
    maxFrame > 0 ? plotLeft + (frame / maxFrame) * (plotRight - plotLeft) : plotLeft;

  // --- stable chart props --------------------------------------------------

  const formatValue = useCallback(
    (n: number) => formatCurrency(n, i18n.language),
    [i18n.language],
  );

  return (
    <GlassCard className="flex flex-col">
      <h2 className="text-sm font-medium text-text-muted">{t("replay.title")}</h2>

      {isLoading ? (
        <div className="mt-4 space-y-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-52" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-[220px] w-full" />
        </div>
      ) : total === 0 ? (
        <EmptyState
          icon={<History className="size-8" aria-hidden />}
          title={t("empty.title")}
          hint={t("empty.hint")}
        />
      ) : (
        <>
          {/* Readouts sit above the chart: the eye lands on the number that
              is moving, and the curve stays a stable backdrop. */}
          <div className="mt-4">
            <div className="tnum text-xs font-medium uppercase tracking-[0.18em] text-accent">
              {dateLabel}
            </div>
            <div className="tnum mt-1 text-3xl font-[650] tracking-tight md:text-4xl">
              {formatCurrency(value, i18n.language)}
            </div>
          </div>

          <div className="mt-4 space-y-1.5">
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-bg-subtle">
              {positives.map((entry) => (
                <div
                  key={entry.cls}
                  title={`${t(assetClassLabelKey(entry.cls), { ns: "common" })} · ${formatCurrency(entry.value, i18n.language)}`}
                  className="h-full min-w-0"
                  style={{
                    width: `${(entry.value / positiveTotal) * 100}%`,
                    backgroundColor: ASSET_CLASS_COLORS[entry.cls],
                  }}
                />
              ))}
            </div>
            {liability < 0 && (
              <div className="flex h-1.5 w-full">
                <div
                  title={`${t(assetClassLabelKey("LIABILITY"), { ns: "common" })} · ${formatCurrency(liability, i18n.language)}`}
                  className="h-full rounded-full"
                  style={{
                    width: `${liabilityShare * 100}%`,
                    backgroundColor: ASSET_CLASS_COLORS.LIABILITY,
                  }}
                />
              </div>
            )}
          </div>

          <div ref={plotRef} className="relative mt-4">
            <ReplayChart
              data={series}
              formatValue={formatValue}
              height={CHART_HEIGHT}
            />
            <div
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 w-px"
              style={{
                height: CHART_HEIGHT,
                transform: `translateX(${cursorX}px)`,
                // Short enough to feel attached to the scrubber, long enough
                // to smooth a dropped frame.
                transition: "transform 70ms linear",
                background: "var(--accent)",
                boxShadow: "0 0 10px 1px var(--accent)",
                opacity: plotWidth > 0 ? 0.9 : 0,
              }}
            />
          </div>

          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => setPlaying((p) => !p)}
              aria-label={playing ? t("replay.pause") : t("replay.play")}
              className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-accent text-accent-fg shadow-glow-accent transition-transform hover:scale-105 active:scale-95"
            >
              {playing ? (
                <Pause className="size-5" aria-hidden />
              ) : (
                <Play className="size-5 translate-x-px" aria-hidden />
              )}
            </button>
            <input
              type="range"
              min={0}
              max={maxFrame}
              step={0.01}
              value={frame}
              aria-label={t("replay.scrub")}
              aria-valuetext={dateLabel}
              onChange={(e) => {
                // Taking the scrubber pauses playback — otherwise the loop
                // would fight the pointer for the same value.
                setPlaying(false);
                setFrameBoth(Number(e.target.value));
              }}
              style={{
                background: `linear-gradient(to right, var(--accent) ${
                  maxFrame > 0 ? (frame / maxFrame) * 100 : 0
                }%, var(--border) 0%)`,
              }}
              className={
                "h-1.5 w-full cursor-pointer appearance-none rounded-full outline-none " +
                "[&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-glow-accent " +
                "[&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-accent"
              }
            />
          </div>
        </>
      )}
    </GlassCard>
  );
}
