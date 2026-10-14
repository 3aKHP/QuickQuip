<template>
  <div class="exchange-panel">
    <UiCard padding="lg">
      <h3 class="exchange-panel__title">导出配置</h3>
      <p class="muted">导出为 JSON 文件，可用于备份或迁移到另一套环境。</p>
      <div class="exchange-panel__row">
        <select v-model="exportSource" aria-label="选择导出版本">
          <option value="draft">服务器草稿（{{ store.draftLabel.value }}）</option>
          <option value="published">已发布快照（{{ store.publishedLabel.value }}）</option>
          <option v-for="snapshot in store.history.value" :key="snapshot.revision" :value="String(snapshot.revision)">历史快照 · {{ store.versionLabel(snapshot.revision) }}</option>
        </select>
        <UiButton icon="Download" :disabled="store.busy.value" @click="download">导出 JSON</UiButton>
        <UiButton variant="ghost" :disabled="!store.document.value" @click="downloadLocal">导出当前编辑（含未保存修改）</UiButton>
      </div>
    </UiCard>

    <UiCard padding="lg">
      <h3 class="exchange-panel__title">导入配置</h3>
      <p class="muted">导入会<strong>整体替换服务器草稿</strong>（不影响正在运行的配置），校验通过后才能提交。密钥只接受 ${变量名} 引用。</p>
      <div class="exchange-panel__row">
        <label class="file-picker">
          <UiIcon name="FolderOpen" :size="14" />
          选择 JSON 文件（不超过 1 MiB）
          <input type="file" accept="application/json,.json" :disabled="store.busy.value" @change="readFile" />
        </label>
      </div>
      <textarea
        v-model="importText"
        rows="10"
        spellcheck="false"
        placeholder='粘贴配置 JSON，例如 { "format_version": 2, ... }'
        :disabled="store.busy.value"
        @input="preview = null"
      />
      <div class="exchange-panel__row">
        <UiButton :loading="previewing" :disabled="store.busy.value || previewing || !importText.trim() || store.conflict.value" @click="doPreview">校验并预览</UiButton>
        <UiButton variant="primary" :disabled="store.busy.value || previewing || !preview?.valid || store.conflict.value" @click="doCommit">确认导入为草稿</UiButton>
      </div>

      <div v-if="preview" class="preview" :class="{ 'preview--invalid': !preview.valid }">
        <h4>{{ preview.valid ? '校验通过' : '校验未通过' }}</h4>
        <p class="muted">与当前草稿 {{ store.draftLabel.value }} 相比有 {{ preview.changes.length }} 处变更</p>
        <div v-if="preview.warnings.length" class="preview__warnings">
          <p v-for="(warning, index) in preview.warnings" :key="index" class="warn-text">{{ configWarningText(warning) }}</p>
        </div>
        <div v-if="preview.changes.length" class="preview__changes">
          <details v-for="item in summarizedChanges" :key="item.raw.field_path">
            <summary>{{ item.summary.title }}<span v-if="item.summary.lines.length">（{{ item.summary.lines.length }} 项）</span></summary>
            <ul v-if="item.summary.lines.length" class="preview__lines">
              <li v-for="(line, i) in item.summary.lines" :key="i">{{ line }}</li>
            </ul>
            <pre>当前草稿：{{ compact(item.raw.before) }}
导入值：{{ compact(item.raw.after) }}</pre>
            <details v-if="isTruncated(item.raw.before) || isTruncated(item.raw.after)" class="full-json">
              <summary>查看完整 JSON</summary>
              <pre>当前草稿：{{ fullJson(item.raw.before) }}

导入值：{{ fullJson(item.raw.after) }}</pre>
            </details>
          </details>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiIcon from '../ui/UiIcon.vue'
