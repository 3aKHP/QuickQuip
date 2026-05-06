<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 原始请求/响应查看、Trace 控制、文本规则回归测试" />

    <UiCard padding="md" shadow="sm" class="diag-section">
      <h3 class="section-title">样本请求</h3>
      <p class="section-desc">按 provider/model 发送一次 LLM 请求，查看原始 JSON 和解析结果。</p>

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
          <div class="field">
            <label>Max Tokens</label>
            <input v-model.number="sample.max_output_tokens" type="number" min="1" max="4096" style="width:100px" />
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
            <textarea v-model="sample.user_prompt" rows="2" />
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
          <UiTag size="sm" :variant="sampleResult.finish_reason === 'stop' ? 'ok' : 'warn'">
            {{ sampleResult.finish_reason || 'N/A' }}
          </UiTag>
          <span class="token-info" v-if="sampleResult.input_tokens">
            in {{ sampleResult.input_tokens }} / out {{ sampleResult.output_tokens }}
          </span>
        </div>
        <div class="result-text">{{ sampleResult.text }}</div>
        <details v-if="sampleResult.thinking_blocks?.length" class="thinking-detail">
          <summary>Thought Blocks ({{ sampleResult.thinking_blocks.length }})</summary>
          <pre class="json-block">{{ prettyJson(sampleResult.thinking_blocks) }}</pre>
        </details>
        <details v-if="sampleResult.raw_traces?.length" class="trace-detail">
          <summary>Raw Traces ({{ sampleResult.raw_traces.length }})</summary>
          <div v-for="(t, i) in sampleResult.raw_traces" :key="i" class="trace-item">
            <div class="trace-head">
              <UiTag size="sm" :variant="t.direction === 'request' ? 'warn' : 'ok'">
                {{ t.direction.toUpperCase() }}
              </UiTag>
              <span class="trace-meta">{{ t.timestamp }}</span>
            </div>
            <pre class="json-block">{{ t.payload }}</pre>
          </div>
        </details>
      </div>
    </UiCard>

    <UiCard padding="md" shadow="sm" class="diag-section">
      <h3 class="section-title">Trace 控制</h3>
      <p class="section-desc">控制 LLM_TRACE_FLAG_FILE 开关，浏览最近 trace 条目。</p>

      <div class="trace-controls">
        <div class="trace-status-row">
          <UiToggle :model-value="traceActive" :disabled="!traceFlagFile" @update:model-value="toggleTrace" />
          <span class="status-label">
            {{ traceActive ? 'Trace 已开启' : 'Trace 已关闭' }}
            <span v-if="traceFlagFile" class="flag-path">({{ traceFlagFile }})</span>
            <span v-else class="flag-unset">(LLM_TRACE_FLAG_FILE 未设置)</span>
          </span>
        </div>
        <div class="trace-actions">
          <UiButton size="sm" icon="RefreshCw" @click="loadTraces">刷新 ({{ traceCount }})</UiButton>
          <UiButton size="sm" variant="danger" icon="Trash2" @click="doClearTraces" :disabled="traceCount === 0">
            清空
          </UiButton>
        </div>
      </div>

      <div v-if="traceEntries.length" class="trace-list">
        <div v-for="(t, i) in traceEntries" :key="i" class="trace-entry">
          <div class="trace-entry-head">
            <span class="trace-index">#{{ traceEntries.length - i }}</span>
            <UiTag size="sm" :variant="t.direction === 'request' ? 'warn' : 'ok'">
              {{ t.direction.toUpperCase() }}
            </UiTag>
            <UiTag size="sm" variant="info">{{ t.provider_id }}</UiTag>
            <UiTag v-if="t.stream" size="sm">STREAM</UiTag>
            <span class="trace-time">{{ t.timestamp }}</span>
          </div>
          <pre class="json-block">{{ t.payload }}</pre>
        </div>
      </div>
      <UiEmpty v-else icon="FileCode" title="无 trace 条目" />
    </UiCard>

    <UiCard padding="md" shadow="sm" class="diag-section">
      <h3 class="section-title">文本规则回归</h3>
      <p class="section-desc">输入测试文本，查看哪些规则命中。</p>

      <div class="regression-form">
        <div class="form-row">
          <div class="field grow">
            <label>测试样本（每行一条，前面可用 | 分隔标签）</label>
            <textarea
              v-model="regressionInput"
              rows="6"
              placeholder="标签1 | 你好世界&#10;标签2 | 今天天气真好"
            />
          </div>
        </div>
        <div class="form-actions">
          <UiButton icon="Play" :loading="regressionLoading" @click="runRegress">运行</UiButton>
        </div>
      </div>

      <div v-if="regressionError" class="error-block">{{ regressionError }}</div>

      <div v-if="regressionResults.length" class="regression-results">
        <div v-for="(r, i) in regressionResults" :key="i" class="regression-item" :class="{ matched: r.matched }">
          <div class="regression-head">
            <span class="regression-label">{{ r.label || `#${i + 1}` }}</span>
            <span class="regression-text">{{ r.text }}</span>
            <UiTag size="sm" :variant="r.matched ? 'ok' : 'muted'">{{ r.matched ? '命中' : '未命中' }}</UiTag>
          </div>
          <div v-if="r.rules.length" class="regression-rules">
            <div v-for="(rule, j) in r.rules" :key="j" class="regression-rule">
              <span class="rule-pattern">/{{ rule.pattern }}/</span>
              <span class="rule-reply">{{ rule.reply }}</span>
              <span class="rule-prio">P{{ rule.priority }}</span>
            </div>
          </div>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import {
  fetchProviders,
  fetchTraceStatus,
  setTraceStatus,
  fetchRecentTraces,
  clearTraces,
  runSampleRequest,
  runRegression,
} from '../api/diagnostics'

