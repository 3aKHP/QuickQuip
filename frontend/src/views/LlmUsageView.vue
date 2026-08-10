<template>
  <div class="usage-view">
    <UiPageHeader title="LLM 用量与成本" subtitle="每次 complete() 调用的 token / 成本 / 耗时">
      <template #actions>
        <select v-model="range" class="range-select" @change="load">
          <option value="1d">近 1 天</option>
          <option value="7d">近 7 天</option>
          <option value="30d">近 30 天</option>
          <option value="90d">近 90 天</option>
        </select>
        <UiButton :loading="loading" icon="RefreshCw" @click="load">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="loading && !data" />
    <template v-else-if="data">
      <p class="bounds-note">{{ data.bounds_note }}</p>

      <div class="stat-cards">
        <article class="stat-card stat-card--primary">
          <span class="stat-card__label">总成本（下界）</span>
          <span class="stat-card__value">${{ fmtCost(data.total_cost) }}</span>
          <span class="stat-card__sub">{{ fmtNum(data.total_tokens) }} 输入/输出 tokens · {{ data.total_calls }} 次</span>
        </article>
        <article class="stat-card" :class="{ 'stat-card--warn': data.unpriced_calls_count > 0 }">
          <span class="stat-card__label">未定价调用</span>
          <span class="stat-card__value">{{ data.unpriced_calls_count }}</span>
          <span class="stat-card__sub">{{ data.unpriced_calls_count ? fmtNum(data.unpriced_tokens_total) + ' tokens 未计入' : '全部已定价' }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-card__label">失败 / 超时</span>
          <span class="stat-card__value">{{ data.error_count + data.cancelled_count }}</span>
          <span class="stat-card__sub">错误 {{ data.error_count }} · 取消 {{ data.cancelled_count }}</span>
        </article>
      </div>

      <div class="buckets">
        <UiCard v-for="b in buckets" :key="b.title" padding="md" shadow="sm">
          <h4 class="bucket-title">{{ b.title }}</h4>
          <div v-if="b.items.length" class="bar-list">
            <div v-for="it in b.items" :key="it.key" class="bar-row" :title="`${it.calls} 次调用`">
              <span class="bar-label" :title="it.key">{{ it.key }}</span>
              <div class="bar-track"><div class="bar-fill" :style="{ width: pct(it.cost, b.max) + '%' }" /></div>
              <span class="bar-value">${{ fmtCost(it.cost) }}</span>
            </div>
          </div>
          <UiEmpty v-else icon="BarChart3" title="暂无" />
        </UiCard>
      </div>

      <UiCard v-if="timeline.length" padding="md" shadow="sm">
        <h4 class="bucket-title">每日成本趋势（近 30 天）</h4>
        <div class="timeline">
          <div v-for="t in timeline" :key="t.date" class="tl-col" :title="`${t.date}: $${fmtCost(t.cost)} · ${fmtNum(t.tokens)} tokens`">
            <div class="tl-bar" :style="{ height: (tlMax ? Math.round(t.cost / tlMax * 100) : 0) + '%' }" />
          </div>
        </div>
        <div class="timeline-axis">
          <span>{{ timeline[0]?.date.slice(5) }}</span>
          <span>{{ timeline[timeline.length - 1]?.date.slice(5) }}</span>
        </div>
      </UiCard>
    </template>
    <UiEmpty v-else icon="BarChart3" title="暂无用量数据" description="部署后产生 LLM 调用即会出现" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchLlmUsageSummary, fetchLlmUsageTimeline, type LlmUsageSummary, type TimelinePoint, type UsageBucket } from '../api/llmUsage'

const range = ref('7d')
const data = ref<LlmUsageSummary | null>(null)
const timeline = ref<TimelinePoint[]>([])
const loading = ref(false)
const error = ref('')

const buckets = computed(() => {
  if (!data.value) return []
  const mk = (title: string, items: UsageBucket[]) => ({
    title, items, max: Math.max(0, ...items.map((i) => i.cost)),
  })
  return [
    mk('按 Provider', data.value.by_provider),
    mk('按功能', data.value.by_feature),
    mk('按模型', data.value.by_model),
    mk('按群', data.value.by_group),
  ]
})
const tlMax = computed(() => Math.max(0, ...timeline.value.map((t) => t.cost)))

function fmtCost(v: number) {
  return v < 0.01 ? v.toFixed(4) : v.toFixed(2)
}
function fmtNum(v: number) {
  return v.toLocaleString()
}
function pct(v: number, m: number) {
  return m ? Math.max(4, Math.round((v / m) * 100)) : 0
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, t] = await Promise.all([
      fetchLlmUsageSummary(range.value),
      fetchLlmUsageTimeline('30d'),
    ])
    data.value = s
    timeline.value = t
  } catch (e) {
    error.value = (e as Error).message || String(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.bounds-note {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  margin-bottom: var(--qq-gap-md);
}
.range-select {
  padding: 4px 8px;
  border: 1px solid var(--qq-border, rgba(0, 0, 0, 0.1));
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  color: var(--qq-text-base);
  font-size: var(--qq-text-sm);
}
.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-lg);
}
.stat-card {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border, rgba(0, 0, 0, 0.08));
  border-radius: var(--qq-radius-card);
  padding: var(--qq-gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}
.stat-card__label {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}
.stat-card__value {
  font-size: var(--qq-text-3xl);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stat-card__sub {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
}
.stat-card--primary {
  background: var(--qq-gradient-brand);
  color: #fff;
  border-color: transparent;
}
.stat-card--primary .stat-card__label,
.stat-card--primary .stat-card__sub {
  color: rgba(255, 255, 255, 0.85);
}
.stat-card--warn {
  border-color: var(--qq-warn);
}
.buckets {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
}
.bucket-title {
  font-size: var(--qq-text-md);
  font-weight: 600;
  margin-bottom: var(--qq-gap-sm);
}
.bar-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}
.bar-row {
  display: grid;
  grid-template-columns: minmax(70px, 130px) 1fr 68px;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: var(--qq-text-sm);
}
.bar-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bar-track {
  height: 6px;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-full);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: var(--qq-primary);
  border-radius: var(--qq-radius-full);
  transition: width 0.4s ease;
}
.bar-value {
  text-align: right;
  color: var(--qq-text-muted);
  font-variant-numeric: tabular-nums;
}
.timeline {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 120px;
}
.tl-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  height: 100%;
}
.tl-bar {
  width: 100%;
  min-height: 2px;
  background: var(--qq-primary);
  border-radius: 2px 2px 0 0;
  transition: height 0.4s ease;
}
.timeline-axis {
  display: flex;
  justify-content: space-between;
  margin-top: var(--qq-gap-xs);
  font-size: 10px;
  color: var(--qq-text-muted);
}
.error {
  color: var(--qq-danger);
}
</style>
