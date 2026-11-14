import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      // Local package scripts start Uvicorn on 8000. Docker/deployed setups
      // can override this with VITE_API_PROXY_TARGET (for example 18000).
      proxy: {
        '/api': apiTarget,
        '/health': apiTarget,
      },
    },
  }
})
