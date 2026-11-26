<template>
  <header class="status-bar" aria-label="后台状态条">
    <span class="status-bar__seg status-bar__seg--path">
      <span class="dot" :class="{ 'dot--err': lastApiError }" aria-hidden="true" />
      <svg
        class="status-bar__ecg"
        :class="{ 'status-bar__ecg--active': apiActive, 'status-bar__ecg--err': lastApiError }"
        viewBox="0 0 28 12"
        width="28"
        height="12"
        aria-hidden="true"
      >
        <path
          class="status-bar__ecg-bg"
          d="M0 6 L7 6 L9.5 6 L11.5 2 L14 10 L16.2 4.2 L18 6 L28 6"
        />
        <path
          class="status-bar__ecg-wave"
          d="M0 6 L7 6 L9.5 6 L11.5 2 L14 10 L16.2 4.2 L18 6 L28 6"
        />
      </svg>
      <span class="accent">{{ path }}</span>
      <span v-if="pageLabel" class="quiet status-bar__page">/ {{ pageLabel }}</span>
    </span>
    <span class="status-bar__seg status-bar__seg--hint">
      <span class="quiet">QuickQuip Admin</span>
    </span>
    <span class="status-bar__seg status-bar__seg--cmd">
      <button
        type="button"
        class="status-bar__cmd-btn"
        aria-haspopup="dialog"
        aria-keyshortcuts="Meta+K Control+K"
        :title="`打开快捷命令面板 (${shortcutLabel})`"
        aria-label="打开快捷命令面板"
        @click="openPalette"
      >
        <UiIcon name="Search" :size="11" />
        <span class="status-bar__cmd-text">跳转</span>
        <kbd class="status-bar__cmd-kbd">{{ shortcutLabel }}</kbd>
      </button>
    </span>
    <span class="status-bar__seg seg-clock">
      <span class="quiet">{{ clock }} </span>
      <span class="accent">CST</span>
    </span>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import UiIcon from '../ui/UiIcon.vue'
import { NAV_ITEMS, NAV_SECTIONS } from '../../config/nav'
import { subscribeApiActivity } from '../../lib/lightFieldBus'
import { useCommandPalette } from '../../composables/useCommandPalette'

const route = useRoute()
const { openPalette } = useCommandPalette()

const isMac = typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const shortcutLabel = isMac ? '⌘K' : 'Ctrl K'

const currentItem = computed(() => NAV_ITEMS.find(item => item.path === route.path))

const path = computed(() => {
  const sectionKey = currentItem.value?.section
  const section = NAV_SECTIONS.find(s => s.key === sectionKey)
  if (route.path === '/') return 'quickquip@overview'
  if (section) return `quickquip@${section.key}`
  return 'quickquip@admin'
})

const pageLabel = computed(() => currentItem.value?.label || '')

const clock = ref('00:00:00')
const apiActive = ref(false)
const lastApiError = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
let pulseHoldTimer: ReturnType<typeof setTimeout> | null = null
let unsubscribeApi: (() => void) | null = null

function pad(n: number): string {
  return n.toString().padStart(2, '0')
}

function tick() {
  const d = new Date()
  // CST = UTC+8
  const utcMs = d.getTime() + d.getTimezoneOffset() * 60_000
  const cst = new Date(utcMs + 8 * 3600_000)
  clock.value = `${pad(cst.getHours())}:${pad(cst.getMinutes())}:${pad(cst.getSeconds())}`
}

function onVisibilityChange() {
  if (!document.hidden) tick()
}

