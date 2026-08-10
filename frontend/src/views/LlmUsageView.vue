<template>
  <div class="usage-view">
    <UiPageHeader title="LLM 用量与成本" subtitle="按请求观察 token、成本、成功率与耗时">
      <template #actions>
        <select v-model="range" class="control" @change="reload">
          <option value="1d">近 1 天</option>
          <option value="7d">近 7 天</option>
          <option value="30d">近 30 天</option>
          <option value="90d">近 90 天</option>
        </select>
        <UiButton :loading="loading" icon="RefreshCw" @click="reload">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <div class="filters">
      <select v-model="filters.provider" class="control" aria-label="Provider 筛选" @change="reload">
        <option value="">全部 Provider</option>
        <option v-for="item in data?.by_provider || []" :key="item.key" :value="item.key">{{ item.key }}</option>
      </select>
      <select v-model="filters.model" class="control" aria-label="模型筛选" @change="reload">
        <option value="">全部模型</option>
        <option v-for="item in data?.by_model || []" :key="item.key" :value="item.key">{{ item.key }}</option>
      </select>
      <select v-model="filters.feature" class="control" aria-label="功能筛选" @change="reload">
        <option value="">全部功能</option>
        <option v-for="item in data?.by_feature || []" :key="item.key" :value="item.key">{{ item.key }}</option>
      </select>
      <select v-model="filters.group" class="control" aria-label="群筛选" @change="reload">
        <option value="">全部群</option>
        <option v-for="item in data?.by_group || []" :key="item.key" :value="item.key">{{ item.key }}</option>
      </select>
      <select v-model="filters.state" class="control" aria-label="状态筛选" @change="reload">
        <option value="">全部状态</option>
        <option value="ok">成功</option>
        <option value="error">错误</option>
        <option value="cancelled">取消</option>
      </select>
    </div>

    <UiLoading v-if="loading && !data" />
    <template v-else-if="data">
      <p class="bounds-note">{{ data.bounds_note }}</p>

      <div class="stat-cards">
        <article class="stat-card stat-card--primary">
          <span class="stat-label">总成本</span>
          <strong>${{ fmtCost(data.total_cost) }}</strong>
          <small>{{ fmtNum(data.total_tokens) }} tokens</small>
        </article>
        <article class="stat-card">
          <span class="stat-label">请求 / 成功率</span>
          <strong>{{ fmtNum(data.request_count) }}</strong>
          <small>{{ pct(data.success_rate) }} 成功</small>
        </article>
        <article class="stat-card">
          <span class="stat-label">平均耗时</span>
          <strong>{{ fmtDuration(data.average_duration_ms) }}</strong>
          <small>所有请求</small>
        </article>
        <article class="stat-card">
          <span class="stat-label">缓存命中率</span>
          <strong>{{ pct(data.cache_hit_rate) }}</strong>
          <small>{{ fmtNum(data.total_cache_read_tokens) }} read tokens</small>
        </article>
        <article class="stat-card" :class="{ 'stat-card--warn': data.unpriced_calls_count > 0 }">
          <span class="stat-label">未定价 / 错误</span>
          <strong>{{ data.unpriced_calls_count }} / {{ data.error_count }}</strong>
          <small>{{ fmtNum(data.unpriced_tokens_total) }} tokens 未计价</small>
        </article>
      </div>

      <section class="panel chart-panel">
        <div class="panel-heading">
          <h3>趋势</h3>
          <select v-model="metric" class="control control--small" @change="loadTimeline">
            <option value="cost">成本</option>
            <option value="tokens">Tokens</option>
            <option value="requests">请求数</option>
            <option value="errors">错误数</option>
            <option value="duration">平均耗时</option>
          </select>
        </div>
        <div v-if="timeline.length" class="chart-wrap">
          <svg viewBox="0 0 720 220" role="img" aria-label="LLM 用量趋势图" preserveAspectRatio="none">
            <line x1="36" y1="12" x2="36" y2="194" class="chart-axis" />
            <line x1="36" y1="194" x2="708" y2="194" class="chart-axis" />
            <polyline :points="chartLine" class="chart-line" />
            <circle v-for="point in chartPoints" :key="point.key" :cx="point.x" :cy="point.y" r="3.5" class="chart-dot">
              <title>{{ point.label }}: {{ point.display }}</title>
            </circle>
          </svg>
          <div class="chart-axis-labels"><span>{{ timeline[0]?.date }}</span><span>{{ timeline[timeline.length - 1]?.date }}</span></div>
        </div>
        <UiEmpty v-else icon="BarChart3" title="暂无趋势数据" />
      </section>

      <section class="panel">
        <div class="tabs" role="tablist">
          <button v-for="tab in breakdownTabs" :key="tab.key" :class="['tab', { active: breakdown === tab.key }]" @click="breakdown = tab.key">{{ tab.label }}</button>
        </div>
        <div v-if="breakdownItems.length" class="bar-list">
          <div v-for="item in breakdownItems" :key="item.key" class="bar-row">
            <span class="bar-label" :title="item.key">{{ item.key }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: `${barPct(item.cost)}%` }" /></div>
            <span class="bar-value">${{ fmtCost(item.cost) }} · {{ fmtNum(item.calls) }} 次</span>
          </div>
        </div>
        <UiEmpty v-else icon="BarChart3" title="暂无维度数据" />
      </section>

      <section class="panel request-panel">
        <div class="panel-heading">
          <h3>请求明细</h3>
          <span class="muted">{{ events.length }} 条</span>
        </div>
        <UiEmpty v-if="!events.length && !eventsLoading" icon="ListChecks" title="暂无请求" />
        <div v-else class="event-list">
          <button v-for="event in events" :key="event.id" class="event-row" @click="toggleEvent(event.id)">
            <span class="event-main"><strong>{{ event.model }}</strong><small>{{ event.provider_id }} · {{ event.feature || '未归因' }}</small></span>
            <span class="event-metrics"><span>{{ fmtNum(event.total_tokens ?? 0) }} tok</span><span>${{ fmtCost(event.cost_usd) }}</span><span :class="`state-${event.state}`">{{ stateLabel(event.state) }}</span></span>
            <UiIcon :name="expandedId === event.id ? 'ChevronDown' : 'ChevronRight'" :size="16" />
            <div v-if="expandedId === event.id" class="event-detail" @click.stop>
              <dl>
                <div><dt>时间</dt><dd>{{ formatTs(event.ts) }}</dd></div>
                <div><dt>耗时</dt><dd>{{ fmtDuration(event.duration_ms) }}</dd></div>
                <div><dt>输入 / 输出</dt><dd>{{ fmtNum(event.input_tokens ?? 0) }} / {{ fmtNum(event.output_tokens ?? 0) }}</dd></div>
                <div><dt>缓存</dt><dd>{{ fmtNum(event.cache_read_tokens ?? 0) }} read · {{ fmtNum(event.cache_creation_tokens ?? 0) }} write</dd></div>
                <div><dt>定价</dt><dd>{{ event.pricing_model || '未定价' }}<span v-if="event.pricing_source"> · {{ event.pricing_source }}</span></dd></div>
                <div v-if="event.error_message"><dt>错误</dt><dd class="error">{{ event.error_message }}</dd></div>
              </dl>
            </div>
          </button>
        </div>
        <UiButton v-if="nextCursor" class="load-more" size="sm" variant="ghost" icon="ChevronDown" :loading="eventsLoading" @click="loadMore">加载更多</UiButton>
      </section>
    </template>
    <UiEmpty v-else icon="BarChart3" title="暂无用量数据" description="产生 LLM 调用后会显示统计" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import {
  fetchLlmUsageEvents,
  fetchLlmUsageSummary,
  fetchLlmUsageTimeline,
  type LlmUsageSummary,
  type TimelinePoint,
  type UsageBucket,
  type UsageEvent,
  type UsageFilters,
  type UsageMetric,
} from '../api/llmUsage'

