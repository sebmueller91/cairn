import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { api, type AllocationResponse } from "../../lib/api";
import { formatPercent } from "../../lib/format";
import { ASSET_CLASS_COLORS, assetClassLabelKey, type AssetClass } from "../../lib/assetClasses";

function DriftBadge({ driftPp, lang }: { driftPp: number; lang: string }) {
  const cls = driftPp > 0 ? "text-positive" : driftPp < 0 ? "text-negative" : "text-text-muted";
  return (
    <span className={`tnum shrink-0 text-xs font-medium ${cls}`}>
      {driftPp > 0 ? "+" : ""}
      {formatPercent(driftPp / 100, lang)}
    </span>
  );
}

function DriftRowView({
  assetClass,
  currentPct,
  targetPct,
  driftPp,
  lang,
  grown,
}: {
  assetClass: AssetClass;
  currentPct: number;
  targetPct: number;
  driftPp: number;
  lang: string;
  grown: boolean;
}) {
  const { t } = useTranslation(["portfolio", "common"]);
  const color = ASSET_CLASS_COLORS[assetClass];
  const current = Math.max(0, Math.min(100, currentPct));
  const target = Math.max(0, Math.min(100, targetPct));

  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-sm">
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
        <span className="truncate">{t(`common:${assetClassLabelKey(assetClass)}`)}</span>
        <span className="tnum ml-auto shrink-0 text-text-muted">
          {formatPercent(currentPct / 100, lang)} / {formatPercent(targetPct / 100, lang)}
        </span>
        <DriftBadge driftPp={driftPp} lang={lang} />
      </div>
      <div className="relative h-2 w-full rounded-full bg-border/60">
        <div
          className="h-full rounded-full"
          style={{
            width: grown ? `${current}%` : "0%",
            transition: "width 700ms cubic-bezier(0.22, 1, 0.36, 1)",
            background: `linear-gradient(90deg, ${color}, color-mix(in srgb, ${color} 15%, transparent))`,
            boxShadow: `0 0 10px color-mix(in srgb, ${color} 30%, transparent)`,
          }}
        />
        <div
          aria-hidden
          className="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 rounded-full bg-text"
          style={{ left: `${target}%` }}
        />
      </div>
    </div>
  );
}

/** Section 4 — target vs. actual allocation per asset class, read-only. */
export function TargetVsActualCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["allocation"],
    queryFn: () => api.get<AllocationResponse>("/api/allocation"),
  });

  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const rows = (data?.drift ?? []).filter(
    (r) => Number(r.current_pct) !== 0 || Number(r.target_pct) !== 0,
  );

  return (
    <GlassCard>
      <h2 className="mb-4 font-medium">{t("targetVsActual.title")}</h2>
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={t("common:status.empty")} />
      ) : (
        <div className="space-y-4">
          {rows.map((row) => (
            <DriftRowView
              key={row.asset_class}
              assetClass={row.asset_class as AssetClass}
              currentPct={Number(row.current_pct)}
              targetPct={Number(row.target_pct)}
              driftPp={Number(row.drift_pp)}
              lang={i18n.language}
              grown={grown}
            />
          ))}
        </div>
      )}
    </GlassCard>
  );
}