onMounted(() => {
  tick()
  // 隐藏标签页不刷时钟：无人观看，跳过重渲染；切回时立即补刷一次
  timer = setInterval(() => { if (!document.hidden) tick() }, 1000)
  document.addEventListener('visibilitychange', onVisibilityChange)

  unsubscribeApi = subscribeApiActivity((snap) => {
    if (pulseHoldTimer) {
      clearTimeout(pulseHoldTimer)
      pulseHoldTimer = null
    }
    if (snap.inFlight > 0) {
      apiActive.value = true
      lastApiError.value = false
    } else {
      lastApiError.value = !snap.lastOk
      apiActive.value = true
      pulseHoldTimer = setTimeout(() => {
        apiActive.value = false
        lastApiError.value = false
        pulseHoldTimer = null
      }, 650)
    }
  })
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (pulseHoldTimer) clearTimeout(pulseHoldTimer)
  unsubscribeApi?.()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.status-bar {
  position: sticky;
  top: 0;
  z-index: var(--qq-z-status);
  display: flex;
  align-items: center;
  gap: 0;
  height: var(--qq-status-bar-height);
  padding: 0 var(--qq-gap-md);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 70%),
    var(--qq-shell-status-bg);
  border-bottom: 1px solid var(--qq-shell-glass-border);
  box-shadow: 0 8px 26px var(--qq-shell-shadow);
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1;
  user-select: none;
  overflow: hidden;
  flex-shrink: 0;
}

.status-bar__seg {
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 0 10px;
  border-right: 1px solid var(--qq-border);
  white-space: nowrap;
  gap: 5px;
}

.status-bar__seg--path { padding-left: 0; }
.status-bar__seg--hint { color: var(--qq-text-muted); }
.status-bar__seg--cmd { margin-left: auto; border-right: 1px solid var(--qq-border); padding: 0 8px; }
.status-bar__page { margin-left: 2px; }
.seg-clock { padding-right: 0; border-right: 0; }

.accent { color: var(--qq-primary-ink); font-weight: 600; }
.quiet  { color: var(--qq-text-muted); }

.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--qq-primary);
  box-shadow: 0 0 0 2px var(--qq-primary-soft);
  vertical-align: middle;
  animation: dot-pulse 2.8s var(--qq-ease-pulse) infinite;
}

.dot--err {
  background: var(--qq-danger);
  box-shadow: 0 0 0 2px var(--qq-danger-soft);
  animation-name: dot-pulse-err;
}

/* 超微 28×12px 实时心电波形：常态柔和巡航，API 活跃时提速增亮 */
.status-bar__ecg {
  display: inline-block;
  flex-shrink: 0;
  overflow: visible;
}

.status-bar__ecg-bg {
  fill: none;
  stroke: var(--qq-border-strong);
  stroke-width: 1.1;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.55;
}

.status-bar__ecg-wave {
  fill: none;
  stroke: var(--qq-primary-ink);
  stroke-width: 1.3;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 12 36;
  stroke-dashoffset: 48;
  opacity: 0.72;
  animation: ecg-sweep 2.8s linear infinite;
  transition: stroke var(--qq-transition-fast), opacity var(--qq-transition-fast);
}

.status-bar__ecg--active .status-bar__ecg-wave {
  stroke: var(--qq-cyan-ink);
  opacity: 1;
  animation-duration: 0.85s;
}

.status-bar__ecg--err .status-bar__ecg-wave {
  stroke: var(--qq-danger);
  opacity: 1;
}

@keyframes ecg-sweep {
  from { stroke-dashoffset: 48; }
  to   { stroke-dashoffset: 0; }
}

@keyframes dot-pulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 2px var(--qq-primary-soft);
  }
  50% {
    opacity: 0.55;
    box-shadow: 0 0 0 4px transparent;
  }
}

@keyframes dot-pulse-err {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 2px var(--qq-danger-soft);
  }
  50% {
    opacity: 0.55;
    box-shadow: 0 0 0 4px transparent;
  }
}

.status-bar__cmd-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 18px;
  padding: 0 6px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-shell-control-active);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-base);
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  transition: border-color var(--qq-transition-fast), color var(--qq-transition-fast), background var(--qq-transition-fast);
}

.status-bar__cmd-btn:hover {
  color: var(--qq-text);
  border-color: var(--qq-primary-border);
  background: var(--qq-shell-control-hover);
}

.status-bar__cmd-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-glow);
}

.status-bar__cmd-kbd {
  font-family: var(--qq-font-mono);
  font-size: 10px;
  color: var(--qq-primary-ink);
  font-weight: 600;
}

@media (max-width: 640px) {
  .status-bar { font-size: calc(var(--qq-text-xs) - 1px); padding: 0 var(--qq-gap-sm); }
  .status-bar__seg { padding: 0 6px; }
  .status-bar__seg--path { border-right: 0; }
  .status-bar__ecg { display: none; }
  .status-bar__seg--hint { display: none; }
  .status-bar__seg--cmd { display: none; }
  .seg-clock { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .dot { animation: none; }
  .status-bar__ecg-wave {
    animation: none;
    stroke-dasharray: none;
    stroke-dashoffset: 0;
    opacity: 0.45;
  }
}
</style>

<style>
html[data-motion="reduced"] .status-bar .dot {
  animation: none;
}

html[data-motion="reduced"] .status-bar__ecg-wave {
  animation: none;
  stroke-dasharray: none;
  stroke-dashoffset: 0;
  opacity: 0.45;
}
</style>
