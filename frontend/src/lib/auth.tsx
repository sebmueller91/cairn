import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "./api";

type Scope = "full" | "read_only";

interface AuthState {
  scope: Scope | null;
  checking: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .get<{ scope: Scope }>("/api/auth/me")
      .then((res) => setScope(res.scope))
      .catch(() => setScope(null))
      .finally(() => setChecking(false));
  }, []);

  const login = useCallback(async (token: string) => {
    const res = await api.post<{ scope: Scope }>("/api/auth/session", { token });
    setScope(res.scope);
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setScope(null);
  }, []);

  return (
    <AuthContext.Provider value={{ scope, checking, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export { ApiError };
