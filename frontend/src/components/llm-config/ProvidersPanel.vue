<template>
  <div class="providers-panel">
    <nav class="providers-panel__list">
      <div class="providers-panel__list-head">
        <span>渠道</span>
        <UiButton size="sm" icon="Plus" @click="addProvider">添加渠道</UiButton>
      </div>
      <UiEmpty v-if="!providers.length" icon="Server" title="还没有渠道" description="添加第一个 LLM 渠道，填写 API 地址和密钥变量名" />
      <button
        v-for="(provider, index) in providers"
        :key="index"
        class="provider-item qq-selectable"
        :class="{ active: index === selected }"
        @click="selected = index"
      >
        <span class="provider-item__head">
          <span class="provider-item__id">{{ provider.id || '未命名渠道' }}</span>
          <UiTag v-if="provider.enabled === false" size="sm">已停用</UiTag>
          <UiTag v-if="isDefault(provider)" size="sm" variant="cyan">默认</UiTag>
        </span>
        <span class="provider-item__meta">
          <span>{{ protocolLabel(provider.protocol) }}</span>
          <span>{{ modelCount(provider) }} 个模型</span>
          <span v-if="envState(provider) === 'missing'" class="provider-item__warn">密钥未配置</span>
        </span>
      </button>
    </nav>

    <div v-if="current" class="providers-panel__detail">
      <UiCard padding="lg" class="detail-card">
        <header class="detail-card__head">
          <h3>基本设置</h3>
          <UiToggle :model-value="current.enabled !== false" @update:model-value="patch({ enabled: $event })" />
        </header>
        <div class="form-grid">
          <SettingField label="渠道 ID" :model-value="String(current.id ?? '')" :hint="L.id.hint" placeholder="my-provider" @update:model-value="onIdInput" />
          <SettingField label="协议" :model-value="String(current.protocol ?? 'openai')" :options="protocolOptions" @update:model-value="patch({ protocol: String($event) })" />
          <SettingField class="form-grid__wide" label="API 地址" :model-value="String(current.base_url ?? '')" :hint="L.base_url.hint" :placeholder="L.base_url.placeholder" @update:model-value="patch({ base_url: String($event) })" />
          <div class="form-grid__wide api-key-row">
            <SettingField label="密钥环境变量" :model-value="String(current.api_key_env ?? '')" :hint="L.api_key_env.hint" :placeholder="L.api_key_env.placeholder" @update:model-value="patch({ api_key_env: String($event) })" />
            <span v-if="keyEnvState" class="env-badge" :class="`env-badge--${keyEnvState.kind}`">{{ keyEnvState.text }}</span>
          </div>
          <SettingField label="认证方式" :model-value="String(current.auth_method ?? 'api_key')" :options="authOptions" @update:model-value="patch({ auth_method: String($event) })" />
          <SettingField label="默认模型" :model-value="String(current.default_model ?? '')" :options="defaultModelOptions" :hint="L.default_model.hint" @update:model-value="patch({ default_model: String($event) })" />
          <SettingField class="form-grid__wide" label="代理" :model-value="String(current.proxy ?? '')" :placeholder="L.proxy.placeholder" @update:model-value="patch({ proxy: String($event) })" />
          <div class="form-grid__wide">
            <p class="sub-label">备用地址 <UiInfoTip :text="L.fallback_urls.hint" /></p>
            <StringListEditor :model-value="stringList(current.fallback_urls)" @update:model-value="patch({ fallback_urls: $event })" />
          </div>
          <div class="form-grid__wide">
            <p class="sub-label">附加请求头 <UiInfoTip :text="L.headers.hint" /></p>
            <KeyValueEditor :model-value="objectValue(current.headers)" value-placeholder="值（密钥用 ${变量名} 引用）" @update:model-value="patch({ headers: $event })" />
          </div>
        </div>
      </UiCard>

      <UiCard padding="lg" class="detail-card">
        <header class="detail-card__head">
          <h3>模型 <span class="head-count">{{ models.length }}</span></h3>
          <UiButton size="sm" icon="Plus" @click="addModel">添加模型</UiButton>
        </header>
        <UiEmpty v-if="!models.length" icon="Boxes" title="尚未配置模型" description="渠道至少需要一个模型才能使用" />
        <div v-for="(model, index) in models" :key="index" class="model-row">
          <div class="model-row__main">
            <UiToggle size="sm" :model-value="model.enabled !== false" @update:model-value="patchModel(index, { enabled: $event })" />
            <input
              class="model-row__name"
              :value="String(model.model ?? '')"
              placeholder="模型名（API 请求中的名称）"
              autocomplete="off"
              spellcheck="false"
              @input="patchModel(index, { model: ($event.target as HTMLInputElement).value })"
            />
            <label class="model-row__flag" title="关闭后不再向该模型发送图片">
              <input type="checkbox" :checked="model.vision !== false" @change="patchModel(index, { vision: ($event.target as HTMLInputElement).checked })" />
              图片
            </label>
            <input
              class="model-row__context"
              type="number"
              min="1024"
              step="1"
              :value="model.context_window ?? ''"
              placeholder="上下文容量（留空自动）"
              title="上下文容量（token），留空自动识别"
              @input="onContextInput(index, $event)"
            />
            <button type="button" class="model-row__remove" title="移除该模型" @click="removeModel(index)"><UiIcon name="X" :size="14" /></button>
          </div>
          <details class="model-row__params">
            <summary>参数覆盖 <span v-if="overrideCount(model)" class="override-count">{{ overrideCount(model) }} 项</span></summary>
            <ParamsEditor :model-value="objectValue(model.parameters)" :metadata="parametersMeta" :style-profiles="styleProfileNames" @update:model-value="patchModel(index, { parameters: $event })" />
          </details>
        </div>
      </UiCard>

      <UiCard padding="lg" class="detail-card">
        <header class="detail-card__head">
          <h3>别名 <UiInfoTip text="给模型起短名，配置路由时用别名引用。别名在本渠道内唯一。" /></h3>
          <UiButton size="sm" icon="Plus" :disabled="!models.length" @click="addAlias">添加别名</UiButton>
        </header>
        <p v-if="!aliases.length" class="muted">暂无别名。</p>
        <div v-for="(alias, index) in aliases" :key="index" class="alias-row">
          <input :value="String(alias.alias ?? '')" placeholder="别名" autocomplete="off" spellcheck="false" @input="patchAlias(index, { alias: ($event.target as HTMLInputElement).value })" />
          <UiIcon name="ArrowRight" :size="14" class="alias-row__arrow" />
          <select :value="String(alias.model ?? '')" @change="patchAlias(index, { model: ($event.target as HTMLSelectElement).value })">
            <option value="" disabled>选择模型</option>
            <option v-for="name in modelNames" :key="name" :value="name">{{ name }}</option>
          </select>
          <button type="button" class="model-row__remove" title="移除别名" @click="removeAlias(index)"><UiIcon name="X" :size="14" /></button>
        </div>
      </UiCard>

      <UiCard padding="lg" class="detail-card">
        <header class="detail-card__head">
          <h3>渠道参数覆盖 <UiInfoTip text="覆盖全局默认的请求参数；模型级覆盖优先于渠道级。" /></h3>
        </header>
        <ParamsEditor :model-value="objectValue(current.parameters)" :metadata="parametersMeta" :style-profiles="styleProfileNames" @update:model-value="patch({ parameters: $event })" />
      </UiCard>

      <UiCard padding="lg" class="detail-card">
        <header class="detail-card__head">
          <h3>生效参数与探测</h3>
        </header>
        <div class="effective-bar">
          <select v-model="effectiveModel">
            <option value="" disabled>选择模型</option>
            <option v-for="name in modelNames" :key="name" :value="name">{{ name }}</option>
          </select>
          <UiButton size="sm" :disabled="!effectiveModel || store.dirty.value" :title="store.dirty.value ? '先保存草稿再查看' : ''" @click="loadEffective">查看生效参数</UiButton>
        </div>
        <p v-if="store.dirty.value" class="muted">有未保存修改，生效参数基于已保存草稿。</p>
        <table v-if="effective" class="effective-table">
          <thead><tr><th>参数</th><th>生效值</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="(parameter, key) in effective.parameters" :key="key">
              <td>{{ paramLabel(String(key)) }}</td>
              <td class="mono">{{ formatValue(parameter.value) }}</td>
              <td><UiTag size="sm" :variant="parameter.source === 'unknown' ? 'warn' : 'info'">{{ PARAM_SOURCE_LABELS[parameter.source] || parameter.source }}</UiTag></td>
            </tr>
          </tbody>
        </table>
        <div class="probe-bar">
          <p class="muted">探测会让 Bot 用该配置发起一次真实请求，<strong>可能产生费用</strong>，且不会自动重试。</p>
          <div class="probe-bar__controls">
            <select v-model="probeSource">
              <option value="published">按已发布配置</option>
              <option value="draft">按已保存草稿</option>
            </select>
            <UiButton size="sm" variant="danger" icon="Zap" :disabled="!effectiveModel || store.dirty.value || store.busy.value" @click="probe">探测该模型</UiButton>
          </div>
        </div>
      </UiCard>

      <UiCard padding="lg" class="detail-card detail-card--danger">
        <header class="detail-card__head">
          <h3>危险操作</h3>
        </header>
        <div class="danger-row">
          <p class="muted">删除后保存时会检查引用依赖；仍被路由、默认渠道或功能引用时不允许删除。</p>
          <UiButton size="sm" variant="danger" icon="Trash2" @click="removeProvider">删除渠道</UiButton>
        </div>
      </UiCard>
    </div>
    <div v-else class="providers-panel__placeholder">
      <UiEmpty icon="Server" title="从左侧选择渠道查看与编辑" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiTag from '../ui/UiTag.vue'
