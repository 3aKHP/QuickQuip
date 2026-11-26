import { ref } from 'vue'

const KEY = 'qq-admin-low-motion'

/** 低动态偏好：开启后氛围光场只渲染静态帧并联动全站 CSS 降级（独立于系统 prefers-reduced-motion） */
const lowMotion = ref(false)
let loaded = false

function syncDocumentMotion(reduced: boolean) {
  if (typeof document === 'undefined') return
  if (reduced) document.documentElement.dataset.motion = 'reduced'
  else delete document.documentElement.dataset.motion
}

function load() {
  if (loaded) return
  loaded = true
  try {
    lowMotion.value = localStorage.getItem(KEY) === '1'
  } catch { /* ignore */ }
  syncDocumentMotion(lowMotion.value)
}

function toggleLowMotion() {
  lowMotion.value = !lowMotion.value
  syncDocumentMotion(lowMotion.value)
  try {
    localStorage.setItem(KEY, lowMotion.value ? '1' : '0')
  } catch { /* ignore */ }
}

export function useMotionPrefs() {
  load()
  return { lowMotion, toggleLowMotion }
}
