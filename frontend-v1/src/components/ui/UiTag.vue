<template>
  <span class="ui-tag" :class="[variantClass, sizeClass]">
    <slot />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  variant: { type: String, default: 'info' },
  size: { type: String, default: 'md' },
})

const variantClass = computed(() => `ui-tag--${props.variant}`)
const sizeClass = computed(() => `ui-tag--${props.size}`)
</script>

<style scoped>
.ui-tag {
  display: inline-flex;
  align-items: center;
  border-radius: var(--qq-radius-pill);
  font-weight: 500;
  line-height: 1;
}

.ui-tag--md {
  min-height: 24px;
  padding: 0 10px;
  font-size: var(--qq-text-xs);
}

.ui-tag--sm {
  min-height: 20px;
  padding: 0 8px;
  font-size: var(--qq-text-xs);
}

.ui-tag--info {
  background: var(--qq-accent-soft);
  color: var(--qq-accent);
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
