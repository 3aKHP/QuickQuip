import { nextTick, ref, watch } from 'vue'
import { triggerLightFieldSonar } from '../lib/lightFieldBus'

const THEME_KEY = 'qq-admin-theme'

export type ThemeOrigin = MouseEvent | { x: number; y: number }

interface ViewTransitionLike {
  ready: Promise<void>
  finished?: Promise<void>
}

type DocumentWithVT = Document & {
  startViewTransition?: (callback: () => void | Promise<void>) => ViewTransitionLike
}

const theme = ref<'light' | 'dark'>('light')

function applyTheme(t: 'light' | 'dark') {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', t)
}

function isReducedMotion(): boolean {
  if (typeof document === 'undefined') return true
  if (document.documentElement.dataset.motion === 'reduced') return true
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function resolveRevealPoint(origin?: ThemeOrigin): { x: number; y: number } {
  const vw = typeof window !== 'undefined' ? window.innerWidth : 0
  const vh = typeof window !== 'undefined' ? window.innerHeight : 0
  if (origin && 'clientX' in origin) {
    // 键盘触发的 click 事件 clientX/clientY 均为 0，回落到触发元素中心
    if (origin.clientX !== 0 || origin.clientY !== 0) {
      return { x: origin.clientX, y: origin.clientY }
    }
    const target = origin.currentTarget instanceof Element
      ? origin.currentTarget
      : origin.target instanceof Element
        ? origin.target
        : null
    if (target) {
      const rect = target.getBoundingClientRect()
      if (rect.width > 0 || rect.height > 0) {
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
      }
    }
  } else if (origin && typeof origin.x === 'number' && typeof origin.y === 'number') {
    return { x: origin.x, y: origin.y }
  }
  return { x: vw / 2, y: vh / 2 }
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

let themeAnimTimer: number | null = null

function commitTheme(next: 'light' | 'dark') {
  theme.value = next
  try { localStorage.setItem(THEME_KEY, next) } catch { /* ignore */ }
  applyTheme(next)
}

function toggleTheme(origin?: ThemeOrigin) {
  const root = typeof document !== 'undefined' ? document.documentElement : null
  const doc = typeof document !== 'undefined' ? (document as DocumentWithVT) : null

  if (
    root
    && doc
    && typeof doc.startViewTransition === 'function'
    && typeof root.animate === 'function'
    && !isReducedMotion()
  ) {
    const { x, y } = resolveRevealPoint(origin)
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    )

    // 取消可能残留的传统过渡类，避免与 View Transition 叠层
    if (themeAnimTimer !== null) {
      window.clearTimeout(themeAnimTimer)
      themeAnimTimer = null
    }
    root.classList.remove('theme-anim')

    // 在回调内按当前 theme.value 计算目标色并 await nextTick()，避免连击竞态并确保新快照包含 Vue 渲染结果
    const transition = doc.startViewTransition(async () => {
      const next: 'light' | 'dark' = theme.value === 'light' ? 'dark' : 'light'
      commitTheme(next)
      await nextTick()
    })

    transition.ready
      .then(() => {
        triggerLightFieldSonar({ x, y, kind: 'action', scale: 1.35 })
        root.animate(
          {
            clipPath: [
              `circle(0px at ${x}px ${y}px)`,
              `circle(${endRadius}px at ${x}px ${y}px)`,
            ],
          },
          {
            duration: 460,
            easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
            pseudoElement: '::view-transition-new(root)',
          },
        )
      })
      .catch(() => { /* 快速连击中断上一过渡时静默忽略 */ })
    return
  }

  const next: 'light' | 'dark' = theme.value === 'light' ? 'dark' : 'light'

  // 降级路径：不支持 View Transitions API 或开启低动态模式
  if (!root || isReducedMotion()) {
    commitTheme(next)
    return
  }

  root.classList.add('theme-anim')
  commitTheme(next)
  if (themeAnimTimer !== null) window.clearTimeout(themeAnimTimer)
  themeAnimTimer = window.setTimeout(() => {
    root.classList.remove('theme-anim')
    themeAnimTimer = null
  }, 320)
}

watch(theme, applyTheme, { flush: 'sync' })

export function useTheme() {
  return { theme, loadTheme, toggleTheme }
}
