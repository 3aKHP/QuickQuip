<template>
  <div :class="['setting-field', { 'setting-field--row': kind === 'toggle' }]">
    <div class="setting-field__head">
      <label :for="controlId" class="setting-field__label">
        {{ label }}
        <UiInfoTip v-if="hint" :text="hint" />
      </label>
      <span v-if="unit && kind !== 'toggle'" class="setting-field__unit">{{ unit }}</span>
    </div>
    <UiToggle v-if="kind === 'toggle'" :model-value="modelValue === true" size="sm" @update:model-value="emit('update:modelValue', $event)" />
    <select
      v-else-if="kind === 'select'"
      :id="controlId"
      class="setting-field__control"
      :value="stringValue"
      @change="onSelect"
    >
      <option v-for="option in selectOptions" :key="String(option.value)" :value="String(option.value)">{{ option.label }}</option>
    </select>
    <input
      v-else-if="kind === 'number'"
      :id="controlId"
      class="setting-field__control"
      type="number"
      :step="meta?.type === 'integer' ? 1 : 'any'"
      :min="meta?.minimum"
      :max="meta?.maximum ?? undefined"
      :value="typeof modelValue === 'number' ? modelValue : ''"
      :placeholder="placeholder"
      @input="onNumber"
    />
    <StringListEditor v-else-if="kind === 'list'" :model-value="listValue" :placeholder="placeholder" @update:model-value="emit('update:modelValue', $event)" />
    <textarea
      v-else-if="kind === 'textarea'"
      :id="controlId"
      class="setting-field__control"
      rows="3"
      :value="stringValue"
      :placeholder="placeholder"
      autocomplete="off"
      spellcheck="false"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
    <input
      v-else
      :id="controlId"
      class="setting-field__control"
      :value="stringValue"
      :placeholder="placeholder"
      autocomplete="off"
      spellcheck="false"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p v-if="rangeHint" class="setting-field__range">{{ rangeHint }}</p>
  </div>
</template>

<script lang="ts">
// 模块级计数器：保证跨实例的表单 control id 唯一
let controlSequence = 0

export type SettingFieldKind = 'toggle' | 'select' | 'number' | 'text' | 'textarea' | 'list'
</script>

<script setup lang="ts">
import { computed } from 'vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiToggle from '../ui/UiToggle.vue'
import StringListEditor from './StringListEditor.vue'
import { ENUM_OPTION_LABELS, type FieldMetadata, type JsonValue } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{
  label: string
  /** 注意：必须是 unknown —— 若类型联合含 boolean，Vue 运行时会把空字符串布尔转型为 true */
  modelValue: unknown
  /** 显式控件类型；缺省时按 meta.type 推导，绝不嗅探值类型 */
  kind?: SettingFieldKind
  meta?: FieldMetadata
  hint?: string
  unit?: string
  placeholder?: string
  options?: { value: string | number | boolean; label: string }[]
  /** 枚举字段的词典键（如 tools.enabled_mode），用于查中文显示名 */
  enumKey?: string
  multiline?: boolean
}>(), { kind: undefined, meta: undefined, hint: undefined, unit: undefined, placeholder: undefined, options: undefined, enumKey: undefined, multiline: false })

const emit = defineEmits<{ 'update:modelValue': [value: JsonValue] }>()

const controlId = `setting-field-${++controlSequence}`

const kind = computed<SettingFieldKind>(() => {
  if (props.kind) return props.kind
  if (props.options) return 'select'
  const type = props.meta?.type
  if (type === 'boolean') return 'toggle'
  if (props.meta?.enum) return 'select'
  if (['integer', 'number', 'float', 'int'].includes(type || '')) return 'number'
  if (type === 'array') return 'list'
  if (props.multiline) return 'textarea'
  return 'text'
})

/** 下拉选项：显式 options 优先，否则用 meta.enum + 中文词典 */
const selectOptions = computed(() => {
  if (props.options) return props.options
  const values = props.meta?.enum ?? []
  const labels = (props.enumKey && ENUM_OPTION_LABELS[props.enumKey]) || {}
  return values.map(value => ({
    value: value as string | number | boolean,
    label: labels[String(value)] ?? (value === '' ? '（空）' : String(value)),
  }))
})

const stringValue = computed(() => props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue))
const listValue = computed(() => Array.isArray(props.modelValue) ? props.modelValue.map(String) : [])
const rangeHint = computed(() => {
  if (kind.value !== 'number' || (props.meta?.minimum === undefined && props.meta?.maximum === undefined)) return ''
  const min = props.meta?.minimum ?? '不限'
  const max = props.meta?.maximum ?? '不限'
  return `范围 ${min} ~ ${max}${props.unit ? ` ${props.unit}` : ''}`
})

function onSelect(event: Event) {
  const text = (event.target as HTMLSelectElement).value
  const option = selectOptions.value.find(item => String(item.value) === text)
  emit('update:modelValue', (option ? option.value : text) as JsonValue)
}

function onNumber(event: Event) {
  const text = (event.target as HTMLInputElement).value
  if (text === '') return
  const value = Number(text)
  if (Number.isFinite(value)) emit('update:modelValue', value)
}
</script>

<style scoped>
.setting-field {
  display: grid;
  gap: 6px;
  min-width: 0;
  align-content: start;
}

.setting-field--row {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.setting-field__head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.setting-field__label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.setting-field__unit {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}

.setting-field__control {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.setting-field__control:focus {
  border-color: var(--qq-primary-border);
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-soft);
}

textarea.setting-field__control {
  resize: vertical;
  line-height: 1.6;
}

.setting-field__range {
  margin: 0;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}
</style>
