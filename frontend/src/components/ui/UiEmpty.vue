<template>
  <div class="ui-empty">
    <slot name="icon">
      <UiIcon v-if="icon" :name="icon" :size="48" class="ui-empty__icon" />
    </slot>
    <p class="ui-empty__title">{{ title }}</p>
    <p v-if="description" class="ui-empty__desc">{{ description }}</p>
    <slot />
    <div v-if="$slots.action" class="ui-empty__action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
import UiIcon from './UiIcon.vue'

withDefaults(defineProps<{
  icon?: string
  title?: string
  description?: string
}>(), {
  title: '暂无数据',
})
</script>

<style scoped>
.ui-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--qq-gap-2xl) var(--qq-gap-md);
  text-align: center;
}

.ui-empty__icon {
  color: var(--qq-text-muted);
  opacity: 0.3;
  margin-bottom: var(--qq-gap-md);
}

.ui-empty__title {
  font-size: var(--qq-text-md);
  font-weight: 600;
  color: var(--qq-text);
  margin-bottom: var(--qq-gap-xs);
}

.ui-empty__desc {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  max-width: 360px;
  line-height: 1.6;
}

.ui-empty__action {
  margin-top: var(--qq-gap-lg);
}
</style>