import * as api from '../../api/llmConfiguration'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { toast } from '../../toast'
import { configWarningText, describeChange, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const exportSource = ref('draft')
const importText = ref('')
// shallowRef：ImportPreview 内含递归 JsonObject，避免响应式深展开的性能与类型开销
const preview = shallowRef<api.ImportPreview | null>(null)
const previewing = ref(false)

watch(importText, () => { preview.value = null; previewing.value = false })
watch(() => store.revision.value, () => { preview.value = null })

/** 预览变更的人话摘要（与发布面板同一套 describeChange） */
const summarizedChanges = computed(() => (preview.value?.changes ?? []).map(change => {
  return { raw: change, summary: describeChange(change.field_path, change.before, change.after) }
}))

function downloadObject(value: JsonObject, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' }))
  const link = window.document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

async function download() {
  try { downloadObject(await api.exportLlmConfiguration(exportSource.value), `llm-${exportSource.value}.json`) }
  catch (cause: unknown) { toast((cause as Error).message, 'error') }
}

function downloadLocal() {
  if (store.document.value) {
    const stamp = new Date().toISOString().slice(0, 16).replace('T', '-').replace(':', '')
    downloadObject(store.document.value, `llm-local-edit-${stamp}.json`)
  }
}

async function readFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  preview.value = null
  try {
    if (!file) return
    if (file.size > 1024 * 1024) throw new Error('配置文件超过 1 MiB')
    importText.value = await file.text()
  } catch (cause: unknown) {
    toast((cause as Error).message, 'error')
  } finally {
    input.value = ''
  }
}

/** 预览结果只与发起时的输入绑定：输入或草稿基准变化后，迟到响应直接丢弃 */
async function doPreview() {
  const text = importText.value
  preview.value = null
  previewing.value = true
  try {
    const result = await store.previewImportText(text)
    if (importText.value !== text) return
    preview.value = result
  } finally {
    if (importText.value === text) previewing.value = false
  }
}

async function doCommit() {
  const current = preview.value
  if (!current) return
  if (current.expected_draft_revision !== store.revision.value) {
    toast('草稿基准已变化，请重新校验并预览', 'error')
    preview.value = null
    return
  }
  if (store.dirty.value && !confirm('导入会替换服务器草稿，并覆盖当前未保存修改。是否继续？')) return
  if (await store.commitImport(current)) {
    importText.value = ''
    preview.value = null
    toast('已导入为新草稿，需要单独应用')
  }
}


const JSON_PREVIEW_LIMIT = 200

function compact(value: JsonValue): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (text === undefined) return '（空）'
  return text.length > JSON_PREVIEW_LIMIT ? `${text.slice(0, JSON_PREVIEW_LIMIT)}…` : text
}

function isTruncated(value: JsonValue): boolean {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return (text ?? '').length > JSON_PREVIEW_LIMIT
}

function fullJson(value: JsonValue): string {
  return JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.exchange-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.exchange-panel__title {
  margin: 0 0 var(--qq-gap-xs);
  font-size: var(--qq-text-md);
}

.muted {
  margin: 0 0 var(--qq-gap-sm);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
}

.exchange-panel__row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: var(--qq-gap-sm);
}

.exchange-panel select {
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}

.file-picker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px dashed var(--qq-border-strong);
  border-radius: var(--qq-radius-md);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  cursor: pointer;
}

.file-picker:hover {
  border-color: var(--qq-primary-border);
  color: var(--qq-primary);
}

.file-picker input {
  display: none;
}

textarea {
  width: 100%;
  margin-bottom: var(--qq-gap-sm);
  padding: 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.6;
  resize: vertical;
}

.preview {
  border: 1px solid var(--qq-success);
  border-radius: var(--qq-radius-md);
  padding: 12px;
  display: grid;
  gap: 8px;
}

.preview--invalid {
  border-color: var(--qq-danger);
}

.preview h4 {
  margin: 0;
  font-size: var(--qq-text-sm);
}

.preview__changes {
  display: grid;
  gap: 4px;
  max-height: 300px;
  overflow-y: auto;
}

.preview__changes details {
  border: 1px solid var(--qq-border-soft);
  border-radius: var(--qq-radius-sm);
  padding: 6px 10px;
}

.preview__changes summary {
  cursor: pointer;
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
}

.preview__changes pre {
  font-size: var(--qq-text-xs);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  color: var(--qq-text-muted);
}

.preview__lines {
  margin: 6px 0;
  padding-left: 18px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
}

.full-json {
  margin-top: 6px;
}

.full-json summary {
  cursor: pointer;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.full-json pre {
  overflow: auto;
  max-height: 360px;
  white-space: pre-wrap;
}

.warn-text {
  margin: 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
}
</style>
