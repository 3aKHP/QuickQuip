<template>
  <div class="page">
    <UiPageHeader title="日志归档" subtitle="浏览、预览与下载已轮转的历史日志文件">
      <template #subtitle><UiInfoTip text="日志按天轮转：每天 0 点切换到新的 quickquip_YYYY-MM-DD.log，仅保留最近 14 天，过期文件自动删除。" /></template>
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="loadFiles">刷新归档</UiButton>
      </template>
    </UiPageHeader>

    <UiCard padding="md" shadow="sm" class="panel">
      <div class="archive-grid">
        <div class="archive-list">
          <button
            v-for="file in files"
            :key="file.name"
            class="archive-item qq-selectable"
            :class="{ active: file.name === selectedFile }"
            @click="selectFile(file.name)"
          >
            <div class="archive-item-head">
              <span class="archive-name">{{ file.name }}</span>
              <UiTag v-if="file.is_current" size="sm" variant="success">当前</UiTag><UiInfoTip v-if="file.is_current" text="该文件是机器人当前正在写入的当日日志，内容仍在持续增长，刷新可看到更新。" />
            </div>
            <div class="archive-meta">
              <span>{{ formatBytes(file.size) }}</span>
              <span>{{ formatTime(file.mtime) }}</span>
            </div>
            <div class="archive-actions">
              <a class="download-link" :href="downloadUrl(file.name)" target="_blank" rel="noreferrer" @click.stop>下载</a>
            </div>
          </button>
          <UiEmpty v-if="!loading && !files.length" icon="FolderOpen" title="暂无日志归档" />
        </div>

        <div class="archive-preview">
          <p v-if="loadError" class="error-note">{{ loadError }}</p>
          <UiLoading v-if="previewLoading" text="正在读取日志尾部" />
          <UiEmpty v-else-if="!selectedFile" icon="FolderOpen" :title="files.length ? '选择一个日志文件查看预览' : '暂无日志归档'" />
          <template v-else>
            <div class="preview-head">
              <span class="preview-title">{{ selectedFile }}</span>
              <div class="preview-tools">
                <input v-model="previewFilter" type="search" class="preview-filter" placeholder="过滤预览行…" aria-label="过滤预览行" />
                <UiTag size="sm">{{ filteredPreview.length }} / {{ previewLines.length }} 行</UiTag>
                <UiInfoTip :text="`预览只显示该文件末尾的 ${PREVIEW_TAIL_LINES} 行；查看完整内容请使用「下载」。`" />
              </div>
            </div>
            <p v-if="previewError" class="error-note">{{ previewError }}</p>
            <div v-else class="preview-block">
              <div v-for="(line, i) in filteredPreview" :key="i" class="preview-line" :class="line.cls">{{ line.text }}</div>
              <UiEmpty v-if="!filteredPreview.length" icon="Search" title="无匹配日志行" />
            </div>
          </template>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { buildLogDownloadUrl, fetchLogIndex, fetchLogTail } from '../api/logs'

interface LogFileItem {
  name: string
  size: number
  mtime: number
  is_current: boolean
}

const loading = ref(false)
const previewLoading = ref(false)
const loadError = ref('')
const previewError = ref('')
const files = ref<LogFileItem[]>([])
const selectedFile = ref('')
const previewLines = ref<string[]>([])
const previewFilter = ref('')
let previewSeq = 0

function classifyLine(line: string): string {
  if (/\[(?:ERROR|CRITICAL)\]|\|\s*(?:ERROR|CRITICAL)\b|\b(?:ERROR|CRITICAL):|Traceback|Exception:/.test(line)) return 'lvl-error'
  if (/\[WARNING\]|\|\s*WARNING\b|\bWARNING:/.test(line)) return 'lvl-warning'
  if (/\[SUCCESS\]|\|\s*SUCCESS\b/.test(line)) return 'lvl-success'
  if (/\[INFO\]|\|\s*INFO\b|\bINFO:/.test(line)) return 'lvl-info'
  if (/\[DEBUG\]|\|\s*DEBUG\b|\bDEBUG:/.test(line)) return 'lvl-debug'
  return ''
}

const classifiedLines = computed(() => previewLines.value.map(text => ({ text, cls: classifyLine(text) })))
const filteredPreview = computed(() => {
  const q = previewFilter.value.trim().toLowerCase()
  if (!q) return classifiedLines.value
  return classifiedLines.value.filter(item => item.text.toLowerCase().includes(q))
})

function formatTime(ts: number): string {
  if (!ts) return ''
  const date = new Date(ts * 1000)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatBytes(size: number): string {
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function downloadUrl(name: string): string {
  return buildLogDownloadUrl(name)
}

/** 预览尾读行数：说明文案与请求共用同一取值 */
const PREVIEW_TAIL_LINES = 240

async function loadPreview(name: string) {
  if (!name) return
  const seq = ++previewSeq
  previewLoading.value = true
  previewError.value = ''
  try {
    const data = await fetchLogTail(name, PREVIEW_TAIL_LINES)
    if (seq !== previewSeq) return
    previewLines.value = data.lines || []
  } catch (e: unknown) {
    if (seq !== previewSeq) return
    previewLines.value = []
    previewError.value = `读取日志失败：${(e as Error).message}`
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

async function loadFiles() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchLogIndex()
    files.value = data.files || []
    if (!selectedFile.value || !files.value.some(file => file.name === selectedFile.value)) {
      selectedFile.value = data.current_file || files.value[0]?.name || ''
    }
    if (selectedFile.value) {
      await loadPreview(selectedFile.value)
    } else {
      previewLines.value = []
    }
  } catch (e: unknown) {
    loadError.value = `加载日志归档列表失败：${(e as Error).message}`
  } finally {
    loading.value = false
  }
}

async function selectFile(name: string) {
  if (!name || name === selectedFile.value) return
  selectedFile.value = name
  await loadPreview(name)
}

onMounted(() => {
  loadFiles()
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
  min-width: 0;
  background: linear-gradient(180deg, var(--qq-surface), var(--qq-surface-elevated));
}

.archive-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.42fr) minmax(0, 1fr);
  gap: var(--qq-gap-md);
  min-height: 0;
}

.archive-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.archive-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  text-align: left;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
  color: var(--qq-text);
  cursor: pointer;
}


.archive-item-head,
.archive-meta,
.preview-head {
  display: flex;
  align-items: center;
}

.archive-item-head,
.preview-head {
  gap: var(--qq-gap-sm);
}

.archive-name,
.preview-title {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text);
}

.archive-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-meta {
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.archive-actions {
  display: flex;
  justify-content: flex-end;
}

.download-link {
  color: var(--qq-primary);
  text-decoration: none;
  font-size: var(--qq-text-xs);
}

.archive-preview {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.preview-head {
  justify-content: space-between;
  flex-wrap: wrap;
}

.preview-tools {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
}

.preview-filter {
  min-height: 28px;
  height: 28px;
  padding: 2px 8px;
  font-size: var(--qq-text-xs);
  width: 170px;
}

.error-note {
  margin: 0;
  color: var(--qq-danger-ink);
  font-size: var(--qq-text-xs);
}

.preview-block {
  min-height: 62vh;
  max-height: 75vh;
  margin: 0;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.preview-line {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: normal;
}

.lvl-error { color: var(--qq-log-error); }
.lvl-warning { color: var(--qq-log-warn); }
.lvl-success { color: var(--qq-log-success); }
.lvl-info { color: var(--qq-log-info); }
.lvl-debug { color: var(--qq-log-debug); }

@media (max-width: 1100px) {
  .archive-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .preview-block {
    min-height: 56vh;
  }
}
</style>
