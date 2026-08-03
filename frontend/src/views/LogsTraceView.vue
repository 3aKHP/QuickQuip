<template>
  <div class="page">
    <UiPageHeader title="LLM Trace" subtitle="QuickQuip 与 LLM Provider 的完整 HTTP JSON 传输">
      <template #actions>
        <UiButton size="sm" icon="RefreshCw" :loading="loading" @click="reload">刷新</UiButton>
        <UiButton size="sm" icon="Trash2" variant="danger" :disabled="!calls.length" @click="clear">清空</UiButton>
      </template>
    </UiPageHeader>

    <div class="sensitive-notice">
      <UiIcon name="ShieldAlert" :size="16" />
      <span>Trace 包含完整请求、响应、认证 Header、系统提示和用户内容，仅在排障期间开启。</span>
    </div>

    <UiCard padding="md" shadow="sm" class="trace-shell">
      <div class="status-row">
        <label class="trace-switch">
          <UiToggle :model-value="traceActive" :disabled="!traceFlagFile" @update:model-value="toggleTrace" />
          <span>{{ traceActive ? '正在采集' : '采集已关闭' }}</span>
        </label>
        <UiTag size="sm" :variant="connected ? 'success' : 'warn'">
          {{ connected ? '实时流已连接' : '实时流连接中' }}
        </UiTag>
        <span class="status-stat">{{ totalCount }} 次调用</span>
        <span class="status-stat">{{ formatBytes(storageBytes) }}</span>
      </div>

      <div class="toolbar">
        <label class="search">
          <UiIcon name="Search" :size="14" />
          <input v-model="filter" type="search" placeholder="Provider / Model / URL / 状态" />
        </label>
        <select v-model="stateFilter" class="state-filter" aria-label="调用状态">
          <option value="">全部状态</option>
          <option value="pending">Pending</option>
          <option value="success">Success</option>
          <option value="error">Error</option>
        </select>
      </div>

      <p v-if="error" class="error-banner">{{ error }}</p>

      <div class="workspace">
        <section class="call-list" aria-label="HTTP 调用列表">
          <UiLoading v-if="loading && !calls.length" text="加载调用索引..." />
          <UiEmpty v-else-if="!filteredCalls.length" icon="FileCode" title="暂无 HTTP Trace" />
          <article v-for="group in groupedCalls" :key="group.loopId" class="loop-group">
            <header class="loop-head">
              <span class="loop-title">AGENT LOOP</span>
              <code>{{ shortId(group.loopId) }}</code>
              <UiTag size="sm" :variant="loopVariant(group.calls)">{{ loopStatus(group.calls) }}</UiTag>
              <span>{{ group.calls.length }} 次 HTTP</span>
            </header>
            <button
              v-for="call in group.calls"
              :key="call.call_id"
              class="call-row"
              :class="{ selected: call.call_id === selectedCallId }"
              @click="selectCall(call.call_id)"
            >
              <span class="call-step">
                <span class="state-dot" :class="call.state" />
                <small>#{{ call.loop_sequence }}</small>
              </span>
              <span class="call-main">
                <span class="call-primary">
                  <strong>{{ call.provider_id }}</strong>
                  <span>{{ call.model || call.protocol }}</span>
                </span>
                <code>{{ call.url }}</code>
                <span v-if="call.error_message" class="call-error">{{ call.error_message }}</span>
              </span>
              <span class="call-meta">
                <time>{{ formatTime(call.started_at) }}</time>
                <span>{{ formatStatus(call) }}</span>
                <span>{{ formatDuration(call.duration_ms) }}</span>
                <span>{{ formatBytes(call.request_bytes + (call.response_raw_bytes || call.response_bytes)) }}</span>
              </span>
            </button>
          </article>

          <UiButton
            v-if="nextBeforeId"
            class="load-more"
            size="sm"
            icon="ChevronDown"
            :loading="loadingMore"
            @click="loadMore"
          >加载更早记录</UiButton>
        </section>

        <TraceDetailPanel :detail="detail" :loading="detailLoading" @close="closeDetail" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import TraceDetailPanel from '../components/trace/TraceDetailPanel.vue'
import { clearTraces, fetchTraceStatus, setTraceStatus } from '../api/diagnostics'
import {
  buildTraceStreamUrl,
  fetchTraceCall,
  fetchTraceCalls,
  type TraceCallDetail,
  type TraceCallSummary,
} from '../api/logs'
import { toast } from '../toast'

const PAGE_SIZE = 50
const MAX_LIVE_CALLS = 300

