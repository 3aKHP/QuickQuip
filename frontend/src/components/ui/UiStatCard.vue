<template>
  <component
    :is="to ? 'router-link' : 'article'"
    :to="to || undefined"
    :class="cardClasses"
    data-glow-card
    :data-tilt-card="to ? '' : undefined"
    :data-tilt-max="to ? '3.4' : undefined"
  >
    <div class="ui-stat-card__head">
      <span class="ui-stat-card__label">{{ label }}<UiInfoTip v-if="tip" :text="tip" /></span>
      <span class="ui-stat-card__head-right">
        <UiIcon v-if="icon" :name="icon" :size="15" class="ui-stat-card__icon" />
        <UiIcon v-if="to" name="ArrowUpRight" :size="13" class="ui-stat-card__arrow" aria-hidden="true" />
      </span>
    </div>
    <div class="ui-stat-card__value-row">
      <strong class="ui-stat-card__value">
        <UiDigitRoll v-if="useOdometer" :value="displayValue" />
        <template v-else>{{ displayValue }}</template>
      </strong>
      <small v-if="unit" class="ui-stat-card__unit">{{ unit }}</small>
    </div>
    <small v-if="sub" class="ui-stat-card__sub">{{ sub }}</small>
  </component>
</template>

<script setup lang="ts">
/**
 * 统计卡。
 * - 传入 to（路由路径）时渲染为可点击入口卡，启用 3D 玻璃微倾与右上角跳转微箭头；
 * - 未传入 to 的纯遥测统计卡仅保留柔和邻近追光边框，避免“看起来像按钮但点不动”的可供性错位；
 * - 传入 countTo（数值）时默认启用 UiDigitRoll 机械滚轮动效（可通过 :digit-roll="false" 切回 count-up）。
 */
import { computed } from 'vue'
import UiIcon from './UiIcon.vue'
import UiInfoTip from './UiInfoTip.vue'
import UiDigitRoll from './UiDigitRoll.vue'
import { useCountUp } from '../../composables/useCountUp'

const props = withDefaults(defineProps<{
  label: string
  value?: string
  /** 单位后缀：与数值同行的小号单位（如 tok/轮），避免单位混入大数值导致换行。 */
  unit?: string
  /** 标签术语的悬浮解释（UiInfoTip） */
  tip?: string
  sub?: string
  icon?: string
  variant?: 'default' | 'primary' | 'warn'
  /** 可选目标路由：传入后整卡作为导航入口渲染，并启用 3D 微倾与跳转提示 */
  to?: string
  /** 数值型指标：传入后启用数字滚轮过渡（覆盖 value 的展示） */
  countTo?: number
  /** 数值展示格式化（如万缩写），默认千分位取整 */
  countFormat?: (n: number) => string
  /** 是否使用机械滚轮数字动效（countTo 默认开启，value 默认关闭） */
  digitRoll?: boolean
}>(), {
  value: '',
  unit: undefined,
  tip: undefined,
  sub: undefined,
  icon: undefined,
  variant: 'default',
  to: undefined,
  countTo: undefined,
  countFormat: undefined,
  digitRoll: undefined,
})

const cardClasses = computed(() => [
  'ui-stat-card',
  `ui-stat-card--${props.variant}`,
  'qq-glow-card',
  {
    'ui-stat-card--clickable': Boolean(props.to),
    'qq-tilt-card': Boolean(props.to),
  },
])

const useOdometer = computed(() => {
  if (props.digitRoll !== undefined) return props.digitRoll
  return props.countTo !== undefined
})

// 仅在显式关闭 digitRoll 时才运行 JS 逐帧 count-up，避免与 CSS 滚轮冲突
const counted = useCountUp(() => (useOdometer.value ? undefined : props.countTo))

