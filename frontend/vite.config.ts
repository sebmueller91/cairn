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
      manifest: {
        name: 'Cairn',
        short_name: 'Cairn',
        description: 'Self-hosted net worth and portfolio tracker.',
        theme_color: '#2563eb',
        background_color: '#ffffff',
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
        // App shell: everything Vite builds is precached automatically
        // (effectively CacheFirst — served from cache, never re-fetched
        // until a new deploy changes the precache manifest).
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        runtimeCaching: [
          {
            // GET only — Workbox's urlPattern+handler matching applies to
            // GET by default and this is never given a `method` override,
            // so POST/PATCH/DELETE always pass straight through to the
            // network uninterrupted (ADR 0005: caching a write would let
            // it silently "succeed" offline without ever reaching the
            // server, which is exactly the footgun offline writes are
            // deliberately not supporting elsewhere).
            urlPattern: ({ url, request }) =>
              url.pathname.startsWith('/api/') && request.method === 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              networkTimeoutSeconds: 2,
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: process.env.CAIRN_API_URL || 'http://raspberrypi5:8000',
        changeOrigin: true,
      },
    },
  },
})
