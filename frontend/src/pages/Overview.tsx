import { useTranslation } from "react-i18next";
import { Construction } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";

export function Overview() {
  const { t } = useTranslation("overview");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} />
      <EmptyState
        icon={<Construction className="size-8" aria-hidden />}
        title={t("building_title")}
        hint={t("building_hint")}
      />
    </div>
  );
}
