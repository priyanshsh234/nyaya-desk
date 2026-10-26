import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the React app runs on :5174 (5173 is often taken by other
// Vite projects) and proxies /api to FastAPI on
// :8000, so the browser sees a single origin (no CORS, and the captcha image
// URL works as a plain <img src>). In production FastAPI serves the built
// files itself, so the same relative /api paths keep working.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
