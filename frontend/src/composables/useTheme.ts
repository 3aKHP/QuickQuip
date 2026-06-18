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
    }
  } catch { /* ignore */ }
  applyTheme(theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  try { localStorage.setItem(THEME_KEY, theme.value) } catch { /* ignore */ }
  applyTheme(theme.value)
}

watch(theme, applyTheme)

export function useTheme() {
  return { theme, loadTheme, toggleTheme }
}
