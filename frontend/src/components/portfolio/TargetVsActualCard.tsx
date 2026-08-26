import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { api, type AllocationResponse } from "../../lib/api";
import { formatPercent } from "../../lib/format";
import { ASSET_CLASS_COLORS, assetClassLabelKey, type AssetClass } from "../../lib/assetClasses";
import { TargetAllocationModal } from "./TargetAllocationModal";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

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

/** Section 4 — target vs. actual allocation per asset class. */
export function TargetVsActualCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data, isPending, isError } = useCachedQuery({
    queryKey: ["allocation"],
    queryFn: () => api.get<AllocationResponse>("/api/allocation"),
  });
  const pending = useIsLoading(isPending);

  const [editing, setEditing] = useState(false);
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const rows = (data?.drift ?? []).filter(
    (r) => Number(r.current_pct) !== 0 || Number(r.target_pct) !== 0,
  );
  // Only the classes the drift actually covers are offered as targets — see
  // the note in TargetAllocationModal.
  const editableClasses = rows.map((r) => r.asset_class as AssetClass);
  const hasTargets = rows.some((r) => Number(r.target_pct) !== 0);

  return (
    <GlassCard>
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-medium">{t("targetVsActual.title")}</h2>
        <button
          type="button"
          onClick={() => setEditing(true)}
          disabled={editableClasses.length === 0}
          className="shrink-0 rounded-full border border-border px-3 py-1 text-xs font-medium text-text-muted transition-colors hover:border-accent hover:text-text disabled:opacity-40"
        >
          {t("targetVsActual.edit")}
        </button>
      </div>
      {/* Without this the card reads as contradicting the donut above: the
          rebalancing endpoint only counts tradeable positions, so a house
          shows as 0% here while it dominates the allocation chart. */}
      <p className="mb-4 mt-1 text-xs text-text-muted">{t("targetVsActual.scopeNote")}</p>
      {pending ? (
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
          {!hasTargets && (
            <p className="text-xs text-text-muted">{t("targetVsActual.noTargets")}</p>
          )}
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
      <TargetAllocationModal
        open={editing}
        onClose={() => setEditing(false)}
        classes={editableClasses}
      />
    </GlassCard>
  );
}
