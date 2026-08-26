import { useTranslation } from "react-i18next";
import { PageHeader } from "../components/ui/PageHeader";
import { AssetClassChips } from "../components/AssetClassChips";
import { AssetPresetChips } from "../components/AssetPresetChips";
import { ClassDistributionCard } from "../components/portfolio/ClassDistributionCard";
import { InstrumentDistributionCard } from "../components/portfolio/InstrumentDistributionCard";
import { ConcentrationCard } from "../components/portfolio/ConcentrationCard";
import { EquityBreakdownCard } from "../components/portfolio/EquityBreakdownCard";
import { EtfSplitCard } from "../components/portfolio/EtfSplitCard";
import { LookThroughCard } from "../components/portfolio/LookThroughCard";
import { TargetVsActualCard } from "../components/portfolio/TargetVsActualCard";
import { RealAssetsLoansCard } from "../components/portfolio/RealAssetsLoansCard";

export function Portfolio() {
  const { t } = useTranslation("portfolio");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")}>
        <AssetClassChips />
        <AssetPresetChips />
      </PageHeader>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ClassDistributionCard />
        <InstrumentDistributionCard />
      </div>

      <ConcentrationCard />
      <EquityBreakdownCard />
      <EtfSplitCard />
      <LookThroughCard />
      <TargetVsActualCard />
      <RealAssetsLoansCard />
    </div>
  );
}
