<template>
  <div class="pricing-panel">
    <p class="pricing-panel__intro">
      价格用于用量统计的费用估算，单位是 <strong>美元 / 百万 token</strong>。0 表示免费；缓存价留空表示与输入价相同。
      「全渠道兜底」适用于任何渠道下的同名模型；精确到渠道的价格优先于兜底价。
    </p>

    <UiCard v-if="missingPriced.length" padding="md" accent="warn">
      <p class="missing-note">
        以下 {{ missingPriced.length }} 个已配置模型未配置价格，暂无法估算费用：
        <span v-for="item in missingPriced" :key="item" class="missing-note__item mono">{{ item }}</span>
      </p>
    </UiCard>

    <UiCard padding="lg">
      <div class="pricing-panel__toolbar">
        <h3>价格表 <span class="count">{{ rows.length }}</span></h3>
        <UiButton size="sm" icon="Plus" @click="addRow">添加价格</UiButton>
      </div>
      <UiEmpty v-if="!rows.length" icon="Coins" title="暂无价格配置" description="添加模型价格后，用量页才会统计费用" />
      <div v-else class="pricing-table-wrap">
        <table class="pricing-table">
          <thead>
            <tr>
              <th>模型</th>
              <th>渠道</th>
              <th>输入价</th>
              <th>输出价</th>
              <th>缓存读价</th>
              <th>缓存写价</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="index" :class="{ 'pricing-table--dupe': isDupe(index) }">
              <td><input :value="String(row.model ?? '')" placeholder="模型名" autocomplete="off" spellcheck="false" @input="patch(index, { model: ($event.target as HTMLInputElement).value })" /></td>
              <td>
                <select :value="row.provider_id === null || row.provider_id === undefined ? '' : String(row.provider_id)" @change="patch(index, { provider_id: ($event.target as HTMLSelectElement).value || null })">
                  <option value="">全渠道兜底</option>
                  <option v-for="provider in providers" :key="String(provider.id)" :value="String(provider.id)">仅 {{ provider.id }}</option>
                </select>
              </td>
              <td><input type="number" min="0" step="any" :value="numberText(row.input_per_mtok)" @input="patchNumber(index, 'input_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="numberText(row.output_per_mtok)" @input="patchNumber(index, 'output_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="nullableText(row.cache_read_per_mtok)" placeholder="同输入价" @input="patchNullableNumber(index, 'cache_read_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="nullableText(row.cache_write_per_mtok)" placeholder="同输入价" @input="patchNullableNumber(index, 'cache_write_per_mtok', $event)" /></td>
              <td><button type="button" class="row-remove" title="删除该价格" @click="remove(index)"><UiIcon name="X" :size="14" /></button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="dupes.length" class="dupe-note">存在重复的「渠道 + 模型」组合：{{ dupes.join('、') }}，保存时会被拒绝。</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { fieldTemplate, isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const rows = computed<JsonObject[]>(() => Array.isArray(store.document.value?.pricing) ? store.document.value.pricing.filter(isObject) : [])
const providers = computed<JsonObject[]>(() => Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : [])

function commit(next: JsonObject[]) { store.updateSection('pricing', next) }
function patch(index: number, fields: JsonObject) { commit(rows.value.map((row, i) => i === index ? { ...row, ...fields } : row)) }
function remove(index: number) { commit(rows.value.filter((_, i) => i !== index)) }
function addRow() { commit([...rows.value, structuredClone(fieldTemplate('pricing'))]) }

function numberText(value: JsonValue | undefined) { return typeof value === 'number' ? String(value) : '0' }
function nullableText(value: JsonValue | undefined) { return typeof value === 'number' ? String(value) : '' }
function patchNumber(index: number, key: string, event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (Number.isFinite(value)) patch(index, { [key]: value })
}
function patchNullableNumber(index: number, key: string, event: Event) {
  const text = (event.target as HTMLInputElement).value
  if (text === '') { patch(index, { [key]: null }); return }
  const value = Number(text)
  if (Number.isFinite(value)) patch(index, { [key]: value })
}

function keyOf(row: JsonObject) { return `${row.provider_id ?? ''}::${String(row.model ?? '')}` }
const dupes = computed(() => {
  const seen = new Map<string, number>()
  for (const row of rows.value) seen.set(keyOf(row), (seen.get(keyOf(row)) ?? 0) + 1)
  return [...seen.entries()].filter(([, count]) => count > 1).map(([key]) => key.replace('::', ' / ') || '（空）')
})
function isDupe(index: number) { const key = keyOf(rows.value[index]!); return dupes.value.some(dupe => dupe === (key.replace('::', ' / ') || '（空）')) }

/** 已配置但无任何匹配价格的「渠道 · 模型」，与后端 price_missing 口径一致（精确 → 兜底） */
const missingPriced = computed(() => {
  const missing: string[] = []
  for (const provider of providers.value) {
    if (provider.enabled === false) continue
    const models = Array.isArray(provider.models) ? provider.models.filter(isObject) : []
    for (const model of models) {
      if (model.enabled === false) continue
      const name = String(model.model ?? '')
      const hit = rows.value.some(row => String(row.model ?? '') === name && (row.provider_id === null || row.provider_id === undefined || row.provider_id === provider.id))
      if (name && !hit) missing.push(`${provider.id} · ${name}`)
    }
  }
  return missing
})
</script>

<style scoped>
.pricing-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.pricing-panel__intro {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
}

.missing-note {
  margin: 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
  line-height: 1.8;
}

.missing-note__item {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 1px 8px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-warn-soft);
}

.pricing-panel__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--qq-gap-sm);
}

.pricing-panel__toolbar h3 {
  margin: 0;
  font-size: var(--qq-text-md);
}

.count {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.pricing-table-wrap {
  overflow-x: auto;
}

.pricing-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--qq-text-sm);
}

.pricing-table th {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--qq-border);
  white-space: nowrap;
}

.pricing-table td {
  padding: 4px 8px 4px 0;
  border-bottom: 1px solid var(--qq-border-soft);
}

.pricing-table input,
.pricing-table select {
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.pricing-table td:first-child input { font-family: var(--qq-font-mono); }

.pricing-table input[type='number'] { width: 110px; }

.pricing-table--dupe td {
  background: var(--qq-warn-soft);
}

.row-remove {
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

.dupe-note {
  margin: 10px 0 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
}

.mono { font-family: var(--qq-font-mono); }
</style>
