// Pure transforms behind the Wealth page. Nothing here touches React, the
// network or the DOM, which is why it is the one part of that page covered
// by unit tests (`allocationSeries.test.ts`).
//
// DECIMAL BOUNDARY: ADR 0001 keeps money as strings all the way from the
// API so a float can never sneak into arithmetic that matters. These
// functions convert to `number` on purpose — everything downstream of them
// is chart geometry (pixels, widths, a regression slope), where a float is
// the correct representation and a Decimal would be theatre. Nothing here
// feeds a value back into a write path.

import type { AllocationTimeseriesPoint } from "./api";
import { ASSET_CLASSES, type AssetClass } from "./assetClasses";

export interface SeriesPoint {
  date: string;
  value: number;
}

export interface MixEntry {
  cls: AssetClass;
  value: number;
}

export interface Crossing {
  milestone: number;
  date: string;
}

const DAY_MS = 86_400_000;

/** Trailing window the projection fits, in days. */
const FIT_WINDOW_DAYS = 365;

/**
 * Beyond this, a projection stops being information. A near-flat slope can
 * put "1 Mio." four centuries out; showing that is worse than showing
 * nothing, because a rendered date reads as a forecast either way.
 */
const MAX_HORIZON_DAYS = 365.25 * 30;

function toNumber(raw: string | undefined): number {
  if (raw === undefined) return 0;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Collapses the per-class buckets into one total per date, counting only
 * `classes`. A key missing from `values` means zero for that date (the
 * backend only emits buckets that had a row), and LIABILITY arrives
 * negative — so a selection that includes it subtracts, as it should.
 */
export function sumSelected(
  points: AllocationTimeseriesPoint[],
  classes: Set<AssetClass>,
): SeriesPoint[] {
  return points.map((point) => {
    let total = 0;
    for (const cls of classes) total += toNumber(point.values[cls]);
    return { date: point.date, value: total };
  });
}

/**
 * The selected classes of a single point, in ASSET_CLASSES order so a
 * stacked bar or legend built from it never reshuffles between frames.
 * Classes with no bucket come back as 0 rather than being dropped.
 */
export function latestMix(
  point: AllocationTimeseriesPoint | undefined,
  classes: Set<AssetClass>,
): MixEntry[] {
  if (!point) return [];
  return ASSET_CLASSES.filter((cls) => classes.has(cls)).map((cls) => ({
    cls,
    value: toNumber(point.values[cls]),
  }));
}

const STEP_MULTIPLIERS = [1, 2, 5] as const;

/**
 * Ascending 1/2/5 x 10^n "nice" numbers from 1 000 up to and including the
 * first entry strictly greater than `maxValue` — so the last element is
 * always the milestone still ahead.
 *
 * Mirrors `milestones_service.next_round_number` on the backend, including
 * its deliberate gaps: 100k is followed by 200k, not 150k. A milestone is
 * meant to be a number worth celebrating, not every round-ish figure, and
 * the two implementations must agree or the server's "next milestone" would
 * land between two nodes of this ladder.
 */
export function milestoneLadder(maxValue: number): number[] {
  const ceiling = Number.isFinite(maxValue) ? maxValue : 0;
  const ladder: number[] = [];
  // 10^3 (1 000) up to 10^15 — a bound, not an expectation.
  for (let exponent = 3; exponent <= 15; exponent++) {
    const power = 10 ** exponent;
    for (const multiplier of STEP_MULTIPLIERS) {
      const candidate = multiplier * power;
      ladder.push(candidate);
      if (candidate > ceiling) return ladder;
    }
  }
  return ladder;
}

/**
 * The first date each milestone was reached.
 *
 * RE-CROSSING: a milestone that is passed, lost in a drawdown and passed
 * again keeps its FIRST date. "You first hit 100k in March 2024" is a fact
 * about the history that a later dip does not undo, and a journey whose
 * labels move backwards and forwards as the market swings would be unreadable.
 * `find` returning the earliest match is exactly that rule.
 *
 * Milestones never reached are absent from the result rather than present
 * with a null date, so the caller can treat presence as "crossed".
 */
export function findCrossings(
  series: SeriesPoint[],
  ladder: number[],
): Crossing[] {
  const crossings: Crossing[] = [];
  for (const milestone of ladder) {
    const hit = series.find((point) => point.value >= milestone);
    if (hit) crossings.push({ milestone, date: hit.date });
  }
  return crossings;
}

/**
 * When a straight line through the trailing ~365 days would reach `target`.
 *
 * Ordinary least squares on (days since the window's first point, value).
 * Returns an ISO date, or null when the question has no honest answer:
 * fewer than two points in the window, a flat or falling trend, a target
 * already reached, or a slope so shallow the crossing is decades away.
 */
export function linearProjection(
  series: SeriesPoint[],
  target: number,
): string | null {
  if (series.length < 2 || !Number.isFinite(target)) return null;

  const last = series[series.length - 1];
  const lastMs = Date.parse(last.date);
  if (Number.isNaN(lastMs)) return null;
  if (last.value >= target) return null;

  const windowStart = lastMs - FIT_WINDOW_DAYS * DAY_MS;
  const window = series.filter((point) => {
    const ms = Date.parse(point.date);
    return !Number.isNaN(ms) && ms >= windowStart;
  });
  if (window.length < 2) return null;

  const originMs = Date.parse(window[0].date);
  const xs = window.map((point) => (Date.parse(point.date) - originMs) / DAY_MS);
  const ys = window.map((point) => point.value);
  const n = xs.length;

  const meanX = xs.reduce((a, b) => a + b, 0) / n;
  const meanY = ys.reduce((a, b) => a + b, 0) / n;

  let covariance = 0;
  let variance = 0;
  for (let i = 0; i < n; i++) {
    covariance += (xs[i] - meanX) * (ys[i] - meanY);
    variance += (xs[i] - meanX) ** 2;
  }
  // All points share one date: no slope is defined, not a slope of zero.
  if (variance === 0) return null;

  const slope = covariance / variance;
  // `!(slope > 0)` rather than `slope <= 0` so NaN falls through here too.
  if (!(slope > 0)) return null;

  const intercept = meanY - slope * meanX;
  const targetX = (target - intercept) / slope;
  if (!Number.isFinite(targetX)) return null;

  const lastX = xs[n - 1];
  if (targetX - lastX > MAX_HORIZON_DAYS) return null;

  // The fitted line can already sit above `target` at the last observation
  // even though the actual value does not — a noisy final point. "Now" is
  // the honest answer there; a date in the past is not.
  const projectedX = Math.max(targetX, lastX);
  return new Date(originMs + projectedX * DAY_MS).toISOString().slice(0, 10);
}

export interface CpiPoint {
  date: string;
  index_value: string;
}

/**
 * Restates a series in the purchasing power of the newest CPI reading:
 * `nominal(t) * CPI(latest) / CPI(t)`, looked up by carry-forward against
 * a typically monthly index.
 *
 * A direct port of backend `real_wealth_service.deflate_series`, and it has
 * to stay one. The backend applies this to the whole portfolio; doing it
 * here as well is what lets the real view follow the asset filter, since
 * deflation is a scalar per date and therefore distributes over any subset
 * of the classes being summed.
 *
 * Points older than the first CPI reading come back untouched rather than
 * dropped — there is nothing to deflate against yet, and shortening the
 * series would silently misalign it with the nominal one.
 */
export function deflateSeries(
  series: SeriesPoint[],
  cpiPoints: CpiPoint[],
): SeriesPoint[] {
  if (cpiPoints.length === 0) return series;
  const sorted = [...cpiPoints].sort((a, b) => a.date.localeCompare(b.date));
  const latest = Number(sorted[sorted.length - 1].index_value);
  if (!Number.isFinite(latest) || latest === 0) return series;

  let idx = -1;
  let current: number | null = null;
  return series.map((point) => {
    while (idx + 1 < sorted.length && sorted[idx + 1].date <= point.date) {
      idx += 1;
      current = Number(sorted[idx].index_value);
    }
    if (current === null || !Number.isFinite(current) || current === 0) return point;
    return { date: point.date, value: (point.value * latest) / current };
  });
}
