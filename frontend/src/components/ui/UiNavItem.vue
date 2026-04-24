<template>
  <button
    class="ui-nav-item"
    :class="{ active }"
    @click="$emit('click')"
  >
    <UiIcon v-if="icon" :name="icon" :size="16" />
    <span class="label">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
import UiIcon from './UiIcon.vue'

defineProps({
  label: { type: String, required: true },
  icon: { type: String, default: '' },
  active: { type: Boolean, default: false },
})

defineEmits(['click'])
</script>

<style scoped>
.ui-nav-item {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-size: 14px;
  cursor: pointer;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast), border-color var(--qq-transition-fast);
}

.ui-nav-item:hover {
  color: var(--qq-text);
  background: var(--qq-surface);
}

.ui-nav-item.active {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
  border-color: var(--qq-border-strong);
}
</style>
