<template>
  <a :class="['ui-nav-item', { active }]" href="#" @click.prevent="$emit('click')">
    <UiIcon :name="icon" :size="18" class="ui-nav-item__icon" />
    <span class="ui-nav-item__label">{{ label }}</span>
  </a>
</template>

<script setup lang="ts">
import UiIcon from './UiIcon.vue'

defineProps<{
  label: string
  icon: string
  active?: boolean
}>()

defineEmits<{
  click: []
}>()
</script>

<style scoped>
.ui-nav-item {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 0 14px;
  height: 38px;
  border-radius: var(--qq-radius-nav);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-base);
  font-weight: 500;
  text-decoration: none;
  transition: all var(--qq-transition-fast);
  cursor: pointer;
  user-select: none;
}

.ui-nav-item:hover {
  color: var(--qq-text);
  background: var(--qq-surface-hover);
}

.ui-nav-item.active {
  color: var(--qq-primary);
  background: var(--qq-primary-soft);
}

.ui-nav-item__icon {
  flex-shrink: 0;
  opacity: 0.65;
}

.ui-nav-item.active .ui-nav-item__icon {
  opacity: 1;
}

.ui-nav-item__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
