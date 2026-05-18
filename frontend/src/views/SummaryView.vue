<template>
  <div class="sum-view">
    <UiPageHeader title="每日总结" />

    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <label>
          群组
          <select v-model="groupId" @change="loadList">
            <option value="">-- 选择群 --</option>
            <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
          </select>
        </label>
        <UiButton :loading="listLoading" icon="RefreshCw" :disabled="!groupId" @click="loadList">刷新</UiButton>
      </div>
    </UiCard>

    <div v-if="listError" class="error-block">
      <UiIcon name="CircleX" :size="16" />
      <span>{{ listError }}</span>
    </div>

    <UiLoading v-if="listLoading && !selected" text="正在加载总结记录" class="summary-loading" />

    <div v-else-if="!selected" class="summary-list">
      <article
        v-for="item in normalizedList"
        :key="item.date"
        class="summary-row"
      >
        <div class="summary-main">
          <span class="sum-date">{{ item.date }}</span>
          <span class="meta" :title="`${item.model} · ${item.charCount} 字`">
            {{ item.model }} · {{ item.charCount }} 字
          </span>
          <UiTag class="status-tag" :variant="item.published ? 'success' : 'warn'">
            {{ item.published ? '已发布' : '未发布' }}
          </UiTag>
        </div>
        <div class="sum-actions">
          <UiButton size="sm" icon="BookOpen" @click="open(item.date)">阅读</UiButton>
          <UiButton size="sm" variant="danger" icon="Trash2" @click="del(item.date)">删除</UiButton>
        </div>
      </article>

      <UiEmpty v-if="groupId && !listLoading && normalizedList.length === 0" icon="FileText" title="暂无总结记录" />
    </div>

    <UiCard v-else padding="lg" shadow="md" class="detail-card">
      <div class="detail-bar">
        <span class="detail-title">
          <UiIcon name="FileText" :size="20" />
          <strong>{{ groupId }} / {{ selected }}</strong>
        </span>
        <UiButton size="sm" icon="ChevronLeft" @click="closeDetail">返回</UiButton>
      </div>

      <div class="detail-scroll">
        <div v-if="detailLoading" class="detail-loading">
          <UiLoading text="正在读取总结正文" />
        </div>

        <div v-else-if="detailError" class="error-block">
          <UiIcon name="CircleX" :size="16" />
          <span>{{ detailError }}</span>
        </div>

        <div v-else class="sum-body markdown-body" v-html="renderedContent" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchSummaryGroups, fetchSummaries, fetchSummaryDetail, deleteSummary } from '../api/summaries'
import { renderMarkdown } from '../composables/useMarkdown'
import { toast } from '../toast'

interface SummaryListRow {
  summary_date?: string
  date?: string
  generated_date?: string
  day?: string
  model_used?: string
  model?: string
  char_count?: number | string
  characters?: number | string
  content_length?: number | string
  published_at?: string | null
  published?: boolean
}

interface SummaryDetailRow extends SummaryListRow {
  content?: string
}

interface SummaryListItem {
  date: string
  model: string
  charCount: number | string
  published: boolean
}

const groups = ref<string[]>([])
const groupId = ref('')
const list = ref<SummaryListRow[]>([])
const listLoading = ref(false)
const listError = ref<string | null>(null)
const selected = ref<string | null>(null)
const detail = ref<SummaryDetailRow | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const normalizedList = computed<SummaryListItem[]>(() => {
  return list.value
    .map((item) => {
      const date = item.summary_date || item.date || item.generated_date || item.day || ''
      return {
        date: String(date || '未知日期'),
        model: item.model_used || item.model || '—',
        charCount: item.char_count ?? item.characters ?? item.content_length ?? '—',
        published: Boolean(item.published_at || item.published),
      }
    })
    .filter(item => item.date && item.date !== '未知日期')
})

const renderedContent = computed(() => {
  const content = detail.value?.content || ''
  return content ? renderMarkdown(content) : ''
})

