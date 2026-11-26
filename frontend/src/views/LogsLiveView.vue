<template>
  <div class="page">
    <UiPageHeader title="实时日志" subtitle="查看当前运行日志，支持关键词与正则过滤">
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="loadCurrent">刷新状态</UiButton>
        <UiButton v-if="currentFile" icon="Download" @click="openDownload">下载当前文件</UiButton>
      </template>
    </UiPageHeader>

    <UiCard padding="md" shadow="sm" class="panel">
      <div class="meta-row">
        <UiTag size="sm" variant="info">{{ currentFileLabel }}</UiTag><UiInfoTip text="机器人当前正在写入的日志文件，按日期命名 quickquip_YYYY-MM-DD.log，每天 0 点切换到新文件，仅保留最近 14 天；文件只记录 INFO 及以上级别（DEBUG 不落盘）。" />
        <UiTag size="sm" :variant="connected ? 'success' : 'warn'">{{ connected ? (currentFile ? '已连接' : '已连接，等待日志') : '连接中断' }}</UiTag><UiInfoTip text="实时日志推送通道（SSE）的连接状态；断开后浏览器会自动重连并从断点续传，跨天轮转会自动跟随新的当日文件。" />
        <span class="line-count">{{ filteredLines.length }} / {{ lines.length }} 行</span>
      </div>

      <div class="toolbar">
        <label class="filter" :class="{ 'filter--invalid': regexError }">
          <UiIcon name="Search" :size="14" />
          <input v-model="filter" type="search" :placeholder="useRegex ? '正则过滤（不区分大小写）' : '关键词过滤（不区分大小写）'" />
          <button
            type="button"
            class="regex-toggle"
            :class="{ active: useRegex }"
            :title="useRegex ? '当前为正则模式，点击切回关键词模式' : '点击启用正则模式'"
            :aria-pressed="useRegex"
            @click.prevent="useRegex = !useRegex"
          >.*</button>
        </label>
        <div class="level-pills" role="group" aria-label="日志级别筛选">
          <button
            v-for="lv in LEVELS"
            :key="lv.key"
            type="button"
            class="level-pill"
            :class="[lv.cls, { active: levelFilter === lv.key }]"
            @click="levelFilter = lv.key"
          >
            {{ lv.label }}
            <span v-if="lv.key !== 'all' && levelCounts[lv.key]" class="level-pill__n">{{ levelCounts[lv.key] }}</span>
          </button>
        </div>
        <label class="toggle">
          <input v-model="autoScroll" type="checkbox" @change="autoScroll && jumpToBottom()" />
          <span>自动滚动</span>
        </label>
        <UiButton size="sm" variant="ghost" icon="Trash2" :disabled="!lines.length" @click="clearBuffer">清屏</UiButton>
      </div>
      <p v-if="regexError" class="regex-error">{{ regexError }}</p>

      <div class="stream-wrap">
        <div ref="logEl" class="stream-box" @scroll.passive="onLogScroll">
          <div v-if="filteredLines.length" class="stream-lines">
            <div v-for="item in filteredLines" :key="item.id" class="stream-line" :class="item.cls">
              {{ item.text }}
            </div>
          </div>
          <UiEmpty v-else icon="FileText" title="暂无日志内容" />
        </div>
        <button v-if="!autoScroll && unreadCount > 0" type="button" class="jump-bottom" @click="jumpToBottom">
          <UiIcon name="ArrowDown" :size="14" />
          <span>回到底部（{{ unreadCount }} 条新日志）</span>
        </button>
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
import UiIcon from '../components/ui/UiIcon.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { buildLogDownloadUrl, buildLogStreamUrl, fetchLogIndex } from '../api/logs'

type LevelKey = 'all' | 'error' | 'warning' | 'success' | 'info'
interface LogLine { id: number; text: string; cls: string; level: LevelKey }

const LEVELS: Array<{ key: LevelKey; label: string; cls: string }> = [
  { key: 'all', label: '全部', cls: '' },
  { key: 'error', label: 'ERROR', cls: 'pill-error' },
  { key: 'warning', label: 'WARN', cls: 'pill-warning' },
  { key: 'success', label: 'SUCCESS', cls: 'pill-success' },
  { key: 'info', label: 'INFO', cls: 'pill-info' },
]

