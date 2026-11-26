<template>
  <div class="ui-segmented" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="(option, idx) in options"
      :key="String(option.value)"
      :ref="(el) => setBtnRef(idx, el)"
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
import type { ComponentPublicInstance } from 'vue'
/**
 * 分段选择器。NiuNiuView 的 .tab-row、SummaryView 的 .tab-group 为同构模式，
 * 后续回填这些视图时可统一替换为本组件。
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

const btnMap = new Map<number, HTMLButtonElement>()
function setBtnRef(idx: number, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLButtonElement) btnMap.set(idx, el)
  else btnMap.delete(idx)
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
  emit('update:modelValue', props.options[nextIdx].value)
  btnMap.get(nextIdx)?.focus()
}
</script>

<style scoped>
.ui-segmented {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface-strong);
}

.ui-segmented__item {
  padding: 4px 12px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-base);
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--qq-transition-fast), color var(--qq-transition-fast);
}

.ui-segmented__item:hover {
  color: var(--qq-text);
}

.ui-segmented__item:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--qq-primary-glow);
}

.ui-segmented__item--active {
  background: var(--qq-surface);
  color: var(--qq-primary-ink);
  font-weight: 600;
  box-shadow: var(--qq-shadow-sm);
}
</style>
