<template>
  <Teleport to="body">
    <Transition name="palette-fade">
      <div
        v-if="paletteOpen"
        class="cmd-palette-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="快捷命令面板"
        @click.self="close"
      >
        <div class="cmd-palette__panel" @keydown="onPanelKeydown">
          <div class="cmd-palette__whisper" aria-hidden="true" />
          <div class="cmd-palette__search">
            <UiIcon name="Search" :size="16" class="cmd-palette__search-icon" />
            <input
              ref="inputRef"
              v-model="query"
              type="search"
              role="combobox"
              aria-expanded="true"
              aria-autocomplete="list"
              aria-controls="cmd-palette-list"
              class="cmd-palette__input"
              placeholder="跳转页面或执行快捷操作（支持中文 / 拼音首字母 / 路径）…"
              autocomplete="off"
              spellcheck="false"
              aria-label="搜索页面或命令"
              :aria-activedescendant="activeEntry ? `cmd-opt-${activeEntry.id}` : undefined"
            >
            <kbd class="cmd-palette__kbd">Esc</kbd>
          </div>

          <div
            v-if="results.length"
            id="cmd-palette-list"
            ref="listRef"
            class="cmd-palette__list"
            role="listbox"
            aria-label="匹配结果"
          >
            <div
              v-if="highlight.ready"
              class="cmd-palette__highlight"
              :class="{ 'cmd-palette__highlight--animated': highlight.animated }"
              :style="highlightStyle"
              aria-hidden="true"
            />
            <button
              v-for="(entry, idx) in results"
              :id="`cmd-opt-${entry.id}`"
              :key="entry.id"
              :ref="(el) => setRowRef(entry.id, el)"
              type="button"
              role="option"
              tabindex="-1"
              class="cmd-palette__row"
              :class="{
                'cmd-palette__row--active': idx === activeIdx,
                'cmd-palette__row--current': entry.path === route.path,
              }"
              :aria-selected="idx === activeIdx"
              :disabled="entry.actionId === 'logout' && logoutDisabled"
              @mousemove="onRowMouseMove($event, idx)"
              @click="execute(entry)"
            >
              <span class="cmd-palette__dot" :style="{ background: dotColor(entry.section) }" aria-hidden="true" />
              <UiIcon :name="entry.icon" :size="16" class="cmd-palette__row-icon" />
              <span class="cmd-palette__row-label">{{ entry.label }}</span>
              <span v-if="!query.trim() && isRecent(entry)" class="cmd-palette__badge">最近</span>
              <span class="cmd-palette__row-section">{{ entry.sectionLabel }}</span>
              <span v-if="entry.path" class="cmd-palette__row-path">{{ entry.path }}</span>
            </button>
          </div>
          <div v-else id="cmd-palette-list" class="cmd-palette__empty" role="status" aria-live="polite">
            未找到与「{{ query }}」匹配的页面或操作
          </div>

          <div class="cmd-palette__footer">
            <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
            <span><kbd>↵</kbd> 执行</span>
            <span><kbd>{{ shortcutLabel }}</kbd> 开关</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UiIcon from '../ui/UiIcon.vue'
import { NAV_ITEMS, NAV_SECTIONS } from '../../config/nav'
import { useMotionPrefs } from '../../composables/useMotionPrefs'
import { useCommandPalette } from '../../composables/useCommandPalette'
import { buildCommandEntries, searchCommandEntries, type CommandEntry } from '../../lib/commandSearch'

const props = defineProps<{
  theme: 'light' | 'dark'
  logoutDisabled?: boolean
}>()

const emit = defineEmits<{
  toggleTheme: [origin?: { x: number; y: number }]
  logout: []
}>()

const route = useRoute()
const router = useRouter()
const { lowMotion, toggleLowMotion } = useMotionPrefs()
const { paletteOpen, recentPaths, closePalette, togglePalette } = useCommandPalette()

const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const query = ref('')
const activeIdx = ref(0)
const rowMap = new Map<string, HTMLElement>()
let previousFocus: HTMLElement | null = null
let skipFocusRestore = false
let lastPointerX = -1
let lastPointerY = -1

const highlight = reactive({ ready: false, animated: false, y: 0, h: 0 })

const isMac = typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const shortcutLabel = isMac ? '⌘K' : 'Ctrl K'

const allEntries = computed(() =>
  buildCommandEntries(NAV_ITEMS, NAV_SECTIONS, {
    theme: props.theme,
    lowMotion: lowMotion.value,
  }),
)

