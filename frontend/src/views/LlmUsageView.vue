<template>
  <div class="usage-view">
    <UiPageHeader title="LLM 用量与成本" subtitle="按请求观察 token、成本、成功率与耗时">
      <template #actions>
        <UiSegmented v-model="range" :options="rangeOptions" aria-label="时间范围" @update:model-value="reload" />
        <UiButton :loading="loading" icon="RefreshCw" @click="reload">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <div class="filters">
      <select v-model="filters.provider" aria-label="Provider 筛选" @change="reload">
        <option value="">全部 Provider</option>
        <option v-for="item in dimensionOptions.provider" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.model" aria-label="模型筛选" @change="reload">
        <option value="">全部模型</option>
        <option v-for="item in dimensionOptions.model" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.feature" aria-label="功能筛选" @change="reload">
        <option value="">全部功能</option>
        <option v-for="item in dimensionOptions.feature" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.group" aria-label="群筛选" @change="reload">
        <option value="">全部群</option>
        <option v-for="item in dimensionOptions.group" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.state" aria-label="状态筛选" @change="reload">
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
        <UiStatCard label="总成本" :value="`$${fmtCost(data.total_cost)}`" :sub="`${fmtNum(data.total_tokens)} tokens`" icon="Coins" variant="primary" />
        <UiStatCard label="请求 / 成功率" :value="fmtNum(data.request_count)" :sub="`${pct(data.success_rate)} 成功`" icon="Activity" />
        <UiStatCard label="平均耗时" :value="fmtDuration(data.average_duration_ms)" sub="所有请求" icon="Clock" />
        <UiStatCard label="缓存命中率" :value="pct(data.cache_hit_rate)" :sub="`${fmtNum(data.total_cache_read_tokens)} read tokens`" icon="Zap" />
        <UiStatCard label="未定价 / 错误" :value="`${data.unpriced_calls_count} / ${data.error_count}`" :sub="`${fmtNum(data.unpriced_tokens_total)} tokens 未计价`" icon="AlertTriangle" :variant="data.unpriced_calls_count > 0 ? 'warn' : 'default'" />
      </div>

      <section class="panel">
        <div class="panel-heading">
          <h3>趋势</h3>
          <UiSegmented :model-value="metric" :options="metricOptions" aria-label="趋势指标" @update:model-value="value => { metric = value as UsageMetric; loadTimeline() }" />
        </div>
        <EChart v-if="timeline.length" :option="trendOption" :height="280" />
        <UiEmpty v-else icon="BarChart3" title="暂无趋势数据" />
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h3>维度分布</h3>
          <UiSegmented :model-value="breakdown" :options="breakdownOptions" aria-label="分布维度" @update:model-value="value => breakdown = value as BreakdownKey" />
        </div>
        <p class="hint"><UiIcon name="MousePointerClick" :size="13" /> 点击条形可将该维度值填入上方筛选器</p>
        <EChart v-if="breakdownItems.length" :option="barOption" :height="barHeight" @click="onBarClick" />
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
                <div><dt>新鲜输入</dt><dd>{{ fmtNum(event.fresh_input_tokens ?? 0) }}</dd></div>
                <div><dt>缓存</dt><dd>{{ fmtNum(event.cache_read_tokens ?? 0) }} read · {{ fmtNum(event.cache_creation_tokens ?? 0) }} write</dd></div>
                <div v-if="event.thinking_tokens"><dt>思考</dt><dd>{{ fmtNum(event.thinking_tokens) }} tokens</dd></div>
                <div><dt>成本分项</dt><dd>{{ costBreakdown(event) }}</dd></div>
                <div><dt>定价</dt><dd>{{ pricingLabel(event) }}</dd></div>
                <div v-if="event.agent_loop_id"><dt>Agent Loop</dt><dd>{{ event.agent_loop_id }}</dd></div>
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
import EChart from '../components/ui/EChart.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSegmented from '../components/ui/UiSegmented.vue'
import UiStatCard from '../components/ui/UiStatCard.vue'
import type { ECOption } from '../charts/echarts'
import { useChartTheme } from '../composables/useChartTheme'
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

type BreakdownKey = 'provider' | 'model' | 'feature' | 'group'

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
const breakdown = ref<BreakdownKey>('provider')
const filters = reactive<UsageFilters>({ provider: '', model: '', feature: '', group: '', state: '' })

const { chartTheme } = useChartTheme()

