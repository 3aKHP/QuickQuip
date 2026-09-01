<template>
  <div class="ui-loading">
    <div class="ui-loading__bar ui-loading__bar--1" />
    <div class="ui-loading__bar ui-loading__bar--2" />
    <div class="ui-loading__bar ui-loading__bar--3" />
    <p v-if="text" class="ui-loading__text">{{ text }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  text?: string
}>(), {
  text: '加载中...',
})
</script>

<style scoped>
.ui-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--qq-gap-sm);
  max-width: 320px;
  margin: 0 auto;
  padding: var(--qq-gap-2xl) 0;
}

.ui-loading__bar {
  height: 10px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-surface-strong);
  animation: pulse 1.5s var(--qq-ease-pulse) infinite;
}

.ui-loading__bar--1 { width: 100%; animation-delay: 0s; }
.ui-loading__bar--2 { width: 75%; animation-delay: 0.15s; }
.ui-loading__bar--3 { width: 50%; animation-delay: 0.3s; }

.ui-loading__text {
  margin-top: var(--qq-gap-sm);
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 0.7; }
}
</style>
