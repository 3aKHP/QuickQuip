<template>
  <article :class="['ui-stat-card', `ui-stat-card--${variant}`]">
    <div class="ui-stat-card__head">
      <span class="ui-stat-card__label">{{ label }}</span>
      <UiIcon v-if="icon" :name="icon" :size="15" class="ui-stat-card__icon" />
    </div>
    <strong class="ui-stat-card__value">{{ value }}</strong>
    <small v-if="sub" class="ui-stat-card__sub">{{ sub }}</small>
  </article>
</template>

<script setup lang="ts">
/**
 * 统计卡。DashboardView 的 .stat-card 为同构样式，后续可统一回填。
 */
import UiIcon from './UiIcon.vue'

withDefaults(defineProps<{
  label: string
  value: string
  sub?: string
  icon?: string
  variant?: 'default' | 'primary' | 'warn'
}>(), {
  sub: undefined,
  icon: undefined,
  variant: 'default',
})
</script>

<style scoped>
.ui-stat-card {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: var(--qq-gap-md);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
}

.ui-stat-card--primary {
  color: var(--qq-on-primary);
  background: var(--qq-gradient-brand);
  border-color: transparent;
}

.ui-stat-card--warn {
  border-color: var(--qq-warn);
}

.ui-stat-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
}

.ui-stat-card__label,
.ui-stat-card__sub {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.ui-stat-card__icon {
  color: var(--qq-text-muted);
  flex-shrink: 0;
}

.ui-stat-card--primary .ui-stat-card__label,
.ui-stat-card--primary .ui-stat-card__sub,
.ui-stat-card--primary .ui-stat-card__icon {
  color: rgba(255, 255, 255, 0.82);
}

.ui-stat-card__value {
  font-size: var(--qq-text-2xl);
  font-variant-numeric: tabular-nums;
  line-height: var(--qq-line-tight);
}
</style>
