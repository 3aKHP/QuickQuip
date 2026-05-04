<template>
  <div class="ui-empty">
    <div v-if="$slots.icon || icon" class="icon-wrap">
      <slot name="icon">
        <UiIcon v-if="icon" :name="icon" :size="36" />
      </slot>
    </div>
    <div v-if="title" class="title">{{ title }}</div>
    <div v-if="description" class="desc">{{ description }}</div>
    <div v-if="$slots.action" class="action">
      <slot name="action" />
    </div>
    <div v-if="$slots.default" class="extra">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
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
  padding: var(--qq-gap-xl) var(--qq-gap-md);
  color: var(--qq-text-muted);
  text-align: center;
}

.icon-wrap {
  opacity: 0.45;
  margin-bottom: var(--qq-gap-xs);
  display: flex;
  align-items: center;
  justify-content: center;
}

.title {
  font-size: var(--qq-text-base);
  color: var(--qq-text);
}

.desc {
  font-size: var(--qq-text-sm);
  max-width: 360px;
  color: var(--qq-text-muted);
}

.action {
  margin-top: var(--qq-gap-sm);
}

.extra {
  margin-top: var(--qq-gap-xs);
}
</style>
