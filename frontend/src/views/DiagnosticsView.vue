<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 样本请求与文本规则回归测试" />

    <div class="diag-stack">
      <UiCard padding="md" shadow="sm" class="diag-card">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="Wrench" :size="18" /></span>
          <div>
            <h3>运行时操作</h3>
            <p>重载配置、人格、聊天规则和 MCP，并执行一次轻量健康检查。</p>
          </div>
        </div>

        <div class="runtime-actions">
          <UiButton icon="Activity" :loading="healthLoading" @click="loadHealth(false)">健康检查</UiButton>
          <UiButton icon="ListTree" :loading="healthLoadingVerbose" @click="loadHealth(true)">详细健康</UiButton>
          <UiButton icon="Zap" :loading="probeLoading" @click="runProbe">探活 Provider</UiButton>
          <UiButton icon="RefreshCw" :loading="runtimeLoading === 'llm'" @click="runRuntimeAction('llm')">重载 LLM</UiButton>
          <UiButton icon="Network" :loading="runtimeLoading === 'mcp'" @click="runRuntimeAction('mcp')">重载 MCP</UiButton>
          <UiButton icon="Drama" :loading="runtimeLoading === 'personas'" @click="runRuntimeAction('personas')">重载人格</UiButton>
          <UiButton icon="ToggleLeft" :loading="runtimeLoading === 'rules'" @click="runRuntimeAction('rules')">重载规则</UiButton>
        </div>

        <div class="context-tools">
          <label class="inline-field">
            <span>Scope</span>
            <input v-model="contextScope" placeholder="群号或 private:USER_ID" />
          </label>
          <UiButton icon="Eraser" variant="danger" :disabled="!contextScope" :loading="runtimeLoading === 'clear'" @click="clearContext">清空上下文</UiButton>
          <label class="inline-field">
            <span>Message ID</span>
            <input v-model="contextMessageId" placeholder="OneBot message_id" />
          </label>
          <UiButton icon="Trash2" variant="danger" :disabled="!contextScope || !contextMessageId" :loading="runtimeLoading === 'delete-msg'" @click="deleteContextMessage">删除消息</UiButton>
        </div>

        <div v-if="runtimeError" class="error-block">{{ runtimeError }}</div>
        <pre v-if="healthText" class="health-block">{{ healthText }}</pre>
        <pre v-if="probeText" class="health-block">{{ probeText }}</pre>

        <div class="action-panel">
          <div class="action-panel__head">
            <h4>最近动作</h4>
            <UiButton size="sm" icon="RefreshCw" :loading="actionsLoading" @click="loadActions">刷新</UiButton>
          </div>
          <UiEmpty v-if="!actions.length" icon="Activity" title="暂无动作记录" />
          <div v-else class="action-list">
            <div v-for="item in actions" :key="item.id" class="action-item">
              <div class="action-main">
                <span class="mono">{{ actionLabel(item.action_type) }}</span>
                <UiTag size="sm" :variant="actionVariant(item.status)">{{ statusLabel(item.status) }}</UiTag>
                <span class="action-time">{{ formatActionTime(item.updated_at || item.created_at) }}</span>
              </div>
              <div v-if="item.error" class="action-error">{{ item.error }}</div>
              <pre v-else-if="item.result?.text" class="action-result">{{ item.result.text }}</pre>
              <pre v-else-if="item.result" class="action-result">{{ prettyJson(item.result) }}</pre>
            </div>
          </div>
        </div>
      </UiCard>

      <UiCard padding="md" shadow="sm" class="diag-card">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="Send" :size="18" /></span>
          <div>
            <h3>样本请求</h3>
            <p>按 provider / model 发送一次请求，查看解析结果和该次调用的原始 trace。</p>
          </div>
        </div>

        <div class="sample-form">
          <div class="form-row">
            <div class="field">
              <label>Provider</label>
              <select v-model="sample.provider_id" @change="onProviderChange">
                <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.id }}</option>
              </select>
            </div>
            <div class="field">
              <label>Model</label>
              <select v-model="sample.model">
                <option value="">(default)</option>
                <option v-for="m in currentModels" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
            <div class="field field--small">
              <label>Max Tokens</label>
              <input v-model.number="sample.max_output_tokens" type="number" min="1" max="4096" />
            </div>
          </div>

          <div class="form-row">
            <div class="field grow">
              <label>System Prompt</label>
              <textarea v-model="sample.system_prompt" rows="3" />
            </div>
          </div>

          <div class="form-row">
            <div class="field grow">
              <label>User Prompt</label>
              <textarea v-model="sample.user_prompt" rows="3" />
            </div>
          </div>

          <div class="form-actions">
            <UiButton icon="Send" :loading="sampleLoading" @click="sendSample">发送请求</UiButton>
            <span v-if="sampleResult" class="duration">耗时 {{ sampleResult.duration_ms }}ms</span>
          </div>
        </div>

        <div v-if="sampleError" class="error-block">{{ sampleError }}</div>

        <div v-if="sampleResult" class="sample-result">
          <div class="result-meta">
            <UiTag size="sm" variant="info">{{ sampleResult.model }}</UiTag>
            <UiTag size="sm" :variant="sampleResult.finish_reason === 'stop' ? 'success' : 'warn'">
              {{ sampleResult.finish_reason || 'N/A' }}
            </UiTag>
            <span v-if="sampleResult.input_tokens != null" class="token-info">
              in {{ sampleResult.input_tokens }} / out {{ sampleResult.output_tokens }}
            </span>
          </div>
          <div class="result-text">{{ sampleResult.text }}</div>

          <details v-if="sampleResult.thinking_blocks?.length" class="data-detail">
            <summary>Thought Blocks ({{ sampleResult.thinking_blocks.length }})</summary>
            <pre class="json-block">{{ prettyJson(sampleResult.thinking_blocks) }}</pre>
          </details>

          <details v-if="sampleResult.raw_traces?.length" class="data-detail">
            <summary>Raw Traces ({{ sampleResult.raw_traces.length }})</summary>
            <div v-for="(t, i) in sampleResult.raw_traces" :key="i" class="trace-item">
              <div class="trace-head">
                <UiTag size="sm" :variant="t.direction === 'request' ? 'warn' : 'success'">
                  {{ t.direction.toUpperCase() }}
                </UiTag>
                <span class="trace-meta">{{ t.timestamp }}</span>
              </div>
              <pre class="json-block">{{ t.payload }}</pre>
            </div>
          </details>
        </div>
      </UiCard>

      <UiCard padding="md" shadow="sm" class="diag-card">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="ListChecks" :size="18" /></span>
          <div>
            <h3>文本规则回归</h3>
            <p>每行一条样本，快速确认哪些规则命中。</p>
          </div>
        </div>

        <div class="form-row">
          <div class="field grow">
            <label>测试样本（`标签 | 文本`）</label>
            <textarea
              v-model="regressionInput"
              rows="8"
              placeholder="标签1 | 你好世界&#10;标签2 | 今天天气真好"
            />
          </div>
        </div>

        <div class="form-actions">
          <UiButton icon="Play" :loading="regressionLoading" @click="runRegress">运行</UiButton>
        </div>

        <div v-if="regressionError" class="error-block">{{ regressionError }}</div>

        <div v-if="regressionResults.length" class="regression-results">
          <div v-for="(r, i) in regressionResults" :key="i" class="regression-item" :class="{ matched: r.matched }">
            <div class="regression-head">
              <span class="regression-label">{{ r.label || `#${i + 1}` }}</span>
              <span class="regression-text">{{ r.text }}</span>
              <UiTag size="sm" :variant="r.matched ? 'success' : 'info'">{{ r.matched ? '命中' : '未命中' }}</UiTag>
            </div>
            <div v-if="r.rules.length" class="regression-rules">
              <div v-for="(rule, j) in r.rules" :key="j" class="regression-rule">
                <span class="rule-name">{{ rule.name }}</span>
                <span class="rule-patterns">{{ rule.patterns.join(' | ') }}</span>
                <span class="rule-prio">P{{ rule.priority }}</span>
              </div>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiTag from '../components/ui/UiTag.vue'
