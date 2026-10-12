<template>
  <div class="settings-group">
    <UiCard v-for="block in blocks" :key="block.title" padding="lg">
      <h3 class="settings-group__title">
        {{ block.title }}
        <UiInfoTip v-if="block.tip" :text="block.tip" />
      </h3>
      <SettingsForm :section="block.section" :fields="block.fields" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import UiCard from '../ui/UiCard.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import SettingsForm from './SettingsForm.vue'

export interface SettingsBlock {
  title: string
  section: string
  fields?: string[]
  tip?: string
}

withDefaults(defineProps<{ blocks: SettingsBlock[] }>(), {})
</script>

<style scoped>
.settings-group {
  display: grid;
  gap: var(--qq-gap-md);
}

.settings-group__title {
  margin: 0 0 var(--qq-gap-md);
  font-size: var(--qq-text-md);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
