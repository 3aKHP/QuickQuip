<template>
  <div class="styles-panel">
    <p class="styles-panel__intro">
      风格档案是一段可复用的回复风格指令，在渠道或模型的「参数覆盖 → 风格档案」中引用。删除仍被引用的风格会被拒绝。
    </p>
    <UiCard padding="lg">
      <div class="styles-panel__toolbar">
        <h3>风格档案 <span class="count">{{ entries.length }}</span></h3>
        <UiButton size="sm" icon="Plus" @click="add">添加风格</UiButton>
      </div>
      <UiEmpty v-if="!entries.length" icon="Palette" title="暂无风格档案" description="添加后可被任意渠道或模型引用" />
      <div v-for="(entry, index) in entries" :key="index" class="style-row">
        <div class="style-row__head">
          <input
            class="style-row__name"
            :value="entry.name"
            placeholder="风格名（引用用）"
            autocomplete="off"
            spellcheck="false"
            @input="rename(index, ($event.target as HTMLInputElement).value)"
          />
          <UiTag v-if="referencedBy(entry.name)" size="sm" variant="cyan">被 {{ referencedBy(entry.name) }} 处引用</UiTag>
          <button type="button" class="row-remove" title="删除该风格" @click="remove(index)"><UiIcon name="Trash2" :size="14" /></button>
        </div>
        <textarea
          class="style-row__text"
          rows="3"
          :value="entry.text"
          placeholder="写给模型的风格指令，例如：回复要简短、口语化，少用术语。"
          spellcheck="false"
          @input="update(index, ($event.target as HTMLTextAreaElement).value)"
        />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiTag from '../ui/UiTag.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { isObject, type JsonObject } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const profiles = computed<JsonObject>(() => isObject(store.document.value?.style_profiles) ? store.document.value.style_profiles : {})
const entries = computed(() => Object.entries(profiles.value).map(([name, value]) => ({ name, text: String(value ?? '') })))

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

function commit(next: JsonObject) { store.updateSection('style_profiles', next) }
function rebuild(list: { name: string; text: string }[]) {
  const result: JsonObject = {}
  for (const entry of list) if (entry.name.trim()) result[entry.name.trim()] = entry.text
  commit(result)
}
function rename(index: number, name: string) {
  rebuild(entries.value.map((entry, i) => i === index ? { ...entry, name } : entry))
}
function update(index: number, text: string) {
  rebuild(entries.value.map((entry, i) => i === index ? { ...entry, text } : entry))
}
function remove(index: number) {
  rebuild(entries.value.filter((_, i) => i !== index))
}
function add() {
  const base = 'new-style'
  let name = base
  let suffix = 2
  while (profiles.value[name] !== undefined) name = `${base}-${suffix++}`
  commit({ ...profiles.value, [name]: '' })
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

.style-row__head {
  display: flex;
  align-items: center;
  gap: 8px;
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
