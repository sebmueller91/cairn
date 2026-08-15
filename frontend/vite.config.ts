import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev only: proxying /api to the backend means the browser sees one
// origin, so no CORS headers are needed on the backend — and it matches
// how production actually works (Caddy serving both from one origin,
// spec 6.4's "one entry point" posture), not a dev-only workaround.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: process.env.CAIRN_API_URL || 'http://raspberrypi5:8000',
        changeOrigin: true,
      },
    },
  },
})
