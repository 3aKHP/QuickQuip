<template>
  <button
    class="ui-button"
    :class="[variantClass, sizeClass]"
    :type="type"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <UiIcon v-if="loading" name="Loader2" class="spin" :size="iconSize" />
    <UiIcon v-else-if="icon" :name="icon" :size="iconSize" />
    <span v-if="$slots.default" class="ui-button-text"><slot /></span>
  </button>
</template>

<script>
import UiIcon from './UiIcon.vue'

export default {
  name: 'UiButton',
  components: { UiIcon },
  props: {
    variant: { type: String, default: 'default' }, // primary | default | danger | ghost
    size: { type: String, default: 'md' }, // sm | md
    type: { type: String, default: 'button' },
    disabled: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
    icon: { type: String, default: '' },
  },
  emits: ['click'],
  computed: {
    variantClass() {
      return `ui-button--${this.variant}`
    },
    sizeClass() {
      return `ui-button--${this.size}`
    },
    iconSize() {
      return this.size === 'sm' ? 14 : 16
    },
  },
}
</script>

<style scoped>
.ui-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--qq-gap-sm);
  border: 1px solid var(--qq-border-strong);
  background: var(--qq-surface-elevated);
  color: var(--qq-text);
  font-size: 13px;
  cursor: pointer;
  transition: background var(--qq-transition-fast), border-color var(--qq-transition-fast), transform var(--qq-transition-fast);
}

.ui-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ui-button:not(:disabled):active {
  transform: translateY(1px);
}

.ui-button--md {
  min-height: 36px;
  padding: 0 14px;
  border-radius: var(--qq-radius-sm);
}

.ui-button--sm {
  min-height: 28px;
  padding: 0 10px;
  border-radius: var(--qq-radius-sm);
  font-size: 12px;
}

.ui-button--default:hover:not(:disabled) {
  background: var(--qq-surface);
  border-color: var(--qq-border-strong);
}

.ui-button--primary {
  background: linear-gradient(180deg, rgba(88, 166, 255, 0.22), rgba(88, 166, 255, 0.10));
  border-color: rgba(88, 166, 255, 0.35);
  color: #fff;
}
.ui-button--primary:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(88, 166, 255, 0.30), rgba(88, 166, 255, 0.14));
}

.ui-button--danger {
  background: var(--qq-danger-soft);
  border-color: rgba(248, 81, 73, 0.35);
  color: var(--qq-danger);
}
.ui-button--danger:hover:not(:disabled) {
  background: rgba(248, 81, 73, 0.18);
}

.ui-button--ghost {
  background: transparent;
  border-color: transparent;
  color: var(--qq-text-muted);
}
.ui-button--ghost:hover:not(:disabled) {
  color: var(--qq-text);
  background: var(--qq-surface);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
