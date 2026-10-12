<template>
  <div class="params-editor">
    <section v-for="group in groups" :key="group.key" class="params-group">
      <header class="params-group__head">
        <h4>{{ PARAM_GROUP_LABELS[group.key] || group.key }}</h4>
        <UiTag v-if="group.overridden" size="sm" variant="cyan">{{ group.overridden }} 项覆盖</UiTag>
      </header>
      <div class="params-group__rows">
        <div v-for="name in group.names" :key="name" class="param-row" :class="{ 'param-row--inherited': !isOverridden(name) }">
          <div class="param-row__label">
            <span class="param-row__name">{{ labelFor(name).label || name }}</span>
            <UiInfoTip v-if="labelFor(name).hint" :text="labelFor(name).hint" />
            <span v-if="labelFor(name).unit" class="param-row__unit">{{ labelFor(name).unit }}</span>
          </div>
          <div v-if="isOverridden(name)" class="param-row__control">
            <UiSegmented
              v-if="metaFor(name)?.type === 'boolean'"
              :model-value="valueFor(name) ? 'on' : 'off'"
              :options="[{ value: 'on', label: '开' }, { value: 'off', label: '关' }]"
              @update:model-value="setParam(name, $event === 'on')"
            />
            <select
              v-else-if="name === 'style_profile'"
              :value="String(valueFor(name) ?? '')"
              @change="setParam(name, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">（不使用风格）</option>
              <option v-for="profile in styleProfiles" :key="profile" :value="profile">{{ profile }}</option>
            </select>
            <select
              v-else-if="metaFor(name)?.enum"
              :value="String(valueFor(name) ?? '')"
              @change="setParam(name, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="option in metaFor(name)!.enum!" :key="String(option)" :value="String(option)">{{ option === '' ? '（不发送）' : option }}</option>
            </select>
            <textarea
              v-else-if="metaFor(name)?.type === 'object'"
              rows="2"
              spellcheck="false"
              :value="jsonText(name)"
              @change="onJsonChange(name, $event)"
            />
            <input
              v-else-if="isNumeric(name)"
              type="number"
              :step="metaFor(name)?.type === 'integer' ? 1 : 'any'"
              :min="metaFor(name)?.minimum"
              :max="metaFor(name)?.maximum ?? undefined"
              :value="valueFor(name) === null ? '' : Number(valueFor(name))"
              @input="onNumber(name, $event)"
            />
            <input
              v-else
              :value="String(valueFor(name) ?? '')"
              autocomplete="off"
              spellcheck="false"
              @input="setParam(name, ($event.target as HTMLInputElement).value)"
            />
            <button type="button" class="param-row__reset" title="恢复为跟随上层" @click="clearParam(name)">
              <UiIcon name="RotateCcw" :size="13" />
            </button>
          </div>
          <div v-else class="param-row__inherited">
            <span class="param-row__inherit-chip">跟随上层</span>
            <UiButton size="sm" variant="ghost" @click="overrideParam(name)">覆盖</UiButton>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiSegmented from '../ui/UiSegmented.vue'
import UiTag from '../ui/UiTag.vue'
import { toast } from '../../toast'
import { PARAM_GROUPS, PARAM_GROUP_LABELS, PARAM_LABELS, type FieldMetadata, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{
  modelValue: JsonObject
  metadata?: Record<string, FieldMetadata>
  styleProfiles?: string[]
}>(), { metadata: () => ({}), styleProfiles: () => [] })

const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()

/** 覆盖态判定：键存在且非 null 即为覆盖；null/缺失都表示跟随上层 */
function isOverridden(name: string) {
  return props.modelValue[name] !== null && props.modelValue[name] !== undefined
}
function valueFor(name: string): JsonValue {
  return props.modelValue[name] ?? null
}
function metaFor(name: string): FieldMetadata | undefined {
  return props.metadata[name]
}
function labelFor(name: string) {
  return PARAM_LABELS[name] || { label: name }
}
function isNumeric(name: string) {
  return ['integer', 'number', 'float', 'int'].includes(props.metadata[name]?.type || '')
}
/** 覆盖时的初始值：元数据默认 → 类型兜底 */
function initialValue(name: string): JsonValue {
  const meta = props.metadata[name]
  if (meta?.default !== undefined && meta.default !== null) return structuredClone(meta.default)
  if (meta?.enum?.length) return meta.enum[0]!
  if (meta?.type === 'boolean') return true
  if (isNumeric(name)) return meta?.minimum ?? 0
  if (meta?.type === 'object') return {}
  return ''
}

const groups = computed(() => {
  const available = Object.keys(props.metadata).length ? Object.keys(props.metadata) : Object.values(PARAM_GROUPS).flat()
  return Object.entries(PARAM_GROUPS)
    .map(([key, names]) => {
      const present = names.filter(name => available.includes(name))
      return { key, names: present, overridden: present.filter(isOverridden).length }
    })
    .filter(group => group.names.length > 0)
})

function setParam(name: string, value: JsonValue) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}
function clearParam(name: string) {
  emit('update:modelValue', { ...props.modelValue, [name]: null })
}
function overrideParam(name: string) {
  setParam(name, initialValue(name))
}
function onNumber(name: string, event: Event) {
  const text = (event.target as HTMLInputElement).value
  if (text === '') return
  const value = Number(text)
  if (Number.isFinite(value)) setParam(name, value)
}
function jsonText(name: string) {
  const value = props.modelValue[name]
  return value === null || value === undefined ? '' : JSON.stringify(value, null, 2)
}
function onJsonChange(name: string, event: Event) {
  const text = (event.target as HTMLTextAreaElement).value.trim()
  if (!text) { setParam(name, {}); return }
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('not an object')
    setParam(name, parsed as JsonObject)
  } catch {
    toast('附加请求体必须是 JSON 对象', 'error')
    ;(event.target as HTMLTextAreaElement).value = jsonText(name)
  }
}
</script>

<style scoped>
.params-editor {
  display: grid;
  gap: var(--qq-gap-md);
}

.params-group {
  display: grid;
  gap: 4px;
}

.params-group__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--qq-border);
}

.params-group__head h4 {
  margin: 0;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.params-group__rows {
  display: grid;
}

.param-row {
  display: grid;
  grid-template-columns: minmax(160px, 240px) minmax(0, 1fr);
  gap: var(--qq-gap-sm);
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid var(--qq-border-soft);
}

.param-row:last-child {
  border-bottom: 0;
}

.param-row--inherited {
  opacity: 0.75;
}

.param-row__label {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.param-row__name {
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.param-row__unit {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.param-row__control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-row__control input,
.param-row__control select,
.param-row__control textarea {
  flex: 1;
  min-width: 0;
  max-width: 280px;
  padding: 6px 9px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.param-row__control textarea {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  resize: vertical;
}

.param-row__reset {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
}

.param-row__reset:hover {
  background: var(--qq-warn-soft);
  color: var(--qq-warn);
}

.param-row__inherited {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-row__inherit-chip {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

@media (max-width: 700px) {
  .param-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
</style>
