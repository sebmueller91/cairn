import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// Dev only: proxying /api to the backend means the browser sees one
// origin, so no CORS headers are needed on the backend — and it matches
// how production actually works (Caddy serving both from one origin,
// spec 6.4's "one entry point" posture), not a dev-only workaround.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: false }, // SW only in production builds — dev already has HMR
      // Auto-injected registration (the `window.addEventListener('load', ...)`
      // form vite-plugin-pwa would otherwise inline) only ever checks for an
      // update on page load/navigation. An iOS home-screen PWA resumed from
      // the app switcher fires neither, so it can run a stale worker for
      // weeks. `false` here means main.tsx must register the service worker
      // itself via `import { registerSW } from 'virtual:pwa-register'` and
      // add a periodic `registration.update()` call (e.g. on an interval and
      // on `visibilitychange`) — see the deploy-bugs report for the exact
      // shape. `registerType: 'autoUpdate'` already makes that registerSW
      // call reload the page automatically once the new worker activates
      // (workbox-window's `activated` event with `isUpdate`/`isExternal`),
      // so no separate `controllerchange` listener is needed as long as
      // main.tsx doesn't override `onNeedReload`.
      injectRegister: false,
      manifest: {
        name: 'Cairn',
        short_name: 'Cairn',
        description: 'Self-hosted net worth and portfolio tracker.',
        theme_color: '#05070d',
        background_color: '#05070d',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // vite-plugin-pwa only auto-sets these two for `registerType:
        // 'autoUpdate'` when `injectRegister` is left at its default
        // ('auto'/null) — with it forced to `false` above, that wiring is
        // skipped and both default back to off, silently turning
        // "autoUpdate" into "a new worker installs but never takes
        // control until every tab closes". Set explicitly to keep the
        // originally-intended semantics: the new worker activates and
        // claims open pages immediately, which is what makes the
        // reload-on-activate flow in main.tsx's registerSW() call
        // meaningful in the first place.
        skipWaiting: true,
        clientsClaim: true,
        // App shell: everything Vite builds is precached automatically
        // (effectively CacheFirst — served from cache, never re-fetched
        // until a new deploy changes the precache manifest).
        // woff2 included so an offline cold start still gets Inter — the
        // browser only ever *fetches* the latin subset, but precache pulls
        // whatever the glob matches, which is why fontsource's per-subset
        // files (~218 kB total) are an acceptable one-time cost on a LAN.
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        // A plain top-level navigation (e.g. Settings.tsx's
        // `<a href="/api/export/full">`) is a `navigate`-mode request, so
        // without this the NavigationRoute registered below matches it
        // first — in registration order — and serves the precached
        // index.html instead of ever reaching the API. /api/* is never
        // meant to fall back to the SPA shell; it either serves from the
        // network/runtime cache below or fails visibly.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            // GET only — Workbox's urlPattern+handler matching applies to
            // GET by default and this is never given a `method` override,
            // so POST/PATCH/DELETE always pass straight through to the
            // network uninterrupted (ADR 0005: caching a write would let
            // it silently "succeed" offline without ever reaching the
            // server, which is exactly the footgun offline writes are
            // deliberately not supporting elsewhere).
            //
            // /api/auth/* is excluded entirely — never intercepted, never
            // cached. The session cookie has no max_age, so a cached
            // `{"scope":"full"}` from /api/auth/me would let a resumed
            // iOS PWA restore a "logged in" shell from Cache Storage after
            // the real session is long gone: nav renders, some cards 401.
            // Auth state must always be a live network answer.
            urlPattern: ({ url, request }) =>
              url.pathname.startsWith('/api/') &&
              !url.pathname.startsWith('/api/auth/') &&
              request.method === 'GET',
            handler: 'NetworkFirst',
            options: {
              // Versioned so a deploy that changes a response shape gets a
              // fresh, empty bucket instead of serving old-shaped bodies
              // out of an existing one (the component then throws during
              // render on the unexpected shape) — bump this alongside
              // persister.ts's CACHE_BUSTER when an API response shape
              // changes. The old-named cache is simply no longer written
              // to or read from; its own bounds below keep it from being a
              // permanent leak.
              cacheName: 'api-cache-v1',
              // 2s is nothing for this hardware: a decade-wide aggregate
              // over SQLite with Decimal arithmetic on a Pi 5 can
              // legitimately take several seconds. At 2s, the app was
              // splitting along the cache-hit line — a previously-visited
              // range rendered from cache, a newly chosen one hard-failed
              // even though the network would have answered a few seconds
              // later. 10s is long enough to cover a slow real query
              // without being so long it hides a genuinely dead network
              // from the offline banner (ADR 0005).
              networkTimeoutSeconds: 10,
              // Bounded so this cache can't grow without limit across
              // every distinct query string (date ranges, filters, ...).
              // 24h/100 entries is deliberately looser than the TanStack
              // persister's "no hard TTL" (ADR 0005 — that's the app's
              // real offline cache, with staleness surfaced in the UI);
              // this is just the raw HTTP layer backing NetworkFirst, so
              // it only needs to not grow forever and not outlive a
              // response-shape change for very long.
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 24 * 60 * 60,
              },
              // No `cacheableResponse` override — NetworkFirst already
              // caches only real 200s by default. The previous
              // `statuses: [0, 200]` additionally allowed opaque (status
              // 0) responses, which only occur for cross-origin no-cors
              // requests; every request here is same-origin (Caddy is the
              // one entry point, ADR 0014), so `0` could never legitimately
              // happen and would only ever cache an empty opaque body.
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        // Caddy is the only published entry point since ADR 0014 — the
        // api container's port 8000 is no longer reachable directly, so
        // this must go through Caddy's HTTPS on :443 like every other
        // client now. `secure: false` skips verifying the mkcert leaf
        // cert here since this is a dev-only proxy hop on the same LAN.
        target: process.env.CAIRN_API_URL || 'https://raspberrypi5',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  // Same proxy as `server`, for `vite preview` — verifying the production
  // build (service worker, precache, IndexedDB persister) needs the real
  // backend too, and only `preview` actually serves the built app + SW.
  preview: {
    proxy: {
      '/api': {
        // Caddy is the only published entry point since ADR 0014 — the
        // api container's port 8000 is no longer reachable directly, so
        // this must go through Caddy's HTTPS on :443 like every other
        // client now. `secure: false` skips verifying the mkcert leaf
        // cert here since this is a dev-only proxy hop on the same LAN.
        target: process.env.CAIRN_API_URL || 'https://raspberrypi5',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
