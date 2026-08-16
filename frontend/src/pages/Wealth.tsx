import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  getAllocationTimeseries,
  type MilestoneResponse,
  type NetWorthPoint,
} from "../lib/api";
import { useAssetFilter } from "../lib/assetFilter";
import { AssetClassChips } from "../components/AssetClassChips";
import { PageHeader } from "../components/ui/PageHeader";
import { ClassMixCard } from "../components/wealth/ClassMixCard";
import { MilestoneJourney } from "../components/wealth/MilestoneJourney";
import { Replay } from "../components/wealth/Replay";
import { WealthCurveCard } from "../components/wealth/WealthCurveCard";
import { rangeFor, type Period } from "../components/wealth/util";

/**
 * The Wealth page: one curve, its composition, the whole history as a
 * scrubbable replay, and the milestone ladder.
 *
 * All four cards read from queries owned here rather than fetching for
 * themselves. Two reasons: the curve and the mix must always show the same
 * window (one query, one loading state, no chance of them disagreeing), and
 * the replay and the milestone journey both want the *full* history — one
 * month-granularity fetch serves both.
 */
export function Wealth() {
  const { t } = useTranslation("wealth");
  const { selected, allSelected } = useAssetFilter();

  const [period, setPeriod] = useState<Period>("1Y");
  const [real, setReal] = useState(false);

  const { from, granularity } = useMemo(() => rangeFor(period), [period]);

  // Windowed allocation — the curve card and the mix card share it.
  const windowQuery = useQuery({
    queryKey: ["allocationTimeseries", from ?? "all", granularity],
    queryFn: () => getAllocationTimeseries({ from, granularity }),
  });

  // Full history, monthly. At `MAX` this is literally the same query key as
  // the one above, so React Query serves both cards from one request.
  const historyQuery = useQuery({
    queryKey: ["allocationTimeseries", "all", "month"],
    queryFn: () => getAllocationTimeseries({ granularity: "month" }),
  });

  // CPI-deflated totals come from a different endpoint and cannot be filtered
  // (the deflation is applied server-side to the whole portfolio), so this
  // only runs when the user asked for real terms with nothing filtered out.
  const realQuery = useQuery({
    queryKey: ["networthReal", from ?? "all", granularity],
    queryFn: () => {
      const params = new URLSearchParams({
        scope: "net",
        granularity,
        real: "true",
      });
      if (from) params.set("from", from);
      return api.get<NetWorthPoint[]>(`/api/timeseries/networth?${params}`);
    },
    enabled: real && allSelected,
  });

  const milestoneQuery = useQuery({
    queryKey: ["milestones", "net"],
    queryFn: () => api.get<MilestoneResponse>("/api/milestones?scope=net"),
    enabled: allSelected,
  });

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")}>
        <AssetClassChips />
      </PageHeader>

      <WealthCurveCard
        points={windowQuery.data}
        realPoints={realQuery.data}
        selected={selected}
        allSelected={allSelected}
        isLoading={windowQuery.isPending}
        isRealLoading={realQuery.isPending}
        period={period}
        onPeriodChange={setPeriod}
        real={real}
        onRealChange={setReal}
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <ClassMixCard
          points={windowQuery.data}
          selected={selected}
          isLoading={windowQuery.isPending}
        />
        <Replay
          points={historyQuery.data}
          selected={selected}
          isLoading={historyQuery.isPending}
        />
      </div>

      <MilestoneJourney
        points={historyQuery.data}
        selected={selected}
        allSelected={allSelected}
        milestone={milestoneQuery.data}
        isLoading={historyQuery.isPending}
      />
    </div>
  );
}
