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
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 8px var(--qq-gap-md);
  border: none;
  border-left: 3px solid transparent;
  border-radius: 0 var(--qq-radius-sm) var(--qq-radius-sm) 0;
  background: transparent;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-base);
  cursor: pointer;
  width: 100%;
  text-align: left;
  transition: color var(--qq-transition-fast),
              background var(--qq-transition-fast),
              border-color var(--qq-transition-fast);
}

.ui-nav-item:hover {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.ui-nav-item.active {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
  border-left-color: var(--qq-accent);
}
</style>
