import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Flag } from "lucide-react";
import type { AllocationTimeseriesPoint, MilestoneResponse } from "../../lib/api";
import {
  findCrossings,
  linearProjection,
  milestoneLadder,
  sumSelected,
} from "../../lib/allocationSeries";
import {
  ASSET_CLASSES,
  assetClassLabelKey,
  type AssetClass,
} from "../../lib/assetClasses";
import { formatNumber } from "../../lib/format";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { ProgressArc } from "../ui/ProgressArc";
import { Skeleton } from "../ui/Skeleton";
import { formatMonthYear } from "./util";

type NodeKind = "crossed" | "next" | "upcoming";

interface JourneyNode {
  milestone: number;
  kind: NodeKind;
  /** Set on crossed nodes only. */
  date?: string;
}

/** Compact currency — "100 Tsd. €" — so nine nodes fit on one line. */
function compactEuro(value: number, lang: string): string {
  return formatNumber(value, lang, {
    style: "currency",
    currency: "EUR",
    notation: "compact",
    maximumFractionDigits: 1,
  });
}

function Dot({ crossed }: { crossed: boolean }) {
  return crossed ? (
    <span
      aria-hidden
      className="block size-3.5 rounded-full bg-accent"
      style={{ boxShadow: "var(--glow-accent)" }}
    />
  ) : (
    <span
      aria-hidden
      className="block size-3.5 rounded-full border border-border bg-bg-subtle"
    />
  );
}

/**
 * The 1/2/5 ladder as a path already walked.
 *
 * The ladder is derived from the highest value ever reached, so the last rung
 * is always still ahead — that one gets a ProgressArc and a projected date
 * instead of a dot and a memory.
 */