const MAX_LINES = 1800
const MAX_PENDING_LINES = 320
const FLUSH_FALLBACK_MS = 250

const loading = ref(false)
const currentFile = ref('')
const connected = ref(false)
const filter = ref('')
const useRegex = ref(false)
const levelFilter = ref<LevelKey>('all')
const autoScroll = ref(true)
const unreadCount = ref(0)
const lines = ref<LogLine[]>([])
const logEl = ref<HTMLElement | null>(null)
let source: EventSource | null = null
let disposed = false
let nextId = 0
let rafId: number | null = null
let fallbackTimerId: number | null = null
const pending: Array<{ text: string; cls: string; level: LevelKey }> = []

const currentFileLabel = computed(() => currentFile.value ? `当前文件：${currentFile.value}` : '当前文件：暂无')

const compiledFilter = computed<{ re: RegExp | null; literal: string; error: string }>(() => {
  const raw = filter.value.trim()
  if (!raw) return { re: null, literal: '', error: '' }
  if (!useRegex.value) return { re: null, literal: raw.toLowerCase(), error: '' }
  try {
    return { re: new RegExp(raw, 'i'), literal: '', error: '' }
  } catch (e: unknown) {
    return { re: null, literal: '', error: `无效正则：${(e as Error).message}` }
  }
})

const regexError = computed(() => compiledFilter.value.error)

const levelCounts = computed<Record<LevelKey, number>>(() => {
  const c: Record<LevelKey, number> = { all: lines.value.length, error: 0, warning: 0, success: 0, info: 0 }
  for (const item of lines.value) {
    if (item.level !== 'all') c[item.level] += 1
  }
  return c
})

const filteredLines = computed(() => {
  const { re, literal } = compiledFilter.value
  const lv = levelFilter.value
  return lines.value.filter(item => {
    if (lv !== 'all' && item.level !== lv) return false
    if (re) return re.test(item.text)
    if (literal) return item.text.toLowerCase().includes(literal)
    return true
  })
})

function classifyLine(line: string): { cls: string; level: LevelKey } {
  if (/\[(?:ERROR|CRITICAL)\]|\|\s*(?:ERROR|CRITICAL)\b|\b(?:ERROR|CRITICAL):|Traceback|Exception:/.test(line)) {
    return { cls: 'lvl-error', level: 'error' }
  }
  if (/\[WARNING\]|\|\s*WARNING\b|\bWARNING:/.test(line)) {
    return { cls: 'lvl-warning', level: 'warning' }
  }
  if (/\[SUCCESS\]|\|\s*SUCCESS\b/.test(line)) {
    return { cls: 'lvl-success', level: 'success' }
  }
  if (/\[INFO\]|\|\s*INFO\b|\bINFO:/.test(line)) {
    return { cls: 'lvl-info', level: 'info' }
  }
  if (/\[DEBUG\]|\|\s*DEBUG\b|\bDEBUG:/.test(line)) {
    return { cls: 'lvl-debug', level: 'all' }
  }
  return { cls: '', level: 'all' }
}

function downloadUrl(name: string): string {
  return buildLogDownloadUrl(name)
}

function openDownload() {
  if (!currentFile.value) return
  window.open(downloadUrl(currentFile.value), '_blank', 'noreferrer')
}

async function loadCurrent() {
  loading.value = true
  try {
    const data = await fetchLogIndex()
    if (!disposed) currentFile.value = data.current_file || ''
  } catch {
    if (!disposed) currentFile.value = ''
  } finally {
    if (!disposed) loading.value = false
  }
}

function onLogScroll() {
  const el = logEl.value
  if (!el) return
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 28
  if (nearBottom) {
    if (!autoScroll.value) autoScroll.value = true
    unreadCount.value = 0
  } else if (autoScroll.value) {
    autoScroll.value = false
  }
}

