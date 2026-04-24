<template>
  <div class="ui-empty">
    <UiIcon v-if="icon" :name="icon" :size="32" class="icon" />
    <div v-if="title" class="title">{{ title }}</div>
    <div v-if="description" class="desc">{{ description }}</div>
    <div v-if="$slots.action" class="action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup>
import UiIcon from './UiIcon.vue'

defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
})
</script>

<style scoped>
.ui-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-xl) 0;
  color: var(--qq-text-muted);
  text-align: center;
}

.icon {
  opacity: 0.5;
  margin-bottom: var(--qq-gap-xs);
}

.title {
  font-size: 14px;
  color: var(--qq-text);
}

.desc {
  font-size: 13px;
  max-width: 320px;
}

.action {
  margin-top: var(--qq-gap-sm);
}
</style>