const range = ref('7d')
const metric = ref<UsageMetric>('cost')
const data = ref<LlmUsageSummary | null>(null)
const timeline = ref<TimelinePoint[]>([])
const events = ref<UsageEvent[]>([])
const nextCursor = ref<string | null>(null)
const expandedId = ref<number | null>(null)
const loading = ref(false)
const eventsLoading = ref(false)
const error = ref('')
const breakdown = ref<'provider' | 'model' | 'feature' | 'group'>('provider')
const filters = reactive<UsageFilters>({ provider: '', model: '', feature: '', group: '', state: '' })

const breakdownTabs = [
  { key: 'provider' as const, label: 'Provider' },
  { key: 'model' as const, label: '模型' },
  { key: 'feature' as const, label: '功能' },
  { key: 'group' as const, label: '群' },
]
const breakdownItems = computed<UsageBucket[]>(() => {
  if (!data.value) return []
  const key = `by_${breakdown.value}` as 'by_provider' | 'by_model' | 'by_feature' | 'by_group'
  return data.value[key]
})
const chartMax = computed(() => Math.max(1, ...timeline.value.map(item => item.value)))
const chartPoints = computed(() => timeline.value.map((item, index) => {
  const x = 36 + (index / Math.max(1, timeline.value.length - 1)) * 672
  const y = 194 - (item.value / chartMax.value) * 174
  return { key: item.date, x, y, label: item.date, display: metricDisplay(item.value) }
}))
const chartLine = computed(() => chartPoints.value.map(point => `${point.x},${point.y}`).join(' '))

