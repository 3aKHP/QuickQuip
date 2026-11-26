<template>
  <span
    ref="rootEl"
    class="ui-info-tip"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
  >
    <span
      ref="btnEl"
      role="button"
      tabindex="0"
      class="ui-info-tip__btn"
      :aria-label="ariaLabel ?? '查看说明'"
      :aria-expanded="open"
      :aria-describedby="open ? tipId : undefined"
      @mouseenter="onMouseEnter"
      @mouseleave="onMouseLeave"
      @click.stop="onClickToggle"
      @keydown.enter.stop.prevent="onClickToggle"
      @keydown.space.stop.prevent="onClickToggle"
      @keydown.esc.stop.prevent="closeAll"
    >
      <UiIcon name="CircleHelp" :size="size" />
    </span>
    <Teleport to="body">
      <Transition name="ui-info-tip">
        <span
          v-if="open"
          :id="tipId"
          ref="bubbleEl"
          role="tooltip"
          class="ui-info-tip__bubble"
          :class="{ 'ui-info-tip__bubble--below': placement === 'below' }"
          :style="pos"
        >
          <slot>{{ text }}</slot>
        </span>
      </Transition>
    </Teleport>
  </span>
</template>

<script setup lang="ts">
/**
 * 「?」悬浮说明。hover / 键盘聚焦显示，点击可固定/收起（触屏主路径），
 * Esc、点击外部或页面滚动关闭。通过 Teleport 挂至 body，避免被卡片 overflow
 * 或 transform 包含块裁切与遮挡。
 */
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import UiIcon from './UiIcon.vue'

withDefaults(defineProps<{
  /** 说明文案（无插槽时显示） */
  text?: string
  /** 图标尺寸，默认 13 */
  size?: number
  /** 无障碍朗读标签，默认「查看说明」 */
  ariaLabel?: string
}>(), {
  text: undefined,
  size: 13,
  ariaLabel: undefined,
})

const tipId = `ui-info-tip-${useId()}`
const hovered = ref(false)
const focused = ref(false)
const pinned = ref(false)
const open = computed(() => hovered.value || focused.value || pinned.value)
const placement = ref<'above' | 'below'>('above')
const rootEl = ref<HTMLElement | null>(null)
const btnEl = ref<HTMLElement | null>(null)
const bubbleEl = ref<HTMLElement | null>(null)
const pos = ref<{ left: string; top: string; width: string }>({ left: '0px', top: '0px', width: '280px' })

let disposed = false
let listenersAttached = false
let rafId = 0
let hoverTimer: number | null = null

function clearHoverTimer() {
  if (hoverTimer !== null) {
    window.clearTimeout(hoverTimer)
    hoverTimer = null
  }
}

function onMouseEnter() {
  clearHoverTimer()
  hoverTimer = window.setTimeout(() => {
    hovered.value = true
    hoverTimer = null
  }, 60)
}

function onMouseLeave() {
  clearHoverTimer()
  hoverTimer = window.setTimeout(() => {
    hovered.value = false
    hoverTimer = null
  }, 90)
}

function onFocusIn() {
  focused.value = true
}

function onFocusOut() {
  focused.value = false
}

function onClickToggle() {
  clearHoverTimer()
  pinned.value = !pinned.value
  if (!pinned.value) {
    hovered.value = false
    focused.value = false
  }
}

function closeAll() {
  clearHoverTimer()
  hovered.value = false
  focused.value = false
  pinned.value = false
}

