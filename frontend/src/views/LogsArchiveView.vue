<template>
  <div class="page">
    <UiPageHeader title="日志归档" subtitle="专门看历史轮转文件，不和实时流挤在同一屏">
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
            class="archive-item"
            :class="{ active: file.name === selectedFile }"
            @click="selectFile(file.name)"
          >
            <div class="archive-item-head">
              <span class="archive-name">{{ file.name }}</span>
              <UiTag v-if="file.is_current" size="sm" variant="success">当前</UiTag>
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
          <UiLoading v-if="previewLoading" text="正在读取日志尾部" />
          <UiEmpty v-else-if="!selectedFile" icon="FolderOpen" title="从左侧选择一个日志文件" />
          <template v-else>
            <div class="preview-head">
              <span class="preview-title">{{ selectedFile }}</span>
              <UiTag size="sm">{{ previewLines.length }} 行</UiTag>
            </div>
            <pre class="preview-block">{{ previewLines.join('\n') }}</pre>
          </template>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import { buildLogDownloadUrl, fetchLogIndex, fetchLogTail } from '../api/logs'

interface LogFileItem {
  name: string
  size: number
  mtime: number
  is_current: boolean
}

const loading = ref(false)
const previewLoading = ref(false)
const files = ref<LogFileItem[]>([])
const selectedFile = ref('')
const previewLines = ref<string[]>([])

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

async function loadPreview(name: string) {
  if (!name) return
  previewLoading.value = true
  try {
    const data = await fetchLogTail(name, 240)
    previewLines.value = data.lines || []
  } catch {
    previewLines.value = []
  } finally {
    previewLoading.value = false
  }
}

async function loadFiles() {
  loading.value = true
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
  } catch {
    files.value = []
    selectedFile.value = ''
    previewLines.value = []
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

.archive-item.active {
  border-color: var(--qq-primary-border);
  background: var(--qq-primary-soft);
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

.preview-block {
  min-height: 62vh;
  max-height: 75vh;
  margin: 0;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

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
