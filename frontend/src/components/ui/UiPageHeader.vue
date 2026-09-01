<template>
  <div class="ui-page-header">
    <div class="ui-page-header__info">
      <h1 class="ui-page-header__title">{{ title }}</h1>
      <p v-if="subtitle" class="ui-page-header__subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="ui-page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<style scoped>
.ui-page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-lg);
  padding-bottom: var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
}

.ui-page-header__title {
  font-family: var(--qq-font-display);
  font-size: var(--qq-text-xl);
  font-weight: 600;
  color: var(--qq-text);
  line-height: 1.3;
}

.ui-page-header__subtitle {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  margin-top: var(--qq-gap-xs);
}

.ui-page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-shrink: 0;
}
</style>
