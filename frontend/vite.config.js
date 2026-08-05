import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Forward /api/* to the FastAPI backend (uvicorn app.main:app --port 8001).
      // Keeps the frontend code free of hardcoded hosts and avoids CORS.
      // NOTE: temporarily on 8001, not 8000 — an earlier dev backend process
      // on 8000 got stuck (hung on a long-running LLM call) and could not be
      // killed (access denied for both Stop-Process and taskkill). Switch
      // back to 8000 once that process is cleared, or leave on 8001.
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
