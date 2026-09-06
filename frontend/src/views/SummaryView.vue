<template>
  <div class="sum-view page-view-fill">
    <UiPageHeader title="总结" />

    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <UiTabs :model-value="activeTab" :tabs="tabs" @change="switchTab" />
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

    <p v-if="groupId && !selected && !listLoading" class="pub-legend">「已发布」= 已推送到群聊；「未发布」= 已生成、等待下次调度推送。</p>

    <div v-if="listError" class="error-block">
      <UiIcon name="CircleX" :size="16" />
      <span>{{ listError }}</span>
    </div>

    <UiSkeleton v-if="listLoading && !selected" :rows="5" class="summary-loading" />

    <UiEmpty
      v-if="!groupId && !selected && !listLoading"
      icon="FileText"
      title="选择一个群组查看总结记录"
      description="每日总结、周报与月报按群组归档；从上方群组下拉框开始。"
    />

    <Transition name="tab-pane" mode="out-in">
      <div v-if="!selected && groupId" :key="activeTab" class="summary-list">
        <article
          v-for="item in normalizedList"
          :key="item.key"
          class="summary-row"
        >
          <div class="summary-main">
            <span class="sum-date">{{ item.key }}</span>
            <span class="meta" :title="`${item.model} · ${item.charCount} 字`">
              {{ item.model }} · {{ item.charCount }} 字
            </span>
            <UiTag class="status-tag" :variant="item.published ? 'success' : 'warn'">
              {{ item.published ? '已发布' : '未发布' }}
            </UiTag>
          </div>
          <div class="sum-actions">
            <UiButton size="sm" icon="BookOpen" @click="open(item.key)">阅读</UiButton>
            <UiButton size="sm" variant="danger" icon="Trash2" @click="del(item.key)">删除</UiButton>
          </div>
        </article>

        <UiEmpty v-if="groupId && !listLoading && normalizedList.length === 0" icon="FileText" title="暂无记录" />
      </div>

      <UiCard v-else-if="selected" key="detail" padding="lg" shadow="md" class="detail-card">
      <div class="detail-bar">
        <span class="detail-title">
          <UiIcon name="FileText" :size="20" />
          <strong>{{ groupId }} / {{ selected }}</strong>
        </span>
        <UiButton size="sm" icon="ChevronLeft" @click="closeDetail">返回</UiButton>
      </div>

      <div class="detail-scroll">
        <div v-if="detailLoading" class="detail-loading">
          <UiLoading text="正在读取正文" />
        </div>

        <div v-else-if="detailError" class="error-block">
          <UiIcon name="CircleX" :size="16" />
          <span>{{ detailError }}</span>
        </div>

        <div v-else class="sum-body markdown-body" v-html="renderedContent" />
      </div>
      </UiCard>
    </Transition>
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
import UiTabs from '../components/ui/UiTabs.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'
import { deleteSummary, fetchSummaryDetail, fetchSummaryGroups, fetchSummaries } from '../api/summaries'
import type { SummaryDetailRow, SummaryListRow } from '../api/summaries'
import { deletePeriodReport, fetchPeriodReportDetail, fetchPeriodReportGroups, fetchPeriodReports } from '../api/period_reports'
import { renderMarkdown } from '../composables/useMarkdown'
import { toast } from '../toast'

type Tab = 'daily' | 'weekly' | 'monthly'

function rowKey(row: SummaryListRow): string {
  return 'summary_date' in row ? row.summary_date : row.period_key
}

interface SummaryListItem {
  key: string
  model: string
  charCount: number | string
  published: boolean
}

interface TabConfig {
  fetchGroups: () => Promise<string[]>
  fetchList: (gid: string) => Promise<SummaryListRow[]>
  fetchDetail: (gid: string, key: string) => Promise<SummaryDetailRow>
  remove: (gid: string, key: string) => Promise<unknown>
}

const tabs: { key: Tab; label: string }[] = [
  { key: 'daily', label: '每日' },
  { key: 'weekly', label: '周报' },
  { key: 'monthly', label: '月报' },
]

const tabConfig: Record<Tab, TabConfig> = {
  daily: {
    fetchGroups: () => fetchSummaryGroups(),
    fetchList: (gid) => fetchSummaries(gid),
    fetchDetail: (gid, key) => fetchSummaryDetail(gid, key),
    remove: (gid, key) => deleteSummary(gid, key),
  },
  weekly: {
    fetchGroups: () => fetchPeriodReportGroups('weekly'),
    fetchList: (gid) => fetchPeriodReports(gid, 'weekly'),
    fetchDetail: (gid, key) => fetchPeriodReportDetail(gid, 'weekly', key),
    remove: (gid, key) => deletePeriodReport(gid, 'weekly', key),
  },
  monthly: {
    fetchGroups: () => fetchPeriodReportGroups('monthly'),
    fetchList: (gid) => fetchPeriodReports(gid, 'monthly'),
    fetchDetail: (gid, key) => fetchPeriodReportDetail(gid, 'monthly', key),
    remove: (gid, key) => deletePeriodReport(gid, 'monthly', key),
  },
}

const activeTab = ref<Tab>('daily')
const current = computed(() => tabConfig[activeTab.value])

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
      const key = rowKey(item)
      return {
        key: key || '未知',
        model: item.model_used || '—',
        charCount: item.char_count ?? '—',
        published: Boolean(item.published_at),
      }
    })
    .filter(item => item.key && item.key !== '未知')
})

const renderedContent = computed(() => {
  const content = detail.value?.content || ''
  return content ? renderMarkdown(content) : ''
})

onMounted(() => loadGroups())

function switchTab(t: Tab) {
  if (activeTab.value === t) return
  activeTab.value = t
  selected.value = null
  detail.value = null
  detailError.value = null
  list.value = []
  groupId.value = ''
  loadGroups()
}

async function loadGroups() {
  listError.value = null
  try {
    groups.value = await current.value.fetchGroups()
  } catch (e: unknown) {
    groups.value = []
    listError.value = `加载群组列表失败: ${(e as Error).message}`
    return
  }
  if (!groupId.value && groups.value.length > 0) {
    groupId.value = groups.value[0]
    await loadList()
  }
}

async function loadList() {
  if (!groupId.value) return
  listLoading.value = true
  listError.value = null
  selected.value = null
  detail.value = null
  detailError.value = null
  try {
    const rows = await current.value.fetchList(groupId.value)
    list.value = Array.isArray(rows) ? rows : []
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listLoading.value = false
  }
}

async function open(key: string) {
  selected.value = key
  detail.value = null
  detailError.value = null
  detailLoading.value = true
  try {
    detail.value = await current.value.fetchDetail(groupId.value, key)
  } catch (e: unknown) {
    detailError.value = (e as Error).message
    toast((e as Error).message, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function del(key: string) {
  if (!confirm(`删除 ${groupId.value} / ${key} ？`)) return
  try {
    await current.value.remove(groupId.value, key)
    list.value = list.value.filter(item => rowKey(item) !== key)
    if (selected.value === key) closeDetail()
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

.pub-legend {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.error-block {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: 1px solid var(--qq-danger-border);
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
