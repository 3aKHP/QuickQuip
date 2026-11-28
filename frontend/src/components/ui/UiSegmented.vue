<template>
  <div ref="rootRef" class="ui-segmented" :class="{ 'has-indicator': indicator.ready }" role="tablist" :aria-label="ariaLabel">
    <div
      v-if="indicator.ready"
      class="ui-segmented__indicator"
      :class="{ 'ui-segmented__indicator--animated': indicator.animated }"
      :style="indicatorStyle"
      aria-hidden="true"
    />
    <button
      v-for="(option, idx) in options"
      :key="String(option.value)"
      :ref="(el) => setBtnRef(String(option.value), el)"
      :class="['ui-segmented__item', { 'ui-segmented__item--active': modelValue === option.value }]"
      role="tab"
      :aria-selected="modelValue === option.value"
      :tabindex="modelValue === option.value ? 0 : -1"
      type="button"
      @click="$emit('update:modelValue', option.value)"
      @keydown="onKeydown($event, idx)"
    >{{ option.label }}</button>
  </div>
</template>

<script setup lang="ts" generic="T extends string = string">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
/**
 * 分段选择器：带 M3 弹簧滑动指示胶囊。
 * 泛型 T 保留调用方的联合类型（如 UsageMetric），v-model 无需 as 断言。
 */
export interface UiSegmentedOption<V extends string = string> {
  value: V
  label: string
}

const props = withDefaults(defineProps<{
  modelValue: T
  options: UiSegmentedOption<T>[]
  ariaLabel?: string
}>(), {
  ariaLabel: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: T]
}>()

const rootRef = ref<HTMLElement | null>(null)
const btnMap = new Map<string, HTMLButtonElement>()
const indicator = reactive({ ready: false, animated: false, x: 0, y: 0, w: 0, h: 0 })
let unmounted = false

function setBtnRef(key: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLButtonElement) btnMap.set(key, el)
  else btnMap.delete(key)
}

// 固定基准尺寸 + 纯 GPU translate3d/scale 过渡，切换零 Layout/Paint 回流
const BASE_W = 100
const BASE_H = 28
const indicatorStyle = computed(() => ({
  transform: `translate3d(${indicator.x}px, ${indicator.y}px, 0) scale(${(indicator.w / BASE_W).toFixed(4)}, ${(indicator.h / BASE_H).toFixed(4)})`,
}))

function measure(animate = true) {
  if (unmounted) return
  const btn = btnMap.get(String(props.modelValue))
  if (!btn || btn.offsetWidth === 0) {
    indicator.ready = false
    return
  }
  const wasReady = indicator.ready
  indicator.animated = animate && wasReady
  indicator.x = btn.offsetLeft
  indicator.y = btn.offsetTop
  indicator.w = btn.offsetWidth
  indicator.h = btn.offsetHeight
  indicator.ready = true
}

function onKeydown(e: KeyboardEvent, idx: number) {
  if (!props.options.length) return
  let nextIdx = -1
  if (e.key === 'ArrowRight') nextIdx = (idx + 1) % props.options.length
  else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + props.options.length) % props.options.length
  else if (e.key === 'Home') nextIdx = 0
  else if (e.key === 'End') nextIdx = props.options.length - 1
  if (nextIdx < 0) return
  e.preventDefault()
  const target = props.options[nextIdx]
  emit('update:modelValue', target.value)
  btnMap.get(String(target.value))?.focus()
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
watch(() => props.options, () => nextTick(() => measure(false)), { deep: true })

onUnmounted(() => {
  unmounted = true
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.ui-segmented {
  position: relative;
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface-strong);
}

.ui-segmented__indicator {
  position: absolute;
  top: 0;
  left: 0;
  width: 100px;
  height: 28px;
  transform-origin: 0 0;
  border-radius: 4px;
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-sm);
  pointer-events: none;
  z-index: 0;
}

.ui-segmented__indicator--animated {
  transition: transform var(--qq-transition-spring);
}

.ui-segmented__item {
  position: relative;
  z-index: 1;
  padding: 4px 12px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-base);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--qq-transition-fast);
}

.ui-segmented__item:hover {
  color: var(--qq-text);
}

.ui-segmented__item:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--qq-primary-glow);
}

.ui-segmented__item--active {
  color: var(--qq-primary-ink);
  font-weight: 600;
}

.ui-segmented:not(.has-indicator) .ui-segmented__item--active {
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-sm);
}

@media (prefers-reduced-motion: reduce) {
  .ui-segmented__indicator--animated {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-segmented__indicator--animated {
  transition: none;
}
</style>
