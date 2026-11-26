import { ref } from 'vue'

const RECENT_KEY = 'qq-admin-recent-routes'
const MAX_RECENT = 5

const paletteOpen = ref(false)
const recentPaths = ref<string[]>([])
let loaded = false

function loadRecent() {
  if (loaded) return
  loaded = true
  try {
    const raw = sessionStorage.getItem(RECENT_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      recentPaths.value = parsed.filter((v): v is string => typeof v === 'string').slice(0, MAX_RECENT)
    }
  } catch { /* ignore */ }
}

function recordVisitedPath(path: string) {
  loadRecent()
  if (!path) return
  const next = [path, ...recentPaths.value.filter(p => p !== path)].slice(0, MAX_RECENT)
  recentPaths.value = next
  try {
    sessionStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch { /* ignore */ }
}

function openPalette() {
  loadRecent()
  paletteOpen.value = true
}

function closePalette() {
  paletteOpen.value = false
}

function togglePalette() {
  if (paletteOpen.value) closePalette()
  else openPalette()
}

export function useCommandPalette() {
  loadRecent()
  return {
    paletteOpen,
    recentPaths,
    openPalette,
    closePalette,
    togglePalette,
    recordVisitedPath,
  }
}
