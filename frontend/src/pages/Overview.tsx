import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { CashBalanceModal } from "../components/CashBalanceModal";
import { NetWorthHero } from "../components/overview/NetWorthHero";
import { ClassMixCard } from "../components/overview/ClassMixCard";
import { NextMilestoneCard } from "../components/overview/NextMilestoneCard";
import { ThisMonthCard } from "../components/overview/ThisMonthCard";
import { FreshnessStrip } from "../components/overview/FreshnessStrip";
import { fetchNetWorth90d, NET_WORTH_QUERY_KEY } from "../components/overview/utils";

/** Mission control: the one-glance view of the whole portfolio. Every card
 * below runs its own query, keyed identically to this page-level one where
 * they overlap (net worth), so TanStack Query dedupes the network calls —
 * this hook exists only to decide whether there's anything to show at all. */
export function Overview() {
  const { t } = useTranslation("overview");
  const [cashModalOpen, setCashModalOpen] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: NET_WORTH_QUERY_KEY,
    queryFn: fetchNetWorth90d,
  });

  const isEmpty = !isLoading && !isError && (data?.length ?? 0) === 0;

  return (
    <div className="space-y-4 md:space-y-5">
      <PageHeader
        title={t("title")}
        actions={
          <button
            type="button"
            onClick={() => setCashModalOpen(true)}
            className="rounded-full border border-border px-3 py-1.5 text-sm font-medium text-text-muted transition-colors hover:border-accent hover:text-text"
          >
            {t("common:actions.updateCash")}
          </button>
        }
      />

      {isEmpty ? (
        <EmptyState
          icon={<Sparkles className="size-8" aria-hidden />}
          title={t("empty.title")}
          hint={t("empty.hint")}
        />
      ) : (
        <>
          <NetWorthHero />

          <div className="grid gap-4 md:grid-cols-3 md:gap-5">
            <ClassMixCard />
            <NextMilestoneCard />
            <ThisMonthCard />
          </div>

          <FreshnessStrip />
        </>
      )}

      <CashBalanceModal open={cashModalOpen} onClose={() => setCashModalOpen(false)} />
    </div>
  );
}
