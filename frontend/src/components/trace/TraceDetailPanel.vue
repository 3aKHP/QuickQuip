<template>
  <section class="detail-panel">
    <div class="detail-head">
      <div class="detail-title">
        <span class="detail-kicker">HTTP CALL</span>
        <strong>{{ detail?.provider_id || '调用详情' }}</strong>
        <code v-if="detail">{{ detail.call_id }}</code>
      </div>
      <UiButton icon="X" size="sm" variant="ghost" title="关闭详情" @click="$emit('close')" />
    </div>

    <UiLoading v-if="loading" text="读取原始传输文本..." />
    <template v-else-if="detail">
      <dl class="meta-grid">
        <div><dt>Model</dt><dd>{{ detail.model || '-' }}</dd></div>
        <div><dt>Status</dt><dd>{{ detail.response_status ?? detail.state }}</dd></div>
        <div><dt>Duration</dt><dd>{{ formatDuration(detail.duration_ms) }}</dd></div>
        <div><dt>Wire Bytes</dt><dd>{{ formatBytes(detail.request_bytes + (detail.response_raw_bytes || detail.response_bytes)) }}</dd></div>
        <div><dt>Agent Loop</dt><dd>{{ detail.agent_loop_id.slice(0, 8) }}</dd></div>
        <div><dt>HTTP Step</dt><dd>#{{ detail.loop_sequence }}</dd></div>
      </dl>

      <div class="endpoint">
        <UiTag size="sm" variant="accent">{{ detail.method }}</UiTag>
        <code>{{ detail.url }}</code>
      </div>

      <div class="segment" role="tablist" aria-label="传输方向">
        <button :class="{ active: direction === 'request' }" @click="direction = 'request'">Request</button>
        <button :class="{ active: direction === 'response' }" @click="direction = 'response'">Response</button>
      </div>

      <div class="payload-toolbar">
        <div class="segment segment--small" role="tablist" aria-label="内容类型">
          <button :class="{ active: contentKind === 'body' }" @click="contentKind = 'body'">JSON</button>
          <button :class="{ active: contentKind === 'headers' }" @click="contentKind = 'headers'">Headers</button>
        </div>
        <div v-if="contentKind === 'body'" class="segment segment--view" role="tablist" aria-label="正文视图">
          <button :class="{ active: bodyView === 'formatted' }" @click="bodyView = 'formatted'">
            {{ formattedLabel }}
          </button>
          <button :class="{ active: bodyView === 'raw' }" @click="bodyView = 'raw'">
            {{ rawLabel }}
          </button>
        </div>
        <div class="payload-actions">
          <UiButton icon="Copy" size="sm" variant="ghost" title="复制当前文本" @click="copyCurrent" />
          <UiButton icon="Download" size="sm" variant="ghost" title="下载当前文本" @click="downloadCurrent" />
        </div>
      </div>

      <pre class="payload">{{ currentText || emptyText }}</pre>

      <div v-if="detail.state === 'error'" class="error-detail">
        <strong>{{ detail.error_type || 'Request error' }}</strong>
        <span>{{ detail.error_message }}</span>
      </div>
    </template>
    <UiEmpty v-else icon="MousePointerClick" title="选择一条 HTTP 调用查看原文" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TraceCallDetail } from '../../api/logs'
import UiButton from '../ui/UiButton.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiLoading from '../ui/UiLoading.vue'
import UiTag from '../ui/UiTag.vue'
import { toast } from '../../toast'

const props = defineProps<{
  detail: TraceCallDetail | null
  loading: boolean
}>()

defineEmits<{ close: [] }>()

const direction = ref<'request' | 'response'>('request')
const contentKind = ref<'body' | 'headers'>('body')
const bodyView = ref<'formatted' | 'raw'>('formatted')

watch(() => props.detail?.call_id, () => {
  direction.value = 'request'
  contentKind.value = 'body'
  bodyView.value = 'formatted'
})