const loading = ref(false)
const loadingMore = ref(false)
const detailLoading = ref(false)
const connected = ref(false)
const traceActive = ref(false)
const traceFlagFile = ref('')
const totalCount = ref(0)
const storageBytes = ref(0)
const latestEventId = ref(0)
const nextBeforeId = ref<number | null>(null)
const calls = ref<TraceCallSummary[]>([])
const detail = ref<TraceCallDetail | null>(null)
const selectedCallId = ref('')
const filter = ref('')
const stateFilter = ref('')
const error = ref('')
let source: EventSource | null = null

const filteredCalls = computed(() => {
  const query = filter.value.trim().toLowerCase()
  return calls.value.filter(call => {
    if (stateFilter.value && call.state !== stateFilter.value) return false
    if (!query) return true
    return `${call.provider_id}\n${call.model}\n${call.protocol}\n${call.url}\n${call.state}`
      .toLowerCase()
      .includes(query)
  })
})

const groupedCalls = computed(() => {
  const groups = new Map<string, TraceCallSummary[]>()
  for (const call of filteredCalls.value) {
    const loopId = call.agent_loop_id || call.call_id
    const group = groups.get(loopId) || []
    group.push(call)
    groups.set(loopId, group)
  }
  return [...groups.entries()].map(([loopId, groupCalls]) => ({
    loopId,
    calls: groupCalls.sort((a, b) => a.loop_sequence - b.loop_sequence),
  }))
})

function upsertCall(call: TraceCallSummary) {
  const index = calls.value.findIndex(item => item.call_id === call.call_id)
  if (index >= 0) calls.value.splice(index, 1, call)
  else {
    calls.value.unshift(call)
    totalCount.value += 1
  }
  calls.value.sort((a, b) => b.id - a.id)
  if (calls.value.length > MAX_LIVE_CALLS) calls.value.length = MAX_LIVE_CALLS
  if (selectedCallId.value === call.call_id && call.state !== 'pending') void selectCall(call.call_id)
}

async function loadStatus() {
  const data = await fetchTraceStatus()
  traceActive.value = !!data.active
  traceFlagFile.value = data.flag_file || ''
  totalCount.value = Number(data.entry_count || 0)
  storageBytes.value = Number(data.storage_bytes || 0)
  latestEventId.value = Number(data.latest_event_id || 0)
}

async function loadCalls() {
  const data = await fetchTraceCalls(PAGE_SIZE)
  calls.value = data.calls || []
  nextBeforeId.value = data.next_before_id ?? null
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    await loadStatus()
    await loadCalls()
    connect()
    if (selectedCallId.value) await selectCall(selectedCallId.value)
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!nextBeforeId.value) return
  loadingMore.value = true
  try {
    const data = await fetchTraceCalls(PAGE_SIZE, nextBeforeId.value)
    const known = new Set(calls.value.map(item => item.call_id))
    calls.value.push(...(data.calls || []).filter((item: TraceCallSummary) => !known.has(item.call_id)))
    nextBeforeId.value = data.next_before_id ?? null
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  } finally {
    loadingMore.value = false
  }
}

