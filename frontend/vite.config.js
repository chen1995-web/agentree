import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式：pnpm dev，/api 代理到后端 8765
// 生产模式：pnpm build 产物在 dist/，由 python3 -m agentree.server 托管
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 2500 },
})
