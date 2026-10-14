<template>
  <div class="provider-picker">
    <select :value="providerId" @change="onProvider">
      <option value="">{{ emptyProviderLabel }}</option>
      <option v-for="provider in enabledProviders" :key="String(provider.id)" :value="String(provider.id)">{{ provider.id }}</option>
    </select>
    <select :value="model" :disabled="!providerId" @change="emit('update:model', ($event.target as HTMLSelectElement).value)">
      <option value="">{{ allowEmptyModel ? '渠道默认模型' : '选择模型' }}</option>
      <option v-for="name in models" :key="name" :value="name">{{ name }}</option>
    </select>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { isObject, type JsonObject } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{
  providerId: string
  model: string
  providers: JsonObject[]
  /** 空渠道选项的文案，如「关闭」 */
  emptyProviderLabel?: string
  /** 模型是否允许留空（= 渠道默认模型） */
  allowEmptyModel?: boolean
}>(), { emptyProviderLabel: '（不选择）', allowEmptyModel: true })

const emit = defineEmits<{ 'update:providerId': [value: string]; 'update:model': [value: string] }>()

const enabledProviders = computed(() => props.providers.filter(provider => provider.enabled !== false))
const models = computed(() => {
  const provider = props.providers.find(item => item.id === props.providerId)
  if (!provider || !Array.isArray(provider.models)) return []
  return provider.models.filter(isObject).map(model => String(model.model ?? '')).filter(Boolean)
})

function onProvider(event: Event) {
  emit('update:providerId', (event.target as HTMLSelectElement).value)
  emit('update:model', '')
}
</script>

<style scoped>
.provider-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.provider-picker select {
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}
</style>
