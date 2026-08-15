import { useTranslation } from "react-i18next";

export function OfflineNotice() {
  const { t } = useTranslation("common");
  return (
    <p className="mb-2 text-sm text-text-muted" role="status">
      {t("status.offlineWritesDisabled")}
    </p>
  );
}
