<template>
  <div ref="rootRef" class="ui-tabs" :class="{ 'has-indicator': indicator.ready }" role="tablist" :aria-label="ariaLabel">
    <div
      v-if="indicator.ready"
      class="ui-tabs__indicator"
      :class="{ 'ui-tabs__indicator--animated': indicator.animated }"
      :style="indicatorStyle"
      aria-hidden="true"
    />
    <div
      v-for="(t, idx) in tabs"
      :key="t.key"
      :ref="(el) => setItemRef(t.key, el)"
      class="ui-tabs__item"
      :class="{ 'ui-tabs__item--active': modelValue === t.key }"
    >
      <button
        :ref="(el) => setBtnRef(t.key, el)"
        type="button"
        role="tab"
        class="ui-tabs__btn"
        :class="{ 'ui-tabs__btn--active': modelValue === t.key, 'ui-tabs__btn--with-tip': Boolean(t.tip) }"
        :aria-selected="modelValue === t.key"
        :tabindex="modelValue === t.key ? 0 : -1"
        @click="select(t.key)"
        @keydown="onKeydown($event, idx)"
      >
        <span class="ui-tabs__label">{{ t.label }}</span>
        <span v-if="t.sub" class="ui-tabs__sub">{{ t.sub }}</span>
      </button>
      <UiInfoTip v-if="t.tip" :text="t.tip" class="ui-tabs__tip" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import UiInfoTip from './UiInfoTip.vue'

export interface UiTabItem {
  key: string
  label: string
  /** 副标题（如文件名），纵向排列在主标签下方 */
  sub?: string
  /** 标签术语的悬浮解释（UiInfoTip） */
  tip?: string
}

const props = defineProps<{
  tabs: UiTabItem[]
  modelValue: string
  ariaLabel?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [key: string]
  change: [key: string]
}>()

const rootRef = ref<HTMLElement | null>(null)
const itemMap = new Map<string, HTMLElement>()
const btnMap = new Map<string, HTMLButtonElement>()
const indicator = reactive({ ready: false, animated: false, x: 0, y: 0, w: 0, h: 0 })
let unmounted = false

function setItemRef(key: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) itemMap.set(key, el)
  else itemMap.delete(key)
}

function setBtnRef(key: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLButtonElement) btnMap.set(key, el)
  else btnMap.delete(key)
}

// 固定基准尺寸 + 纯 GPU translate3d/scale 过渡，切换选项卡零 Layout/Paint 回流
const BASE_W = 100
const BASE_H = 32
const indicatorStyle = computed(() => ({
  transform: `translate3d(${indicator.x}px, ${indicator.y}px, 0) scale(${(indicator.w / BASE_W).toFixed(4)}, ${(indicator.h / BASE_H).toFixed(4)})`,
}))

function measure(animate = true) {
  if (unmounted) return
  const item = itemMap.get(props.modelValue)
  if (!item || item.offsetWidth === 0) {
    indicator.ready = false
    return
  }
  const wasReady = indicator.ready
  indicator.animated = animate && wasReady
  indicator.x = item.offsetLeft
  indicator.y = item.offsetTop
  indicator.w = item.offsetWidth
  indicator.h = item.offsetHeight
  indicator.ready = true
}

function select(key: string) {
  if (key === props.modelValue) return
  emit('update:modelValue', key)
  emit('change', key)
}

function onKeydown(e: KeyboardEvent, idx: number) {
  if (!props.tabs.length) return
  let nextIdx = -1
  if (e.key === 'ArrowRight') nextIdx = (idx + 1) % props.tabs.length
  else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + props.tabs.length) % props.tabs.length
  else if (e.key === 'Home') nextIdx = 0
  else if (e.key === 'End') nextIdx = props.tabs.length - 1
  if (nextIdx < 0) return
  e.preventDefault()
  const target = props.tabs[nextIdx]
  select(target.key)
  btnMap.get(target.key)?.focus()
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(() => measure(false))
  document.fonts?.ready?.then(() => {
    if (!unmounted) nextTick(() => measure(false))
  }).catch(() => {})
  if (rootRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => measure(false))
    resizeObserver.observe(rootRef.value)
  }
})

watch(() => props.modelValue, () => nextTick(() => measure(true)))
watch(() => props.tabs, () => nextTick(() => measure(false)), { deep: true })

onUnmounted(() => {
  unmounted = true
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.ui-tabs {
  position: relative;
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface-strong);
}

/* 滑动指示条：基准盒 100×32，由纯 GPU transform 缩放与平移，避免切换时动画 width/height 触发回流 */
.ui-tabs__indicator {
  position: absolute;
  top: 0;
  left: 0;
  width: 100px;
  height: 32px;
  transform-origin: 0 0;
  border-radius: 4px;
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
  pointer-events: none;
}

.ui-tabs__indicator--animated {
  transition: transform var(--qq-transition-spring);
}

.ui-tabs__item {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
}

.ui-tabs__btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  border: 0;
  padding: 5px 14px;
  border-radius: calc(var(--qq-radius-card) - 3px);
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-sm);
  cursor: pointer;
  transition: color var(--qq-transition-fast);
}

.ui-tabs__btn--with-tip {
  padding-right: 4px;
}

.ui-tabs__tip {
  padding-right: 10px;
}

.ui-tabs__btn:hover {
  color: var(--qq-text);
}

.ui-tabs__btn:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--qq-primary-glow);
}

.ui-tabs__btn--active {
  color: var(--qq-text);
}

.ui-tabs:not(.has-indicator) .ui-tabs__item--active {
  border-radius: calc(var(--qq-radius-card) - 3px);
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
}

.ui-tabs__sub {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

@media (prefers-reduced-motion: reduce) {
  .ui-tabs__indicator--animated {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-tabs__indicator--animated {
  transition: none;
}
</style>
