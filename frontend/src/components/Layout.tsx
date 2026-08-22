import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  LayoutDashboard,
  TrendingUp,
  PieChart,
  Activity,
  Table2,
  Settings as SettingsIcon,
  LogOut,
  Eye,
  EyeOff,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { usePrivacy } from "../lib/privacy";
import { FreshnessIndicator } from "./FreshnessIndicator";
import { RefreshButton } from "./RefreshButton";

const NAV_ITEMS = [
  { to: "/", key: "overview", icon: LayoutDashboard },
  { to: "/wealth", key: "wealth", icon: TrendingUp },
  { to: "/portfolio", key: "portfolio", icon: PieChart },
  { to: "/performance", key: "performance", icon: Activity },
  { to: "/data", key: "data", icon: Table2 },
] as const;

function sidebarLinkClass({ isActive }: { isActive: boolean }) {
  return [
    "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive ? "bg-accent/10 text-accent" : "text-text-muted hover:text-text",
  ].join(" ");
}

function tabLinkClass({ isActive }: { isActive: boolean }) {
  return [
    "flex flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[10px] font-medium",
    isActive ? "text-accent" : "text-text-muted",
  ].join(" ");
}

/** Desktop sidebar (md and up) — icons, labels, and a glowing active bar. */
function Sidebar() {
  const { t } = useTranslation("common");
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-bg-card p-4 backdrop-blur-glass md:flex">
      <div className="mb-6 flex items-center gap-2 px-3">
        <span
          aria-hidden
          className="size-2 rounded-full bg-accent"
          style={{ boxShadow: "var(--glow-accent)" }}
        />
        <span className="text-lg font-semibold tracking-tight">Cairn</span>
      </div>
      <nav className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={sidebarLinkClass}>
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      aria-hidden
                      className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent"
                      style={{ boxShadow: "var(--glow-accent)" }}
                    />
                  )}
                  <Icon className="size-4 shrink-0" aria-hidden />
                  {t(`nav.${item.key}`)}
                </>
              )}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}

/** Mobile bottom tab bar (below md), fixed, safe-area aware. */
function BottomTabs() {
  const { t } = useTranslation("common");
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-bg-card backdrop-blur-glass md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink key={item.to} to={item.to} end={item.to === "/"} className={tabLinkClass}>
            <Icon className="size-5" aria-hidden />
            {t(`nav.${item.key}`)}
          </NavLink>
        );
      })}
    </nav>
  );
}

function Header() {
  const { t } = useTranslation("common");
  const { logout } = useAuth();
  // In the header rather than in Settings: the point of the toggle is to hit
  // it as somebody walks up to the screen, which is no time to go looking
  // through a settings page.
  const { enabled: privacy, toggle: togglePrivacy } = usePrivacy();

  return (
    <header className="flex items-center justify-between border-b border-border bg-bg-card px-4 py-3 backdrop-blur-glass md:px-6">
      <div className="flex items-center gap-3">
        {/* Wordmark only shows here on mobile — the sidebar already carries it on desktop. */}
        <span className="text-sm font-semibold tracking-tight md:hidden">Cairn</span>
        <FreshnessIndicator />
      </div>
      <div className="flex items-center gap-3">
        <RefreshButton />
        <button
          type="button"
          onClick={togglePrivacy}
          aria-pressed={privacy}
          title={t(privacy ? "actions.showAmounts" : "actions.hideAmounts")}
          aria-label={t(privacy ? "actions.showAmounts" : "actions.hideAmounts")}
          className={`transition-colors ${
            privacy ? "text-accent" : "text-text-muted hover:text-text"
          }`}
        >
          {privacy ? (
            <EyeOff className="size-4" aria-hidden />
          ) : (
            <Eye className="size-4" aria-hidden />
          )}
        </button>
        <NavLink
          to="/settings"
          className="text-text-muted hover:text-text"
          aria-label={t("nav.settings")}
        >
          <SettingsIcon className="size-4" aria-hidden />
        </NavLink>
        <button
          onClick={() => logout()}
          className="flex items-center gap-1 text-sm text-text-muted hover:text-text"
        >
          <LogOut className="size-4" aria-hidden />
          <span className="hidden sm:inline">{t("actions.logout")}</span>
        </button>
      </div>
    </header>
  );
}

export function Layout() {
  return (
    <div className="flex min-h-screen bg-bg text-text">
      <Sidebar />
      {/* min-w-0: a flex child defaults to min-width:auto, so one wide chart
          or table would push the whole column past the viewport and scroll
          the page sideways. Wide content scrolls inside its own card. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 pb-20 md:p-6 md:pb-6">
          <Outlet />
        </main>
        <BottomTabs />
      </div>
    </div>
  );
}
