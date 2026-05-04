<template>
  <div class="audit-view">
    <UiPageHeader title="审计日志" subtitle="Web 管理后台所有变更操作的审计记录" />

    <UiCard padding="md" shadow="sm" class="audit-filter">
      <div class="filter-row">
        <div class="field">
          <label>操作类型</label>
          <select v-model="filters.action">
            <option value="">全部</option>
            <option value="create">create</option>
            <option value="update">update</option>
            <option value="delete">delete</option>
            <option value="toggle">toggle</option>
          </select>
        </div>
        <div class="field">
          <label>目标类型</label>
          <select v-model="filters.target_type">
            <option value="">全部</option>
            <option value="rule">rule</option>
            <option value="group">group</option>
            <option value="memory">memory</option>
            <option value="persona">persona</option>
            <option value="config">config</option>
            <option value="llm_about">llm_about</option>
            <option value="group_setting">group_setting</option>
          </select>
        </div>
        <div class="field">
          <label>起始日期</label>
          <input v-model="filters.since" type="date" />
        </div>
        <div class="field">
          <label>结束日期</label>
          <input v-model="filters.until" type="date" />
        </div>
        <div class="field field-action">
          <UiButton icon="Search" @click="search">查询</UiButton>
          <UiButton variant="ghost" size="sm" icon="RotateCcw" @click="reset">重置</UiButton>
        </div>
      </div>
    </UiCard>

    <UiCard padding="md" shadow="sm" class="audit-table-card">
      <UiLoading v-if="loading" text="加载审计日志..." />

      <div v-else-if="error" class="error-block">{{ error }}</div>

      <template v-else-if="items.length > 0">
        <div class="table-wrap">
          <table class="audit-table">
            <thead>
              <tr>
                <th class="col-time">时间</th>
                <th class="col-operator">操作者</th>
                <th class="col-action">操作</th>
                <th class="col-target">目标类型</th>
                <th class="col-target-id">目标 ID</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="entry in items" :key="entry.id">
                <tr class="audit-row" @click="toggleExpand(entry.id)">
                  <td class="col-time">{{ entry.timestamp }}</td>
                  <td class="col-operator">{{ entry.operator }}</td>
                  <td class="col-action">
                    <UiTag size="sm" :variant="actionVariant(entry.action)">{{ entry.action }}</UiTag>
                  </td>
                  <td class="col-target">
                    <UiTag size="sm" :variant="targetTypeVariant(entry.target_type)">{{ entry.target_type }}</UiTag>
                  </td>
                  <td class="col-target-id">{{ entry.target_id }}</td>
                </tr>
                <tr v-if="expandedRows.has(entry.id)" class="summary-row">
                  <td colspan="5">
                    <div class="summary-panels">
                      <div v-if="entry.summary_before" class="summary-panel summary-before">
                        <span class="summary-label">变更前</span>
                        <pre class="json-block">{{ prettyJson(entry.summary_before) }}</pre>
                      </div>
                      <div v-if="entry.summary_after" class="summary-panel summary-after">
                        <span class="summary-label">变更后</span>
                        <pre class="json-block">{{ prettyJson(entry.summary_after) }}</pre>
                      </div>
                      <div v-if="!entry.summary_before && !entry.summary_after" class="summary-none">
                        无摘要信息
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div class="pagination">
          <UiButton size="sm" variant="ghost" icon="ChevronLeft" :disabled="page <= 1" @click="goPage(page - 1)" />
          <span class="page-info">第 {{ page }} 页 / 共 {{ totalPages }} 页 ({{ total }} 条)</span>
          <UiButton size="sm" variant="ghost" icon="ChevronRight" :disabled="page >= totalPages" @click="goPage(page + 1)" />
        </div>
      </template>

      <UiEmpty v-else icon="ShieldCheck" title="暂无审计记录" description="当管理后台发生变更操作时，记录会出现在这里。" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive, computed } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchAuditEntries, type AuditEntry, type AuditQueryParams } from '../api/audit'

const loading = ref(true)
const error = ref<string | null>(null)
const items = ref<AuditEntry[]>([])
const total = ref(0)
const page = ref(1)
const limit = 50
const expandedRows = ref(new Set<number>())

const filters = reactive<AuditQueryParams>({
  action: '',
  target_type: '',
  since: '',
  until: '',
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit)))

function actionVariant(action: string): string {
  switch (action) {
    case 'create': return 'success'
    case 'update': return 'info'
    case 'delete': return 'danger'
    case 'toggle': return 'warn'
    default: return 'info'
  }
}

function targetTypeVariant(targetType: string): string {
  switch (targetType) {
    case 'rule': return 'warn'
    case 'group': return 'info'
    case 'memory': return 'success'
    case 'persona': return 'info'
    case 'config': return 'danger'
    case 'llm_about': return 'success'
    case 'group_setting': return 'warn'
    default: return 'info'
  }
}

function prettyJson(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function toggleExpand(id: number) {
  const next = new Set(expandedRows.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expandedRows.value = next
}

async function loadEntries() {
  loading.value = true
  error.value = null
  try {
    const params: AuditQueryParams = {
      page: page.value,
      limit,
    }
    if (filters.action) params.action = filters.action
    if (filters.target_type) params.target_type = filters.target_type
    if (filters.since) params.since = filters.since + 'T00:00:00'
    if (filters.until) params.until = filters.until + 'T23:59:59'

    const data = await fetchAuditEntries(params)
    items.value = data.items
    total.value = data.total
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  expandedRows.value = new Set()
  loadEntries()
}

function reset() {
  filters.action = ''
  filters.target_type = ''
  filters.since = ''
  filters.until = ''
  page.value = 1
  expandedRows.value = new Set()
  loadEntries()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  expandedRows.value = new Set()
  loadEntries()
}

onMounted(() => {
  loadEntries()
})
</script>

<style scoped>
.audit-view {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-lg);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.audit-filter {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.filter-row {
  display: flex;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
  align-items: flex-end;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-weight: 500;
}

.field-action {
  display: flex;
  flex-direction: row;
  gap: var(--qq-gap-xs);
  align-items: flex-end;
}

select, input {
  padding: 6px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
}

.audit-table-card {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.table-wrap {
  overflow-x: auto;
}

.audit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--qq-text-sm);
}

.audit-table thead {
  border-bottom: 2px solid var(--qq-border-strong);
}

.audit-table th {
  padding: var(--qq-gap-sm) var(--qq-gap-sm);
  text-align: left;
  font-weight: 600;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  white-space: nowrap;
}

.audit-table td {
  padding: var(--qq-gap-sm);
  border-bottom: 1px solid var(--qq-border);
  color: var(--qq-text);
}

.col-time {
  white-space: nowrap;
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.col-operator {
  font-family: var(--qq-font-mono);
}

.col-target-id {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-row {
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.audit-row:hover {
  background: var(--qq-surface-strong);
}

.summary-row td {
  padding: 0 var(--qq-gap-sm) var(--qq-gap-sm);
}

.summary-panels {
  display: flex;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.summary-panel {
  flex: 1;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-label {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-weight: 500;
}

.summary-before .summary-label { color: var(--qq-warn); }
.summary-after .summary-label { color: var(--qq-success); }

.json-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-border);
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre;
  color: var(--qq-text-muted);
  max-height: 200px;
  overflow-y: auto;
}

.summary-none {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  padding: var(--qq-gap-sm);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--qq-gap-sm);
  padding-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
}

.page-info {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
}

.error-block {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-danger);
}
</style>