export function MilestoneJourney({
  points,
  selected,
  allSelected,
  milestone,
  isLoading,
}: {
  /** Full history at month granularity. */
  points: AllocationTimeseriesPoint[] | undefined;
  selected: Set<AssetClass>;
  allSelected: boolean;
  /** Server-side milestone, only meaningful (and only fetched) when unfiltered. */
  milestone: MilestoneResponse | undefined;
  isLoading: boolean;
}) {
  const { t, i18n } = useTranslation(["wealth", "common"]);

  const series = useMemo(
    () => sumSelected(points ?? [], selected),
    [points, selected],
  );

  const journey = useMemo(() => {
    if (series.length === 0) return null;

    const peak = series.reduce((max, p) => Math.max(max, p.value), 0);
    const ladder = milestoneLadder(peak);
    const crossed = new Map(
      findCrossings(series, ladder).map((c) => [c.milestone, c.date]),
    );

    // The ladder's last rung is > peak by construction, so an uncrossed one
    // always exists.
    const next = ladder.find((m) => !crossed.has(m)) ?? ladder[ladder.length - 1];
    // One rung past `next`, shown faintly so the path visibly continues.
    const beyond = milestoneLadder(next);
    const upcoming = beyond[beyond.length - 1];

    const nodes: JourneyNode[] = ladder
      .filter((m) => crossed.has(m))
      .map((m) => ({ milestone: m, kind: "crossed" as const, date: crossed.get(m) }));
    nodes.push({ milestone: next, kind: "next" });
    if (upcoming > next) nodes.push({ milestone: upcoming, kind: "upcoming" });

    return { nodes, next, current: series[series.length - 1].value };
  }, [series]);

  const subtitle = useMemo(() => {
    if (allSelected) return null;
    return ASSET_CLASSES.filter((c) => selected.has(c))
      .map((c) => t(assetClassLabelKey(c), { ns: "common" }))
      .join(" + ");
  }, [allSelected, selected, t]);

  // The server's estimate is computed for *its* next milestone, off the total
  // portfolio. It only answers the question on screen when the filter is off
  // AND the two ladders agree on which rung is next; otherwise fall back to
  // the client-side fit, clearly marked as an estimate.
  const serverDate =
    allSelected &&
    milestone?.estimated_date &&
    journey &&
    Number(milestone.next_milestone_eur) === journey.next
      ? milestone.estimated_date
      : null;

  const projectedDate = useMemo(
    () => (serverDate || !journey ? null : linearProjection(series, journey.next)),
    [serverDate, journey, series],
  );

  const pct =
    journey && journey.next > 0
      ? (journey.current / journey.next) * 100
      : 0;

  function projectionLabel(): string {
    if (serverDate) return formatMonthYear(serverDate, i18n.language);
    if (projectedDate) return `≈ ${formatMonthYear(projectedDate, i18n.language)}`;
    return t("milestones.noProjection");
  }

  function nodeCore(node: JourneyNode) {
    if (node.kind !== "next") return <Dot crossed={node.kind === "crossed"} />;
    return (
      <ProgressArc pct={pct} size={76} strokeWidth={7} label={`${Math.round(pct)}%`} />
    );
  }

  function nodeDate(node: JourneyNode): string {
    if (node.kind === "crossed") {
      return node.date ? formatMonthYear(node.date, i18n.language) : "";
    }
    if (node.kind === "next") return projectionLabel();
    return "";
  }

  return (
    <GlassCard>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-text-muted">
          {t("milestones.title")}
        </h2>
        {subtitle && (
          <p className="text-xs text-text-muted/70">{subtitle}</p>
        )}
      </div>

      {isLoading ? (
        <div className="mt-6 flex items-end gap-6">
          <Skeleton className="h-20 w-full" />
        </div>
      ) : !journey ? (
        <EmptyState
          icon={<Flag className="size-8" aria-hidden />}
          title={t("empty.title")}
          hint={t("empty.hint")}
        />
      ) : (
        <>
          {/* Desktop: a path walked left to right. Scrolls sideways rather
              than squeezing, so a long history stays legible. */}
          <ol className="no-scrollbar mt-2 hidden overflow-x-auto md:flex">
            {journey.nodes.map((node, i) => {
              const first = i === 0;
              const last = i === journey.nodes.length - 1;
              return (
                <li
                  key={node.milestone}
                  className="flex min-w-[7.5rem] flex-1 flex-col items-center"
                >
                  <div
                    className={`tnum h-8 text-center text-sm font-medium ${
                      node.kind === "upcoming" ? "text-text-muted/50" : ""
                    }`}
                  >
                    {compactEuro(node.milestone, i18n.language)}
                  </div>
                  <div className="relative flex h-24 w-full items-center justify-center">
                    {/* Each column paints its own segment of the path, so the
                        line is centred on the nodes without any magic offset. */}
                    <div
                      aria-hidden
                      className={`absolute top-1/2 h-px -translate-y-1/2 bg-border ${
                        first ? "left-1/2 right-0" : last ? "left-0 right-1/2" : "inset-x-0"
                      }`}
                    />
                    <div className="relative">{nodeCore(node)}</div>
                  </div>
                  <div className="h-8 pt-1 text-center text-xs text-text-muted">
                    {nodeDate(node)}
                  </div>
                </li>
              );
            })}
          </ol>

          {/* Mobile: the same nodes, stacked. The rail is a sibling of the
              list, not a child — an <ol> may only contain <li>. */}
          <div className="relative mt-4 md:hidden">
            <div
              aria-hidden
              className="absolute bottom-3 left-[6px] top-3 w-px bg-border"
            />
            <ol className="space-y-4 pl-7">
              {journey.nodes.map((node) => (
                <li
                  key={node.milestone}
                  className="relative flex items-center gap-3"
                >
                  <span className="absolute -left-7 top-1/2 -translate-y-1/2">
                    <Dot crossed={node.kind === "crossed"} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div
                      className={`tnum text-sm font-medium ${
                        node.kind === "upcoming" ? "text-text-muted/50" : ""
                      }`}
                    >
                      {compactEuro(node.milestone, i18n.language)}
                    </div>
                    <div className="text-xs text-text-muted">
                      {node.kind === "crossed"
                        ? t("milestones.reached", { date: nodeDate(node) })
                        : node.kind === "next"
                          ? t("milestones.projected", { date: nodeDate(node) })
                          : t("milestones.later")}
                    </div>
                  </div>
                  {node.kind === "next" && (
                    <ProgressArc
                      pct={pct}
                      size={56}
                      strokeWidth={5}
                      label={`${Math.round(pct)}%`}
                    />
                  )}
                </li>
              ))}
            </ol>
          </div>

          {!serverDate && projectedDate && (
            <p className="mt-4 text-xs text-text-muted/70">
              {t("milestones.estimateNote")}
            </p>
          )}
        </>
      )}
    </GlassCard>
  );
}
