import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type DataQualityResponse } from "../lib/api";
import { Card } from "./Card";

export function DataQualityPanel() {
  const { t } = useTranslation(["dashboard", "common"]);
  const { data } = useQuery({
    queryKey: ["data-quality"],
    queryFn: () => api.get<DataQualityResponse>("/api/data-quality"),
    refetchInterval: 5 * 60_000,
  });

  if (!data || data.issues.length === 0) return null;

  return (
    <Card>
      <h2 className="mb-3 font-medium">{t("dataQuality.title")}</h2>
      <ul className="space-y-1 text-sm">
        {data.issues.map((issue, idx) => (
          <li key={idx} className="flex items-baseline gap-2">
            <span className="text-warning">●</span>
            <span>
              {issue.instrument_name ? `${issue.instrument_name}: ` : ""}
              {t(`dataQuality.kinds.${issue.kind}`)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
