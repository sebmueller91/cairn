import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, authEvents, UNAUTHORIZED_EVENT } from "./api";
import { persister } from "./persister";

// Prefix of the Workbox `NetworkFirst` cache for `/api/*` GETs
// (vite.config.ts, `cacheName`). Matched by prefix rather than by exact
// name on purpose: this was `"api-cache"` while the real cache had already
// been versioned to `api-cache-v1`, so the `caches.delete()` below deleted
// nothing at all and every cached figure survived sign-out — precisely what
// it exists to prevent. The cache name is documented to be bumped again on
// a response-shape change, so an exact name here is a constant invitation
// to drift back out of sync.
const SW_API_CACHE_PREFIX = "api-cache";

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
  const queryClient = useQueryClient();

  // Single place that reacts to a 401 from *any* request, not just the
  // initial /api/auth/me check below. Without this, an expired session
  // cookie left the shell looking logged in (scope restored from
  // localStorage) while every individual card 401'd on its own query —
  // a second, independent cause of "some elements can not load".
  useEffect(() => {
    const handleUnauthorized = () => {
      setScope(null);
      localStorage.removeItem(SCOPE_STORAGE_KEY);
    };
    authEvents.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => authEvents.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

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
    try {
      await api.post("/api/auth/logout");
    } finally {
      // Clear local state even if the network call failed — the user still
      // wants to be logged out on this device. Every net-worth figure,
      // position and transaction lives in the query cache (IndexedDB,
      // `maxAge: Infinity` per persister.ts) and the service worker's own
      // `api-cache-*`; clearing only the scope flag left both fully
      // populated for whoever opens the app next.
      setScope(null);
      localStorage.removeItem(SCOPE_STORAGE_KEY);
      queryClient.clear();
      await persister.removeClient();
      if (typeof caches !== "undefined") {
        const names = await caches.keys();
        await Promise.all(
          names
            .filter((name) => name.startsWith(SW_API_CACHE_PREFIX))
            .map((name) => caches.delete(name)),
        );
      }
    }
  }, [queryClient]);

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
