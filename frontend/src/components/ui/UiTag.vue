<template>
  <span :class="['ui-tag', `ui-tag--${variant}`, `ui-tag--${size}`]">
    <slot />
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'info' | 'success' | 'warn' | 'danger'
  size?: 'md' | 'sm'
}>(), {
  variant: 'info',
  size: 'md',
})
</script>

<style scoped>
.ui-tag {
  display: inline-flex;
  align-items: center;
  border-radius: var(--qq-radius-full);
  font-weight: 500;
  font-size: var(--qq-text-xs);
  line-height: 1;
  white-space: nowrap;
}

.ui-tag--md {
  height: 24px;
  padding: 0 10px;
}

.ui-tag--sm {
  height: 20px;
  padding: 0 8px;
}

.ui-tag--info {
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.ui-tag--success {
  background: var(--qq-success-soft);
  color: var(--qq-success);
}

.ui-tag--warn {
  background: var(--qq-warn-soft);
  color: var(--qq-warn);
}

.ui-tag--danger {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}
</style>
