<template>
  <label :class="['ui-toggle', `ui-toggle--${size}`, { 'ui-toggle--disabled': disabled }]" role="switch" :aria-checked="modelValue">
    <input type="checkbox" :checked="modelValue" :disabled="disabled" @change="toggle" />
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
}>(), {
  modelValue: false,
  size: 'md',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function toggle(e: Event) {
  emit('update:modelValue', (e.target as HTMLInputElement).checked)
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

.ui-toggle input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.ui-toggle__track {
  position: relative;
  border-radius: var(--qq-radius-full);
  background: #D1D5DB;
  transition: background var(--qq-transition-fast);
}

.ui-toggle__knob {
  position: absolute;
  background: #FFFFFF;
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

.ui-toggle--md input:checked + .ui-toggle__track {
  background: var(--qq-primary);
}

.ui-toggle--md input:checked + .ui-toggle__track .ui-toggle__knob {
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

.ui-toggle--sm input:checked + .ui-toggle__track {
  background: var(--qq-primary);
}

.ui-toggle--sm input:checked + .ui-toggle__track .ui-toggle__knob {
  transform: translateX(12px);
}
</style>
