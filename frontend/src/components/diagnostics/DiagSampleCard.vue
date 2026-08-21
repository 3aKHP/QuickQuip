<template>
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

      <details v-if="sampleResult.trace_calls?.length" class="data-detail">
        <summary>HTTP Traces ({{ sampleResult.trace_calls.length }})</summary>
        <div v-for="call in sampleResult.trace_calls" :key="call.call_id" class="trace-item">
          <div class="trace-head">
            <UiTag size="sm" :variant="call.state === 'success' ? 'success' : 'danger'">
              {{ call.state.toUpperCase() }}
            </UiTag>
            <span class="trace-meta">{{ call.method }} {{ call.url }}</span>
          </div>
          <details open>
            <summary>Request JSON · {{ call.request_bytes }} bytes</summary>
            <pre class="json-block">{{ call.request_text }}</pre>
          </details>
          <details>
            <summary>Response JSON · {{ call.response_bytes }} bytes</summary>
            <pre class="json-block">{{ call.response_text }}</pre>
          </details>
        </div>
      </details>
    </div>
  </UiCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiTag from '../ui/UiTag.vue'
import { fetchProviders, runSampleRequest } from '../../api/diagnostics'
import type { DiagnosticsProvider, SampleRequestResult } from '../../api/diagnostics'

const providers = ref<DiagnosticsProvider[]>([])
const sampleLoading = ref(false)
const sampleError = ref<string | null>(null)
const sampleResult = ref<SampleRequestResult | null>(null)

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

function prettyJson(obj: unknown): string {
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
    sampleResult.value = await runSampleRequest({
      provider_id: sample.value.provider_id,
      model: sample.value.model || null,
      system_prompt: sample.value.system_prompt,
      user_prompt: sample.value.user_prompt,
      stream: false,
      max_output_tokens: sample.value.max_output_tokens,
    })
  } catch (e: unknown) {
    sampleError.value = (e as Error).message
  } finally {
    sampleLoading.value = false
  }
}

onMounted(() => {
  loadProviders()
})
</script>

<style scoped>
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
.sample-result {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.form-row,
.form-actions,
.result-meta,
.trace-head {
  display: flex;
  align-items: center;
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
.trace-meta {
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
