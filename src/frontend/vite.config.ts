import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 端口可由环境变量配置（start.sh 会 export VITE_FRONTEND_PORT / VITE_BACKEND_PORT）
const frontendPort = Number(process.env.VITE_FRONTEND_PORT || 13000)
const backendPort = process.env.VITE_BACKEND_PORT || '18080'

export default defineConfig({
  plugins: [react()],
  server: {
    port: frontendPort,
    strictPort: true, // 端口被占时直接报错而非静默 +1，便于健康检查定位
    watch: {
      usePolling: true,
      interval: 1000,
    },
    proxy: {
      '/api': `http://localhost:${backendPort}`,
      '/health': `http://localhost:${backendPort}`,
      '/ws': {
        target: `ws://localhost:${backendPort}`,
        ws: true,
      },
    },
  },
})
