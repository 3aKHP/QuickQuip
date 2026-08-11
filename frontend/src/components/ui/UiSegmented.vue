<template>
  <div class="ui-segmented" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="option in options"
      :key="String(option.value)"
      :class="['ui-segmented__item', { 'ui-segmented__item--active': modelValue === option.value }]"
      role="tab"
      :aria-selected="modelValue === option.value"
      type="button"
      @click="$emit('update:modelValue', option.value)"
    >{{ option.label }}</button>
  </div>
</template>

<script setup lang="ts">
/**
 * 分段选择器。NiuNiuView 的 .tab-row、SummaryView 的 .tab-group 为同构模式，
 * 后续回填这些视图时可统一替换为本组件。
 */
export interface UiSegmentedOption<T = string> {
  value: T
  label: string
}

withDefaults(defineProps<{
  modelValue: string
  options: UiSegmentedOption[]
  ariaLabel?: string
}>(), {
  ariaLabel: undefined,
})

defineEmits<{
  'update:modelValue': [value: string]
}>()
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

.ui-segmented__item--active {
  background: var(--qq-surface);
  color: var(--qq-primary);
  font-weight: 600;
  box-shadow: var(--qq-shadow-sm);
}
</style>