function fmtCost(value: number) { return value < 0.01 ? value.toFixed(4) : value.toFixed(2) }
function fmtNum(value: number) { return value.toLocaleString() }
function pct(value: number) { return `${(value * 100).toFixed(1)}%` }
function fmtDuration(value: number | null) { return value == null ? '-' : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms` }
function formatTs(value: string) { return new Date(value).toLocaleString() }
function stateLabel(value: string) { return value === 'ok' ? '成功' : value === 'cancelled' ? '取消' : '错误' }
function metricDisplay(value: number) { return metric.value === 'cost' ? `$${fmtCost(value)}` : metric.value === 'duration' ? fmtDuration(value) : fmtNum(value) }
function barPct(value: number) { const max = Math.max(1, ...breakdownItems.value.map(item => item.cost)); return value ? Math.max(4, value / max * 100) : 0 }

async function loadTimeline() {
  try { timeline.value = await fetchLlmUsageTimeline(range.value, metric.value, filters) } catch (e) { error.value = (e as Error).message || String(e) }
}
async function loadEvents(reset = true) {
  eventsLoading.value = true
  try {
    const result = await fetchLlmUsageEvents(range.value, filters, reset ? undefined : nextCursor.value || undefined)
    events.value = reset ? result.items : [...events.value, ...result.items]
    nextCursor.value = result.next_cursor
  } catch (e) { error.value = (e as Error).message || String(e) } finally { eventsLoading.value = false }
}
async function reload() {
  loading.value = true
  error.value = ''
  expandedId.value = null
  try {
    const [summary] = await Promise.all([fetchLlmUsageSummary(range.value, filters), loadTimeline(), loadEvents()])
    data.value = summary
  } catch (e) { error.value = (e as Error).message || String(e) } finally { loading.value = false }
}
function loadMore() { return loadEvents(false) }
function toggleEvent(id: number) { expandedId.value = expandedId.value === id ? null : id }

onMounted(reload)
</script>

<style scoped>
.usage-view { display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.control { min-height: 34px; padding: 0 9px; border: 1px solid var(--qq-border); border-radius: var(--qq-radius-md); background: var(--qq-surface); color: var(--qq-text); font-size: var(--qq-text-sm); }
.control--small { min-height: 30px; }
.filters { display: flex; flex-wrap: wrap; gap: var(--qq-gap-sm); }
.bounds-note, .muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: var(--qq-gap-sm); }
.stat-card { display: flex; flex-direction: column; gap: 5px; padding: var(--qq-gap-md); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-card); background: var(--qq-surface); }
.stat-card--primary { color: var(--qq-on-primary); background: var(--qq-primary); border-color: var(--qq-primary); }
.stat-card--warn { border-color: var(--qq-warn); }
.stat-label, .stat-card small { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.stat-card--primary .stat-label, .stat-card--primary small { color: rgba(255,255,255,.82); }
.stat-card strong { font-size: var(--qq-text-2xl); font-variant-numeric: tabular-nums; }
.panel { padding: var(--qq-gap-md); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-card); background: var(--qq-surface); }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); }
.panel-heading h3 { margin: 0; font-size: var(--qq-text-md); }
.chart-wrap { min-height: 220px; }
.chart-wrap svg { display: block; width: 100%; height: 220px; overflow: visible; }
.chart-axis { stroke: var(--qq-border); stroke-width: 1; }
.chart-line { fill: none; stroke: var(--qq-primary); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.chart-dot { fill: var(--qq-surface); stroke: var(--qq-primary); stroke-width: 2; }
.chart-axis-labels { display: flex; justify-content: space-between; color: var(--qq-text-muted); font-size: 11px; }
.tabs { display: flex; gap: var(--qq-gap-sm); border-bottom: 1px solid var(--qq-border); margin-bottom: var(--qq-gap-md); overflow-x: auto; }
.tab { padding: 7px 3px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--qq-text-muted); cursor: pointer; white-space: nowrap; }
.tab.active { color: var(--qq-primary); border-bottom-color: var(--qq-primary); }
.bar-list { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.bar-row { display: grid; grid-template-columns: minmax(90px, 180px) 1fr minmax(125px, auto); align-items: center; gap: var(--qq-gap-sm); font-size: var(--qq-text-sm); }
.bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { height: 7px; background: var(--qq-surface-strong); border-radius: var(--qq-radius-full); overflow: hidden; }
.bar-fill { height: 100%; background: var(--qq-primary); border-radius: inherit; }
.bar-value { color: var(--qq-text-muted); text-align: right; font-variant-numeric: tabular-nums; }
.event-list { display: flex; flex-direction: column; }
.event-row { position: relative; display: grid; grid-template-columns: 1fr auto 18px; gap: var(--qq-gap-sm); align-items: center; padding: 11px 2px; border: 0; border-bottom: 1px solid var(--qq-border); background: transparent; color: var(--qq-text); text-align: left; cursor: pointer; }
.event-row:hover { background: var(--qq-surface-strong); }
.event-main, .event-metrics { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.event-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event-main small, .event-metrics { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.event-metrics { flex-direction: row; gap: var(--qq-gap-md); white-space: nowrap; }
.state-ok { color: var(--qq-success); } .state-error { color: var(--qq-danger); } .state-cancelled { color: var(--qq-warn); }
.event-detail { grid-column: 1 / -1; padding: var(--qq-gap-sm) 0 2px; cursor: default; }
.event-detail dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 20px; margin: 0; padding: var(--qq-gap-sm); border-left: 2px solid var(--qq-primary); background: var(--qq-surface-strong); }
.event-detail dl div { display: flex; gap: 8px; font-size: var(--qq-text-sm); } .event-detail dt { color: var(--qq-text-muted); } .event-detail dd { margin: 0; word-break: break-word; }
.load-more { align-self: center; margin-top: var(--qq-gap-sm); }
.error { color: var(--qq-danger); }
@media (max-width: 680px) { .bar-row { grid-template-columns: minmax(80px, 1fr) auto; } .bar-track { grid-column: 1 / -1; grid-row: 2; } .event-row { grid-template-columns: 1fr 18px; } .event-metrics { grid-column: 1 / -1; flex-wrap: wrap; } }
</style>
