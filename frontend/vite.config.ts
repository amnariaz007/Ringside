import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api is proxied to Django so the browser sees one origin (no CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': process.env.VITE_API_TARGET ?? 'http://localhost:8000' },
  },
})
