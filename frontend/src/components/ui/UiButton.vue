<template>
  <button
    :class="classes"
    :type="type"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <UiIcon v-if="loading" name="Loader2" :size="iconSize" class="ui-btn__loading spin" />
    <UiIcon v-else-if="icon" :name="icon" :size="iconSize" :motion="iconMotion" />
    <span v-if="$slots.default" class="ui-btn__text">
      <slot />
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue'
import UiIcon from './UiIcon.vue'

const props = withDefaults(defineProps<{
  variant?: 'default' | 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'md' | 'sm'
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  loading?: boolean
  icon?: string
}>(), {
  variant: 'default',
  size: 'md',
  type: 'button',
})

defineEmits<{
  click: [e: MouseEvent]
}>()

const slots = useSlots()
const iconSize = computed(() => props.size === 'sm' ? 14 : 16)
const isIconOnly = computed(() => !slots.default && Boolean(props.icon || props.loading))

// 按图标语义自动分配 hover 微动效：刷新类旋转，方向类前移
const SPIN_ICONS = new Set(['RefreshCw', 'RotateCw'])
const NUDGE_ICONS = new Set(['Send', 'ArrowRight', 'ChevronRight', 'ExternalLink', 'Download', 'Upload'])
const iconMotion = computed(() => {
  if (!props.icon) return undefined
  if (SPIN_ICONS.has(props.icon)) return 'spin' as const
  if (NUDGE_ICONS.has(props.icon)) return 'nudge' as const
  return undefined
})

const classes = computed(() => [
  'ui-btn',
  `ui-btn--${props.variant}`,
  `ui-btn--${props.size}`,
  { 'ui-btn--icon-only': isIconOnly.value },
])
</script>

<style scoped>
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: none;
  border-radius: var(--qq-radius-md);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-base);
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--qq-transition-fast),
    border-color var(--qq-transition-fast),
    color var(--qq-transition-fast),
    box-shadow var(--qq-transition-fast),
    transform var(--qq-transition-fast);
  user-select: none;
}

.ui-btn:active:not(:disabled) {
  transform: translateY(1px) scale(0.97);
}

.ui-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ui-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-glow);
}

.ui-btn--md {
  min-height: 36px;
  padding: 0 16px;
}

.ui-btn--sm {
  min-height: 28px;
  padding: 0 12px;
  font-size: var(--qq-text-sm);
}

.ui-btn--md.ui-btn--icon-only {
  width: 36px;
  padding: 0;
}

.ui-btn--sm.ui-btn--icon-only {
  width: 28px;
  padding: 0;
}

.ui-btn--default {
  background: var(--qq-surface);
  color: var(--qq-text);
  border: 1px solid var(--qq-border);
}

.ui-btn--default:hover:not(:disabled) {
  background: var(--qq-surface-elevated);
  border-color: var(--qq-border-strong);
}

.ui-btn--primary {
  background: var(--qq-primary);
  color: var(--qq-on-primary);
  border: 1px solid var(--qq-primary);
}

.ui-btn--primary:hover:not(:disabled) {
  background: var(--qq-primary-hover);
  border-color: var(--qq-primary-hover);
}

.ui-btn--secondary {
  background: transparent;
  color: var(--qq-primary-ink);
  border: 1px solid var(--qq-primary-border);
}

.ui-btn--secondary:hover:not(:disabled) {
  background: var(--qq-primary-soft);
}

.ui-btn--danger {
  background: var(--qq-danger);
  color: var(--qq-on-primary);
  border: 1px solid var(--qq-danger);
}

.ui-btn--danger:hover:not(:disabled) {
  background: var(--qq-danger-deep);
  border-color: var(--qq-danger-deep);
}

.ui-btn--ghost {
  background: transparent;
  color: var(--qq-text-muted);
  border: 1px solid transparent;
}

.ui-btn--ghost:hover:not(:disabled) {
  color: var(--qq-text);
  background: var(--qq-surface-strong);
}

.ui-btn__loading {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
