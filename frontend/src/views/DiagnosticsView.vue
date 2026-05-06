<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 原始请求/响应查看、Trace 控制、文本规则回归测试" />

    <div class="diag-grid">
      <section class="diag-card diag-card--sample">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="Send" :size="18" /></span>
          <div>
            <h3>样本请求</h3>
            <p>按 provider/model 发送一次 LLM 请求，查看原始 JSON 和解析结果。</p>
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
            <UiTag size="sm" :variant="sampleResult.finish_reason === 'stop' ? 'success' : 'warn'">
              {{ sampleResult.finish_reason || 'N/A' }}
            </UiTag>
            <span v-if="sampleResult.input_tokens" class="token-info">
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
      </section>

      <section class="diag-card diag-card--trace">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="FileCode" :size="18" /></span>
          <div>
            <h3>Trace 控制</h3>
            <p>控制 LLM_TRACE_FLAG_FILE 开关，浏览最近 trace 条目。</p>
          </div>
        </div>

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
            <UiButton size="sm" variant="danger" icon="Trash2" :disabled="traceCount === 0" @click="doClearTraces">
              清空
            </UiButton>
          </div>
        </div>

        <div v-if="traceEntries.length" class="trace-list">
          <div v-for="(t, i) in traceEntries" :key="i" class="trace-entry">
            <div class="trace-entry-head">
              <span class="trace-index">#{{ traceEntries.length - i }}</span>
              <UiTag size="sm" :variant="t.direction === 'request' ? 'warn' : 'success'">
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
      </section>

      <section class="diag-card diag-card--regression">
        <div class="diag-card__head">
          <span class="diag-card__icon"><UiIcon name="ListChecks" :size="18" /></span>
          <div>
            <h3>文本规则回归</h3>
            <p>输入测试文本，查看哪些规则命中。</p>
          </div>
        </div>

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
              <UiTag size="sm" :variant="r.matched ? 'success' : 'info'">{{ r.matched ? '命中' : '未命中' }}</UiTag>
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
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import {
  clearTraces,
  fetchProviders,
  fetchRecentTraces,
  fetchTraceStatus,
  runRegression,
  runSampleRequest,
  setTraceStatus,
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
  loadTraceStatus()
  loadTraces()
})
</script>

<style scoped>
.diag-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.diag-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  grid-template-areas:
    "sample trace"
    "regression trace";
  gap: var(--qq-gap-md);
  align-items: start;
}

.diag-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--qq-gap-md);
  padding: var(--qq-gap-md);
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}

.diag-card--sample { grid-area: sample; }
.diag-card--trace { grid-area: trace; }
.diag-card--regression { grid-area: regression; }

.diag-card__head {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: var(--qq-gap-sm);
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
.regression-form,
.sample-result {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.form-row {
  display: flex;
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

.form-actions,
.result-meta,
.trace-head,
.trace-controls,
.trace-status-row,
.trace-actions,
.trace-entry-head,
.regression-head,
.regression-rule {
  display: flex;
  align-items: center;
}

.form-actions,
.result-meta,
.trace-head,
.trace-status-row,
.trace-actions,
.regression-head,
.regression-rule {
  gap: var(--qq-gap-sm);
}

.trace-controls {
  justify-content: space-between;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.duration,
.token-info,
.trace-meta,
.flag-path,
.trace-index,
.trace-time,
.regression-label,
.rule-pattern,
.rule-prio {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.status-label {
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.flag-unset {
  color: var(--qq-warn);
  font-size: var(--qq-text-xs);
}

.error-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-danger-soft);
  border: 1px solid rgba(250, 81, 81, 0.25);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.result-text,
.json-block {
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
  white-space: pre;
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

.trace-list,
.regression-results {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.trace-list {
  max-height: 640px;
  overflow-y: auto;
}

.trace-entry,
.regression-item {
  overflow: hidden;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
}

.trace-entry-head {
  gap: var(--qq-gap-xs);
  padding: 6px var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-bottom: 1px solid var(--qq-border);
}

.trace-time {
  margin-left: auto;
}

.regression-item {
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
}

.regression-item.matched {
  border-color: rgba(18, 183, 245, 0.42);
  background: var(--qq-primary-soft);
}

.regression-text {
  flex: 1;
  min-width: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
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

.rule-pattern {
  min-width: 92px;
  color: var(--qq-primary);
}

.rule-reply {
  flex: 1;
  min-width: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .diag-grid {
    grid-template-columns: 1fr;
    grid-template-areas:
      "sample"
      "trace"
      "regression";
  }
}

@media (max-width: 640px) {
  .diag-card {
    padding: var(--qq-gap-sm);
  }

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

  .trace-time {
    width: 100%;
    margin-left: 0;
  }
}
</style>
