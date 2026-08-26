import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api, getHealth, type DataQualityResponse } from "../../lib/api";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { hoursSince, STALE_OFFSITE_THRESHOLD_HOURS, STALE_THRESHOLD_HOURS } from "./utils";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

type DotState = "fresh" | "stale" | "unknown";

// "Unknown" (health failed to load) reads as neutral/muted rather than the
// alarming amber "stale" — ADR 0015's whole point is that the backup and
// NAS signals must not lie about each other, and asserting "stale" for all
// four dots from an /api/health 500 would be exactly that kind of lie.
function StatusDot({ label, state }: { label: string; state: DotState }) {
  const color =
    state === "fresh" ? "bg-positive" : state === "stale" ? "bg-warning" : "bg-text-muted";
  return (
    <div className="flex items-center gap-1.5">
      <span
        aria-hidden
        className={`size-2 shrink-0 rounded-full ${color}`}
        style={{
          boxShadow:
            state === "fresh"
              ? "var(--glow-positive)"
              : state === "stale"
                ? "0 0 6px color-mix(in srgb, var(--warning) 45%, transparent)"
                : "none",
        }}
      />
      <span className="text-text-muted">{label}</span>
    </div>
  );
}

/** Thin status strip: four freshness dots (prices / snapshot / backup /
 * offsite copy on the NAS) plus a data-quality issue count that expands
 * into the issue list. The backup and NAS dots are deliberately separate
 * signals reading separate markers (ADR 0015) — a sleeping NAS must not
 * make this strip claim there is no backup at all. */
export function FreshnessStrip() {
  const { t } = useTranslation("overview");
  const [expanded, setExpanded] = useState(false);

  const health = useCachedQuery({
    queryKey: ["health", "overview"],
    queryFn: getHealth,
  });

  const quality = useCachedQuery({
    queryKey: ["data-quality", "overview"],
    queryFn: () => api.get<DataQualityResponse>("/api/data-quality"),
  });

  const pending = useIsLoading(health.isPending, quality.isPending);

  if (pending) {
    return (
      <GlassCard>
        <Skeleton className="h-4 w-full max-w-md" />
      </GlassCard>
    );
  }

  const issues = quality.data?.issues ?? [];
  const qualityKnown = !quality.isError;
  // Same guard as qualityKnown above, previously missing here — a failed
  // /api/health was falling through to isFresh(undefined) === false for
  // all four dots, i.e. "everything is stale", which is a stronger and
  // false claim ("unknown" is not "confirmed stale").
  const healthKnown = !health.isError;

  const isFresh = (iso: string | null | undefined, threshold = STALE_THRESHOLD_HOURS) => {
    const hours = hoursSince(iso);
    return hours !== null && hours <= threshold;
  };
  const dotState = (iso: string | null | undefined, threshold = STALE_THRESHOLD_HOURS): DotState =>
    !healthKnown ? "unknown" : isFresh(iso, threshold) ? "fresh" : "stale";

  return (
    <GlassCard>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusDot label={t("freshness.prices")} state={dotState(health.data?.last_price_fetch)} />
          <StatusDot label={t("freshness.snapshot")} state={dotState(health.data?.last_snapshot)} />
          <StatusDot label={t("freshness.backup")} state={dotState(health.data?.last_backup)} />
          <StatusDot
            label={t("freshness.offsite")}
            state={dotState(health.data?.last_offsite_backup, STALE_OFFSITE_THRESHOLD_HOURS)}
          />
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          disabled={!qualityKnown || issues.length === 0}
          aria-expanded={expanded}
          aria-label={expanded ? t("freshness.collapse") : t("freshness.expand")}
          className="flex items-center gap-1.5 font-medium disabled:cursor-default"
        >
          <span className="text-text-muted">{t("freshness.dataQuality")}</span>
          <span
            className={
              !qualityKnown
                ? "text-text-muted"
                : issues.length === 0
                  ? "text-positive"
                  : "text-warning"
            }
          >
            {!qualityKnown
              ? t("common:status.error")
              : issues.length === 0
                ? t("freshness.issuesNone")
                : t("freshness.issuesCount", { count: issues.length })}
          </span>
          {qualityKnown && issues.length > 0 && (
            <ChevronDown
              aria-hidden
              className={`size-3.5 text-text-muted transition-transform ${expanded ? "rotate-180" : ""}`}
            />
          )}
        </button>
      </div>
      {expanded && issues.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-border pt-3 text-xs">
          {issues.map((issue, idx) => (
            <li key={idx} className="flex flex-wrap items-baseline gap-1.5">
              <span aria-hidden className="text-warning">
                ●
              </span>
              {issue.instrument_name && (
                <span className="font-medium text-text">{issue.instrument_name}</span>
              )}
              <span className="text-text-muted">
                {t(`freshness.kinds.${issue.kind}`, { defaultValue: issue.kind })}
              </span>
              <span className="text-text-muted/70">— {issue.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}
