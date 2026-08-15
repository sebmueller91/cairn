import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Performance } from "./pages/Performance";
import { Allocation } from "./pages/Allocation";
import { Positions } from "./pages/Positions";
import { Transactions } from "./pages/Transactions";
import { Accounts } from "./pages/Accounts";
import { Instruments } from "./pages/Instruments";
import { Assets } from "./pages/Assets";
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
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="performance" element={<Performance />} />
          <Route path="allocation" element={<Allocation />} />
          <Route path="positions" element={<Positions />} />
          <Route path="transactions" element={<Transactions />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="instruments" element={<Instruments />} />
          <Route path="assets" element={<Assets />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
