import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/ops/',
  server: {
    proxy: {
      '/ops/api': 'http://127.0.0.1:5104',
    },
  },
})
