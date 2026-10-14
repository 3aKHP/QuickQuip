<template>
  <div class="cascade-editor">
    <p v-if="!entries.length" class="cascade-editor__empty">尚未配置候选，运行时等同于只使用「默认渠道」。</p>
    <ol v-else class="cascade-editor__list">
      <li v-for="(entry, index) in entries" :key="index" class="cascade-editor__row">
        <span class="cascade-editor__order">{{ index + 1 }}</span>
        <template v-if="isDefaultEntry(entry)">
          <span class="cascade-editor__default">
            <UiIcon name="Sparkles" :size="13" />
            默认渠道
            <small>跟随「总开关与默认」里的默认渠道</small>
          </span>
        </template>
        <template v-else>
          <select
            class="cascade-editor__provider"
            :value="entryProvider(entry)"
            @change="setEntry(index, { provider_id: ($event.target as HTMLSelectElement).value, model: '' })"
          >
            <option v-if="!entryProvider(entry)" value="" disabled>选择渠道</option>
            <option v-for="provider in providers" :key="String(provider.id)" :value="String(provider.id)">{{ provider.id }}</option>
          </select>
          <select
            class="cascade-editor__model"
            :value="entryModel(entry)"
            @change="setEntry(index, { provider_id: entryProvider(entry), model: ($event.target as HTMLSelectElement).value })"
          >
            <option value="" disabled>选择模型</option>
            <option v-for="model in modelsOf(entryProvider(entry))" :key="model" :value="model">{{ model }}</option>
          </select>
        </template>
        <span class="cascade-editor__actions">
          <button type="button" :disabled="index === 0" title="上移" @click="move(index, -1)"><UiIcon name="ArrowUp" :size="13" /></button>
          <button type="button" :disabled="index === entries.length - 1" title="下移" @click="move(index, 1)"><UiIcon name="ArrowDown" :size="13" /></button>
          <button type="button" title="移除" class="cascade-editor__remove" @click="remove(index)"><UiIcon name="X" :size="13" /></button>
        </span>
      </li>
    </ol>
    <div class="cascade-editor__adder">
      <UiButton size="sm" icon="Plus" :disabled="!providers.length" @click="addExplicit">添加渠道模型</UiButton>
      <UiButton size="sm" variant="ghost" icon="Sparkles" @click="addDefault">添加默认渠道</UiButton>
    </div>
    <p class="cascade-editor__hint">任务失败时按顺序尝试下一个候选。</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'
import { isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const props = withDefaults(defineProps<{ modelValue: JsonValue[]; providers: JsonObject[] }>(), { providers: () => [] })
const emit = defineEmits<{ 'update:modelValue': [value: JsonValue[]] }>()

const entries = computed(() => Array.isArray(props.modelValue) ? props.modelValue : [])

function isDefaultEntry(entry: JsonValue) { return entry === '@default' }
function entryProvider(entry: JsonValue) { return isObject(entry) && typeof entry.provider_id === 'string' ? entry.provider_id : '' }
function entryModel(entry: JsonValue) { return isObject(entry) && typeof entry.model === 'string' ? entry.model : '' }
function modelsOf(providerId: string): string[] {
  const provider = props.providers.find(item => item.id === providerId)
  if (!provider || !Array.isArray(provider.models)) return []
  return provider.models.filter(isObject).map(model => String(model.model ?? '')).filter(Boolean)
}

function commit(next: JsonValue[]) { emit('update:modelValue', next) }
function setEntry(index: number, value: JsonObject) { commit(entries.value.map((entry, i) => i === index ? value : entry)) }
function move(index: number, direction: number) {
  const next = [...entries.value]
  const target = index + direction
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  commit(next)
}
function remove(index: number) { commit(entries.value.filter((_, i) => i !== index)) }
function addDefault() { commit([...entries.value, '@default']) }
function addExplicit() {
  const first = props.providers[0]
  const models = first ? modelsOf(String(first.id ?? '')) : []
  commit([...entries.value, { provider_id: String(first?.id ?? ''), model: models[0] ?? '' }])
}
</script>

<style scoped>
.cascade-editor {
  display: grid;
  gap: 8px;
}

.cascade-editor__empty {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.cascade-editor__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.cascade-editor__row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface-elevated);
}

.cascade-editor__order {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
  font-size: var(--qq-text-xs);
  font-weight: 700;
}

.cascade-editor__default {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-cyan-deep);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.cascade-editor__default small {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  font-weight: 400;
}

.cascade-editor__provider,
.cascade-editor__model {
  min-width: 0;
  padding: 6px 9px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.cascade-editor__provider { max-width: 200px; }
.cascade-editor__model { flex: 1; }

.cascade-editor__actions {
  margin-left: auto;
  display: inline-flex;
  gap: 2px;
}

.cascade-editor__actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
}

.cascade-editor__actions button:hover:not(:disabled) {
  background: var(--qq-surface-hover);
  color: var(--qq-text);
}

.cascade-editor__actions button:disabled {
  opacity: 0.35;
  cursor: default;
}

.cascade-editor__actions .cascade-editor__remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

.cascade-editor__adder {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cascade-editor__hint {
  margin: 0;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}
</style>