const results = computed(() =>
  searchCommandEntries(allEntries.value, query.value, recentPaths.value),
)

const activeEntry = computed(() => results.value[activeIdx.value] ?? null)

const highlightStyle = computed(() => ({
  transform: `translateY(${highlight.y}px)`,
  height: `${highlight.h}px`,
}))

function setRowRef(id: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) rowMap.set(id, el)
  else rowMap.delete(id)
}

function dotColor(section: string): string {
  if (section === 'overview') return 'var(--qq-primary)'
  if (section === 'action') return 'var(--qq-accent)'
  return `var(--qq-domain-${section}, var(--qq-primary))`
}

function isRecent(entry: CommandEntry): boolean {
  return Boolean(entry.path && recentPaths.value.includes(entry.path))
}

function measureHighlight(animate = true) {
  const entry = activeEntry.value
  const row = entry ? rowMap.get(entry.id) : undefined
  if (!row || row.offsetHeight === 0) {
    highlight.ready = false
    return
  }
  const wasReady = highlight.ready
  highlight.animated = animate && wasReady
  highlight.y = row.offsetTop
  highlight.h = row.offsetHeight
  highlight.ready = true
}

function setActiveIndex(idx: number, scroll = false) {
  if (!results.value.length) return
  const wrapped = ((idx % results.value.length) + results.value.length) % results.value.length
  activeIdx.value = wrapped
  const targetId = results.value[wrapped]?.id
  nextTick(() => {
    measureHighlight(true)
    if (scroll && targetId) {
      rowMap.get(targetId)?.scrollIntoView({ block: 'nearest' })
    }
  })
}

function onRowMouseMove(e: MouseEvent, idx: number) {
  // 仅真实鼠标移动时同步高亮，避免键盘 scrollIntoView 滚动列表时静止光标抢占选中项
  if (e.clientX === lastPointerX && e.clientY === lastPointerY) return
  lastPointerX = e.clientX
  lastPointerY = e.clientY
  if (idx !== activeIdx.value) setActiveIndex(idx, false)
}

function close() {
  closePalette()
}

function execute(entry: CommandEntry) {
  if (entry.kind === 'route' && entry.path) {
    const changingRoute = entry.path !== route.path
    if (changingRoute) skipFocusRestore = true
    close()
    if (changingRoute) {
      void router.push(entry.path)
    }
    return
  }
  if (entry.actionId === 'toggle-theme') {
    const rect = inputRef.value?.getBoundingClientRect()
    const origin = rect
      ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
      : undefined
    close()
    // 等面板卸载一帧后再启动 View Transition，避免过渡快照截入正在退场的遮罩层
    nextTick(() => {
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => emit('toggleTheme', origin))
      } else {
        emit('toggleTheme', origin)
      }
    })
  } else if (entry.actionId === 'toggle-motion') {
    close()
    toggleLowMotion()
  } else if (entry.actionId === 'logout' && !props.logoutDisabled) {
    skipFocusRestore = true
    close()
    emit('logout')
  }
}

function isImeComposing(e: KeyboardEvent): boolean {
  return e.isComposing || e.keyCode === 229
}

function onPanelKeydown(e: KeyboardEvent) {
  if (isImeComposing(e)) return
  if (e.key === 'Tab') {
    // 模态焦点陷阱：始终保留焦点在检索框内，方向键驱动候选项
    e.preventDefault()
    inputRef.value?.focus()
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    close()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    setActiveIndex(activeIdx.value + 1, true)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    setActiveIndex(activeIdx.value - 1, true)
    return
  }
  if (e.key === 'Enter' && activeEntry.value) {
    e.preventDefault()
    e.stopPropagation()
    execute(activeEntry.value)
  }
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (isImeComposing(e)) return
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    togglePalette()
  } else if (e.key === 'Escape' && paletteOpen.value) {
    e.preventDefault()
    close()
  }
}

watch(paletteOpen, (open) => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    skipFocusRestore = false
    lastPointerX = -1
    lastPointerY = -1
    query.value = ''
    activeIdx.value = 0
    highlight.ready = false
    highlight.animated = false
    nextTick(() => {
      inputRef.value?.focus()
      measureHighlight(false)
    })
  } else {
    const restore = skipFocusRestore ? null : previousFocus
    previousFocus = null
    skipFocusRestore = false
    if (restore && restore.isConnected) {
      // 延后到下一帧恢复焦点，避免触发面板关闭的 Enter 键 keyup 穿透激活原聚焦按钮
      const restoreFocus = () => {
        if (restore.isConnected && !paletteOpen.value) restore.focus()
      }
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(restoreFocus)
      } else {
        setTimeout(restoreFocus, 0)
      }
    }
  }
})

