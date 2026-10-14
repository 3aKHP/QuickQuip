<template>
  <div class="pricing-panel">
    <UiCard padding="md" class="pricing-summary">
      <div class="pricing-summary__stats">
        <span><strong>{{ rows.length }}</strong> 条价格</span>
        <span :class="{ warn: missing.length }"><strong>{{ missing.length }}</strong> 个模型未定价</span>
        <span v-if="incomplete.length" class="warn"><strong>{{ incomplete.length }}</strong> 条单价未填写</span>
        <span v-if="orphans.length" class="warn"><strong>{{ orphans.length }}</strong> 条不在渠道模型清单</span>
        <span v-if="dupes.size" class="danger"><strong>{{ dupes.size }}</strong> 组重复</span>
      </div>
      <div class="pricing-summary__actions">
        <select v-model="providerFilter" aria-label="按渠道筛选">
          <option value="">全部渠道</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.id }}</option>
        </select>
        <UiButton size="sm" icon="ListPlus" :disabled="!visibleMissing.length" @click="addMissing(visibleMissing)">为未定价模型添加价格行</UiButton>
      </div>
      <p class="pricing-summary__hint">
        计费按「渠道 + 配置的模型 ID」精确匹配，不跨渠道兜底。单位为美元 / 百万 token；0 表示免费，缓存价留空表示与输入价相同。新添加的行需填写输入价与输出价后才能保存。
      </p>
    </UiCard>

    <UiEmpty v-if="!groups.length" icon="Server" title="还没有渠道" description="先在「渠道与模型」添加渠道和模型，再为模型配置价格" />

    <UiCard v-for="group in visibleGroups" :key="group.id" padding="lg" class="pricing-group" :accent="group.known ? undefined : 'danger'">
      <header class="pricing-group__head">
        <div class="pricing-group__title">
          <h3 class="mono">{{ group.id }}</h3>
          <UiTag v-if="!group.known" size="sm" variant="danger">渠道不存在</UiTag>
          <UiTag v-else-if="group.disabled" size="sm">已停用</UiTag>
          <span class="muted">已定价 {{ group.priced }} / {{ group.models.length }} 个模型</span>
        </div>
        <UiButton v-if="group.known" size="sm" icon="Plus" :disabled="!group.unpriced.length" :title="group.unpriced.length ? '' : '该渠道所有模型均已定价'" @click="addMissing(group.unpriced.map(model => ({ provider: group.id, model })))">添加价格</UiButton>
      </header>

      <div v-if="group.unpriced.length" class="unpriced">
        <span class="unpriced__label">未定价：</span>
        <button v-for="model in group.unpriced" :key="model" type="button" class="unpriced__chip mono" title="点击添加该模型的价格行" @click="addMissing([{ provider: group.id, model }])">
          <UiIcon name="Plus" :size="12" />{{ model }}
        </button>
      </div>

      <p v-if="!group.rows.length" class="muted">该渠道暂无价格。</p>
      <div v-else class="pricing-table-wrap">
        <table class="pricing-table">
          <thead>
            <tr>
              <th>模型</th>
              <th>输入价</th>
              <th>输出价</th>
              <th>缓存读价</th>
              <th>缓存写价</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="{ row, index } in group.rows" :key="index" :class="{ 'row--dupe': isDupe(row), 'row--orphan': isOrphan(row) }">
              <td class="model-cell">
                <select :value="String(row.model ?? '')" :disabled="!group.known" @change="patch(index, { model: ($event.target as HTMLSelectElement).value })">
                  <option v-if="!row.model" value="" disabled>选择模型</option>
                  <option v-if="row.model && isOrphan(row)" :value="String(row.model)">{{ row.model }}（不在模型清单）</option>
                  <option v-for="model in modelOptions(group, row)" :key="model" :value="model">{{ model }}</option>
                </select>
              </td>
              <td><input type="number" min="0" step="any" :value="numberText(row.input_per_mtok)" :class="{ invalid: !isNumber(row.input_per_mtok) }" placeholder="必填" @change="patchNumber(index, 'input_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="numberText(row.output_per_mtok)" :class="{ invalid: !isNumber(row.output_per_mtok) }" placeholder="必填" @change="patchNumber(index, 'output_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="numberText(row.cache_read_per_mtok)" placeholder="同输入价" @change="patchNumber(index, 'cache_read_per_mtok', $event)" /></td>
              <td><input type="number" min="0" step="any" :value="numberText(row.cache_write_per_mtok)" placeholder="同输入价" @change="patchNumber(index, 'cache_write_per_mtok', $event)" /></td>
              <td>
                <div class="row-actions">
                  <select
                    v-if="group.known"
                    class="copy-select"
                    :disabled="!copyTargets(row).length"
                    :title="copyTargets(row).length ? '把这行单价复制到配置了同名模型且尚未定价的渠道' : '没有其他渠道配置了该模型且未定价'"
                    value=""
                    @change="copyTo(row, $event)"
                  >
                    <option value="">复制到…</option>
                    <option v-for="target in copyTargets(row)" :key="target" :value="target">{{ target }}</option>
                  </select>
                  <button type="button" class="row-remove" title="删除该价格" @click="remove(index)"><UiIcon name="X" :size="14" /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiTag from '../ui/UiTag.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { fieldTemplate, isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const rows = computed<JsonObject[]>(() => Array.isArray(store.document.value?.pricing) ? store.document.value.pricing.filter(isObject) : [])
const providers = computed<JsonObject[]>(() => Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : [])
const providerFilter = ref('')

/** 每个渠道配置的模型 ID（计费键的唯一合法取值） */
const configured = computed(() => new Map(providers.value.map(provider => [
  String(provider.id ?? ''),
  (Array.isArray(provider.models) ? provider.models.filter(isObject) : []).map(model => String(model.model ?? '')).filter(Boolean),
])))

function keyOf(row: JsonObject) { return `${String(row.provider_id ?? '')}::${String(row.model ?? '')}` }
const priced = computed(() => new Set(rows.value.map(keyOf)))
const dupes = computed(() => {
  const seen = new Map<string, number>()
  for (const row of rows.value) seen.set(keyOf(row), (seen.get(keyOf(row)) ?? 0) + 1)
  return new Set([...seen].filter(([, count]) => count > 1).map(([key]) => key))
})
function isDupe(row: JsonObject) { return dupes.value.has(keyOf(row)) }
function isOrphan(row: JsonObject) {
  const models = configured.value.get(String(row.provider_id ?? ''))
  return !!row.model && !models?.includes(String(row.model))
}
function isNumber(value: JsonValue | undefined) { return typeof value === 'number' && Number.isFinite(value) }

interface Group {
  id: string; known: boolean; disabled: boolean; models: string[]; unpriced: string[]; priced: number
  rows: { row: JsonObject; index: number }[]
}
/** 展示按渠道分组；行仍按文档原序存放，index 指回 pricing 数组 */
const groups = computed<Group[]>(() => {
  const byProvider = new Map<string, Group>()
  for (const provider of providers.value) {
    const id = String(provider.id ?? '')
    if (!id) continue
    const models = configured.value.get(id) ?? []
    // 未定价提示只看启用的模型；停用模型仍可在下拉中选择定价
    const enabled = (Array.isArray(provider.models) ? provider.models.filter(isObject) : []).filter(model => model.enabled !== false).map(model => String(model.model ?? ''))
    const unpriced = models.filter(model => enabled.includes(model) && !priced.value.has(`${id}::${model}`))
    byProvider.set(id, { id, known: true, disabled: provider.enabled === false, models, unpriced, priced: models.filter(model => priced.value.has(`${id}::${model}`)).length, rows: [] })
  }
  rows.value.forEach((row, index) => {
    const id = String(row.provider_id ?? '')
    if (!byProvider.has(id)) byProvider.set(id, { id: id || '（未指定渠道）', known: false, disabled: false, models: [], unpriced: [], priced: 0, rows: [] })
    byProvider.get(id)!.rows.push({ row, index })
  })
  return [...byProvider.values()]
})
const visibleGroups = computed(() => providerFilter.value ? groups.value.filter(group => group.id === providerFilter.value) : groups.value)
const missing = computed(() => groups.value.filter(group => !group.disabled).flatMap(group => group.unpriced.map(model => ({ provider: group.id, model }))))
const visibleMissing = computed(() => providerFilter.value ? missing.value.filter(item => item.provider === providerFilter.value) : missing.value)
const incomplete = computed(() => rows.value.filter(row => !isNumber(row.input_per_mtok) || !isNumber(row.output_per_mtok)))
const orphans = computed(() => rows.value.filter(isOrphan))

/** 模型下拉：本行当前值 + 本渠道尚未定价的模型 */
function modelOptions(group: Group, row: JsonObject) {
  const current = String(row.model ?? '')
  return group.models.filter(model => model === current || !priced.value.has(`${group.id}::${model}`))
}
function copyTargets(row: JsonObject) {
  const model = String(row.model ?? '')
  if (!model) return []
  return [...configured.value].filter(([id, models]) => id !== row.provider_id && models.includes(model) && !priced.value.has(`${id}::${model}`)).map(([id]) => id)
}

function commit(next: JsonObject[]) { store.updateSection('pricing', next) }
function patch(index: number, fields: JsonObject) { commit(rows.value.map((row, i) => i === index ? { ...row, ...fields } : row)) }
function remove(index: number) { commit(rows.value.filter((_, i) => i !== index)) }
/** 新行单价留空：0 是「免费」，不能当默认值；未填写时后端拒绝保存 */
function addMissing(items: { provider: string; model: string }[]) {
  const template = fieldTemplate('pricing') as JsonObject
  commit([...rows.value, ...items.map(item => ({ ...structuredClone(template), provider_id: item.provider, model: item.model, input_per_mtok: null, output_per_mtok: null }))])
}
function copyTo(row: JsonObject, event: Event) {
  const select = event.target as HTMLSelectElement
  const target = select.value
  select.value = ''
  if (target) commit([...rows.value, { ...row, provider_id: target }])
}

function numberText(value: JsonValue | undefined) { return isNumber(value) ? String(value) : '' }
/** change（失焦/回车）时提交：输入过程中不回写，避免小数点与退格被规范化吞掉。
 * 清空即 null：缓存价表示「同输入价」，输入/输出价表示待填写（保存时被拒绝） */
function patchNumber(index: number, key: string, event: Event) {
  const input = event.target as HTMLInputElement
  const text = input.value.trim()
  if (text === '') { patch(index, { [key]: null }); return }
  const value = Number(text)
  if (Number.isFinite(value) && value >= 0) patch(index, { [key]: value })
  else input.value = numberText(rows.value[index]?.[key])
}
</script>

<style scoped>
.pricing-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.pricing-summary__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}

