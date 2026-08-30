import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8090'
  return {
    plugins: [vue()],
    server: {
      proxy: {
        '/api': apiTarget,
        '/health': apiTarget,
      },
    },
  }
})
