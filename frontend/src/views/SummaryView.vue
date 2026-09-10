<template>
  <div class="sum-view page-view-fill">
    <UiPageHeader title="总结" />

    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <UiTabs :model-value="activeTab" :tabs="tabs" @change="switchTab" />
        <UiInfoTip text="周报键为 ISO 周（如 2026-W24，周一起算），月报键为年月（如 2026-06）；内容均为上一个完整周期（上周/上月），由 llm.toml 的 [weekly_report]/[monthly_report] 定时生成。" />
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

    <UiCard v-if="health" padding="md" shadow="sm" class="health-card">
      <div class="health-head">
        <strong>生成健康度<UiInfoTip text="汇总日报、简报、周月报三条生成链路近期的 LLM 调用结果：正文是否被采纳、异常分布、耗时与按模型定价估算的美元成本；未记录结果的历史调用计入「历史未知」。" /></strong>
        <label class="health-days">
          近
          <select v-model.number="healthDays" @change="loadHealth">
            <option :value="7">7</option>
            <option :value="30">30</option>
          </select>
          天
        </label>
        <UiButton size="sm" icon="RefreshCw" :loading="healthLoading" @click="loadHealth">刷新</UiButton>
      </div>
      <table v-if="healthRows.length" class="health-table">
        <thead><tr><th>链路<UiInfoTip text="三条生成链路：日报 = 每日群聊总结；简报 = 早/午/晚播报（llm.toml [daily_briefing]，直接发群、不在下方归档列表）；周月报 = 周报与月报共用同一链路统计。" /></th><th>调用</th><th>接受<UiInfoTip text="该跳响应被采纳的判定：正文非空且模型正常结束（finish_reason 为 stop/end_turn/stop_sequence/eos 之一）；级联中未被采纳才会尝试下一跳。" /></th><th>异常<UiInfoTip text="各异常标签含义：完成原因异常 = 模型非正常结束（截断/内容过滤等），正文被丢弃；空响应 = 模型返回空文本；调用失败 = 服务商报错；已取消 = 请求中途被取消；历史未知 = 旧版本未记录该次结果。" /></th><th>均耗时</th><th>成本</th></tr></thead>
        <tbody>
          <tr v-for="row in healthRows" :key="row.feature">
            <td>{{ featureLabel(row.feature) }}</td>
            <td>{{ row.calls }}</td>
            <td><span class="health-accept">{{ row.accepted }} · {{ acceptPct(row) }}%</span></td>
            <td class="health-issues">
              <template v-if="row.issues.length">
                <UiTag v-for="issue in row.issues" :key="issue.outcome" size="sm" :variant="issueVariant(issue.outcome)">{{ outcomeLabel(issue.outcome) }} ×{{ issue.calls }}</UiTag>
              </template>
              <span v-else class="health-none">—</span>
            </td>
            <td>{{ Math.round(row.avgDurationMs / 1000) }}s</td>
            <td>${{ row.cost.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="healthRows.length" class="health-empty">按级联尝试统计，一次报文生成可能包含多跳；成本含被丢弃正文的调用。每跳明细见报文详情的「生成日志」。</p>
      <p v-else class="health-empty">近 {{ health.days }} 天无总结族调用记录。</p>
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

        <details v-if="detail && !detailLoading && !detailError" class="genlog" @toggle="onGenLogToggle">
          <summary>生成日志<UiInfoTip text="记录这份报文生成时经历的每一跳模型调用：按级联配置依次尝试，前一跳未被采纳（空响应/异常结束/调用失败）才走下一跳，「被采纳」的一跳即为正文来源。" /></summary>
          <UiLoading v-if="genLogLoading" text="正在读取生成日志" />
          <div v-else-if="genLogError" class="error-block">
            <UiIcon name="CircleX" :size="16" />
            <span>{{ genLogError }}</span>
          </div>
          <template v-else-if="genLog">
            <p v-if="!genLog.hops.length" class="health-empty">没有可归因的调用记录（手动触发未入库的生成、或用量记录已过保留期的不在此列）。</p>
            <template v-else>
              <ol class="genlog-list">
                <li v-for="(hop, i) in genLog.hops" :key="i" class="genlog-hop">
                  <div class="genlog-hop__main">
                    <span class="mono genlog-seq">#{{ i + 1 }}</span>
                    <span class="genlog-time">{{ hopTime(hop.ts) }}</span>
                    <span class="mono genlog-model">{{ hop.provider_id }}/{{ hop.model }}</span>
                    <UiTag size="sm" :variant="hopVariant(hop)">{{ hopLabel(hop) }}</UiTag>
                  </div>
                  <div class="genlog-hop__meta mono">{{ hopMeta(hop) }}<UiInfoTip text="finish 是模型上报的结束原因：stop/end_turn 等为正常结束；其他值（如 max_tokens、内容过滤）会导致该跳正文被判「完成原因异常」而丢弃；「未上报」表示服务商未返回该字段。" /></div>
                  <div v-if="hop.error_message" class="genlog-hop__error">{{ hop.error_message }}</div>
                </li>
              </ol>
              <p class="genlog-foot">
                共 {{ genLog.hops.length }} 跳 · 合计 {{ totalHopSeconds }}s · ${{ totalHopCost }} ·
                {{ genLog.attribution === 'run_id' ? '精确归因' : '按时间窗推算（历史报文）' }}
                <UiInfoTip text="精确归因 = 按生成时写入的 run_id 精确匹配本次调用；历史报文无 run_id，按「上一条同群同类报文之后、本报文之前、最长 6 小时」的时间窗推算，窗口内手动触发的调用可能被并入。" />
              </p>
            </template>
          </template>
        </details>
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
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'
import { deleteSummary, fetchSummariesHealth, fetchSummaryDetail, fetchSummaryGenerationLog, fetchSummaryGroups, fetchSummaries } from '../api/summaries'
import type { GenerationHop, GenerationLog, SummariesHealth } from '../api/summaries'
import type { SummaryDetailRow, SummaryListRow } from '../api/summaries'
import { deletePeriodReport, fetchPeriodReportDetail, fetchPeriodReportGenerationLog, fetchPeriodReportGroups, fetchPeriodReports } from '../api/period_reports'
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
  fetchGenerationLog: (gid: string, key: string) => Promise<GenerationLog>
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
    fetchGenerationLog: (gid, key) => fetchSummaryGenerationLog(gid, key),
    remove: (gid, key) => deleteSummary(gid, key),
  },
  weekly: {
    fetchGroups: () => fetchPeriodReportGroups('weekly'),
    fetchList: (gid) => fetchPeriodReports(gid, 'weekly'),
    fetchDetail: (gid, key) => fetchPeriodReportDetail(gid, 'weekly', key),
    fetchGenerationLog: (gid, key) => fetchPeriodReportGenerationLog(gid, 'weekly', key),
    remove: (gid, key) => deletePeriodReport(gid, 'weekly', key),
  },
  monthly: {
    fetchGroups: () => fetchPeriodReportGroups('monthly'),
    fetchList: (gid) => fetchPeriodReports(gid, 'monthly'),
    fetchDetail: (gid, key) => fetchPeriodReportDetail(gid, 'monthly', key),
    fetchGenerationLog: (gid, key) => fetchPeriodReportGenerationLog(gid, 'monthly', key),
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

onMounted(() => {
  loadGroups()
  loadHealth()
})

const health = ref<SummariesHealth | null>(null)
const healthLoading = ref(false)
const healthDays = ref(7)

const featureLabels: Record<string, string> = {
  summary: '日报',
  briefing: '简报',
  period_report: '周月报',
}

function featureLabel(feature: string): string {
  return featureLabels[feature] ?? feature
}

const outcomeLabels: Record<string, string> = {
  accepted: '已接受正文',
  discarded_finish: '完成原因异常',
  discarded_empty: '空响应',
  provider_error: '调用失败',
  cancelled: '已取消',
  unknown: '历史未知',
}

function outcomeLabel(outcome: string): string {
  return outcomeLabels[outcome] ?? outcome
}

type TagVariant = 'info' | 'success' | 'warn' | 'danger'

function issueVariant(outcome: string): TagVariant {
  return ['unknown', 'cancelled'].includes(outcome) ? 'warn' : 'danger'
}

interface HealthRow {
  feature: string
  calls: number
  accepted: number
  cost: number
  avgDurationMs: number
  issues: { outcome: string; calls: number }[]
}

const FEATURE_ORDER = ['summary', 'briefing', 'period_report']

/** 把 feature × outcome 的桶聚合成每个链路一行（前端聚合，后端契约不变） */
const healthRows = computed<HealthRow[]>(() => {
  const rows = health.value?.features ?? []
  const byFeature = new Map<string, HealthRow>()
  for (const r of rows) {
    let agg = byFeature.get(r.feature)
    if (!agg) {
      agg = { feature: r.feature, calls: 0, accepted: 0, cost: 0, avgDurationMs: 0, issues: [] }
      byFeature.set(r.feature, agg)
    }
    agg.calls += r.calls
    agg.cost += Number(r.cost_usd ?? 0)
    agg.avgDurationMs += Number(r.avg_duration_ms ?? 0) * r.calls
    if (r.outcome === 'accepted') agg.accepted += r.calls
    else agg.issues.push({ outcome: r.outcome, calls: r.calls })
  }
  const result = [...byFeature.values()]
  for (const agg of result) agg.avgDurationMs = agg.calls ? agg.avgDurationMs / agg.calls : 0
  result.sort((a, b) => {
    const rank = (f: string) => (FEATURE_ORDER.includes(f) ? FEATURE_ORDER.indexOf(f) : 99)
    return rank(a.feature) - rank(b.feature)
  })
  return result
})

function acceptPct(row: HealthRow): number {
  return row.calls ? Math.round((row.accepted / row.calls) * 100) : 0
}

// ── 生成日志（报文详情内懒加载） ──

const genLog = ref<GenerationLog | null>(null)
const genLogLoading = ref(false)
const genLogError = ref<string | null>(null)

function resetGenLog() {
  genLog.value = null
  genLogLoading.value = false
  genLogError.value = null
}

function onGenLogToggle(event: Event) {
  const el = event.target as HTMLDetailsElement
  if (!el.open || genLog.value || genLogLoading.value || !selected.value) return
  loadGenLog()
}

async function loadGenLog() {
  if (!selected.value) return
  // 捕获发起时的报文坐标；响应落地时已切走（慢网络）则丢弃，防止错串（CR S3）
  const gid = groupId.value
  const key = selected.value
  genLogLoading.value = true
  genLogError.value = null
  try {
    const data = await current.value.fetchGenerationLog(gid, key)
    if (selected.value !== key || groupId.value !== gid) return
    genLog.value = data
  } catch (e: unknown) {
    if (selected.value !== key || groupId.value !== gid) return
    genLogError.value = (e as Error).message
  } finally {
    if (selected.value === key && groupId.value === gid) genLogLoading.value = false
  }
}

function hopTime(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function hopLabel(hop: GenerationHop): string {
  if (hop.state === 'error') return '调用失败'
  if (hop.state === 'cancelled') return '已取消'
  if (hop.response_outcome === 'accepted') return '被采纳'
  return outcomeLabel(hop.response_outcome || 'unknown')
}

function hopVariant(hop: GenerationHop): TagVariant {
  if (hop.state === 'ok' && hop.response_outcome === 'accepted') return 'success'
  return issueVariant(hop.response_outcome || (hop.state === 'cancelled' ? 'cancelled' : 'unknown'))
}

function hopMeta(hop: GenerationHop): string {
  const seconds = ((hop.duration_ms ?? 0) / 1000).toFixed(1)
  const tokens = hop.total_tokens != null
    ? `${hop.total_tokens} tok`
    : `in ${hop.input_tokens ?? '—'} / out ${hop.output_tokens ?? '—'}`
  const cost = Number(hop.cost_usd ?? 0).toFixed(4)
  return `${seconds}s · ${tokens} · $${cost} · finish=${hop.finish_reason || '未上报'}`
}

const totalHopSeconds = computed(() =>
  ((genLog.value?.hops ?? []).reduce((sum, h) => sum + (h.duration_ms ?? 0), 0) / 1000).toFixed(1),
)
const totalHopCost = computed(() =>
  (genLog.value?.hops ?? []).reduce((sum, h) => sum + Number(h.cost_usd ?? 0), 0).toFixed(4),
)

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await fetchSummariesHealth(healthDays.value)
  } catch {
    health.value = null
  } finally {
    healthLoading.value = false
  }
}

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
  resetGenLog()
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
  resetGenLog()
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

.health-card {
  margin-bottom: var(--qq-gap-md);
}

.health-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
}

