<template>
  <div class="kv-editor">
    <div v-for="row in rows" :key="row.id" class="kv-editor__row">
      <input
        class="kv-editor__key"
        :class="{ 'is-duplicate': isDuplicateKey(row.key) }"
        :value="row.key"
        placeholder="名称"
        autocomplete="off"
        spellcheck="false"
        @input="update(row.id, ($event.target as HTMLInputElement).value, undefined)"
      />
      <input
        class="kv-editor__value"
        :value="row.value"
        :placeholder="valuePlaceholder"
        autocomplete="off"
        spellcheck="false"
        @input="update(row.id, undefined, ($event.target as HTMLInputElement).value)"
      />
      <button type="button" class="kv-editor__remove" :aria-label="`移除 ${row.key || '该行'}`" @click="remove(row.id)">
        <UiIcon name="X" :size="13" />
      </button>
    </div>
    <p v-if="duplicateKeys.size" class="kv-editor__warn">
      存在重复键：{{ [...duplicateKeys].join('、') }}（重名行未覆盖已有键值，请修改重复项）
    </p>
    <UiButton size="sm" icon="Plus" @click="append">添加一行</UiButton>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, toRaw, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'
import { isObject, type JsonObject } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{ modelValue: JsonObject; valuePlaceholder?: string }>(), { valuePlaceholder: '值' })
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()

interface Row { id: number; key: string; value: string }

let nextRowId = 1

function toRows(source: JsonObject): Row[] {
  return Object.entries(isObject(source) ? source : {}).map(([key, value]) => ({
    id: nextRowId++,
    key,
    value: String(value ?? ''),
  }))
}

// 本地行编辑态：稳定行 ID + 引用身份保护，避免自提交重建行，同时保证外部重载/切换对象立即刷新
const rows = ref<Row[]>(toRows(props.modelValue))
let lastEmittedObj: JsonObject | null = toRaw(props.modelValue)

watch(() => props.modelValue, value => {
  const raw = toRaw(value)
  if (raw === lastEmittedObj) return
  rows.value = toRows(value)
  lastEmittedObj = raw
})

const duplicateKeys = computed(() => {
  const counts = new Map<string, number>()
  for (const row of rows.value) {
    const key = row.key.trim()
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([key]) => key))
})

function isDuplicateKey(rawKey: string): boolean {
  const key = rawKey.trim()
  return Boolean(key && duplicateKeys.value.has(key))
}

function commit(next: Row[]) {
  rows.value = next
  const result: JsonObject = {}
  for (const row of next) {
    const key = row.key.trim()
    if (key && !(key in result)) result[key] = row.value
  }
  lastEmittedObj = result
  emit('update:modelValue', result)
}

function update(id: number, key?: string, value?: string) {
  commit(rows.value.map(row => row.id === id ? { ...row, key: key ?? row.key, value: value ?? row.value } : row))
}

function remove(id: number) {
  commit(rows.value.filter(row => row.id !== id))
}

function append() {
  rows.value = [...rows.value, { id: nextRowId++, key: '', value: '' }]
}
</script>

<style scoped>
.kv-editor {
  display: grid;
  gap: 8px;
  justify-items: start;
}

.kv-editor__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) auto;
  gap: 8px;
  width: 100%;
  align-items: center;
}

.kv-editor__row input {
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
}

.kv-editor__key.is-duplicate {
  border-color: var(--qq-warn);
}

.kv-editor__warn {
  margin: 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-xs);
}

.kv-editor__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
}

.kv-editor__remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}
</style>
