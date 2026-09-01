<template>
  <div class="ui-skeleton" :class="`ui-skeleton--${variant}`" aria-hidden="true">
    <template v-if="variant === 'table'">
      <div class="ui-skeleton__row ui-skeleton__row--head" />
      <div v-for="i in rows" :key="i" class="ui-skeleton__row" />
    </template>
    <template v-else>
      <div
        v-for="i in rows"
        :key="i"
        class="ui-skeleton__line"
        :style="{ width: lineWidth(i) }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  /** text：文本行（末行短）；table：表头 + 等宽行 */
  variant?: 'text' | 'table'
  rows?: number
}>(), {
  variant: 'text',
  rows: 4,
})

function lineWidth(i: number): string {
  if (props.variant === 'table') return '100%'
  if (i === props.rows) return '46%'
  return `${88 - ((i * 13) % 14)}%`
}
</script>

<style scoped>
.ui-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-md) 0;
}

.ui-skeleton__line,
.ui-skeleton__row {
  border-radius: var(--qq-radius-sm);
  background: linear-gradient(
    90deg,
    var(--qq-surface-strong) 25%,
    var(--qq-surface-hover) 50%,
    var(--qq-surface-strong) 75%
  );
  background-size: 200% 100%;
  animation: ui-skeleton-shimmer 1.4s var(--qq-ease-loop) infinite;
}

.ui-skeleton__line {
  height: 12px;
}

.ui-skeleton__row {
  height: 34px;
}

.ui-skeleton__row--head {
  height: 26px;
  opacity: 0.72;
}

@keyframes ui-skeleton-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .ui-skeleton__line,
  .ui-skeleton__row {
    animation: none;
  }
}
</style>
