import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "../components/ui/PageHeader";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { ReturnsTab } from "../components/performance/ReturnsTab";
import { AttributionTab } from "../components/performance/AttributionTab";
import { TaxTab } from "../components/performance/TaxTab";

type Tab = "returns" | "attribution" | "tax";

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
      />
      {tab === "returns" && <ReturnsTab />}
      {tab === "attribution" && <AttributionTab />}
      {tab === "tax" && <TaxTab />}
    </div>
  );
}
