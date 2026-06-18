<template>
  <div class="status-bar" role="status" aria-label="后台状态条">
    <span class="status-bar__seg status-bar__seg--path">
      <span class="dot" aria-hidden="true" />
      <span class="accent">{{ path }}</span>
    </span>
    <span class="status-bar__seg status-bar__seg--hint">
      <span class="quiet">QuickQuip Admin</span>
    </span>
    <span class="status-bar__seg seg-clock">
      <span class="quiet">{{ clock }} </span>
      <span class="accent">CST</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_ITEMS, NAV_SECTIONS } from '../../config/nav'

const route = useRoute()

const path = computed(() => {
  const sectionItem = NAV_ITEMS.find(item => item.path === route.path)
  const sectionKey = sectionItem?.section
  const section = NAV_SECTIONS.find(s => s.key === sectionKey)
  if (route.path === '/') return 'quickquip@overview'
  if (section) return `quickquip@${section.key}`
  return 'quickquip@admin'
})

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

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.status-bar {
  position: sticky;
  top: 0;
  z-index: 200;
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
  font-size: 11px;
  line-height: 1;
  user-select: none;
  overflow: hidden;
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
.seg-clock { margin-left: auto; padding-right: 0; border-right: 0; }

.accent { color: var(--qq-primary); font-weight: 600; }
.quiet  { color: var(--qq-text-muted); }

.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--qq-primary);
  box-shadow: 0 0 0 2px var(--qq-primary-soft);
  vertical-align: middle;
  animation: dot-pulse 2.4s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@media (max-width: 640px) {
  .status-bar { font-size: 10px; padding: 0 var(--qq-gap-sm); }
  .status-bar__seg { padding: 0 6px; }
  .status-bar__seg--hint { display: none; }
  .seg-clock { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .dot { animation: none; }
}
</style>