const rangeOptions = [
  { value: '1d', label: '1 天' },
  { value: '7d', label: '7 天' },
  { value: '30d', label: '30 天' },
  { value: '90d', label: '90 天' },
]
const metricOptions = [
  { value: 'cost', label: '成本' },
  { value: 'tokens', label: 'Tokens' },
  { value: 'requests', label: '请求' },
  { value: 'errors', label: '错误' },
  { value: 'duration', label: '耗时' },
]
const breakdownOptions = [
  { value: 'provider', label: 'Provider' },
  { value: 'model', label: '模型' },
  { value: 'feature', label: '功能' },
  { value: 'group', label: '群' },
]

/** 维度筛选选项：并入历次 summary 的 by_* 桶（union），避免筛选后选项塌缩 */
const dimensionOptions = reactive<Record<'provider' | 'model' | 'feature' | 'group', string[]>>({
  provider: [],
  model: [],
  feature: [],
  group: [],
})

function mergeDimensionOptions(summary: LlmUsageSummary) {
  const sources: Record<keyof typeof dimensionOptions, UsageBucket[]> = {
    provider: summary.by_provider,
    model: summary.by_model,
    feature: summary.by_feature,
    group: summary.by_group,
  }
  for (const [dim, buckets] of Object.entries(sources) as [keyof typeof dimensionOptions, UsageBucket[]][]) {
    const merged = new Set(dimensionOptions[dim])
    for (const bucket of buckets) merged.add(bucket.key)
    dimensionOptions[dim] = [...merged].sort()
  }
}

const breakdownItems = computed<UsageBucket[]>(() => {
  if (!data.value) return []
  const key = `by_${breakdown.value}` as 'by_provider' | 'by_model' | 'by_feature' | 'by_group'
  return data.value[key]
})

const trendOption = computed<ECOption>(() => {
  const t = chartTheme.value
  const points = timeline.value
  return {
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      ...t.tooltip,
      axisPointer: { type: 'line', lineStyle: { color: t.primary } },
      valueFormatter: (value: number | string) => metricDisplay(Number(value)),
    },
    xAxis: {
      type: 'category',
      data: points.map(point => point.date),
      boundaryGap: false,
      axisLine: t.axisLine,
      axisLabel: t.axisLabel,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { ...t.axisLabel, formatter: (value: number) => fmtAxis(value) },
      splitLine: t.splitLine,
    },
    dataZoom: points.length > 31 ? [{ type: 'inside' }] : [],
    series: [{
      type: 'line',
      data: points.map(point => point.value),
      showSymbol: points.length <= 45,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 2, color: t.primary },
      itemStyle: { color: t.primary },
      areaStyle: { color: t.primary, opacity: 0.10 },
    }],
  }
})

const BAR_LIMIT = 12

const barOption = computed<ECOption>(() => {
  const t = chartTheme.value
  const items = [...breakdownItems.value].slice(0, BAR_LIMIT).reverse()
  const total = breakdownItems.value.reduce((sum, item) => sum + item.cost, 0)
  const share = (cost: number) => total > 0 ? `${(cost / total * 100).toFixed(1)}%` : '0%'
  return {
    grid: { left: 8, right: 96, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'item',
      ...t.tooltip,
      formatter: (params: { name: string; value: number }) =>
        `${params.name}<br/>成本 $${fmtCost(params.value)}（${share(params.value)}）<br/>点击填入筛选器`,
    },
    xAxis: {
      type: 'value',
      axisLabel: { ...t.axisLabel, formatter: (value: number) => fmtAxis(value) },
      splitLine: t.splitLine,
    },
    yAxis: {
      type: 'category',
      data: items.map(item => item.key),
      axisLine: t.axisLine,
      axisLabel: { ...t.axisLabel, width: 120, overflow: 'truncate' as const },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: items.map(item => item.cost),
      barMaxWidth: 16,
      itemStyle: { color: t.primary, borderRadius: [0, 3, 3, 0] },
      emphasis: { itemStyle: { color: t.cyan } },
      label: {
        show: true,
        position: 'right' as const,
        color: t.textMuted,
        fontSize: 11,
        formatter: (params: { value: number }) => `$${fmtCost(params.value)} · ${share(params.value)}`,
      },
    }],
  }
})

const barHeight = computed(() => Math.max(180, Math.min(breakdownItems.value.length, BAR_LIMIT) * 32 + 24))

