import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { GlassCard } from "../components/ui/GlassCard";
import { ThemeToggle } from "../components/ThemeToggle";
import { LanguageToggle } from "../components/LanguageToggle";
import { useAuth } from "../lib/auth";

export function Settings() {
  const { t } = useTranslation("settings");
  const { scope } = useAuth();

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} />

      <GlassCard className="max-w-md space-y-4">
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {t("sections.appearance")}
        </h2>
        <div className="flex items-center justify-between">
          <span className="text-sm">{t("language")}</span>
          <LanguageToggle />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm">{t("theme")}</span>
          <ThemeToggle />
        </div>
      </GlassCard>

      {scope && (
        <GlassCard className="max-w-md space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted">
            {t("sections.session")}
          </h2>
          <div className="flex items-center justify-between">
            <span className="text-sm">{t("loggedInAs")}</span>
            <span className="rounded-full border border-border bg-bg-subtle px-3 py-1 text-xs font-medium text-text">
              {scope === "full" ? t("scopeFull") : t("scopeReadOnly")}
            </span>
          </div>
        </GlassCard>
      )}

      <GlassCard className="max-w-md space-y-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {t("export.title")}
        </h2>
        <p className="text-sm text-text-muted">{t("export.description")}</p>
        <a
          href="/api/export/full"
          className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg shadow-glow-accent"
        >
          <Download className="size-4" aria-hidden />
          {t("export.download")}
        </a>
      </GlassCard>
    </div>
  );
}
