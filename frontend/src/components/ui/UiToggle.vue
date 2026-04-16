<template>
  <label class="ui-toggle" :class="sizeClass">
    <input
      type="checkbox"
      role="switch"
      :aria-checked="modelValue"
      :checked="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.checked)"
    />
    <span class="slider" />
  </label>
</template>

<script>
export default {
  name: 'UiToggle',
  props: {
    modelValue: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    size: { type: String, default: 'md' }, // sm | md
  },
  emits: ['update:modelValue'],
  computed: {
    sizeClass() {
      return `ui-toggle--${this.size}`
    },
  },
}
</script>

<style scoped>
.ui-toggle {
  position: relative;
  display: inline-block;
  cursor: pointer;
}

.ui-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  inset: 0;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border-strong);
  border-radius: var(--qq-radius-pill);
  transition: background var(--qq-transition-fast), border-color var(--qq-transition-fast);
}

.slider::before {
  content: '';
  position: absolute;
  background: var(--qq-text-muted);
  border-radius: 50%;
  transition: transform var(--qq-transition-fast), background var(--qq-transition-fast);
}

.ui-toggle input:checked + .slider {
  background: var(--qq-accent-soft);
  border-color: var(--qq-accent);
}

.ui-toggle input:checked + .slider::before {
  background: var(--qq-accent);
}

.ui-toggle input:disabled + .slider {
  opacity: 0.5;
  cursor: not-allowed;
}

/* md: 36x20 */
.ui-toggle--md {
  width: 36px;
  height: 20px;
}
.ui-toggle--md .slider::before {
  width: 14px;
  height: 14px;
  left: 2px;
  top: 2px;
}
.ui-toggle--md input:checked + .slider::before {
  transform: translateX(16px);
}

/* sm: 28x16 */
.ui-toggle--sm {
  width: 28px;
  height: 16px;
}
.ui-toggle--sm .slider::before {
  width: 10px;
  height: 10px;
  left: 2px;
  top: 2px;
}
.ui-toggle--sm input:checked + .slider::before {
  transform: translateX(12px);
}
</style>