watch(query, () => {
  activeIdx.value = 0
  nextTick(() => {
    measureHighlight(false)
    if (listRef.value) listRef.value.scrollTop = 0
  })
})

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  // 鉴权失效卸载时同步重置单例打开态，避免重新登录后直接弹出无焦点面板
  if (paletteOpen.value) closePalette()
})
</script>

<style scoped>
.cmd-palette-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--qq-z-modal);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: min(14vh, 110px) var(--qq-gap-md) var(--qq-gap-lg);
  background: var(--qq-overlay);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.cmd-palette__panel {
  position: relative;
  width: min(100%, 560px);
  max-height: min(68vh, 520px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--qq-radius-xl);
  border: 1px solid var(--qq-shell-glass-border);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 22%),
    var(--qq-shell-drawer-bg);
  box-shadow:
    var(--qq-shadow-lg),
    0 0 0 1px var(--qq-border-soft);
  backdrop-filter: blur(22px) saturate(1.26);
  -webkit-backdrop-filter: blur(22px) saturate(1.26);
}

/* Gemini / AI Studio 风格顶部极细棱镜光丝 */
.cmd-palette__whisper {
  height: 1.5px;
  flex-shrink: 0;
  background: linear-gradient(
    90deg,
    transparent 4%,
    var(--qq-primary) 32%,
    var(--qq-cyan) 68%,
    transparent 96%
  );
  opacity: 0.78;
}

.cmd-palette__search {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 12px 14px;
  border-bottom: 1px solid var(--qq-border);
}

.cmd-palette__search-icon {
  color: var(--qq-primary-ink);
  flex-shrink: 0;
}

.cmd-palette__input {
  flex: 1;
  min-width: 0;
  height: 28px;
  min-height: 28px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--qq-text);
  font-size: var(--qq-text-md);
  box-shadow: none;
}

.cmd-palette__input:focus {
  border: 0;
  background: transparent;
  box-shadow: none;
}

.cmd-palette__input::placeholder {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-sm);
}

.cmd-palette__kbd,
.cmd-palette__footer kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-border-strong);
  background: var(--qq-surface-strong);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: 10px;
  line-height: 1;
}

.cmd-palette__list {
  position: relative;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px;
}

.cmd-palette__highlight {
  position: absolute;
  top: 0;
  left: 6px;
  right: 6px;
  border-radius: var(--qq-radius-md);
  background: var(--qq-primary-soft);
  border: 1px solid var(--qq-primary-border);
  pointer-events: none;
  z-index: 0;
}

.cmd-palette__highlight--animated {
  transition:
    transform var(--qq-transition-spring-fast),
    height var(--qq-transition-spring-fast);
}

.cmd-palette__row {
  position: relative;
  z-index: 1;
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-md);
  background: transparent;
  color: var(--qq-text);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-sm);
  text-align: left;
  cursor: pointer;
}

.cmd-palette__row:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cmd-palette__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cmd-palette__row-icon {
  color: var(--qq-text-muted);
  flex-shrink: 0;
}

.cmd-palette__row--active .cmd-palette__row-icon {
  color: var(--qq-primary-ink);
}

.cmd-palette__row-label {
  font-weight: 500;
  color: var(--qq-text);
  white-space: nowrap;
}

.cmd-palette__row--current .cmd-palette__row-label {
  color: var(--qq-primary-ink);
}

.cmd-palette__badge {
  padding: 1px 5px;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  color: var(--qq-text-muted);
  font-size: 10px;
  line-height: 1.4;
}

.cmd-palette__row-section {
  margin-left: auto;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  white-space: nowrap;
}

.cmd-palette__row-path {
  color: var(--qq-text-quiet);
  font-family: var(--qq-font-mono);
  font-size: 11px;
  white-space: nowrap;
}

.cmd-palette__empty {
  padding: 28px 16px;
  text-align: center;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.cmd-palette__footer {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  padding: 8px 14px;
  border-top: 1px solid var(--qq-border);
  background: var(--qq-surface-elevated);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.cmd-palette__footer span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 640px) {
  .cmd-palette__row-path {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cmd-palette__highlight--animated {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .cmd-palette__highlight--animated {
  transition: none;
}
</style>