function formatJson(value: string): string {
  if (!value) return ''
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

const currentText = computed(() => {
  if (!props.detail) return ''
  if (direction.value === 'request') {
    if (contentKind.value === 'headers') return props.detail.request_headers
    return bodyView.value === 'formatted'
      ? formatJson(props.detail.request_text)
      : props.detail.request_text
  }
  if (contentKind.value === 'headers') return props.detail.response_headers
  if (bodyView.value === 'formatted') return formatJson(props.detail.response_text)
  return props.detail.stream && props.detail.response_raw_text
    ? props.detail.response_raw_text
    : props.detail.response_text
})

const formattedLabel = computed(() => direction.value === 'response' && props.detail?.stream
  ? '组合 JSON'
  : '格式化 JSON')

const rawLabel = computed(() => direction.value === 'response' && props.detail?.stream
  ? 'SSE 原文'
  : '传输原文')

const emptyText = computed(() => direction.value === 'response' && props.detail?.state === 'pending'
  ? '响应尚未完成。'
  : '没有可显示的文本。')

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(value: number | null): string {
  if (value == null) return '-'
  return value < 1000 ? `${value.toFixed(0)} ms` : `${(value / 1000).toFixed(2)} s`
}

async function copyCurrent() {
  try {
    await navigator.clipboard.writeText(currentText.value)
    toast('已复制传输文本')
  } catch (error: unknown) {
    toast((error as Error).message || '复制失败', 'error')
  }
}

function downloadCurrent() {
  if (!props.detail) return
  const blob = new Blob([currentText.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.detail.call_id}-${direction.value}-${contentKind.value}-${bodyView.value}.txt`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.detail-panel {
  min-width: 0;
  min-height: 560px;
  border-left: 1px solid var(--qq-border);
  padding-left: var(--qq-gap-md);
}

.detail-head,
.payload-toolbar,
.endpoint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
}

.detail-title {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.detail-title code,
.endpoint code {
  overflow: hidden;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-kicker,
dt {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  text-transform: uppercase;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: var(--qq-gap-md) 0;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
}

.meta-grid > div {
  min-width: 0;
  padding: 8px 10px;
  border-right: 1px solid var(--qq-border);
}

.meta-grid > div:nth-child(3n) { border-right: 0; }
.meta-grid > div:nth-child(-n + 3) { border-bottom: 1px solid var(--qq-border); }
.meta-grid dd { margin: 3px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.endpoint {
  justify-content: flex-start;
  min-width: 0;
  padding: 8px 0;
}

.endpoint code { flex: 1; }

.segment {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(90px, 1fr));
  margin: var(--qq-gap-sm) 0;
  padding: 2px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.segment button {
  min-height: 30px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
}

.segment button.active {
  background: var(--qq-surface);
  color: var(--qq-text);
  box-shadow: var(--qq-shadow-sm);
}

.segment--small { grid-template-columns: repeat(2, 76px); }
.segment--small button { min-height: 26px; font-size: var(--qq-text-xs); }
.segment--view { grid-template-columns: repeat(2, minmax(88px, auto)); margin-left: auto; }
.segment--view button { min-height: 26px; padding: 0 9px; font-size: var(--qq-text-xs); }
.payload-actions { display: flex; gap: 2px; }

.payload {
  min-height: 360px;
  max-height: 62vh;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: var(--qq-line-mono);
  white-space: pre-wrap;
  word-break: break-word;
}

.error-detail {
  display: grid;
  gap: 4px;
  margin-top: var(--qq-gap-sm);
  padding: 10px 12px;
  border-left: 3px solid var(--qq-danger);
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

@media (max-width: 900px) {
  .detail-panel { min-height: 0; padding: var(--qq-gap-md) 0 0; border-top: 1px solid var(--qq-border); border-left: 0; }
  .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .meta-grid > div { border-right: 1px solid var(--qq-border); border-bottom: 1px solid var(--qq-border); }
  .meta-grid > div:nth-child(2n) { border-right: 0; }
  .meta-grid > div:nth-last-child(-n + 2) { border-bottom: 0; }
}
</style>
