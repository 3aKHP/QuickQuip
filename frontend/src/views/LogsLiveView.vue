<template>
  <div class="page">
    <UiPageHeader title="实时日志" subtitle="只看当前运行日志，避免和 Trace、归档挤在一起">
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="loadCurrent">刷新状态</UiButton>
        <UiButton v-if="currentFile" icon="Download" @click="openDownload">下载当前文件</UiButton>
      </template>
    </UiPageHeader>

    <UiCard padding="md" shadow="sm" class="panel">
      <div class="meta-row">
        <UiTag size="sm" variant="info">{{ currentFileLabel }}</UiTag>
        <UiTag size="sm" :variant="connected ? 'success' : 'warn'">{{ connected ? '已连接' : '连接中断' }}</UiTag>
      </div>

      <div class="toolbar">
        <label class="filter">
          <UiIcon name="Search" :size="14" />
          <input v-model="filter" type="search" placeholder="过滤关键词 / 正则" />
        </label>
        <label class="toggle">
          <input v-model="autoScroll" type="checkbox" />
          <span>自动滚动</span>
        </label>
      </div>

      <div ref="logEl" class="stream-box">
        <div v-if="filteredLines.length" class="stream-lines">
          <div v-for="item in filteredLines" :key="item.id" class="stream-line" :class="classifyLine(item.text)">
            {{ item.text }}
          </div>
        </div>
        <UiEmpty v-else icon="FileText" title="暂无日志内容" />
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
import { buildLogDownloadUrl, buildLogStreamUrl, fetchLogIndex } from '../api/logs'

interface LogLine { id: number; text: string }

const loading = ref(false)
const currentFile = ref('')
const connected = ref(false)
const filter = ref('')
const autoScroll = ref(true)
const lines = ref<LogLine[]>([])
const logEl = ref<HTMLElement | null>(null)
let source: EventSource | null = null
let nextId = 0
let rafId: number | null = null
const pending: string[] = []

const currentFileLabel = computed(() => currentFile.value ? `当前文件：${currentFile.value}` : '当前文件：暂无')

function compileFilter(value: string): RegExp | null {
  const raw = value.trim()
  if (!raw) return null
  try {
    return new RegExp(raw, 'i')
  } catch {
    return null
  }
}

const filteredLines = computed(() => {
  const re = compileFilter(filter.value)
  if (!re) return lines.value
  return lines.value.filter(item => re.test(item.text))
})

function classifyLine(line: string): string {
  if (/\[ERROR\]|\[CRITICAL\]|Exception|Traceback|Error:/.test(line)) return 'lvl-error'
  if (/\[WARNING\]/.test(line)) return 'lvl-warning'
  if (/\[SUCCESS\]/.test(line)) return 'lvl-success'
  if (/\[INFO\]/.test(line)) return 'lvl-info'
  if (/\[DEBUG\]/.test(line)) return 'lvl-debug'
  return ''
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
    currentFile.value = data.current_file || ''
  } catch {
    currentFile.value = ''
  } finally {
    loading.value = false
  }
}

function enqueueLine(line: string) {
  pending.push(line)
  if (rafId == null) {
    rafId = requestAnimationFrame(() => {
      flushPending()
      rafId = null
    })
  }
}

function flushPending() {
  if (!pending.length) return
  for (const text of pending) {
    lines.value.push({ id: nextId++, text })
  }
  if (lines.value.length > 1800) lines.value.splice(0, lines.value.length - 1800)
  pending.length = 0
  if (autoScroll.value) {
    nextTick(() => {
      const el = logEl.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function connect() {
  source?.close()
  source = new EventSource(buildLogStreamUrl(320))
  source.onopen = () => {
    connected.value = true
  }
  source.onerror = () => {
    connected.value = false
  }
  source.onmessage = (event) => {
    if (!event.data) return
    enqueueLine(event.data)
  }
}

onMounted(async () => {
  await loadCurrent()
  connect()
})

onBeforeUnmount(() => {
  source?.close()
  if (rafId != null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
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
  gap: 6px;
}

.stream-line {
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.lvl-error, .lvl-critical { color: #f85149; }
.lvl-warning { color: #d29922; }
.lvl-success { color: #3fb950; }
.lvl-info { color: #79c0ff; }
.lvl-debug { color: #8b949e; }

@media (max-width: 640px) {
  .stream-box {
    min-height: 56vh;
  }
}
</style>
