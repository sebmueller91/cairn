import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { api, getHealth, type DataQualityResponse } from "../../lib/api";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { hoursSince, STALE_THRESHOLD_HOURS } from "./utils";

function StatusDot({ label, fresh }: { label: string; fresh: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        aria-hidden
        className={`size-2 shrink-0 rounded-full ${fresh ? "bg-positive" : "bg-warning"}`}
        style={{
          boxShadow: fresh
            ? "var(--glow-positive)"
            : "0 0 6px color-mix(in srgb, var(--warning) 45%, transparent)",
        }}
      />
      <span className="text-text-muted">{label}</span>
    </div>
  );
}

/** Thin status strip: three freshness dots (prices / snapshot / backup)
 * plus a data-quality issue count that expands into the issue list. */
export function FreshnessStrip() {
  const { t } = useTranslation("overview");
  const [expanded, setExpanded] = useState(false);

  const health = useQuery({
    queryKey: ["health", "overview"],
    queryFn: getHealth,
  });

  const quality = useQuery({
    queryKey: ["data-quality", "overview"],
    queryFn: () => api.get<DataQualityResponse>("/api/data-quality"),
  });

  if (health.isLoading || quality.isLoading) {
    return (
      <GlassCard>
        <Skeleton className="h-4 w-full max-w-md" />
      </GlassCard>
    );
  }

  const issues = quality.data?.issues ?? [];
  const qualityKnown = !quality.isError;

  const isFresh = (iso: string | null | undefined) => {
    const hours = hoursSince(iso);
    return hours !== null && hours <= STALE_THRESHOLD_HOURS;
  };

  return (
    <GlassCard>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusDot label={t("freshness.prices")} fresh={isFresh(health.data?.last_price_fetch)} />
          <StatusDot label={t("freshness.snapshot")} fresh={isFresh(health.data?.last_snapshot)} />
          <StatusDot label={t("freshness.backup")} fresh={isFresh(health.data?.last_backup)} />
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