function jumpToBottom() {
  autoScroll.value = true
  unreadCount.value = 0
  nextTick(() => {
    const el = logEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function clearBuffer() {
  cancelScheduledFlush()
  pending.length = 0
  lines.value = []
  unreadCount.value = 0
}

function enqueueLine(line: string) {
  const { cls, level } = classifyLine(line)
  pending.push({ text: line, cls, level })
  if (pending.length > MAX_PENDING_LINES) pending.splice(0, pending.length - MAX_PENDING_LINES)
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
  const added = pending.length
  for (const entry of pending) {
    lines.value.push({ id: nextId++, text: entry.text, cls: entry.cls, level: entry.level })
  }
  if (lines.value.length > MAX_LINES) lines.value.splice(0, lines.value.length - MAX_LINES)
  pending.length = 0
  if (autoScroll.value) {
    unreadCount.value = 0
    nextTick(() => {
      const el = logEl.value
      if (el) el.scrollTop = el.scrollHeight
    })
  } else {
    unreadCount.value += added
  }
}

function connect() {
  if (disposed) return
  source?.close()
  source = new EventSource(buildLogStreamUrl(MAX_PENDING_LINES))
  source.onopen = () => {
    connected.value = true
  }
  source.onerror = () => {
    connected.value = false
  }
  source.addEventListener('file', (event: MessageEvent) => {
    if (event.data) currentFile.value = String(event.data)
  })
  source.onmessage = (event) => {
    if (!event.data) return
    enqueueLine(event.data)
  }
}

onMounted(async () => {
  await loadCurrent()
  if (!disposed) connect()
})

onBeforeUnmount(() => {
  disposed = true
  source?.close()
  source = null
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
.toggle {
  display: flex;
  align-items: center;
}

.meta-row,
.toolbar {
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.line-count {
  margin-left: auto;
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
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
  flex: 1;
  min-width: min(100%, 260px);
  max-width: 420px;
  padding: 4px 8px 4px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.filter--invalid {
  border-color: var(--qq-danger);
}

.filter input {
  width: 100%;
  min-height: 26px;
  height: 26px;
  padding: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--qq-text);
  font: inherit;
}

.filter input:focus {
  box-shadow: none;
  background: transparent;
}

.regex-toggle {
  padding: 2px 6px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: 11px;
  cursor: pointer;
}

.regex-toggle.active {
  background: var(--qq-primary-soft);
  border-color: var(--qq-primary-border);
  color: var(--qq-primary-ink);
}

.regex-error {
  margin: 0;
  font-size: var(--qq-text-xs);
  color: var(--qq-danger-ink);
}

.level-pills {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.level-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-full);
  background: var(--qq-surface);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--qq-transition-fast), border-color var(--qq-transition-fast), color var(--qq-transition-fast);
}

.level-pill:hover { color: var(--qq-text); border-color: var(--qq-border-strong); }
.level-pill.active { background: var(--qq-primary-soft); border-color: var(--qq-primary-border); color: var(--qq-primary-ink); font-weight: 600; }
.level-pill.pill-error.active { background: var(--qq-danger-soft); border-color: var(--qq-danger-border); color: var(--qq-danger-ink); }
.level-pill.pill-warning.active { background: var(--qq-warn-soft); border-color: var(--qq-warn); color: var(--qq-warn); }
.level-pill.pill-success.active { background: var(--qq-success-soft); border-color: var(--qq-success); color: var(--qq-success-ink); }
.level-pill__n { opacity: 0.8; }

.toggle input {
  margin: 0;
}

.stream-wrap {
  position: relative;
}

.stream-box {
  min-height: 62vh;
  max-height: 75vh;
  overflow-y: auto;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.stream-lines {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.stream-line {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: normal;
  line-height: 1.5;
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.lvl-error, .lvl-critical { color: var(--qq-log-error); }
.lvl-warning { color: var(--qq-log-warn); }
.lvl-success { color: var(--qq-log-success); }
.lvl-info { color: var(--qq-log-info); }
.lvl-debug { color: var(--qq-log-debug); }

.jump-bottom {
  position: absolute;
  right: 16px;
  bottom: 14px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--qq-primary-border);
  border-radius: var(--qq-radius-full);
  background: var(--qq-shell-drawer-bg);
  color: var(--qq-primary-ink);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--qq-shadow-md);
  backdrop-filter: blur(12px);
}

@media (max-width: 640px) {
  /* 收敛移动端整页轻微超高（约 20px）：流区下限略降，首屏内不截断 */
  .stream-box {
    min-height: 52vh;
  }
}
</style>
