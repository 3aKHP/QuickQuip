<template>
  <div class="ui-stat-strip">
    <div v-for="item in items" :key="item.label" class="ui-stat-strip__item">
      <UiIcon v-if="item.icon" :name="item.icon" :size="16" class="ui-stat-strip__icon" />
      <span class="ui-stat-strip__label">{{ item.label }}</span>
      <UiStatValue :value="item.value" :format="item.format" />
    </div>
  </div>
</template>

<script setup lang="ts">
import UiIcon from './UiIcon.vue'
import UiStatValue from './UiStatValue.vue'

export interface UiStatStripItem {
  label: string
  value: number
  icon?: string
  format?: (n: number) => string
}

defineProps<{
  items: UiStatStripItem[]
}>()
</script>

<style scoped>
.ui-stat-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
}

.ui-stat-strip__item {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}

.ui-stat-strip__icon {
  color: var(--qq-primary);
  flex-shrink: 0;
}

.ui-stat-strip__label {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}
</style>
