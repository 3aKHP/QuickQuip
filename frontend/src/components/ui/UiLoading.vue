<template>
  <div class="ui-loading">
    <div class="skeleton">
      <div class="skeleton-bar skeleton-bar--1" />
      <div class="skeleton-bar skeleton-bar--2" />
      <div class="skeleton-bar skeleton-bar--3" />
    </div>
    <span v-if="text" class="text">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps({
  text: { type: String, default: '加载中…' },
})
</script>

<style scoped>
.ui-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-lg) var(--qq-gap-md);
}

.skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  max-width: 320px;
}

.skeleton-bar {
  height: 12px;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-bar--1 {
  width: 100%;
  animation-delay: 0s;
}

.skeleton-bar--2 {
  width: 75%;
  animation-delay: 0.2s;
}

.skeleton-bar--3 {
  width: 50%;
  animation-delay: 0.4s;
}

.text {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.3;
  }
  50% {
    opacity: 0.7;
  }
}
</style>
