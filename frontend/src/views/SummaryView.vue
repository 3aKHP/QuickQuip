<template>
  <div>
    <UiPageHeader title="每日总结" />

    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <label>群组
          <select v-model="groupId" @change="loadList">
            <option value="">-- 选择群 --</option>
            <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
          </select>
        </label>
        <UiButton :loading="loading" icon="RefreshCw" :disabled="!groupId" @click="loadList">刷新</UiButton>
      </div>
    </UiCard>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="!selected" class="summary-list">
      <UiCard
        v-for="s in list"
        :key="s.summary_date"
        padding="md"
        shadow="sm"
        class="summary-item"
      >
        <div class="sum-header">
          <span class="sum-date">{{ s.summary_date }}</span>
          <span class="meta">{{ s.model_used || '—' }} · {{ s.char_count }} 字</span>
          <UiTag v-if="s.published_at" variant="success">已发布</UiTag>
          <UiTag v-else variant="warn">未发布</UiTag>
        </div>
        <div class="sum-actions">
          <UiButton size="sm" icon="BookOpen" @click="open(s.summary_date)">阅读</UiButton>
          <UiButton size="sm" variant="danger" icon="Trash2" @click="del(s.summary_date)">删除</UiButton>
        </div>
      </UiCard>
      <UiEmpty v-if="groupId && !loading && list.length === 0" icon="FileText" title="暂无总结记录" />
    </div>

    <UiCard v-if="selected" padding="lg" shadow="md">
      <div class="sum-detail-header">
        <div class="detail-title">
          <UiIcon name="FileText" :size="20" />
          <strong>{{ groupId }} / {{ selected }}</strong>
        </div>
        <UiButton size="sm" icon="ArrowLeft" @click="closeDetail">返回</UiButton>
      </div>
      <div v-if="detail" class="sum-body markdown-body" v-html="renderedContent" />
      <UiLoading v-else />
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

const groups = ref<string[]>([])
const groupId = ref('')
const list = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const selected = ref<string | null>(null)
const detail = ref<any>(null)

const renderedContent = computed(() => {
  return detail.value ? renderMarkdown(detail.value.content) : ''
})

onMounted(async () => {
  try {
    groups.value = await fetchSummaryGroups()
  } catch (e: unknown) {
    error.value = `加载群组列表失败: ${(e as Error).message}`
  }
})

async function loadList() {
  if (!groupId.value) return
  loading.value = true; error.value = null; selected.value = null; detail.value = null
  try {
    list.value = await fetchSummaries(groupId.value)
  } catch (e: unknown) { error.value = (e as Error).message }
  finally { loading.value = false }
}

async function open(date: string) {
  selected.value = date; detail.value = null
  try {
    detail.value = await fetchSummaryDetail(groupId.value, date)
  } catch (e: unknown) { toast((e as Error).message, 'error'); selected.value = null }
}

async function del(date: string) {
  if (!confirm(`删除 ${groupId.value} / ${date} 的总结？`)) return
  try {
    await deleteSummary(groupId.value, date)
    list.value = list.value.filter(s => s.summary_date !== date)
    if (selected.value === date) closeDetail()
    toast('已删除')
  } catch (e: unknown) { toast((e as Error).message, 'error') }
}

function closeDetail() {
  selected.value = null; detail.value = null
}
</script>

<style scoped>
.error {
  color: var(--qq-danger);
}

.toolbar-card {
  margin-bottom: var(--qq-gap-md);
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

.toolbar-inner select {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-base);
  outline: none;
}

.toolbar-inner select:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.summary-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.summary-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.sum-header {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.sum-date {
  font-weight: 600;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
}

.meta {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}

.sum-actions {
  display: flex;
  gap: var(--qq-gap-xs);
}

.sum-detail-header {
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

.sum-body {
  font-size: var(--qq-text-base);
  line-height: 1.8;
  color: var(--qq-text);
}

/* Markdown rendered content */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin-top: 1.4em;
  margin-bottom: 0.6em;
  font-weight: 600;
  line-height: 1.4;
  color: var(--qq-text);
}

.markdown-body :deep(h1) { font-size: 1.4em; }
.markdown-body :deep(h2) { font-size: 1.25em; }
.markdown-body :deep(h3) { font-size: 1.1em; }

.markdown-body :deep(p) {
  margin-bottom: 0.8em;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin-bottom: 0.8em;
}

.markdown-body :deep(li) {
  margin-bottom: 0.3em;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

.markdown-body :deep(code) {
  padding: 0.15em 0.4em;
  font-size: 0.9em;
  font-family: var(--qq-font-mono);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
}

.markdown-body :deep(pre) {
  padding: var(--qq-gap-md);
  margin-bottom: 0.8em;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-md);
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: none;
  font-size: var(--qq-text-sm);
}

.markdown-body :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.4em 1em;
  border-left: 3px solid var(--qq-accent);
  color: var(--qq-text-muted);
}

.markdown-body :deep(hr) {
  margin: 1.5em 0;
  border: none;
  border-top: 1px solid var(--qq-border);
}

.markdown-body :deep(a) {
  color: var(--qq-accent);
  text-decoration: underline;
}
</style>