async function selectCall(callId: string) {
  selectedCallId.value = callId
  detailLoading.value = true
  try {
    detail.value = await fetchTraceCall(callId)
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  selectedCallId.value = ''
  detail.value = null
}

async function toggleTrace(enabled: boolean) {
  try {
    const data = await setTraceStatus(enabled)
    traceActive.value = !!data.active
    toast(enabled ? 'LLM Trace 已开启' : 'LLM Trace 已关闭')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function clear() {
  if (!confirm('清空全部 LLM HTTP Trace？')) return
  try {
    await clearTraces()
    calls.value = []
    nextBeforeId.value = null
    totalCount.value = 0
    closeDetail()
    toast('LLM Trace 已清空')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

function connect() {
  source?.close()
  source = new EventSource(buildTraceStreamUrl(latestEventId.value))
  source.onopen = () => { connected.value = true }
  source.onerror = () => { connected.value = false }
  source.onmessage = event => {
    if (!event.data) return
    try {
      const call = JSON.parse(event.data) as TraceCallSummary
      latestEventId.value = Math.max(latestEventId.value, Number(call.event_id || event.lastEventId || 0))
      upsertCall(call)
    } catch {
      // EventSource will continue with the next complete event.
    }
  }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function formatStatus(call: TraceCallSummary): string {
  if (call.state === 'pending') return 'PENDING'
  return call.response_status != null ? `HTTP ${call.response_status}` : call.state.toUpperCase()
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(value: number | null): string {
  if (value == null) return '-'
  return value < 1000 ? `${value.toFixed(0)} ms` : `${(value / 1000).toFixed(1)} s`
}

function shortId(value: string): string {
  return value.slice(0, 8)
}

function loopStatus(loopCalls: TraceCallSummary[]): string {
  if (loopCalls.some(call => call.state === 'pending')) return 'RUNNING'
  if (loopCalls.some(call => call.state === 'error') && !loopCalls.some(call => call.state === 'success')) return 'ERROR'
  return 'COMPLETE'
}

function loopVariant(loopCalls: TraceCallSummary[]): string {
  const status = loopStatus(loopCalls)
  return status === 'COMPLETE' ? 'success' : status === 'ERROR' ? 'danger' : 'warn'
}

onMounted(reload)
onBeforeUnmount(() => source?.close())
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: var(--qq-gap-md); min-height: 0; }
.sensitive-notice { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-left: 3px solid var(--qq-accent); background: var(--qq-accent-soft); color: var(--qq-text); font-size: var(--qq-text-sm); }
.trace-shell { min-height: 0; }
.status-row, .toolbar, .trace-switch { display: flex; align-items: center; gap: var(--qq-gap-sm); }
.status-row { flex-wrap: wrap; padding-bottom: var(--qq-gap-sm); border-bottom: 1px solid var(--qq-border); }
.trace-switch { font-weight: 500; }
.status-stat { color: var(--qq-text-muted); font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); }
.toolbar { padding: var(--qq-gap-sm) 0; }
.search { display: flex; align-items: center; flex: 1; min-width: 220px; gap: 6px; padding: 7px 10px; border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); }
.search input { width: 100%; border: 0; outline: 0; background: transparent; color: var(--qq-text); font: inherit; }
.state-filter { min-height: 32px; padding: 0 28px 0 9px; border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); background: var(--qq-surface); color: var(--qq-text); }
.error-banner { margin: 0 0 var(--qq-gap-sm); padding: 8px 10px; background: var(--qq-danger-soft); color: var(--qq-danger); }
.workspace { display: grid; grid-template-columns: minmax(300px, 0.8fr) minmax(0, 1.4fr); min-height: 560px; border-top: 1px solid var(--qq-border); padding-top: var(--qq-gap-md); }
.call-list { min-width: 0; max-height: 72vh; overflow-y: auto; padding-right: var(--qq-gap-md); }
.loop-group { margin-bottom: var(--qq-gap-sm); overflow: hidden; border: 1px solid var(--qq-border); border-left: 3px solid var(--qq-primary); border-radius: var(--qq-radius-sm); }
.loop-head { display: flex; align-items: center; gap: 7px; padding: 6px 9px; border-bottom: 1px solid var(--qq-border); background: var(--qq-surface-strong); color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.loop-head code { color: var(--qq-text-quiet); font-family: var(--qq-font-mono); }
.loop-head > span:last-child { margin-left: auto; }
.loop-title { color: var(--qq-primary); font-weight: 700; letter-spacing: .08em; }
.call-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; width: 100%; min-height: 86px; gap: 9px; padding: 10px 8px; border: 0; border-bottom: 1px solid var(--qq-border); background: transparent; color: var(--qq-text); text-align: left; cursor: pointer; }
.call-row:last-child { border-bottom: 0; }
.call-row:hover, .call-row.selected { background: var(--qq-surface-strong); }
.call-row.selected { box-shadow: inset 2px 0 var(--qq-primary); }
.call-step { display: grid; justify-items: center; align-content: start; gap: 5px; color: var(--qq-text-quiet); font-family: var(--qq-font-mono); }
.state-dot { width: 7px; height: 7px; margin-top: 5px; border-radius: 50%; background: var(--qq-warn); }
.state-dot.success { background: var(--qq-success); }
.state-dot.error { background: var(--qq-danger); }
.call-main { display: grid; min-width: 0; align-content: start; gap: 4px; }
.call-primary { display: flex; align-items: baseline; gap: 7px; }
.call-primary span { overflow: hidden; color: var(--qq-text-muted); font-size: var(--qq-text-xs); text-overflow: ellipsis; white-space: nowrap; }
.call-main code, .call-error { overflow: hidden; font-size: var(--qq-text-xs); text-overflow: ellipsis; white-space: nowrap; }
.call-main code { color: var(--qq-text-quiet); }
.call-error { color: var(--qq-danger); }
.call-meta { display: grid; align-content: start; justify-items: end; gap: 2px; color: var(--qq-text-muted); font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); white-space: nowrap; }
.load-more { width: 100%; margin-top: var(--qq-gap-sm); }
@media (max-width: 900px) { .workspace { grid-template-columns: 1fr; } .call-list { max-height: 48vh; padding: 0 0 var(--qq-gap-md); } }
@media (max-width: 640px) { .toolbar { align-items: stretch; flex-direction: column; } .call-row { grid-template-columns: 34px minmax(0, 1fr); } .call-meta { grid-column: 2; grid-template-columns: repeat(2, max-content); justify-content: space-between; justify-items: start; width: 100%; } }
</style>