onMounted(async () => {
  try {
    groups.value = await fetchSummaryGroups()
    if (!groupId.value && groups.value.length > 0) {
      groupId.value = groups.value[0]
      await loadList()
    }
  } catch (e: unknown) {
    listError.value = `加载群组列表失败: ${(e as Error).message}`
  }
})

async function loadList() {
  if (!groupId.value) return
  listLoading.value = true
  listError.value = null
  selected.value = null
  detail.value = null
  detailError.value = null
  try {
    const rows = await fetchSummaries(groupId.value)
    list.value = Array.isArray(rows) ? rows : []
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listLoading.value = false
  }
}

async function open(date: string) {
  selected.value = date
  detail.value = null
  detailError.value = null
  detailLoading.value = true
  try {
    detail.value = await fetchSummaryDetail(groupId.value, date)
  } catch (e: unknown) {
    detailError.value = (e as Error).message
    toast((e as Error).message, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function del(date: string) {
  if (!confirm(`删除 ${groupId.value} / ${date} 的总结？`)) return
  try {
    await deleteSummary(groupId.value, date)
    list.value = list.value.filter(item => (item.summary_date || item.date || item.generated_date || item.day) !== date)
    if (selected.value === date) closeDetail()
    toast('已删除')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

function closeDetail() {
  selected.value = null
  detail.value = null
  detailError.value = null
  detailLoading.value = false
}
</script>

<style scoped>
.sum-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: var(--qq-gap-md);
}

.toolbar-card {
  flex: 0 0 auto;
  overflow: visible;
  position: relative;
  z-index: 1;
}

.toolbar-inner {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.toolbar-inner label {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.summary-loading {
  width: min(100%, 420px);
}

.summary-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-top: 2px;
  padding-bottom: var(--qq-gap-md);
}

.summary-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--qq-gap-md);
  min-height: 64px;
  padding: 14px 16px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
  overflow: visible;
}

.summary-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.sum-date {
  flex: 0 0 auto;
  font-weight: 600;
  color: var(--qq-text);
  font-size: var(--qq-text-md);
  line-height: 1.35;
}

.meta {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  line-height: 1.35;
}

.status-tag {
  flex: 0 0 auto;
}

.sum-actions {
  display: flex;
  gap: var(--qq-gap-xs);
  justify-content: flex-end;
  flex: 0 0 auto;
}

@media (max-width: 767px) {
  .summary-row {
    grid-template-columns: 1fr;
    align-items: stretch;
    min-height: auto;
    padding: var(--qq-gap-md);
  }

  .summary-main {
    flex-wrap: wrap;
  }

  .sum-actions {
    justify-content: flex-start;
    padding-top: var(--qq-gap-sm);
    border-top: 1px solid var(--qq-border);
  }
}

.detail-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.detail-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--qq-gap-md);
  flex-wrap: wrap;
  gap: var(--qq-gap-sm);
}

.detail-title {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  font-size: var(--qq-text-md);
  color: var(--qq-text);
}

.detail-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: var(--qq-gap-sm);
}

.detail-loading {
  padding: var(--qq-gap-md) 0;
}

.error-block {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: 1px solid rgba(250, 81, 81, 0.25);
  border-radius: var(--qq-radius-card);
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.sum-body {
  font-size: var(--qq-text-base);
  line-height: 1.8;
  color: var(--qq-text);
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin-top: 1.4em;
  margin-bottom: 0.6em;
  font-weight: 600;
}

.markdown-body :deep(h1) {
  font-size: 1.4em;
}

.markdown-body :deep(h2) {
  font-size: 1.25em;
}

.markdown-body :deep(p) {
  margin-bottom: 0.8em;
}

.markdown-body :deep(code) {
  padding: 0.15em 0.4em;
  font-family: var(--qq-font-mono);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
}

.markdown-body :deep(pre) {
  padding: var(--qq-gap-md);
  margin-bottom: 0.8em;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-card);
  overflow-x: auto;
}

.markdown-body :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.4em 1em;
  border-left: 3px solid var(--qq-primary);
  color: var(--qq-text-muted);
}

.markdown-body :deep(a) {
  color: var(--qq-primary);
}
</style>