function fmtCost(value: number) { return value < 0.01 ? value.toFixed(4) : value.toFixed(2) }
function fmtNum(value: number) { return value.toLocaleString() }
function fmtAxis(value: number) {
  if (metric.value === 'cost') return `$${fmtCompact(value)}`
  return fmtCompact(value)
}
function fmtCompact(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(Math.round(value * 100) / 100)
}
function pct(value: number) { return `${(value * 100).toFixed(1)}%` }
function fmtDuration(value: number | null) { return value == null ? '-' : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms` }
function formatTs(value: string) { return new Date(value).toLocaleString() }
function stateLabel(value: string) { return value === 'ok' ? '成功' : value === 'cancelled' ? '取消' : '错误' }
function metricDisplay(value: number) { return metric.value === 'cost' ? `$${fmtCost(value)}` : metric.value === 'duration' ? fmtDuration(value) : fmtNum(value) }
function costBreakdown(event: UsageEvent) {
  if (!event.priced) return '未计价'
  return `in $${fmtCost(event.input_cost_usd)} · out $${fmtCost(event.output_cost_usd)} · cache r $${fmtCost(event.cache_read_cost_usd)} · w $${fmtCost(event.cache_creation_cost_usd)}`
}
function pricingLabel(event: UsageEvent) {
  if (!event.pricing_model) return '未定价'
  const parts = [event.pricing_model]
  if (event.pricing_source) parts.push(event.pricing_source)
  if (event.pricing_confidence) parts.push(event.pricing_confidence)
  return parts.join(' · ')
}

function onBarClick(params: unknown) {
  const name = (params as { name?: string }).name
  if (!name) return
  filters[breakdown.value] = name
  reload()
}

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
    mergeDimensionOptions(summary)
  } catch (e) { error.value = (e as Error).message || String(e) } finally { loading.value = false }
}
function loadMore() { return loadEvents(false) }
function toggleEvent(id: number) { expandedId.value = expandedId.value === id ? null : id }

onMounted(reload)
</script>

<style scoped>
.usage-view { display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.filters { display: flex; flex-wrap: wrap; gap: var(--qq-gap-sm); }
.filters select { min-width: 130px; font-size: var(--qq-text-sm); }
.bounds-note, .muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: var(--qq-gap-sm); }
.panel { padding: var(--qq-gap-md); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-card); background: var(--qq-surface); box-shadow: var(--qq-shadow-card); }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); flex-wrap: wrap; }
.panel-heading h3 { margin: 0; font-size: var(--qq-text-md); }
.hint { display: flex; align-items: center; gap: 5px; margin: calc(-1 * var(--qq-gap-sm)) 0 var(--qq-gap-sm); color: var(--qq-text-quiet); font-size: var(--qq-text-xs); }
.event-list { display: flex; flex-direction: column; }
.event-row { position: relative; display: grid; grid-template-columns: 1fr auto 18px; gap: var(--qq-gap-sm); align-items: center; padding: 11px 2px; border: 0; border-bottom: 1px solid var(--qq-border); background: transparent; color: var(--qq-text); text-align: left; cursor: pointer; }
.event-row:hover { background: var(--qq-surface-strong); }
.event-main, .event-metrics { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.event-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event-main small, .event-metrics { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.event-metrics { flex-direction: row; gap: var(--qq-gap-md); white-space: nowrap; font-variant-numeric: tabular-nums; }
.state-ok { color: var(--qq-success); } .state-error { color: var(--qq-danger); } .state-cancelled { color: var(--qq-warn); }
.event-detail { grid-column: 1 / -1; padding: var(--qq-gap-sm) 0 2px; cursor: default; }
.event-detail dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 20px; margin: 0; padding: var(--qq-gap-sm); border-left: 2px solid var(--qq-primary); background: var(--qq-surface-strong); }
.event-detail dl div { display: flex; gap: 8px; font-size: var(--qq-text-sm); } .event-detail dt { color: var(--qq-text-muted); flex-shrink: 0; } .event-detail dd { margin: 0; word-break: break-word; font-variant-numeric: tabular-nums; }
.load-more { align-self: center; margin-top: var(--qq-gap-sm); }
.error { color: var(--qq-danger); }
@media (max-width: 680px) { .event-row { grid-template-columns: 1fr 18px; } .event-metrics { grid-column: 1 / -1; flex-wrap: wrap; } }
</style>
