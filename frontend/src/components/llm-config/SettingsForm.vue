<template>
  <div class="settings-form">
    <template v-for="field in fieldNames" :key="field">
      <SettingField
        v-if="field === 'default_provider'"
        :label="labelOf(field).label"
        :hint="labelOf(field).hint"
        :model-value="valueOf(field) === null || valueOf(field) === undefined ? '' : String(valueOf(field))"
        :options="defaultProviderOptions"
        @update:model-value="set(field, $event === '' ? null : $event)"
      />
      <SettingField
        v-else
        :label="labelOf(field).label"
        :hint="labelOf(field).hint"
        :unit="labelOf(field).unit"
        :placeholder="labelOf(field).placeholder"
        :meta="metaOf(field)"
        :enum-key="`${section}.${field}`"
        :multiline="isLongText(field)"
        :model-value="valueOf(field)"
        @update:model-value="set(field, $event)"
      />
    </template>
    <p v-if="!fieldNames.length" class="settings-form__empty">该分组的字段说明尚未载入，请重新读取页面。</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import SettingField from './SettingField.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { SETTINGS_FIELD_LABELS, isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{
  section: string
  /** 只渲染这些字段（缺省渲染元数据中的全部字段，按后端定义顺序） */
  fields?: string[]
}>(), { fields: undefined })

const store = injectLlmConfigStore()

const data = computed<JsonObject>(() => {
  const settings = store.document.value?.settings
  if (!isObject(settings) || !isObject(settings[props.section])) return {}
  return settings[props.section] as JsonObject
})
const meta = computed(() => store.metadata.value.settings?.[props.section] || {})
const fieldNames = computed(() => props.fields || Object.keys(meta.value))

function labelOf(field: string) {
  return SETTINGS_FIELD_LABELS[props.section]?.[field] || { label: field }
}
function metaOf(field: string) {
  return meta.value[field]
}
function valueOf(field: string): JsonValue {
  const value = data.value[field]
  return value === undefined ? (metaOf(field)?.default ?? null) : value
}
function set(field: string, value: JsonValue) {
  store.updateSettingsSection(props.section, { ...data.value, [field]: value })
}
function isLongText(field: string) {
  return /prompt|reply$/.test(field) && metaOf(field)?.type === 'string'
}

const providers = computed<JsonObject[]>(() => Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : [])
const defaultProviderOptions = computed(() => [
  { value: '', label: '自动（第一个启用的渠道）' },
  ...providers.value.filter(provider => provider.enabled !== false).map(provider => ({ value: String(provider.id ?? ''), label: String(provider.id ?? '') })),
])
</script>

<style scoped>
.settings-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--qq-gap-md) var(--qq-gap-lg);
}

.settings-form :deep(.setting-field--row) {
  grid-column: 1 / -1;
  padding: 6px 0;
  border-bottom: 1px solid var(--qq-border-soft);
}

.settings-form__empty {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

@media (max-width: 760px) {
  .settings-form { grid-template-columns: 1fr; }
}
</style>
