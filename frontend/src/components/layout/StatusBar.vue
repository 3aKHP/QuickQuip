<template>
  <header class="status-bar" aria-label="后台状态条">
    <span class="status-bar__seg status-bar__seg--path">
      <span class="dot" aria-hidden="true" />
      <span class="accent">{{ path }}</span>
      <span v-if="pageLabel" class="quiet status-bar__page">/ {{ pageLabel }}</span>
    </span>
    <span class="status-bar__seg status-bar__seg--hint">
      <span class="quiet">QuickQuip Admin</span>
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
import { NAV_ITEMS, NAV_SECTIONS } from '../../config/nav'

const route = useRoute()

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
let timer: ReturnType<typeof setInterval> | null = null

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
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
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
  gap: 4px;
}

.status-bar__seg--path { padding-left: 0; }
.status-bar__seg--hint { color: var(--qq-text-muted); }
.status-bar__page { margin-left: 2px; }
.seg-clock { margin-left: auto; padding-right: 0; border-right: 0; }

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

@media (max-width: 640px) {
  .status-bar { font-size: calc(var(--qq-text-xs) - 1px); padding: 0 var(--qq-gap-sm); }
  .status-bar__seg { padding: 0 6px; }
  .status-bar__seg--path { border-right: 0; }
  .status-bar__seg--hint { display: none; }
  .seg-clock { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .dot { animation: none; }
}

:global(html[data-motion="reduced"]) .dot {
  animation: none;
}
</style>
