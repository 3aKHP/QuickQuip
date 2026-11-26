<template>
  <label :class="['ui-toggle', `ui-toggle--${size}`, { 'ui-toggle--on': modelValue, 'ui-toggle--disabled': disabled }]">
    <input
      type="checkbox"
      class="ui-toggle__input"
      role="switch"
      :checked="modelValue"
      :aria-checked="modelValue"
      :aria-label="ariaLabel"
      :disabled="disabled"
      @change="toggle"
    />
    <span class="ui-toggle__track">
      <span class="ui-toggle__knob" />
    </span>
  </label>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  modelValue?: boolean
  disabled?: boolean
  size?: 'md' | 'sm'
  ariaLabel?: string
}>(), {
  modelValue: false,
  size: 'md',
  ariaLabel: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function toggle(e: Event) {
  const input = e.target as HTMLInputElement
  const next = input.checked
  // 受控同步：先回正原生 checkbox，待父级异步/同步更新 modelValue 后再切换，防止接口失败后视觉卡死
  input.checked = props.modelValue
  emit('update:modelValue', next)
}
</script>

<style scoped>
.ui-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.ui-toggle--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ui-toggle__input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
  margin: 0;
  pointer-events: none;
}

.ui-toggle__track {
  position: relative;
  border-radius: var(--qq-radius-full);
  background: var(--qq-toggle-off);
  transition: background var(--qq-transition-fast), box-shadow var(--qq-transition-fast);
}

.ui-toggle__input:focus-visible + .ui-toggle__track {
  box-shadow: 0 0 0 3px var(--qq-primary-glow);
}

.ui-toggle__knob {
  position: absolute;
  background: var(--qq-white);
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  transition: transform var(--qq-transition-fast);
}

/* md size: 34x20 track, 18x18 knob */
.ui-toggle--md .ui-toggle__track {
  width: 34px;
  height: 20px;
}

.ui-toggle--md .ui-toggle__knob {
  width: 18px;
  height: 18px;
  top: 1px;
  left: 1px;
}

.ui-toggle--md.ui-toggle--on .ui-toggle__track {
  background: var(--qq-primary);
}

.ui-toggle--md.ui-toggle--on .ui-toggle__knob {
  transform: translateX(14px);
}

/* sm size: 28x16 track, 14x14 knob */
.ui-toggle--sm .ui-toggle__track {
  width: 28px;
  height: 16px;
}

.ui-toggle--sm .ui-toggle__knob {
  width: 14px;
  height: 14px;
  top: 1px;
  left: 1px;
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__track {
  background: var(--qq-primary);
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__knob {
  transform: translateX(12px);
}

@media (prefers-reduced-motion: reduce) {
  .ui-toggle__track,
  .ui-toggle__knob {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-toggle__track,
html[data-motion="reduced"] .ui-toggle__knob {
  transition: none;
}
</style>
