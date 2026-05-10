<template>
  <div class="diag-view">
    <UiPageHeader title="诊断" subtitle="LLM 样本请求与文本规则回归测试" />

    <div class="diag-stack">
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
import UiIcon from '../components/ui/UiIcon.vue'
import UiTag from '../components/ui/UiTag.vue'
import { fetchProviders, runRegression, runSampleRequest } from '../api/diagnostics'

const providers = ref<any[]>([])
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
  } catch {
    providers.value = []
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
  border-color: rgba(18, 183, 245, 0.42);
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
