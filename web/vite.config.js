import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 本地开发时把 API 转发到本机后端
    proxy: { '/api': 'http://localhost:8000' },
  },
})