import { fetchProviders, probeProviders, runRegression, runSampleRequest } from '../api/diagnostics'
import { clearLlmContext, deleteLlmContextMessage, fetchLlmHealth, fetchLlmRuntimeActions, reloadLlmRuntime, reloadMcpRuntime, reloadPersonas, reloadRules } from '../api/llmRuntime'
import { toast } from '../toast'

const providers = ref<any[]>([])
const sampleLoading = ref(false)
const sampleError = ref<string | null>(null)
const sampleResult = ref<any>(null)
const regressionLoading = ref(false)
const regressionError = ref<string | null>(null)
const regressionResults = ref<any[]>([])
const regressionInput = ref('')
const healthLoading = ref(false)
const healthLoadingVerbose = ref(false)
const healthText = ref('')
const probeLoading = ref(false)
const probeText = ref('')
const runtimeError = ref<string | null>(null)
const runtimeLoading = ref('')
const contextScope = ref('')
const contextMessageId = ref('')
const actionsLoading = ref(false)
const actions = ref<any[]>([])

interface SampleRequest {
  provider_id: string
  model: string
  system_prompt: string
  user_prompt: string
  max_output_tokens: number
}

const sample = ref<SampleRequest>({
  provider_id: '',
  model: '',
  system_prompt: '你是一个测试助手。',
  user_prompt: '你好，请做一下自我介绍。',
  max_output_tokens: 256,
})

