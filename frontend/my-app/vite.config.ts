import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd())
  
  // 代理运行在本机，即使浏览器通过局域网访问前端，也应连接本机后端。
  const apiUrl = process.env.NOVELFLOW_PROXY_TARGET || env.VITE_API_URL || 'http://127.0.0.1:8000'
  console.log('apiUrl', apiUrl)
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: apiUrl,
          // Preserve the browser-visible host so FastAPI slash redirects keep
          // using the Vite proxy instead of exposing 127.0.0.1 to LAN clients.
          changeOrigin: false,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              // The API accepts simulated events only from this local frontend proxy.
              proxyReq.setHeader('X-NovelFlow-Frontend-Proxy', '1')
              proxyReq.removeHeader('X-Forwarded-For')
            })
          },
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
