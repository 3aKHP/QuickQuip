<template>
  <div class="ui-page-header">
    <div class="titles">
      <h2 class="title">{{ title }}</h2>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<style scoped>
.ui-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-lg);
  padding-bottom: var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  flex-wrap: wrap;
}

.titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title {
  font-size: var(--qq-text-lg);
  font-weight: 600;
  color: var(--qq-text);
  margin: 0;
}

.subtitle {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  margin: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}
</style>
