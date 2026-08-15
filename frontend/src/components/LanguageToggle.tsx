import { useTranslation } from "react-i18next";

const LANGUAGES = ["de", "en"] as const;

export function LanguageToggle() {
  const { t, i18n } = useTranslation("settings");

  return (
    <select
      value={i18n.language}
      onChange={(e) => i18n.changeLanguage(e.target.value)}
      aria-label={t("language")}
      className="rounded-md border border-border bg-bg-card px-2 py-1 text-sm text-text"
    >
      {LANGUAGES.map((lng) => (
        <option key={lng} value={lng}>
          {t(`languages.${lng}`)}
        </option>
      ))}
    </select>
  );
}
