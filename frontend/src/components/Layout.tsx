import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../lib/auth";
import { api, type Health } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { ThemeToggle } from "./ThemeToggle";
import { LanguageToggle } from "./LanguageToggle";

const NAV_ITEMS = [
  { to: "/", key: "dashboard" },
  { to: "/positions", key: "positions" },
  { to: "/transactions", key: "transactions" },
  { to: "/accounts", key: "accounts" },
  { to: "/instruments", key: "instruments" },
  { to: "/settings", key: "settings" },
] as const;

function navLinkClass({ isActive }: { isActive: boolean }) {
  return [
    "block rounded-md px-3 py-2 text-sm font-medium",
    isActive
      ? "bg-accent text-accent-fg"
      : "text-text-muted hover:bg-bg-subtle hover:text-text",
  ].join(" ");
}

function FreshnessIndicator() {
  const { t, i18n } = useTranslation("common");
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<Health>("/api/health"),
    refetchInterval: 60_000,
  });

  if (!data) return null;
  const asOf = data.last_snapshot ?? data.last_price_fetch;
  return (
    <span className="tnum text-xs text-text-muted">
      {asOf ? t("status.asOf", { date: formatDateTime(asOf, i18n.language) }) : t("status.empty")}
    </span>
  );
}

export function Layout() {
  const { t } = useTranslation("common");
  const { logout } = useAuth();

  return (
    <div className="flex min-h-screen bg-bg text-text">
      <aside className="w-56 shrink-0 border-r border-border p-4">
        <div className="mb-6 px-3 text-lg font-semibold">Cairn</div>
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={navLinkClass}>
              {t(`nav.${item.key}`)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-3">
          <FreshnessIndicator />
          <div className="flex items-center gap-3">
            <LanguageToggle />
            <ThemeToggle />
            <button
              onClick={() => logout()}
              className="text-sm text-text-muted hover:text-text"
            >
              {t("actions.logout")}
            </button>
          </div>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
