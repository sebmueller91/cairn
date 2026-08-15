import { useTranslation } from "react-i18next";
import { Card } from "../components/Card";
import { ThemeToggle } from "../components/ThemeToggle";
import { LanguageToggle } from "../components/LanguageToggle";

export function Settings() {
  const { t } = useTranslation("settings");

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>

      <Card className="max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm">{t("language")}</span>
          <LanguageToggle />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm">{t("theme")}</span>
          <ThemeToggle />
        </div>
      </Card>

      <Card className="max-w-md space-y-2">
        <h2 className="font-medium">{t("export.title")}</h2>
        <p className="text-sm text-text-muted">{t("export.description")}</p>
        <a
          href="/api/export/full"
          className="inline-block rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg"
        >
          {t("export.download")}
        </a>
      </Card>
    </div>
  );
}