const displayValue = computed(() => {
  if (props.countTo === undefined) return props.value
  const raw = useOdometer.value ? props.countTo : counted.value
  const n = Math.round(raw)
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
  color: var(--qq-text);
  text-decoration: none;
  box-shadow: var(--qq-shadow-card);
  transition: border-color var(--qq-transition-fast), box-shadow var(--qq-transition-fast);
}

.ui-stat-card--clickable {
  cursor: pointer;
}

.ui-stat-card--clickable:hover {
  border-color: var(--qq-primary-border);
  box-shadow: var(--qq-shadow-card-hover);
}

.ui-stat-card--clickable:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-glow), var(--qq-shadow-card-hover);
}

.ui-stat-card--primary {
  color: var(--qq-on-primary);
  background: var(--qq-gradient-brand);
  border-color: transparent;
  --glow-color: rgba(255, 255, 255, 0.58);
  --glow-sheen: rgba(255, 255, 255, 0.12);
}

.ui-stat-card--primary.ui-stat-card--clickable:hover {
  border-color: rgba(255, 255, 255, 0.36);
}

.ui-stat-card--warn {
  border-color: var(--qq-warn);
  --glow-color: rgba(245, 158, 11, 0.55);
  --glow-sheen: rgba(245, 158, 11, 0.08);
}

.ui-stat-card__head,
.ui-stat-card__value-row,
.ui-stat-card__sub {
  position: relative;
  z-index: 1;
}

.ui-stat-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
}

.ui-stat-card__head-right {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
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

.ui-stat-card__arrow {
  color: var(--qq-text-quiet);
  opacity: 0.45;
  transform: translate(0, 0);
  transition: transform var(--qq-transition-fast), opacity var(--qq-transition-fast), color var(--qq-transition-fast);
}

.ui-stat-card--clickable:hover .ui-stat-card__arrow,
.ui-stat-card--clickable:focus-visible .ui-stat-card__arrow {
  opacity: 1;
  color: var(--qq-primary-ink);
  transform: translate(2px, -2px);
}

.ui-stat-card--primary .ui-stat-card__label,
.ui-stat-card--primary .ui-stat-card__sub,
.ui-stat-card--primary .ui-stat-card__icon,
.ui-stat-card--primary .ui-stat-card__arrow {
  color: rgba(255, 255, 255, 0.84);
}

.ui-stat-card--primary.ui-stat-card--clickable:hover .ui-stat-card__arrow,
.ui-stat-card--primary.ui-stat-card--clickable:focus-visible .ui-stat-card__arrow {
  color: #ffffff;
}

/* 渐变卡上的说明图标需反色：UiInfoTip 默认 muted 色对比度不足，
   其 hover 色 --qq-primary 与品牌渐变同色，悬停时图标会隐形 */
.ui-stat-card--primary :deep(.ui-info-tip__btn) {
  color: rgba(255, 255, 255, 0.82);
}

.ui-stat-card--primary :deep(.ui-info-tip__btn:hover),
.ui-stat-card--primary :deep(.ui-info-tip__btn:focus-visible) {
  color: #ffffff;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.45);
}

.ui-stat-card__value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.ui-stat-card__value {
  font-size: clamp(1.25rem, 2.1vw, 1.75rem);
  font-variant-numeric: tabular-nums;
  line-height: var(--qq-line-tight);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ui-stat-card__unit {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  white-space: nowrap;
}

.ui-stat-card--primary .ui-stat-card__unit {
  color: rgba(255, 255, 255, 0.82);
}

@media (prefers-reduced-motion: reduce) {
  .ui-stat-card__arrow {
    transition: none;
  }

  .ui-stat-card--clickable:hover .ui-stat-card__arrow,
  .ui-stat-card--clickable:focus-visible .ui-stat-card__arrow {
    transform: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-stat-card__arrow {
  transition: none;
}

html[data-motion="reduced"] .ui-stat-card--clickable:hover .ui-stat-card__arrow,
html[data-motion="reduced"] .ui-stat-card--clickable:focus-visible .ui-stat-card__arrow {
  transform: none;
}
</style>
