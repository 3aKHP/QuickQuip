import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const pyproject = readFileSync(new URL('../pyproject.toml', import.meta.url), 'utf8')
const version = pyproject.match(/^version\s*=\s*"([^"]+)"\s*$/m)?.[1]

if (!version) {
  throw new Error('Unable to read QuickQuip version from pyproject.toml')
}

export default defineConfig({
  plugins: [vue()],
  base: '/ops/',
  define: {
    __QUICKQUIP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    // 与 tsconfig paths 对齐，供 vitest 用例与源码统一使用 @/ 前缀
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'happy-dom',
    // 只收 tests/unit 下的 vitest 用例；tests/*.test.cjs 由 node --test 跑，避免双跑
    include: ['tests/unit/**/*.test.ts'],
  },
  server: {
    proxy: {
      '/ops/api': {
        target: 'http://127.0.0.1:5104',
        changeOrigin: true,
        // 后端 _enforce_same_origin 要求 Origin 与 Host 同源；
        // dev 代理下浏览器 Origin 是 vite 端口，需随 changeOrigin 一并重写
        headers: { origin: 'http://127.0.0.1:5104' },
      },
    },
  },
})
