import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd())
  
  // This target is used by Vite, not the browser. Browser requests stay same-origin.
  const apiUrl = env.VITE_API_URL || 'http://127.0.0.1:8000'
  console.log('API proxy: /api ->', apiUrl)
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      host: '0.0.0.0',
      watch: {
        usePolling: true,
        interval: 300,
      },
      proxy: {
        '/api': {
          target: apiUrl,
          // Preserve the public host so FastAPI redirects stay on the browser origin.
          changeOrigin: false,
          // 重写路径，确保后端接收正确的路径
          rewrite: (path) => path,
          // 配置 WebSocket 支持（如果需要实时通信）
          ws: true,
        }
      },
      // 确保 CORS 预检请求被正确处理
      cors: {
        origin: '*',
        methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'],
        allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
      }
    }
  }
})
