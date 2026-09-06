<template>
  <article :class="['ui-stat-card', `ui-stat-card--${variant}`]">
    <div class="ui-stat-card__head">
      <span class="ui-stat-card__label">{{ label }}<UiInfoTip v-if="tip" :text="tip" /></span>
      <UiIcon v-if="icon" :name="icon" :size="15" class="ui-stat-card__icon" />
    </div>
    <div class="ui-stat-card__value-row">
      <strong class="ui-stat-card__value">{{ displayValue }}</strong>
      <small v-if="unit" class="ui-stat-card__unit">{{ unit }}</small>
    </div>
    <small v-if="sub" class="ui-stat-card__sub">{{ sub }}</small>
  </article>
</template>

<script setup lang="ts">
/**
 * 统计卡。DashboardView 的 .stat-card 为同构样式，后续可统一回填。
 * 传入 countTo（数值）时启用 count-up 滚动动画，优先于 value 展示。
 */
import { computed } from 'vue'
import UiIcon from './UiIcon.vue'
import UiInfoTip from './UiInfoTip.vue'
import { useCountUp } from '../../composables/useCountUp'

const props = withDefaults(defineProps<{
  label: string
  value: string
  /** 单位后缀：与数值同行的小号单位（如 tok/轮），避免单位混入大数值导致换行。 */
  unit?: string
  /** 标签术语的悬浮解释（UiInfoTip） */
  tip?: string
  sub?: string
  icon?: string
  variant?: 'default' | 'primary' | 'warn'
  /** 数值型指标：传入后启用 count-up 滚动（覆盖 value 的展示） */
  countTo?: number
  /** count-up 展示格式化（如万缩写），默认千分位取整 */
  countFormat?: (n: number) => string
}>(), {
  unit: undefined,
  tip: undefined,
  sub: undefined,
  icon: undefined,
  variant: 'default',
  countTo: undefined,
  countFormat: undefined,
})

const counted = useCountUp(() => props.countTo)
const displayValue = computed(() => {
  if (props.countTo === undefined) return props.value
  const n = Math.round(counted.value)
  return props.countFormat ? props.countFormat(n) : n.toLocaleString()
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

.ui-stat-card__label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
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

.ui-stat-card__value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.ui-stat-card__value {
  font-size: var(--qq-text-2xl);
  font-variant-numeric: tabular-nums;
  line-height: var(--qq-line-tight);
  white-space: nowrap;
}

.ui-stat-card__unit {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  white-space: nowrap;
}

.ui-stat-card--primary .ui-stat-card__unit {
  color: rgba(255, 255, 255, 0.82);
}
</style>
