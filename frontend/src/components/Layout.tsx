import { useCallback, useSyncExternalStore } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../lib/auth";
import { useOnlineStatus } from "../lib/online";
import { formatDateTime } from "../lib/format";
import { ThemeToggle } from "./ThemeToggle";
import { LanguageToggle } from "./LanguageToggle";

const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

// Rolls up the oldest dataUpdatedAt across every currently-mounted query,
// not just one endpoint — the status bar should reflect the actual data
// on screen, which may be a mix of ages once IndexedDB-cached pages are
// visited offline.
function useOldestDataUpdatedAt(): number | null {
  const queryClient = useQueryClient();
  const subscribe = useCallback(
    (onStoreChange: () => void) => queryClient.getQueryCache().subscribe(onStoreChange),
    [queryClient],
  );
  const getSnapshot = useCallback(() => {
    const mounted = queryClient
      .getQueryCache()
      .getAll()
      .filter((q) => q.getObserversCount() > 0 && q.state.dataUpdatedAt > 0);
    if (!mounted.length) return null;
    return Math.min(...mounted.map((q) => q.state.dataUpdatedAt));
  }, [queryClient]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

const NAV_ITEMS = [
  { to: "/", key: "dashboard" },
  { to: "/performance", key: "performance" },
  { to: "/allocation", key: "allocation" },
  { to: "/tax", key: "tax" },
  { to: "/positions", key: "positions" },
  { to: "/transactions", key: "transactions" },
  { to: "/accounts", key: "accounts" },
  { to: "/instruments", key: "instruments" },
  { to: "/assets", key: "assets" },
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
  const online = useOnlineStatus();
  const oldest = useOldestDataUpdatedAt();

  if (oldest == null) return null;
  const isStale = Date.now() - oldest > STALE_AFTER_MS;
  const asOf = t("status.asOf", { date: formatDateTime(new Date(oldest), i18n.language) });

  return (
    <span
      className={[
        "tnum rounded px-1.5 py-0.5 text-xs",
        isStale ? "bg-warning/10 text-warning" : "text-text-muted",
      ].join(" ")}
      title={isStale ? t("status.stale") : undefined}
    >
      {asOf}
      {!online && ` · ${t("status.offline")}`}
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