import UiToggle from '../ui/UiToggle.vue'
import SettingField from './SettingField.vue'
import StringListEditor from './StringListEditor.vue'
import KeyValueEditor from './KeyValueEditor.vue'
import ParamsEditor from './ParamsEditor.vue'
import * as api from '../../api/llmConfiguration'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { toast } from '../../toast'
import { PARAM_LABELS, PARAM_SOURCE_LABELS, PROTOCOL_LABELS, fieldTemplate, isObject, providerEnvVars, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()
const L = { id: { hint: '全局唯一，创建后不可修改。只允许字母、数字、_ . -' }, base_url: { hint: '禁止在 URL 里直接写账号密码。', placeholder: 'https://api.example.com/v1' }, api_key_env: { hint: '只填写根目录 .env 里的变量名，不是密钥本身。', placeholder: 'EXAMPLE_API_KEY' }, default_model: { hint: '未指定模型时的兜底选择，必须在模型列表中。' }, proxy: { placeholder: 'http://127.0.0.1:7890' }, fallback_urls: { hint: '主地址失败时依次尝试。' }, headers: { hint: '涉及密钥的值必须写成 ${变量名} 引用。' } }

const providers = computed<JsonObject[]>(() => Array.isArray(store.document.value?.providers) ? store.document.value.providers.filter(isObject) : [])
const selected = ref(0)
const current = computed(() => providers.value[selected.value] || null)
/** 新建渠道的 id 允许编辑，直到保存后视为既有渠道 */
const freshIds = ref<Set<number>>(new Set())

const models = computed<JsonObject[]>(() => current.value && Array.isArray(current.value.models) ? current.value.models.filter(isObject) : [])
const aliases = computed<JsonObject[]>(() => current.value && Array.isArray(current.value.aliases) ? current.value.aliases.filter(isObject) : [])
const modelNames = computed(() => models.value.map(model => String(model.model ?? '')).filter(Boolean))
const parametersMeta = computed(() => store.metadata.value.parameters || {})
const styleProfileNames = computed(() => isObject(store.document.value?.style_profiles) ? Object.keys(store.document.value.style_profiles) : [])
const protocolOptions = computed(() => (store.metadata.value.protocols?.length ? store.metadata.value.protocols : Object.keys(PROTOCOL_LABELS)).map(value => ({ value, label: PROTOCOL_LABELS[value] || value })))
const authOptions = [{ value: 'api_key', label: 'API Key（x-api-key）' }, { value: 'bearer', label: 'Bearer Token' }]
const defaultModelOptions = computed(() => [{ value: '', label: models.value.length ? '（未选择）' : '（先添加模型）' }, ...modelNames.value.map(name => ({ value: name, label: name }))])

watch(providers, list => { if (selected.value > Math.max(0, list.length - 1)) selected.value = Math.max(0, list.length - 1) })

function protocolLabel(value: JsonValue) { return PROTOCOL_LABELS[String(value)] || String(value ?? '—') }
function modelCount(provider: JsonObject) { return Array.isArray(provider.models) ? provider.models.length : 0 }
function isDefault(provider: JsonObject) { const settings = store.document.value?.settings; return isObject(settings) && isObject(settings.runtime) && settings.runtime.default_provider === provider.id }
function stringList(value: JsonValue | undefined): string[] { return Array.isArray(value) ? value.map(String) : [] }
function objectValue(value: JsonValue | undefined): JsonObject { return isObject(value) ? value : {} }
function overrideCount(model: JsonObject) { return Object.values(objectValue(model.parameters)).filter(value => value !== null && value !== undefined).length }

/** 环境变量配置状态（来自 Bot 心跳上报）：任一明确缺失才算 missing；未检查的变量不算缺失 */
function envState(provider: JsonObject): 'ok' | 'missing' | 'unknown' {
  const env = store.environment.value
  if (!env || !env.available) return 'unknown'
  const vars = providerEnvVars(provider)
  if (!vars.length) return 'unknown'
  const states = vars.map(name => env.variables.find(item => item.name === name)?.configured)
  if (states.some(state => state === false)) return 'missing'
  if (states.every(state => state === true)) return 'ok'
  return 'unknown'
}
const keyEnvState = computed(() => {
  if (!current.value?.api_key_env) return null
  const state = envState(current.value)
  if (state === 'ok') return { kind: 'ok', text: '密钥已配置' }
  if (state === 'missing') return { kind: 'missing', text: 'Bot 环境中未找到该变量' }
  return null
})

function commit(next: JsonObject[]) { store.updateSection('providers', next) }
function patch(fields: JsonObject) { if (current.value) commit(providers.value.map((provider, i) => i === selected.value ? { ...provider, ...fields } : provider)) }
function onIdInput(event: JsonValue) {
  if (!current.value) return
  const id = String(event)
  if (!freshIds.value.has(selected.value) && current.value.id && current.value.id !== id) {
    toast('既有渠道的 ID 不可修改', 'error')
    return
  }
  patch({ id })
}
function addProvider() {
  const provider = structuredClone(fieldTemplate('providers'))
  commit([...providers.value, provider])
  selected.value = providers.value.length - 1
  freshIds.value = new Set([...freshIds.value, selected.value])
}
function removeProvider() {
  if (!current.value) return
  if (!confirm(`确定删除渠道「${current.value.id || '未命名渠道'}」？保存时将检查引用依赖。`)) return
  commit(providers.value.filter((_, i) => i !== selected.value))
  selected.value = Math.max(0, selected.value - 1)
}
function patchModel(index: number, fields: JsonObject) {
  if (!current.value) return
  const next = models.value.map((model, i) => i === index ? { ...model, ...fields } : model)
  patch({ models: next })
}
function addModel() { patch({ models: [...models.value, structuredClone(fieldTemplate('models'))] }) }
function removeModel(index: number) { patch({ models: models.value.filter((_, i) => i !== index) }) }
function onContextInput(index: number, event: Event) {
  const text = (event.target as HTMLInputElement).value
  if (text === '') { patchModel(index, { context_window: null }); return }
  const value = Number(text)
  if (Number.isFinite(value)) patchModel(index, { context_window: value })
}
function patchAlias(index: number, fields: JsonObject) {
  const next = aliases.value.map((alias, i) => i === index ? { ...alias, ...fields } : alias)
  patch({ aliases: next })
}
function addAlias() { patch({ aliases: [...aliases.value, structuredClone(fieldTemplate('aliases'))] }) }
function removeAlias(index: number) { patch({ aliases: aliases.value.filter((_, i) => i !== index) }) }

const effectiveModel = ref('')
const effective = ref<Awaited<ReturnType<typeof api.fetchLlmEffectiveParameters>> | null>(null)
const probeSource = ref('published')
watch(current, () => { effective.value = null; effectiveModel.value = '' })
async function loadEffective() {
  if (!current.value?.id || !effectiveModel.value) return
  try { effective.value = await api.fetchLlmEffectiveParameters(String(current.value.id), effectiveModel.value) }
  catch (error: unknown) { toast((error as Error).message, 'error') }
}
function paramLabel(key: string) { return PARAM_LABELS[key]?.label || key }
function formatValue(value: JsonValue) { return typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—') }
async function probe() {
  if (!current.value?.id || !effectiveModel.value) return
  if (!confirm('探测会通过 Bot 发起一次真实请求，可能产生费用。是否继续？')) return
  const submitted = await store.probe(probeSource.value, String(current.value.id), effectiveModel.value)
  if (submitted) toast('探测任务已提交，到「发布与历史」查看结果')
}

onMounted(() => { if (!store.environment.value) void store.loadEnvironment() })
</script>

<style scoped>
.providers-panel {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: var(--qq-gap-md);
  align-items: start;
}

.providers-panel__list {
  display: grid;
  gap: 4px;
  position: sticky;
  top: 10px;
}

.providers-panel__list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 8px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  font-weight: 600;
}

.provider-item {
  display: grid;
  gap: 3px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.provider-item__head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.provider-item__id {
  font-weight: 600;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
  overflow-wrap: anywhere;
}

.provider-item__meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.provider-item__warn {
  color: var(--qq-warn);
}

.providers-panel__detail {
  display: grid;
  gap: var(--qq-gap-md);
  min-width: 0;
}

.providers-panel__placeholder {
  display: grid;
  place-items: center;
  min-height: 320px;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
}

.detail-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
}

.detail-card__head h3 {
  margin: 0;
  font-size: var(--qq-text-md);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.head-count {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-sm);
  font-weight: 500;
}

.detail-card--danger {
  border-color: var(--qq-danger-border);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--qq-gap-md);
}

