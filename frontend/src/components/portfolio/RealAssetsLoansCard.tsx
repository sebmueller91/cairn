import { useTranslation } from "react-i18next";
import { useIsRestoring, useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { api, type Account, type Loan, type LoanStatus } from "../../lib/api";
import { formatCurrency, formatPercent } from "../../lib/format";
import { usePositionsWithInstruments } from "./usePositionsWithInstruments";
import { SignedAmount } from "./SignedAmount";

function LoanRow({ loan, accountName }: { loan: Loan; accountName: string }) {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  // No useIsRestoring gate needed: this only mounts once the parent card's
  // own `pending` has gone false, and that already folds in isRestoring —
  // by the time a LoanRow exists, the cache restore is over and plain
  // isPending is trustworthy again.
  const { data: status, isPending, isError } = useQuery({
    queryKey: ["loan-status", loan.id],
    queryFn: () => api.get<LoanStatus>(`/api/loans/${loan.id}/status`),
  });

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="truncate">{accountName}</span>
      <span className="tnum ml-auto shrink-0">
        {isPending ? (
          <span aria-hidden className="text-text-muted">
            …
          </span>
        ) : isError ? (
          <AlertTriangle
            className="inline size-3.5 text-negative"
            aria-label={t("common:status.error")}
          />
        ) : (
          <SignedAmount value={-Number(status.balance_eur)} lang={i18n.language} />
        )}
      </span>
      <span
        className="tnum w-14 shrink-0 text-right text-text-muted"
        title={isError ? t("common:status.error") : undefined}
      >
        {isPending
          ? "…"
          : isError
            ? "?"
            : status.ltv
              ? formatPercent(Number(status.ltv), i18n.language)
              : t("realAssetsLoans.noLtv")}
      </span>
    </div>
  );
}

/** Section 5 — non-market assets (real estate, vehicles, ...) and outstanding loans. */
export function RealAssetsLoansCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const isRestoring = useIsRestoring();
  const {
    rows,
    isPending: positionsPending,
    isError: positionsError,
  } = usePositionsWithInstruments();

  const {
    data: loans,
    isPending: loansPending,
    isError: loansError,
  } = useQuery({
    queryKey: ["loans"],
    queryFn: () => api.get<Loan[]>("/api/loans"),
  });
  const {
    data: accounts,
    isPending: accountsPending,
    isError: accountsError,
  } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });

  const pending = isRestoring || positionsPending || loansPending || accountsPending;
  const isError = positionsError || loansError || accountsError;

  const realAssets = (rows ?? []).filter(
    (p) =>
      p.instrument &&
      (p.instrument.valuation_mode === "ANCHORED" || p.instrument.valuation_mode === "MODELED"),
  );

  if (pending) {
    return (
      <GlassCard>
        <h2 className="mb-4 font-medium">{t("realAssetsLoans.title")}</h2>
        <div className="space-y-3">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
        </div>
      </GlassCard>
    );
  }

  // A failed fetch used to fall straight into the "nothing to show, omit
  // the card" branch below — discarding isError entirely — so the house
  // and the car just vanished with no error and no visible gap. Now a
  // genuine failure gets its own state instead of being read as "empty".
  if (isError) {
    return (
      <GlassCard>
        <h2 className="mb-4 font-medium">{t("realAssetsLoans.title")}</h2>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  // Nothing to show at all — the whole card is omitted rather than
  // rendering an empty shell (spec: "if none, omit the card entirely").
  // Only reached once loading and error are both ruled out, so this is a
  // genuine "there is nothing here", not a fetch that silently failed.
  if (realAssets.length === 0 && (loans?.length ?? 0) === 0) return null;

  return (
    <GlassCard>
      <h2 className="mb-4 font-medium">{t("realAssetsLoans.title")}</h2>

      {realAssets.length > 0 && (
        <div className="mb-5">
          <h3 className="mb-2 text-sm font-medium text-text-muted">
            {t("realAssetsLoans.realAssets")}
          </h3>
          <div className="space-y-2">
            {realAssets.map((p) => (
              <div key={p.instrument_id} className="flex items-center gap-2 text-sm">
                <span className="truncate">{p.instrument!.name}</span>
                <span className="tnum ml-auto shrink-0 font-medium">
                  <span className="sensitive">
                    {p.value_eur !== null ? formatCurrency(p.value_eur, i18n.language) : "—"}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {loans && loans.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-medium text-text-muted">
            {t("realAssetsLoans.loans")}
          </h3>
          <div className="space-y-2">
            {loans.map((loan) => (
              <LoanRow
                key={loan.id}
                loan={loan}
                accountName={
                  accounts?.find((a) => a.id === loan.account_id)?.name ??
                  t("realAssetsLoans.unnamedLoan", { id: loan.id })
                }
              />
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
