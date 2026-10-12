<template>
  <div class="kv-editor">
    <div v-for="(row, index) in rows" :key="index" class="kv-editor__row">
      <input
        class="kv-editor__key"
        :value="row.key"
        placeholder="名称"
        autocomplete="off"
        spellcheck="false"
        @input="update(index, ($event.target as HTMLInputElement).value, undefined)"
      />
      <input
        class="kv-editor__value"
        :value="row.value"
        :placeholder="valuePlaceholder"
        autocomplete="off"
        spellcheck="false"
        @input="update(index, undefined, ($event.target as HTMLInputElement).value)"
      />
      <button type="button" class="kv-editor__remove" :aria-label="`移除 ${row.key || '该行'}`" @click="remove(index)">
        <UiIcon name="X" :size="13" />
      </button>
    </div>
    <UiButton size="sm" icon="Plus" @click="append">添加一行</UiButton>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'
import { isObject, type JsonObject } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{ modelValue: JsonObject; valuePlaceholder?: string }>(), { valuePlaceholder: '值' })
const emit = defineEmits<{ 'update:modelValue': [value: JsonObject] }>()

interface Row { key: string; value: string }

function toRows(source: JsonObject): Row[] {
  return Object.entries(isObject(source) ? source : {}).map(([key, value]) => ({ key, value: String(value ?? '') }))
}

// 本地行编辑态：允许空键行存在；外部模型变化（读取/导入/恢复）时重建
const rows = ref<Row[]>(toRows(props.modelValue))
watch(() => props.modelValue, value => {
  const incoming = toRows(value)
  if (JSON.stringify(incoming.map(r => [r.key, r.value])) !== JSON.stringify(rows.value.filter(r => r.key.trim()).map(r => [r.key, r.value]))) {
    rows.value = incoming
  }
}, { deep: true })

function commit(next: Row[]) {
  rows.value = next
  const result: JsonObject = {}
  for (const row of next) if (row.key.trim()) result[row.key.trim()] = row.value
  emit('update:modelValue', result)
}

function update(index: number, key?: string, value?: string) {
  commit(rows.value.map((row, i) => i === index ? { key: key ?? row.key, value: value ?? row.value } : row))
}

function remove(index: number) {
  commit(rows.value.filter((_, i) => i !== index))
}

function append() {
  commit([...rows.value, { key: '', value: '' }])
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
