import { useTranslation } from "react-i18next";
import { useTheme, type Theme } from "../lib/theme";

const OPTIONS: Theme[] = ["light", "dark", "system"];

export function ThemeToggle() {
  const { t } = useTranslation("settings");
  const [theme, setTheme] = useTheme();

  return (
    <select
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      aria-label={t("theme")}
      className="rounded-md border border-border bg-bg-card px-2 py-1 text-sm text-text"
    >
      {OPTIONS.map((opt) => (
        <option key={opt} value={opt}>
          {t(`themes.${opt}`)}
        </option>
      ))}
    </select>
  );
}
