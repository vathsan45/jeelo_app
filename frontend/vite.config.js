import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // frontend/.env sets VITE_API_BASE=/api so the same relative path works
    // in production (via vercel.json's rewrite to the backend service) and
    // locally — this proxy is what makes /api resolve to the real backend
    // during `npm run dev` instead of 404ing against Vite's own dev server.
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
