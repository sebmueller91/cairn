import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type AssetClass,
  type Instrument,
  type ValuationMode,
} from "../lib/api";
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

const VALUATION_MODES: ValuationMode[] = [
  "MARKET",
  "ANCHORED",
  "MODELED",
  "AMORTIZING_LIABILITY",
  "NOMINAL",
];

export function Instruments() {
  const { t } = useTranslation(["assets", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const { data: instruments, isLoading } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const [name, setName] = useState("");
  const [isin, setIsin] = useState("");
  const [ticker, setTicker] = useState("");
  const [assetClass, setAssetClass] = useState<AssetClass>("EQUITY");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("MARKET");
  const [currency, setCurrency] = useState("EUR");
  const [valuationConfigJson, setValuationConfigJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const needsConfig = valuationMode === "ANCHORED" || valuationMode === "MODELED";

  const createInstrument = useMutation({
    mutationFn: () => {
      let valuation_config: Record<string, unknown> | undefined;
      if (needsConfig && valuationConfigJson.trim()) {
        valuation_config = JSON.parse(valuationConfigJson);
      }
      return api.post<Instrument>("/api/instruments", {
        name,
        isin: isin || null,
        ticker: ticker || null,
        asset_class: assetClass,
        valuation_mode: valuationMode,
        currency,
        ...(valuation_config ? { valuation_config } : {}),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
      setName("");
      setIsin("");
      setTicker("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (needsConfig && valuationConfigJson.trim()) {
      try {
        JSON.parse(valuationConfigJson);
      } catch {
        setError(t("assets:instruments.invalidConfigJson"));
        return;
      }
    }
    createInstrument.mutate();
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("assets:instruments.title")}</h1>

      <Card>
        <h2 className="mb-3 font-medium">{t("assets:instruments.new")}</h2>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.name")}
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:instruments.isin")}
            </label>
            <input
              value={isin}
              onChange={(e) => setIsin(e.target.value.toUpperCase())}
              maxLength={12}
              className="w-32 rounded-md border border-border bg-bg px-3 py-1.5 text-sm uppercase"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:instruments.ticker")}
            </label>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="w-28 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.type")}
            </label>
            <select
              value={assetClass}
              onChange={(e) => setAssetClass(e.target.value as AssetClass)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            >
              {ASSET_CLASSES.map((ac) => (
                <option key={ac} value={ac}>
                  {t(`assets:instruments.assetClasses.${ac}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:instruments.valuationModes.MARKET")}
            </label>
            <select
              value={valuationMode}
              onChange={(e) => setValuationMode(e.target.value as ValuationMode)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            >
              {VALUATION_MODES.map((vm) => (
                <option key={vm} value={vm}>
                  {t(`assets:instruments.valuationModes.${vm}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.currency")}
            </label>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              maxLength={3}
              required
              className="w-16 rounded-md border border-border bg-bg px-3 py-1.5 text-sm uppercase"
            />
          </div>
          <button
            type="submit"
            disabled={createInstrument.isPending || !online}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {t("common:actions.create")}
          </button>
        </form>
        {!online && <OfflineNotice />}
        {needsConfig && (
          <div className="mt-3">
            <label className="mb-1 block text-xs text-text-muted">
              {t("assets:instruments.valuationConfig")} ({t("assets:instruments.optional")})
            </label>
            <textarea
              value={valuationConfigJson}
              onChange={(e) => setValuationConfigJson(e.target.value)}
              placeholder={
                valuationMode === "MODELED"
                  ? '{"purchase_price_eur": "20000.00", "purchase_date": "2024-01-01", "first_registration": "2024-01-01", "mileage_at_purchase_km": 0, "annual_mileage_estimate_km": 12000}'
                  : '{"index_series": "bavaria-rural"}'
              }
              rows={2}
              className="w-full rounded-md border border-border bg-bg px-3 py-1.5 font-mono text-xs"
            />
          </div>
        )}
        {error && (
          <p className="mt-2 text-sm text-negative" role="alert">
            {error}
          </p>
        )}
      </Card>

      <Card className="p-0">
        {isLoading ? (
          <p className="p-5 text-text-muted">{t("common:status.loading")}</p>
        ) : !instruments?.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("common:fields.name")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:instruments.isin")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:instruments.ticker")}</th>
                <th className="px-5 py-2 font-medium">{t("common:fields.type")}</th>
                <th className="px-5 py-2 font-medium">{t("common:fields.currency")}</th>
              </tr>
            </thead>
            <tbody>
              {instruments.map((i) => (
                <tr key={i.id} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">{i.name}</td>
                  <td className="px-5 py-2 text-text-muted">{i.isin ?? "—"}</td>
                  <td className="px-5 py-2 text-text-muted">{i.ticker ?? "—"}</td>
                  <td className="px-5 py-2">
                    {t(`assets:instruments.assetClasses.${i.asset_class}`)}
                  </td>
                  <td className="px-5 py-2">{i.currency}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
