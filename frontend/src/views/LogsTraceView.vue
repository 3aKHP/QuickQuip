<template>
  <div class="page">
    <UiPageHeader title="LLM Trace" subtitle="Trace 开关、流式块与最近输出都放在这里">
      <template #actions>
        <UiButton size="sm" icon="RefreshCw" :loading="loading" @click="reloadMeta">刷新状态</UiButton>
        <UiButton size="sm" icon="Trash2" variant="danger" :disabled="!entries.length" @click="clear">清空</UiButton>
      </template>
    </UiPageHeader>

    <UiCard padding="md" shadow="sm" class="panel">
      <div class="meta-row">
        <UiTag size="sm" variant="info">{{ traceFlagLabel }}</UiTag>
        <UiTag size="sm" :variant="connected ? 'success' : 'warn'">{{ connected ? '已连接' : '连接中断' }}</UiTag>
      </div>

      <div class="toolbar">
        <UiToggle :model-value="traceActive" :disabled="!traceFlagFile" @update:model-value="toggleTrace" />
        <label class="filter">
          <UiIcon name="Search" :size="14" />
          <input v-model="filter" type="search" placeholder="过滤关键词 / 正则" />
        </label>
        <label class="toggle">
          <input v-model="autoScroll" type="checkbox" />
          <span>自动滚动</span>
        </label>
      </div>

      <div ref="traceEl" class="trace-box">
        <div v-if="filteredEntries.length" class="trace-stream">
          <article v-for="(entry, i) in filteredEntries" :key="entry.id" class="trace-entry" :class="entry.direction">
            <div class="trace-entry-head">
              <span class="trace-index">#{{ filteredEntries.length - i }}</span>
              <UiTag size="sm" :variant="entry.direction === 'request' ? 'warn' : 'success'">{{ entry.direction.toUpperCase() }}</UiTag>
              <UiTag size="sm" variant="info">{{ entry.provider_id }}</UiTag>
              <UiTag v-if="entry.stream" size="sm">STREAM</UiTag>
              <span class="trace-time">{{ entry.timestamp }}</span>
            </div>
            <pre class="json-block">{{ entry.payload }}</pre>
          </article>
        </div>
        <UiEmpty v-else icon="FileCode" title="暂无 trace 条目" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { clearTraces, fetchTraceStatus, setTraceStatus } from '../api/diagnostics'
import { buildTraceStreamUrl } from '../api/logs'

interface TraceEntry {
  id: number
  timestamp: string
  direction: string
  provider_id: string
  stream: boolean
  payload: string
}

const MAX_ENTRIES = 500
const MAX_PENDING_ENTRIES = 120
const FLUSH_FALLBACK_MS = 250

const loading = ref(false)
const connected = ref(false)
const traceActive = ref(false)
const traceFlagFile = ref('')
const filter = ref('')
const autoScroll = ref(true)
const entries = ref<TraceEntry[]>([])
const traceEl = ref<HTMLElement | null>(null)
let source: EventSource | null = null
let nextId = 0
let rafId: number | null = null
let fallbackTimerId: number | null = null
const pending: TraceEntry[] = []

const traceFlagLabel = computed(() => {
  if (!traceFlagFile.value) return 'LLM_TRACE_FLAG_FILE 未设置'
  return `Trace 开关：${traceActive.value ? '开' : '关'}`
})

function compileFilter(value: string): RegExp | null {
  const raw = value.trim()
  if (!raw) return null
  try {
    return new RegExp(raw, 'i')
  } catch {
    return null
  }
}

const filteredEntries = computed(() => {
  const re = compileFilter(filter.value)
  if (!re) return entries.value
  return entries.value.filter(entry => re.test(`${entry.timestamp}\n${entry.direction}\n${entry.provider_id}\n${entry.payload}`))
})

async function reloadMeta() {
  loading.value = true
  try {
    const data = await fetchTraceStatus()
    traceActive.value = !!data.active
    traceFlagFile.value = data.flag_file || ''
  } catch {
    traceActive.value = false
    traceFlagFile.value = ''
  } finally {
    loading.value = false
  }
}

async function toggleTrace(next: boolean) {
  if (!traceFlagFile.value) return
  try {
    await setTraceStatus(next)
    traceActive.value = next
  } catch {
    // ignore, keep current UI state
  }
}

async function clear() {
  try {
    await clearTraces()
    cancelScheduledFlush()
    pending.length = 0
    entries.value = []
  } catch {
    // ignore
  }
}

function enqueueEntry(entry: TraceEntry) {
  pending.push(entry)
  if (pending.length > MAX_PENDING_ENTRIES) pending.splice(0, pending.length - MAX_PENDING_ENTRIES)
  scheduleFlush()
}

function scheduleFlush() {
  if (rafId != null || fallbackTimerId != null) return
  rafId = requestAnimationFrame(runScheduledFlush)
  fallbackTimerId = window.setTimeout(runScheduledFlush, FLUSH_FALLBACK_MS)
}

function cancelScheduledFlush() {
  if (rafId != null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  if (fallbackTimerId != null) {
    clearTimeout(fallbackTimerId)
    fallbackTimerId = null
  }
}

function runScheduledFlush() {
  cancelScheduledFlush()
  flushPending()
}

function flushPending() {
  if (!pending.length) return
  for (const entry of pending) {
    entries.value.push({ ...entry, id: nextId++ })
  }
  if (entries.value.length > MAX_ENTRIES) entries.value.splice(0, entries.value.length - MAX_ENTRIES)
  pending.length = 0
  if (autoScroll.value) {
    nextTick(() => {
      const el = traceEl.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function connect() {
  source?.close()
  source = new EventSource(buildTraceStreamUrl(100))
  source.onopen = () => {
    connected.value = true
  }
  source.onerror = () => {
    connected.value = false
  }
  source.onmessage = (event) => {
    if (!event.data) return
    try {
      enqueueEntry(JSON.parse(event.data) as TraceEntry)
    } catch {
      // ignore malformed payloads
    }
  }
}

onMounted(async () => {
  await reloadMeta()
  connect()
})

onBeforeUnmount(() => {
  source?.close()
  cancelScheduledFlush()
  pending.length = 0
})
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
  min-height: 0;
}

.panel {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  min-height: 0;
  background: linear-gradient(180deg, var(--qq-surface), var(--qq-surface-elevated));
}

.meta-row,
.toolbar,
.trace-entry-head {
  display: flex;
  align-items: center;
}

.meta-row,
.toolbar {
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.filter,
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.filter {
  min-width: min(100%, 360px);
  padding: 6px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.filter input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--qq-text);
  font: inherit;
}

.toggle input {
  margin: 0;
}

.trace-box {
  min-height: 62vh;
  max-height: 75vh;
  overflow-y: auto;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.trace-stream {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.trace-entry {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
  overflow: hidden;
}

.trace-entry.request {
  border-color: rgba(217, 119, 6, 0.35);
}

.trace-entry.response {
  border-color: rgba(16, 185, 129, 0.35);
}

.trace-entry-head {
  gap: var(--qq-gap-xs);
  padding: 6px 10px;
  background: var(--qq-surface-strong);
  border-bottom: 1px solid var(--qq-border);
  flex-wrap: wrap;
}

.trace-index,
.trace-time {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.trace-time {
  margin-left: auto;
}

.json-block {
  margin: 0;
  padding: 10px 12px;
  overflow-x: auto;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 640px) {
  .trace-box {
    min-height: 56vh;
  }
}
</style>
