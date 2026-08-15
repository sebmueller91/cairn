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

// Remembers the last confirmed scope across reloads so a network failure
// (offline, SW NetworkFirst timing out) doesn't look identical to "not
// authenticated" and bounce the user to a login screen they can't complete
// offline anyway — the offline-cached dashboard becomes unreachable
// otherwise. Only a genuine 401/403 from a reachable server clears it.
const SCOPE_STORAGE_KEY = "cairn-auth-scope";

function readCachedScope(): Scope | null {
  const v = localStorage.getItem(SCOPE_STORAGE_KEY);
  return v === "full" || v === "read_only" ? v : null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope | null>(readCachedScope);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .get<{ scope: Scope }>("/api/auth/me")
      .then((res) => {
        setScope(res.scope);
        localStorage.setItem(SCOPE_STORAGE_KEY, res.scope);
      })
      .catch((err) => {
        // Only a genuine 401/403 means the session itself is gone. Any
        // other failure — network error, or a 5xx from a proxy/backend
        // that's temporarily down — says nothing about the session, so
        // keep the cached scope rather than bouncing to a login screen
        // the user likely can't complete right now anyway.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setScope(null);
          localStorage.removeItem(SCOPE_STORAGE_KEY);
        }
      })
      .finally(() => setChecking(false));
  }, []);

  const login = useCallback(async (token: string) => {
    const res = await api.post<{ scope: Scope }>("/api/auth/session", { token });
    setScope(res.scope);
    localStorage.setItem(SCOPE_STORAGE_KEY, res.scope);
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setScope(null);
    localStorage.removeItem(SCOPE_STORAGE_KEY);
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