const providers = ref<any[]>([])
const traceActive = ref(false)
const traceFlagFile = ref('')
const traceCount = ref(0)
const traceEntries = ref<any[]>([])
const sampleLoading = ref(false)
const sampleError = ref<string | null>(null)
const sampleResult = ref<any>(null)
const regressionLoading = ref(false)
const regressionError = ref<string | null>(null)
const regressionResults = ref<any[]>([])
const regressionInput = ref('')

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
  const p = providers.value.find(p => p.id === sample.value.provider_id)
  return p ? p.models : []
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

async function loadProviders() {
  try {
    const data = await fetchProviders()
    if (data?.providers) {
      providers.value = data.providers
      if (!sample.value.provider_id && providers.value.length) {
        sample.value.provider_id = providers.value[0].id
      }
    }
  } catch { /* ignore */ }
}

async function loadTraceStatus() {
  try {
    const data = await fetchTraceStatus()
    traceActive.value = data.active
    traceFlagFile.value = data.flag_file
    traceCount.value = data.entry_count
  } catch { /* ignore */ }
}

async function loadTraces() {
  try {
    const data = await fetchRecentTraces(50)
    traceEntries.value = data.entries || []
    traceCount.value = traceEntries.value.length
  } catch { /* ignore */ }
}

async function toggleTrace(on: boolean) {
  if (!traceFlagFile.value) return
  try {
    await setTraceStatus(on)
    traceActive.value = on
  } catch { /* ignore */ }
}

async function doClearTraces() {
  try {
    await clearTraces()
    traceEntries.value = []
    traceCount.value = 0
  } catch { /* ignore */ }
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
    const lines = regressionInput.value.split('\n').filter(l => l.trim())
    if (!lines.length) {
      regressionError.value = '请至少输入一条测试样本'
      return
    }
    const samples = lines.map(line => {
      const pipe = line.indexOf('|')
      if (pipe >= 0) return { label: line.slice(0, pipe).trim(), text: line.slice(pipe + 1).trim() }
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
  loadTraceStatus()
  loadTraces()
})
</script>

<style scoped>
.diag-view {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-lg);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.diag-section {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.section-title {
  font-size: var(--qq-text-base);
  font-weight: 600;
  color: var(--qq-text);
  margin: 0;
}

.section-desc {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  margin: 0;
}

.form-row { display: flex; gap: var(--qq-gap-sm); flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field.grow { flex: 1; min-width: 200px; }
.field label {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-weight: 500;
}

select, input, textarea {
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
}
textarea { resize: vertical; }

.form-actions {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  margin-top: 4px;
}

.duration {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
}

.error-block {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-danger);
}

.sample-result {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.result-meta {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
}

.token-info {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
}

.result-text {
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-border);
  font-size: var(--qq-text-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  color: var(--qq-text);
}

.json-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-border);
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre;
  color: var(--qq-text-muted);
}

.thinking-detail, .trace-detail {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.trace-item {
  margin-top: var(--qq-gap-xs);
}

.trace-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 4px;
}

.trace-meta {
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  color: var(--qq-text-muted);
}

.trace-controls {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.trace-status-row {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.status-label {
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.flag-path {
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  color: var(--qq-text-muted);
}

.flag-unset {
  font-size: var(--qq-text-xs);
  color: var(--qq-warn);
}

.trace-actions {
  display: flex;
  gap: var(--qq-gap-xs);
}

.trace-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  max-height: 500px;
  overflow-y: auto;
}

.trace-entry {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  overflow: hidden;
}

.trace-entry-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  padding: 4px var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-bottom: 1px solid var(--qq-border);
  font-size: var(--qq-text-xs);
}

.trace-index {
  font-family: var(--qq-font-mono);
  color: var(--qq-text-muted);
}

.trace-time {
  font-family: var(--qq-font-mono);
  color: var(--qq-text-muted);
  margin-left: auto;
}

.regression-results {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.regression-item {
  padding: var(--qq-gap-sm);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.regression-item.matched {
  border-color: var(--qq-accent);
  background: var(--qq-surface-elevated);
}

.regression-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.regression-label {
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  color: var(--qq-text-muted);
}

.regression-text {
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
  flex: 1;
}

.regression-rules {
  margin-top: var(--qq-gap-xs);
  padding-top: var(--qq-gap-xs);
  border-top: 1px solid var(--qq-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.regression-rule {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: var(--qq-text-xs);
}

.rule-pattern {
  font-family: var(--qq-font-mono);
  color: var(--qq-accent);
  min-width: 80px;
}

.rule-reply {
  color: var(--qq-text-muted);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule-prio {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}
</style>