.pricing-summary__stats strong {
  color: var(--qq-text);
  font-variant-numeric: tabular-nums;
}

.pricing-summary__stats .warn,
.pricing-summary__stats .warn strong { color: var(--qq-warn); }
.pricing-summary__stats .danger,
.pricing-summary__stats .danger strong { color: var(--qq-danger); }

.pricing-summary__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: var(--qq-gap-sm);
}

.pricing-summary__hint {
  margin: var(--qq-gap-sm) 0 0;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  line-height: 1.7;
}

select {
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.pricing-group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: var(--qq-gap-sm);
}

.pricing-group__title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.pricing-group__title h3 {
  margin: 0;
  font-size: var(--qq-text-md);
}

.muted {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.unpriced {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--qq-gap-sm);
  font-size: var(--qq-text-xs);
}

.unpriced__label { color: var(--qq-warn); }

.unpriced__chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border: 1px dashed var(--qq-warn);
  border-radius: var(--qq-radius-full);
  background: var(--qq-warn-soft);
  color: var(--qq-text);
  font-size: var(--qq-text-xs);
  cursor: pointer;
}

.unpriced__chip:hover { border-style: solid; }

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

.pricing-table input {
  width: 110px;
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.pricing-table input.invalid { border-color: var(--qq-warn); }

.model-cell select {
  width: 100%;
  min-width: 180px;
  font-family: var(--qq-font-mono);
}

.row--dupe td { background: var(--qq-danger-soft); }
.row--orphan td { background: var(--qq-warn-soft); }

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.copy-select {
  width: 96px;
  font-size: var(--qq-text-xs);
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

.mono { font-family: var(--qq-font-mono); }
</style>
