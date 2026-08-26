/// <reference types="vite-plugin-pwa/client" />
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { registerSW } from "virtual:pwa-register";
import "./i18n";
import "./index.css";
import { AuthProvider } from "./lib/auth";
import { BoundedPersistProvider } from "./lib/persistProvider";
import { shouldRetry } from "./lib/api";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

// vite.config.ts sets `injectRegister: false`, so nothing registers the
// service worker unless this does. `immediate: true` registers right away
// rather than waiting for the `load` event — which matters here since
// `registerType: 'autoUpdate'` already makes `registerSW` reload the page
// itself once an update activates (its default `onNeedReload`; overriding
// that would break the auto-update).
//
// `onRegisteredSW`'s periodic + visibility-triggered `registration.update()`
// is the actual fix for a separate bug: an iOS home-screen PWA resumed from
// the app switcher fires no `load` event at all, so Workbox's normal
// check-for-update-on-load never runs — a deploy pushed while the app sat
// suspended could go unnoticed for weeks otherwise.
registerSW({
  immediate: true,
  onRegisteredSW(_swScriptUrl, registration) {
    if (!registration) return;
    const UPDATE_INTERVAL_MS = 60 * 60 * 1000; // hourly — plenty for a LAN app with infrequent deploys
    setInterval(() => {
      registration.update();
    }, UPDATE_INTERVAL_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") registration.update();
    });
  },
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Must not be shorter than the persister's `maxAge` (Infinity, see
      // lib/persister.ts), or the two disagree about what "cached" means.
      // The persisted cache is a dehydrated copy of the *in-memory* cache,
      // and `persistQueryClientSubscribe` rewrites it on every cache
      // change — including a garbage collection. At the 5-minute default,
      // a query whose card is currently unmounted (any tab that isn't the
      // one on screen) gets collected five minutes later, and the very
      // next save quietly drops it from IndexedDB too. The offline cache
      // would then only ever hold whatever happened to be mounted in the
      // last five minutes of the previous session — so the Portfolio tab
      // renders on the train and the Performance tab does not, for no
      // reason the user could possibly infer.
      gcTime: Infinity,
      // Was a flat `1`: every 401/403/404/422 got issued twice before
      // failing, for no benefit — a rejected request stays rejected.
      // `shouldRetry` (lib/api.ts) only retries transient 5xx/network
      // failures, once.
      retry: shouldRetry,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <BoundedPersistProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BoundedPersistProvider>
    </ErrorBoundary>
  </StrictMode>,
);
