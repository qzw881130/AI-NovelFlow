import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd())
  
  // 优先使用环境变量 VITE_API_URL
  // 如果没有设置，开发模式下使用当前访问的 IP:8000（支持局域网访问）
  // 这样可以避免硬编码 localhost 导致其他设备无法访问
  const apiUrl = env.VITE_API_URL || 'http://localhost:8000'
  
  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: apiUrl,
          changeOrigin: true,
        }
      }
    }
  }
})
