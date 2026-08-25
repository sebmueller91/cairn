import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  getAllocationTimeseries,
  getCpiPoints,
  type MilestoneResponse,
} from "../lib/api";
import { useAssetFilter } from "../lib/assetFilter";
import { AssetClassChips } from "../components/AssetClassChips";
import { AssetPresetChips } from "../components/AssetPresetChips";
import { PageHeader } from "../components/ui/PageHeader";
import { ClassMixCard } from "../components/wealth/ClassMixCard";
import { MilestoneJourney } from "../components/wealth/MilestoneJourney";
import { OutlookCard } from "../components/wealth/OutlookCard";
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

  // Full history, monthly — the milestone journey needs every crossing ever,
  // not just the ones inside the selected window. At `MAX` this is literally
  // the same query key as the one above, so React Query serves both from one
  // request.
  const historyQuery = useQuery({
    queryKey: ["allocationTimeseries", "all", "month"],
    queryFn: () => getAllocationTimeseries({ granularity: "month" }),
  });

  // The CPI series itself, not a deflated total: deflation is a scalar per
  // date, so handing the client the index lets the real view follow the
  // asset filter instead of being restricted to the whole portfolio.
  const cpiQuery = useQuery({
    queryKey: ["cpi"],
    queryFn: getCpiPoints,
    staleTime: 24 * 60 * 60 * 1000,
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
        <AssetPresetChips />
      </PageHeader>

      <WealthCurveCard
        points={windowQuery.data}
        cpiPoints={cpiQuery.data}
        selected={selected}
        allSelected={allSelected}
        isLoading={windowQuery.isPending}
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
          points={windowQuery.data}
          selected={selected}
          isLoading={windowQuery.isPending}
        />
      </div>

      <MilestoneJourney
        points={historyQuery.data}
        selected={selected}
        allSelected={allSelected}
        milestone={milestoneQuery.data}
        isLoading={historyQuery.isPending}
      />

      {/* Last, deliberately: everything above it is recorded, this one is
          an assumption, and the page should read in that order. Shares the
          full-history query with the milestone ladder above. */}
      <OutlookCard
        history={historyQuery.data}
        selected={selected}
        allSelected={allSelected}
        isLoading={historyQuery.isPending}
      />
    </div>
  );
}
