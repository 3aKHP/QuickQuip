import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
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
  server: {
    proxy: {
      '/ops/api': {
        target: 'http://127.0.0.1:5104',
        changeOrigin: true,
      },
    },
  },
})
