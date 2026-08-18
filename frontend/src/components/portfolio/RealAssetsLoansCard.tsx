import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { api, type Account, type Loan, type LoanStatus } from "../../lib/api";
import { formatCurrency, formatPercent } from "../../lib/format";
import { usePositionsWithInstruments } from "./usePositionsWithInstruments";
import { SignedAmount } from "./SignedAmount";

function LoanRow({ loan, accountName }: { loan: Loan; accountName: string }) {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data: status } = useQuery({
    queryKey: ["loan-status", loan.id],
    queryFn: () => api.get<LoanStatus>(`/api/loans/${loan.id}/status`),
  });

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="truncate">{accountName}</span>
      <span className="tnum ml-auto shrink-0">
        {status ? (
          <SignedAmount value={-Number(status.balance_eur)} lang={i18n.language} />
        ) : (
          "…"
        )}
      </span>
      <span className="tnum w-14 shrink-0 text-right text-text-muted">
        {status?.ltv ? formatPercent(Number(status.ltv), i18n.language) : t("realAssetsLoans.noLtv")}
      </span>
    </div>
  );
}

/** Section 5 — non-market assets (real estate, vehicles, ...) and outstanding loans. */
export function RealAssetsLoansCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { rows, isLoading: positionsLoading } = usePositionsWithInstruments();

  const { data: loans, isLoading: loansLoading } = useQuery({
    queryKey: ["loans"],
    queryFn: () => api.get<Loan[]>("/api/loans"),
  });
  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });

  const isLoading = positionsLoading || loansLoading || accountsLoading;

  const realAssets = (rows ?? []).filter(
    (p) =>
      p.instrument &&
      (p.instrument.valuation_mode === "ANCHORED" || p.instrument.valuation_mode === "MODELED"),
  );

  if (isLoading) {
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

  // Nothing to show at all — the whole card is omitted rather than
  // rendering an empty shell (spec: "if none, omit the card entirely").
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
