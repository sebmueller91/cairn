import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Positions } from "./pages/Positions";
import { Transactions } from "./pages/Transactions";
import { Accounts } from "./pages/Accounts";
import { Instruments } from "./pages/Instruments";
import { Settings } from "./pages/Settings";

export function App() {
  const { scope, checking } = useAuth();

  if (checking) return null;
  if (!scope) return <Login />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="positions" element={<Positions />} />
          <Route path="transactions" element={<Transactions />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="instruments" element={<Instruments />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
