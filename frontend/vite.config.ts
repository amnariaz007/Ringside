import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api is proxied to Django so the browser sees one origin (no CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Keep the browser's Host header (localhost:5173) so Django's CSRF origin
      // check sees the same origin the browser reports.
      '/api': { target: process.env.VITE_API_TARGET ?? 'http://localhost:8000', changeOrigin: false },
    },
  },
})