const currentModels = computed(() => {
  const provider = providers.value.find(p => p.id === sample.value.provider_id)
  return provider ? provider.models : []
})

function onProviderChange() {
  sample.value.model = ''
}

function prettyJson(obj: any): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function actionLabel(actionType: string): string {
  return ({
    llm_reload: '重载 LLM',
    mcp_reload: '重载 MCP',
    personas_reload: '重载人格',
    rules_reload: '重载规则',
    awakening_reload: '重载唤醒',
    clear_context: '清空上下文',
    delete_context_message: '删除上下文消息',
    health_check: '健康检查',
    summary_now: '立即总结',
    briefing_now: '立即播报',
  } as Record<string, string>)[actionType] || actionType
}

function statusLabel(status: string): string {
  return ({
    queued: '等待',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
  } as Record<string, string>)[status] || status
}

function actionVariant(status: string): string {
  return ({
    queued: 'info',
    running: 'warn',
    succeeded: 'success',
    failed: 'danger',
  } as Record<string, string>)[status] || 'info'
}

function formatActionTime(raw: string): string {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function loadActions() {
  actionsLoading.value = true
  try {
    const data = await fetchLlmRuntimeActions(20)
    actions.value = data.actions || []
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    actionsLoading.value = false
  }
}

async function loadProviders() {
  try {
    const data = await fetchProviders()
    if (data?.providers) {
      providers.value = data.providers
      if (!sample.value.provider_id && providers.value.length) {
        sample.value.provider_id = providers.value[0].id
      }
    }
  } catch {
    providers.value = []
  }
}

async function loadHealth(verbose: boolean) {
  if (verbose) healthLoadingVerbose.value = true
  else healthLoading.value = true
  runtimeError.value = null
  try {
    const data = await fetchLlmHealth(verbose)
    if (data?.queued) {
      healthText.value = '健康检查已入队，请稍后查看最近动作。'
      await loadActions()
      toast('健康检查已入队')
    } else {
      healthText.value = data.text || ''
    }
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    healthLoading.value = false
    healthLoadingVerbose.value = false
  }
}

async function runProbe() {
  probeLoading.value = true
  runtimeError.value = null
  try {
    const data = await probeProviders()
    probeText.value = data?.text || '没有已配置的 provider。'
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    probeLoading.value = false
  }
}

async function runRuntimeAction(action: string) {
  runtimeLoading.value = action
  runtimeError.value = null
  try {
    let data: any
    if (action === 'llm') data = await reloadLlmRuntime()
    else if (action === 'mcp') data = await reloadMcpRuntime()
    else if (action === 'personas') data = await reloadPersonas()
    else data = await reloadRules()
    if (data?.load_error || data?.error) {
      runtimeError.value = data.load_error || data.error
      toast('操作完成但存在错误', 'error')
    } else {
      toast(data?.queued ? '操作已入队' : '操作已完成')
    }
    if (data?.queued) await loadActions()
    if (data?.status) healthText.value = data.status
    if (data?.summary) healthText.value = JSON.stringify(data.summary, null, 2)
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('操作失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

async function clearContext() {
  if (!contextScope.value.trim()) return
  if (!confirm(`清空 ${contextScope.value.trim()} 的 LLM 短期上下文？`)) return
  runtimeLoading.value = 'clear'
  runtimeError.value = null
  try {
    const data = await clearLlmContext(contextScope.value.trim())
    toast(data?.queued ? '清空上下文已入队' : `已删除 ${data.deleted || 0} 条`)
    if (data?.queued) await loadActions()
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('清空失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

async function deleteContextMessage() {
  const scope = contextScope.value.trim()
  const messageId = contextMessageId.value.trim()
  if (!scope || !messageId) return
  runtimeLoading.value = 'delete-msg'
  runtimeError.value = null
  try {
    const data = await deleteLlmContextMessage(scope, messageId)
    toast(data?.queued ? '删除消息已入队' : (data.deleted ? '已删除消息' : '未找到消息'))
    if (data?.queued) await loadActions()
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('删除失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

async function sendSample() {
  sampleLoading.value = true
  sampleError.value = null
  sampleResult.value = null
  try {
    sampleResult.value = await runSampleRequest(JSON.stringify({
      provider_id: sample.value.provider_id,
      model: sample.value.model || null,
      system_prompt: sample.value.system_prompt,
      user_prompt: sample.value.user_prompt,
      stream: false,
      max_output_tokens: sample.value.max_output_tokens,
    }))
  } catch (e: unknown) {
    sampleError.value = (e as Error).message
  } finally {
    sampleLoading.value = false
  }
}

async function runRegress() {
  regressionLoading.value = true
  regressionError.value = null
  regressionResults.value = []
  try {
    const lines = regressionInput.value.split('\n').filter(line => line.trim())
    if (!lines.length) {
      regressionError.value = '请至少输入一条测试样本'
      return
    }
    const samples = lines.map(line => {
      const pipe = line.indexOf('|')
      if (pipe >= 0) {
        return { label: line.slice(0, pipe).trim(), text: line.slice(pipe + 1).trim() }
      }
      return { label: '', text: line.trim() }
    })
    const data = await runRegression(JSON.stringify({ samples }))
    regressionResults.value = data.samples || []
  } catch (e: unknown) {
    regressionError.value = (e as Error).message
  } finally {
    regressionLoading.value = false
  }
}

onMounted(() => {
  loadProviders()
  loadActions()
})
</script>

<style scoped>
.diag-view {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
  min-height: 0;
}

.diag-stack {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
}

.diag-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--qq-gap-md);
  background: linear-gradient(180deg, var(--qq-surface), var(--qq-surface-elevated));
}

.diag-card__head {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: var(--qq-gap-sm);
  align-items: center;
}

.diag-card__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.diag-card__head h3 {
  margin: 0 0 2px;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
  line-height: 1.3;
}

.diag-card__head p {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
}

.sample-form,
.sample-result,
.regression-results {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.runtime-actions,
.context-tools {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.action-panel {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
  padding-top: var(--qq-gap-sm);
}

.action-panel__head,
.action-main {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.action-panel__head {
  justify-content: space-between;
}

.action-panel__head h4 {
  margin: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.action-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.action-item {
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.action-main {
  justify-content: space-between;
}

.action-time,
.mono {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.action-error {
  margin-top: 4px;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs);
  word-break: break-word;
}

.action-result {
  margin: 4px 0 0;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  white-space: pre-wrap;
  word-break: break-word;
}

.inline-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.inline-field input {
  width: 190px;
}

.form-row,
.form-actions,
.result-meta,
.trace-head,
.regression-head,
.regression-rule {
  display: flex;
  align-items: center;
}

.form-row,
.form-actions,
.result-meta,
.trace-head,
.regression-head,
.regression-rule {
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.field {
  display: flex;
  min-width: 160px;
  flex-direction: column;
  gap: 4px;
}

.field--small {
  min-width: 118px;
}

.field.grow {
  flex: 1;
  min-width: 220px;
}

.field label {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
}

.field--small input {
  width: 118px;
}

textarea {
  resize: vertical;
}

.duration,
.token-info,
.trace-meta,
.regression-label,
.rule-name,
.rule-prio {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.error-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-danger-soft);
  border: 1px solid var(--qq-danger-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.result-text,
.json-block,
.health-block {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.result-text {
  padding: var(--qq-gap-sm);
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  line-height: 1.6;
  white-space: pre-wrap;
}

.json-block {
  margin: var(--qq-gap-xs) 0 0;
  padding: var(--qq-gap-sm);
  overflow-x: auto;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.health-block {
  margin: 0;
  padding: var(--qq-gap-sm);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.data-detail {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.data-detail summary {
  cursor: pointer;
}

.trace-item {
  margin-top: var(--qq-gap-xs);
}

.regression-results {
  gap: var(--qq-gap-sm);
}

.regression-item {
  overflow: hidden;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
  padding: var(--qq-gap-sm);
}

.regression-item.matched {
  border-color: var(--qq-primary-border);
  background: var(--qq-primary-soft);
}

.regression-text,
.rule-patterns {
  flex: 1;
  min-width: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.rule-patterns {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.regression-rules {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--qq-gap-sm);
  padding-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
}

@media (max-width: 640px) {
  .diag-card__head {
    grid-template-columns: 32px minmax(0, 1fr);
  }

  .diag-card__icon {
    width: 32px;
    height: 32px;
  }

  .field,
  .field.grow,
  .field--small {
    min-width: 100%;
  }

  .field--small input {
    width: 100%;
  }
}
</style>
