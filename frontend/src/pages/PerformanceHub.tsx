import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "../components/ui/PageHeader";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { AssetClassChips } from "../components/AssetClassChips";
import { AssetPresetChips } from "../components/AssetPresetChips";
import { ReturnsTab } from "../components/performance/ReturnsTab";
import { AttributionTab } from "../components/performance/AttributionTab";
import { TaxTab } from "../components/performance/TaxTab";

type Tab = "returns" | "attribution" | "tax";

// The asset filter only appears on tabs where it actually changes a
// number. Returns is a sum over positions, so narrowing it is
// well-defined. Attribution is an identity — its buckets have to add up
// to the change in total net worth, and cash, loan interest and FX have
// no asset class to be filtered by. Tax hangs off annual portfolio-wide
// figures (the Sparerpauschbetrag and the §23 Freigrenze are consumed by
// everything you own, not by a selection). Showing inert chips on those
// two would be worse than showing none.
const FILTERABLE: Record<Tab, boolean> = {
  returns: true,
  attribution: false,
  tax: false,
};

export function PerformanceHub() {
  const { t } = useTranslation("performance");
  const [tab, setTab] = useState<Tab>("returns");

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        actions={
          <SegmentedControl
            options={[
              { value: "returns", label: t("tabs.returns") },
              { value: "attribution", label: t("tabs.attribution") },
              { value: "tax", label: t("tabs.tax") },
            ]}
            value={tab}
            onChange={setTab}
          />
        }
      >
        {FILTERABLE[tab] && (
          <>
            <AssetClassChips />
            <AssetPresetChips />
          </>
        )}
      </PageHeader>
      {tab === "returns" && <ReturnsTab />}
      {tab === "attribution" && <AttributionTab />}
      {tab === "tax" && <TaxTab />}
    </div>
  );
}
