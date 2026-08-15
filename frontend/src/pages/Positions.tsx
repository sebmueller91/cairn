import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type Account, type Instrument, type Position } from "../lib/api";
import { formatCurrency, formatNumber } from "../lib/format";
import { Card } from "../components/Card";

type GroupBy = "account" | "instrument";

// Sign carried by both colour (muted, not traffic-light) and an arrow, so
// meaning never rests on colour alone (spec 8.2) — colour-blind-safe by
// construction, not as an afterthought.
function SignedAmount({ value, lang }: { value: string | null | undefined; lang: string }) {
  if (value == null) return <span className="text-text-muted">—</span>;
  const n = Number(value);
  const cls = n > 0 ? "text-positive" : n < 0 ? "text-negative" : "text-text-muted";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "";
  return (
    <span className={cls}>
      {arrow} {formatCurrency(value, lang)}
    </span>
  );
}

export function Positions() {
  const { t, i18n } = useTranslation(["assets", "common"]);
  const [groupBy, setGroupBy] = useState<GroupBy>("account");

  const { data: positions, isLoading } = useQuery({
    queryKey: ["positions", groupBy],
    queryFn: () => api.get<Position[]>(`/api/positions?group_by=${groupBy}`),
  });
  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const accountName = (id: number | null) =>
    accounts?.find((a) => a.id === id)?.name ?? (id ? `#${id}` : "—");
  const instrumentName = (id: number) =>
    instruments?.find((i) => i.id === id)?.name ?? `#${id}`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("assets:positions.title")}</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">{t("assets:positions.groupBy")}</span>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            className="rounded-md border border-border bg-bg-card px-2 py-1"
          >
            <option value="account">{t("assets:positions.groupByAccount")}</option>
            <option value="instrument">{t("assets:positions.groupByInstrument")}</option>
          </select>
        </div>
      </div>

      <Card className="p-0">
        {isLoading ? (
          <p className="p-5 text-text-muted">{t("common:status.loading")}</p>
        ) : !positions?.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("assets:positions.instrument")}</th>
                {groupBy === "account" && (
                  <th className="px-5 py-2 font-medium">{t("assets:positions.account")}</th>
                )}
                <th className="px-5 py-2 text-right font-medium">
                  {t("common:fields.quantity")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("assets:positions.costBasis")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("assets:positions.value")}
                </th>
                <th className="px-5 py-2 text-right font-medium">
                  {t("assets:positions.unrealizedPl")}
                </th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, idx) => (
                <tr key={idx} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">{instrumentName(p.instrument_id)}</td>
                  {groupBy === "account" && (
                    <td className="px-5 py-2 text-text-muted">{accountName(p.account_id)}</td>
                  )}
                  <td className="tnum px-5 py-2 text-right">
                    {formatNumber(p.quantity, i18n.language, { maximumFractionDigits: 8 })}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {formatNumber(p.cost_basis_eur, i18n.language, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    {p.value_eur ? formatCurrency(p.value_eur, i18n.language) : "—"}
                  </td>
                  <td className="tnum px-5 py-2 text-right">
                    <SignedAmount value={p.unrealized_pl_eur} lang={i18n.language} />
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
