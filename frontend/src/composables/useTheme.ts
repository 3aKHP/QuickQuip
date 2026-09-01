import { ref, watch } from 'vue'

const THEME_KEY = 'qq-admin-theme'

const theme = ref<'light' | 'dark'>('light')

function applyTheme(t: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', t)
}

function loadTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') {
      theme.value = stored
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      // 首访无偏好记录时跟随系统
      theme.value = 'dark'
    }
  } catch { /* ignore */ }
  // watch(theme) 会响应 theme.value 的赋值自动 applyTheme；
  // 仅在 watch 尚未首次触发的初始化场景兜底一次
  applyTheme(theme.value)
}

// 未显式选择过主题时持续跟随系统深浅色切换；一旦用户手动切换（写入存储）即解除跟随
try {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    let stored: string | null = null
    try { stored = localStorage.getItem(THEME_KEY) } catch { /* ignore */ }
    if (stored === 'light' || stored === 'dark') return
    theme.value = e.matches ? 'dark' : 'light'
  })
} catch { /* ignore */ }

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  try { localStorage.setItem(THEME_KEY, theme.value) } catch { /* ignore */ }
  // 主题切换过渡：短暂为全文档启用颜色过渡，结束后移除避免影响常态交互
  const root = document.documentElement
  root.classList.add('theme-anim')
  applyTheme(theme.value)
  window.setTimeout(() => root.classList.remove('theme-anim'), 320)
}

watch(theme, applyTheme)

export function useTheme() {
  return { theme, loadTheme, toggleTheme }
}
