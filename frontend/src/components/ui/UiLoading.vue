<template>
  <div class="ui-loading">
    <div class="spinner" />
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
  align-items: center;
  justify-content: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-lg) 0;
  color: var(--qq-text-muted);
  font-size: 13px;
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--qq-border-strong);
  border-top-color: var(--qq-accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
