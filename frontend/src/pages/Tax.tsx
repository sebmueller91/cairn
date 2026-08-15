import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type Instrument, type TaxOverviewResponse } from "../lib/api";
import { formatCurrency } from "../lib/format";
import { Card } from "../components/Card";

export function Tax() {
  const { t, i18n } = useTranslation(["tax", "common"]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [allowance, setAllowance] = useState("1000");

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const instrumentName = (id: number) =>
    instruments?.find((i) => i.id === id)?.name ?? `#${id}`;

  const { data, isLoading } = useQuery({
    queryKey: ["tax", year, allowance],
    queryFn: () =>
      api.get<TaxOverviewResponse>(`/api/tax?year=${year}&allowance=${allowance}`),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="text-sm text-text-muted">{t("disclaimer")}</p>

      {data?.vorabpauschale_reminder && (
        <Card className="border-warning bg-warning/10">
          <p className="text-sm">{data.vorabpauschale_reminder}</p>
        </Card>
      )}

      <Card>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("year")}</label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              className="w-24 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("allowance")}</label>
            <input
              value={allowance}
              onChange={(e) => setAllowance(e.target.value)}
              className="w-28 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
        </div>

        {isLoading || !data ? (
          <p className="text-text-muted">{t("common:status.loading")}</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <div className="text-xs text-text-muted">{t("realizedGains")}</div>
              <div className="tnum text-lg font-medium">
                {formatCurrency(data.saver_allowance.realized_gains_eur, i18n.language)}
              </div>
            </div>
            <div>
              <div className="text-xs text-text-muted">{t("investmentIncome")}</div>
              <div className="tnum text-lg font-medium">
                {formatCurrency(data.saver_allowance.investment_income_eur, i18n.language)}
              </div>
            </div>
            <div>
              <div className="text-xs text-text-muted">{t("used")}</div>
              <div className="tnum text-lg font-medium">
                {formatCurrency(data.saver_allowance.total_eur, i18n.language)}
              </div>
            </div>
            <div>
              <div className="text-xs text-text-muted">{t("remaining")}</div>
              <div
                className={`tnum text-lg font-medium ${
                  Number(data.saver_allowance.remaining_eur) < 0 ? "text-negative" : ""
                }`}
              >
                {formatCurrency(data.saver_allowance.remaining_eur, i18n.language)}
              </div>
            </div>
          </div>
        )}
      </Card>

      <Card className="p-0">
        <div className="p-5 pb-0">
          <h2 className="font-medium">{t("unrealized.title")}</h2>
        </div>
        {!data?.unrealized.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("common:fields.name")}</th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("unrealized.costBasis")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("unrealized.currentValue")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("unrealized.unrealizedPl")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("unrealized.estimatedTax")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.unrealized.map((row, idx) => (
                <tr key={idx} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">{instrumentName(row.instrument_id)}</td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(row.cost_basis_eur, i18n.language)}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(row.current_value_eur, i18n.language)}
                  </td>
                  <td
                    className={`tnum px-5 py-2 text-right ${
                      Number(row.unrealized_pl_eur) >= 0 ? "text-positive" : "text-negative"
                    }`}
                  >
                    {formatCurrency(row.unrealized_pl_eur, i18n.language)}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatCurrency(row.estimated_tax_eur, i18n.language)}
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
