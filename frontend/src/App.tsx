import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "./lib/auth";
import { AssetFilterProvider } from "./lib/assetFilter";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Wealth } from "./pages/Wealth";
import { Portfolio } from "./pages/Portfolio";
import { PerformanceHub } from "./pages/PerformanceHub";
import { Data } from "./pages/Data";
import { Settings } from "./pages/Settings";

// Unknown paths previously matched nothing and rendered a blank page — the
// dead `/api/export/full` link (a separate agent's fix, service-worker
// side) is what a real user actually hit this on. Not in src/pages/ (that
// directory belongs to another agent) since this isn't a real page, just
// the catch-all's fallback UI.
function NotFound() {
  const { t } = useTranslation("common");
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <h1 className="text-lg font-semibold">{t("notFound.title")}</h1>
      <p className="text-sm text-text-muted">{t("notFound.body")}</p>
      <Link
        to="/"
        className="rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium text-accent-fg"
      >
        {t("notFound.cta")}
      </Link>
    </div>
  );
}

export function App() {
  const { scope, checking } = useAuth();

  // A cached scope from a prior session renders immediately — waiting on
  // `checking` here would blank the whole app behind a slow or offline
  // /api/auth/me call even though everything needed to render is already
  // in IndexedDB. Only block when there's no cached scope to go on yet.
  if (checking && !scope) return null;
  if (!scope) return <Login />;

  return (
    <AssetFilterProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="wealth" element={<Wealth />} />
            <Route path="portfolio" element={<Portfolio />} />
            <Route path="performance" element={<PerformanceHub />} />
            <Route path="data" element={<Data />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AssetFilterProvider>
  );
}