.form-grid__wide {
  grid-column: 1 / -1;
}

.sub-label {
  margin: 0 0 6px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}

.api-key-row {
  display: grid;
  gap: 6px;
}

.env-badge {
  font-size: var(--qq-text-xs);
}

.env-badge--ok { color: var(--qq-success); }
.env-badge--missing { color: var(--qq-danger); }

.muted {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.model-row {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  padding: 10px 12px;
  display: grid;
  gap: 8px;
  margin-bottom: 8px;
}

.model-row__main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.model-row__name {
  flex: 1;
  min-width: 180px;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
}

.model-row__flag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  white-space: nowrap;
}

.model-row__context {
  width: 150px;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.model-row__remove {
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

.model-row__remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

.model-row__params summary {
  cursor: pointer;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.model-row__params[open] summary {
  margin-bottom: 8px;
}

.override-count {
  color: var(--qq-cyan-deep);
  font-size: var(--qq-text-xs);
}

.alias-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.alias-row input,
.alias-row select {
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.alias-row input { width: 180px; font-family: var(--qq-font-mono); }
.alias-row select { flex: 1; }
.alias-row__arrow { color: var(--qq-text-quiet); flex-shrink: 0; }

.effective-bar,
.probe-bar__controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.effective-bar select,
.probe-bar__controls select {
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.effective-table {
  width: 100%;
  margin-top: 10px;
  border-collapse: collapse;
  font-size: var(--qq-text-sm);
}

.effective-table th,
.effective-table td {
  border-bottom: 1px solid var(--qq-border);
  padding: 7px 8px;
  text-align: left;
  overflow-wrap: anywhere;
}

.effective-table th {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
}

.mono { font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); }

.probe-bar {
  margin-top: var(--qq-gap-md);
  padding-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
  display: grid;
  gap: 8px;
}

.danger-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.danger-row .muted { flex: 1; min-width: 220px; }

@media (max-width: 900px) {
  .providers-panel { grid-template-columns: 1fr; }
  .providers-panel__list { position: static; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