/** 按触发点居中放置气泡，并夹取在视口安全区内（避开顶部状态栏/移动导航栏）。 */
function place() {
  const btn = btnEl.value
  const bub = bubbleEl.value
  if (!btn || !bub) return
  const t = btn.getBoundingClientRect()
  const b = bub.getBoundingClientRect()
  const vw = document.documentElement.clientWidth
  const vh = document.documentElement.clientHeight
  const topSafe = vw <= 767 ? 84 : 34
  const width = Math.min(280, Math.max(160, vw - 24))
  let left = t.left + t.width / 2 - width / 2
  left = Math.min(Math.max(8, left), Math.max(8, vw - width - 8))
  const fitsAbove = t.top - b.height - 8 >= topSafe
  placement.value = fitsAbove ? 'above' : 'below'
  let top = fitsAbove ? t.top - b.height - 8 : t.bottom + 8
  const maxTop = Math.max(topSafe, vh - b.height - 8)
  top = Math.max(topSafe, Math.min(top, maxTop))
  pos.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px`, width: `${width}px` }
}

function onDocClick(e: MouseEvent) {
  if (!rootEl.value?.contains(e.target as Node)) closeAll()
}

function onDocKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') closeAll()
}

function onScroll() {
  closeAll()
}

function attachListeners() {
  if (listenersAttached) return
  listenersAttached = true
  document.addEventListener('click', onDocClick, { capture: true })
  document.addEventListener('keydown', onDocKeydown)
  window.addEventListener('scroll', onScroll, { capture: true, passive: true })
  window.addEventListener('resize', onScroll)
}

function detachListeners() {
  if (!listenersAttached) return
  listenersAttached = false
  document.removeEventListener('click', onDocClick, { capture: true })
  document.removeEventListener('keydown', onDocKeydown)
  window.removeEventListener('scroll', onScroll, { capture: true })
  window.removeEventListener('resize', onScroll)
}

watch(open, async (v) => {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
  if (v) {
    await nextTick()
    if (disposed || !open.value) return
    place()
    rafId = requestAnimationFrame(() => {
      rafId = 0
      if (!disposed && open.value) place()
    })
    attachListeners()
  } else {
    detachListeners()
  }
})

onBeforeUnmount(() => {
  disposed = true
  clearHoverTimer()
  if (rafId) cancelAnimationFrame(rafId)
  detachListeners()
})
</script>

<style scoped>
.ui-info-tip {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
  /* inline-flex 内只有 SVG 时基线取盒子底缘，图标会骑在文字基线上偏上；
     下移 0.15em 使图标与 CJK 文字视觉居中（flex 容器内此属性被忽略，无副作用） */
  vertical-align: -0.15em;
}

.ui-info-tip__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px;
  border: 0;
  border-radius: var(--qq-radius-full);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: help;
  user-select: none;
  transition: color var(--qq-transition-fast);
}

.ui-info-tip__btn:hover,
.ui-info-tip__btn:focus-visible {
  color: var(--qq-primary);
  outline: none;
}

.ui-info-tip__bubble {
  position: fixed;
  z-index: var(--qq-z-tooltip);
  padding: 10px 12px;
  border: 1px solid var(--qq-shell-glass-border);
  border-radius: var(--qq-radius-card);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 58%),
    var(--qq-shell-drawer-bg);
  color: var(--qq-text);
  font-size: var(--qq-text-xs);
  line-height: 1.65;
  text-align: left;
  white-space: normal;
  box-shadow: var(--qq-shadow-lg);
  backdrop-filter: blur(18px) saturate(1.2);
  -webkit-backdrop-filter: blur(18px) saturate(1.2);
  pointer-events: none;
}

.ui-info-tip-enter-active,
.ui-info-tip-leave-active {
  transition: opacity 140ms var(--qq-ease-out), transform 140ms var(--qq-ease-out);
}

.ui-info-tip-enter-from,
.ui-info-tip-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.98);
}

.ui-info-tip__bubble--below.ui-info-tip-enter-from,
.ui-info-tip__bubble--below.ui-info-tip-leave-to {
  transform: translateY(-4px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .ui-info-tip-enter-active,
  .ui-info-tip-leave-active {
    transition: none;
  }
}

:global(html[data-motion="reduced"]) .ui-info-tip-enter-active,
:global(html[data-motion="reduced"]) .ui-info-tip-leave-active {
  transition: none;
}
</style>
