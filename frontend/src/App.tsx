import { BrowserRouter, Routes, Route } from "react-router-dom";
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
          </Route>
        </Routes>
      </BrowserRouter>
    </AssetFilterProvider>
  );
}
