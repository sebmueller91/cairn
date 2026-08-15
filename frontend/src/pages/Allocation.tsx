import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type AllocationResponse,
  type AssetClass,
  type LookThroughResponse,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";
import { Card } from "../components/Card";
import { OfflineNotice } from "../components/OfflineNotice";
import { useOnlineStatus } from "../lib/online";

const ASSET_CLASSES: AssetClass[] = [
  "EQUITY",
  "BOND",
  "COMMODITY",
  "CRYPTO",
  "REAL_ESTATE",
  "VEHICLE",
  "CASH",
  "LIABILITY",
];

export function Allocation() {
  const { t, i18n } = useTranslation(["allocation", "assets", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data: targets } = useQuery({
    queryKey: ["allocation-targets"],
    queryFn: () => api.get<Record<string, string>>("/api/allocation/targets"),
  });

  const [draftTargets, setDraftTargets] = useState<Record<string, string>>({});
  const [contribution, setContribution] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lookThroughDimension, setLookThroughDimension] = useState<"region" | "sector">(
    "region",
  );

  const { data: lookThrough } = useQuery({
    queryKey: ["look-through", lookThroughDimension],
    queryFn: () =>
      api.get<LookThroughResponse>(`/api/look-through?dimension=${lookThroughDimension}`),
  });
  const lookThroughTotal = lookThrough?.rows.reduce((sum, r) => sum + Number(r.value_eur), 0) ?? 0;

  const effectiveTargets = { ...(targets ?? {}), ...draftTargets };

  const { data: allocation } = useQuery({
    queryKey: ["allocation", contribution],
    queryFn: () => {
      const params = contribution ? `?contribution=${encodeURIComponent(contribution)}` : "";
      return api.get<AllocationResponse>(`/api/allocation${params}`);
    },
  });

  const saveTargets = useMutation({
    mutationFn: () =>
      api.put<Record<string, string>>("/api/allocation/targets", { targets: effectiveTargets }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["allocation-targets"] });
      queryClient.invalidateQueries({ queryKey: ["allocation"] });
      setDraftTargets({});
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    saveTargets.mutate();
  }

  const targetSum = Object.values(effectiveTargets).reduce(
    (sum, v) => sum + (Number(v) || 0),
    0,
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>

      <Card>
        <h2 className="mb-3 font-medium">{t("targets.title")}</h2>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          {ASSET_CLASSES.map((ac) => (
            <div key={ac}>
              <label className="mb-1 block text-xs text-text-muted">
                {t(`assets:instruments.assetClasses.${ac}`)}
              </label>
              <input
                value={effectiveTargets[ac] ?? ""}
                onChange={(e) =>
                  setDraftTargets((prev) => ({ ...prev, [ac]: e.target.value }))
                }
                placeholder="0"
                className="w-16 rounded-md border border-border bg-bg px-2 py-1.5 text-sm"
              />
            </div>
          ))}
          <button
            type="submit"
            disabled={saveTargets.isPending || !online || targetSum !== 100}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {t("common:actions.save")}
          </button>
        </form>
        <p className="mt-2 text-xs text-text-muted">
          {t("targets.sum", { sum: targetSum })}
        </p>
        {!online && <OfflineNotice />}
        {error && (
          <p className="mt-2 text-sm text-negative" role="alert">
            {error}
          </p>
        )}
      </Card>

      <Card className="p-0">
        <div className="p-5 pb-0">
          <h2 className="font-medium">{t("drift.title")}</h2>
        </div>
        {!allocation?.drift.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("common:fields.type")}</th>
                <th className="px-5 py-2 text-right font-medium">{t("drift.current")}</th>
                <th className="px-5 py-2 text-right font-medium">{t("drift.target")}</th>
                <th className="px-5 py-2 text-right font-medium">{t("drift.driftPp")}</th>
              </tr>
            </thead>
            <tbody>
              {allocation.drift.map((row) => (
                <tr key={row.asset_class} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">
                    {t(`assets:instruments.assetClasses.${row.asset_class}`)}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(row.current_value_eur, i18n.language)} (
                    {formatPercent(Number(row.current_pct) / 100, i18n.language)})
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatPercent(Number(row.target_pct) / 100, i18n.language)}
                  </td>
                  <td
                    className={`tnum px-5 py-2 text-right ${
                      Number(row.drift_pp) > 0 ? "text-positive" : Number(row.drift_pp) < 0 ? "text-negative" : ""
                    }`}
                  >
                    {Number(row.drift_pp) > 0 ? "+" : ""}
                    {formatPercent(Number(row.drift_pp) / 100, i18n.language)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 font-medium">{t("rebalance.title")}</h2>
        <div className="mb-4">
          <label className="mb-1 block text-xs text-text-muted">
            {t("rebalance.contribution")}
          </label>
          <input
            value={contribution}
            onChange={(e) => setContribution(e.target.value)}
            placeholder="0"
            className="w-32 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>

        <h3 className="mb-2 text-sm font-medium text-text-muted">{t("rebalance.full")}</h3>
        <ul className="mb-4 space-y-1 text-sm">
          {allocation?.rebalance_full.length ? (
            allocation.rebalance_full.map((p) => (
              <li key={p.asset_class} className="tnum">
                {t(`assets:instruments.assetClasses.${p.asset_class}`)}:{" "}
                <span className={Number(p.amount_eur) >= 0 ? "text-positive" : "text-negative"}>
                  {Number(p.amount_eur) >= 0
                    ? t("rebalance.buy", { amount: formatCurrency(p.amount_eur, i18n.language) })
                    : t("rebalance.sell", {
                        amount: formatCurrency(Math.abs(Number(p.amount_eur)), i18n.language),
                      })}
                </span>
              </li>
            ))
          ) : (
            <li className="text-text-muted">{t("rebalance.onTarget")}</li>
          )}
        </ul>

        {contribution && (
          <>
            <h3 className="mb-2 text-sm font-medium text-text-muted">
              {t("rebalance.purchasesOnly")}
            </h3>
            <ul className="space-y-1 text-sm">
              {allocation?.rebalance_purchases_only?.length ? (
                allocation.rebalance_purchases_only.map((p) => (
                  <li key={p.asset_class} className="tnum">
                    {t(`assets:instruments.assetClasses.${p.asset_class}`)}:{" "}
                    {t("rebalance.buy", {
                      amount: formatCurrency(p.amount_eur, i18n.language),
                    })}
                  </li>
                ))
              ) : (
                <li className="text-text-muted">{t("rebalance.onTarget")}</li>
              )}
            </ul>
          </>
        )}
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between p-5 pb-0">
          <h2 className="font-medium">{t("lookThrough.title")}</h2>
          <div className="flex gap-1 rounded-md border border-border p-1">
            {(["region", "sector"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setLookThroughDimension(d)}
                className={`rounded px-2 py-1 text-xs font-medium ${
                  d === lookThroughDimension
                    ? "bg-accent text-accent-fg"
                    : "text-text-muted hover:text-text"
                }`}
              >
                {t(`lookThrough.dimensions.${d}`)}
              </button>
            ))}
          </div>
        </div>
        <p className="px-5 pt-3 text-xs text-text-muted">{t("lookThrough.description")}</p>
        {!lookThrough?.rows.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t(`lookThrough.dimensions.${lookThroughDimension}`)}</th>
                <th className="px-5 py-2 text-right font-medium">{t("drift.current")}</th>
              </tr>
            </thead>
            <tbody>
              {lookThrough.rows.map((row) => (
                <tr key={row.category} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">{row.category}</td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(row.value_eur, i18n.language)}
                    {lookThroughTotal > 0 && (
                      <span className="ml-1 text-text-muted">
                        ({formatPercent(Number(row.value_eur) / lookThroughTotal, i18n.language)})
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
