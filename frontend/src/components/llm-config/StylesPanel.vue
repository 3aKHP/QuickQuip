<template>
  <div class="styles-panel">
    <p class="styles-panel__intro">
      风格档案是一段可复用的回复风格指令，在渠道或模型的「参数覆盖 → 风格档案」中引用。删除仍被引用的风格会被拒绝。
    </p>
    <UiCard padding="lg">
      <div class="styles-panel__toolbar">
        <h3>风格档案 <span class="count">{{ rows.length }}</span></h3>
        <UiButton size="sm" icon="Plus" @click="add">添加风格</UiButton>
      </div>
      <UiEmpty v-if="!rows.length" icon="Palette" title="暂无风格档案" description="添加后可被任意渠道或模型引用" />
      <div v-for="row in rows" :key="row.id" class="style-row" :class="{ 'style-row--invalid': Boolean(rowError(row)) }">
        <div class="style-row__head">
          <input
            class="style-row__name"
            :class="{ 'is-invalid': Boolean(rowError(row)) }"
            :value="row.name"
            placeholder="风格名（引用用）"
            autocomplete="off"
            spellcheck="false"
            @input="rename(row.id, ($event.target as HTMLInputElement).value)"
          />
          <UiTag v-if="row.name.trim() && referencedBy(row.name.trim())" size="sm" variant="cyan">被 {{ referencedBy(row.name.trim()) }} 处引用</UiTag>
          <button type="button" class="row-remove" title="删除该风格" @click="remove(row.id)"><UiIcon name="Trash2" :size="14" /></button>
        </div>
        <p v-if="rowError(row)" class="style-row__error">{{ rowError(row) }}</p>
        <textarea
          class="style-row__text"
          rows="3"
          :value="row.text"
          placeholder="写给模型的风格指令，例如：回复要简短、口语化，少用术语。"
          spellcheck="false"
          @input="update(row.id, ($event.target as HTMLTextAreaElement).value)"
        />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, toRaw, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiTag from '../ui/UiTag.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { isObject, type JsonObject } from '../../lib/llmConfig'

interface StyleRow {
  id: number
  name: string
  text: string
}

const store = injectLlmConfigStore()

let nextRowId = 1
function toRows(source: JsonObject): StyleRow[] {
  return Object.entries(source).map(([name, value]) => ({
    id: nextRowId++,
    name,
    text: String(value ?? ''),
  }))
}

const EMPTY_PROFILES: JsonObject = Object.freeze({})
const profiles = computed<JsonObject>(() => isObject(store.document.value?.style_profiles) ? store.document.value.style_profiles : EMPTY_PROFILES)
const rows = ref<StyleRow[]>(toRows(profiles.value))
let lastCommittedObj: JsonObject | null = toRaw(profiles.value)

watch(profiles, next => {
  const raw = toRaw(next)
  if (raw === lastCommittedObj) return
  rows.value = toRows(next)
  lastCommittedObj = raw
})

const duplicateNames = computed(() => {
  const counts = new Map<string, number>()
  for (const row of rows.value) {
    const trimmed = row.name.trim()
    if (trimmed) counts.set(trimmed, (counts.get(trimmed) ?? 0) + 1)
  }
  return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([name]) => name))
})

function rowError(row: StyleRow): string {
  const trimmed = row.name.trim()
  if (!trimmed) return '风格名不能为空，填写后将自动同步到草稿'
  if (duplicateNames.value.has(trimmed)) return `风格名「${trimmed}」与其他条目重复，修改后将自动同步到草稿`
  return ''
}

function hasValidationErrors(list: StyleRow[]): boolean {
  const seen = new Set<string>()
  for (const row of list) {
    const trimmed = row.name.trim()
    if (!trimmed || seen.has(trimmed)) return true
    seen.add(trimmed)
  }
  return false
}

/** 统计某风格被渠道/模型参数引用的次数 */
function referencedBy(name: string): number {
  const providers = Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : []
  let count = 0
  for (const provider of providers) {
    if (isObject(provider.parameters) && provider.parameters.style_profile === name) count++
    for (const model of Array.isArray(provider.models) ? provider.models.filter(isObject) : []) {
      if (isObject(model.parameters) && model.parameters.style_profile === name) count++
    }
  }
  return count
}

function commitIfValid(list: StyleRow[]) {
  if (hasValidationErrors(list)) return
  const result: JsonObject = {}
  for (const row of list) result[row.name.trim()] = row.text
  lastCommittedObj = result
  store.updateSection('style_profiles', result)
}

function rename(id: number, name: string) {
  rows.value = rows.value.map(row => row.id === id ? { ...row, name } : row)
  commitIfValid(rows.value)
}

function update(id: number, text: string) {
  rows.value = rows.value.map(row => row.id === id ? { ...row, text } : row)
  commitIfValid(rows.value)
}

function remove(id: number) {
  rows.value = rows.value.filter(row => row.id !== id)
  commitIfValid(rows.value)
}

function add() {
  const existingNames = new Set([
    ...Object.keys(profiles.value),
    ...rows.value.map(row => row.name.trim()).filter(Boolean),
  ])
  const base = 'new-style'
  let name = base
  let suffix = 2
  while (existingNames.has(name)) name = `${base}-${suffix++}`
  rows.value = [...rows.value, { id: nextRowId++, name, text: '' }]
  commitIfValid(rows.value)
}
</script>

<style scoped>
.styles-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.styles-panel__intro {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
}

.styles-panel__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--qq-gap-sm);
}

.styles-panel__toolbar h3 {
  margin: 0;
  font-size: var(--qq-text-md);
}

.count {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.style-row {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  padding: 10px 12px;
  display: grid;
  gap: 8px;
  margin-bottom: 8px;
}

.style-row--invalid {
  border-color: var(--qq-danger-border, var(--qq-danger));
}

.style-row__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.style-row__name {
  width: 220px;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
}

.style-row__name.is-invalid {
  border-color: var(--qq-danger);
}

.style-row__error {
  margin: 0;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs);
}

.style-row__text {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
  line-height: 1.6;
  resize: vertical;
}

.row-remove {
  margin-left: auto;
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

.row-remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}
</style>
