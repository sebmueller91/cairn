import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "../components/ui/PageHeader";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { AccountsView } from "../components/data/AccountsView";
import { InstrumentsView } from "../components/data/InstrumentsView";
import { LedgerView } from "../components/data/LedgerView";
import { PositionsView } from "../components/data/PositionsView";

type Tab = "ledger" | "positions" | "accounts" | "instruments";

export function Data() {
  const { t } = useTranslation("data");
  const [tab, setTab] = useState<Tab>("ledger");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")}>
        <SegmentedControl
          options={[
            { value: "ledger", label: t("tabs.ledger") },
            { value: "positions", label: t("tabs.positions") },
            { value: "accounts", label: t("tabs.accounts") },
            { value: "instruments", label: t("tabs.instruments") },
          ]}
          value={tab}
          onChange={setTab}
        />
      </PageHeader>

      {tab === "ledger" && <LedgerView />}
      {tab === "positions" && <PositionsView />}
      {tab === "accounts" && <AccountsView />}
      {tab === "instruments" && <InstrumentsView />}
    </div>
  );
}