.health-head strong {
  font-size: 0.95rem;
}

.health-days select {
  margin: 0 4px;
}

.health-head .ui-button {
  margin-left: auto;
}

.health-table {
  width: 100%;
  margin-top: var(--qq-gap-sm);
  border-collapse: collapse;
  font-size: 0.85rem;
}

.health-table th,
.health-table td {
  padding: 6px 10px;
  text-align: left;
  border-bottom: 1px solid var(--qq-border, rgba(0, 0, 0, 0.08));
}

.health-empty {
  margin: var(--qq-gap-sm) 0 0;
  color: var(--qq-text-muted);
  font-size: 0.85rem;
}

.health-accept {
  color: var(--qq-success, #2da44e);
  font-weight: 600;
}

.health-issues {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.health-none {
  color: var(--qq-text-muted);
}

.genlog {
  margin-top: var(--qq-gap-md);
  border-top: 1px solid var(--qq-border, rgba(0, 0, 0, 0.08));
  padding-top: var(--qq-gap-sm);
  font-size: 0.85rem;
}

.genlog .mono {
  font-family: var(--qq-font-mono);
}

.genlog summary {
  cursor: pointer;
  color: var(--qq-text-muted);
}

.genlog-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  margin: var(--qq-gap-sm) 0 0;
  padding: 0;
  list-style: none;
}

.genlog-hop {
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  border: 1px solid var(--qq-border, rgba(0, 0, 0, 0.08));
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong, rgba(0, 0, 0, 0.02));
}

.genlog-hop__main {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.genlog-seq {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs, 12px);
}

.genlog-time,
.genlog-model {
  color: var(--qq-text);
}

.genlog-time {
  font-size: var(--qq-text-xs, 12px);
  color: var(--qq-text-muted);
}

.genlog-hop__meta {
  margin-top: 4px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs, 12px);
  word-break: break-word;
}

.genlog-hop__error {
  margin-top: 4px;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs, 12px);
  word-break: break-word;
}

.genlog-foot {
  margin: var(--qq-gap-sm) 0 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs, 12px);
}
</style>
